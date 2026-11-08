# SPDX-License-Identifier: AGPL-3.0-or-later
# Session de présence du poste client (SSH vers pollux-session) ;
# dépendances : bibliothèque standard, server.commun et admin.app.
# Suivi des versions
#   0.1.12  2026-11-08  Ouverture avec défi signé (challenge, signature, open).
#   3.0.0-alpha.41  2026-11-06  Ouverture, battement, perte et fermeture de la session de présence.
import enum
import re
import secrets
import subprocess
import threading
import time

from server.commun.jumeaux import (CODES_ERREUR, PLAFOND_DELAI, PROTO, ErreurProtocole,
                                   decoder, encoder, id_valide, lire_ligne, verifier_delai)

from . import signature
from .textes import afficher

_PAS = 0.02            # pas d'interrogation de l'horloge par le fil de battement
_DELAI_ARRET = 2.0     # attente de fin de ssh avant kill, puis des fils
_TAILLE_DIAGNOSTIC = 2048
_JETON = re.compile(r'[0-9a-f]{64}')


class Etat(enum.Enum):
    FERMEE = 'fermee'
    OUVERTE = 'ouverte'
    PERDUE = 'perdue'


class ErreurPresence(Exception):
    """Porte un code du serveur (CODES_ERREUR) ou une clé ui_presence_*."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _delai_valide(valeur):
    return (type(valeur) in (int, float) and 0 < valeur <= PLAFOND_DELAI)


class SessionPresence:
    """Une liaison ssh -T vers pollux-session ; le jeton n'est lisible que par jeton()."""

    def __init__(self, ssh, hote, compte, cle_publique, ouverture_s, *, admin, ssh_keygen,
                 signeur=signature.signer, horloge=time.monotonic, lancer=subprocess.Popen,
                 ecouteur=None):
        verifier_delai(ouverture_s)
        self._admin = admin
        self._cle_publique = cle_publique
        self._ssh_keygen = ssh_keygen
        self._signeur = signeur
        self._commande = [ssh, '-T', '-i', cle_publique, '-o', 'IdentitiesOnly=yes',
                          '-o', 'BatchMode=yes', '--', f'{compte}@{hote}']
        self._ouverture_s = ouverture_s
        self._horloge = horloge
        self._lancer = lancer
        self._ecouteur = ecouteur
        self._verrou = threading.RLock()
        self._verrou_fermeture = threading.RLock()
        self._ecriture = threading.Lock()
        self.diagnostic = ''
        self._reinitialiser()

    def _reinitialiser(self):
        self._etat = Etat.FERMEE
        self._numero = 0
        self._jeton = None
        self.heartbeat_s = None
        self.timeout_s = None
        self._proc = None
        self._fils = []
        self._arret = threading.Event()
        self._pret = threading.Event()
        self._echec = None
        self._id_ouverture = None
        self._id_defi = None
        self._phase = 'defi'
        self._defi = None
        self._defi_pret = threading.Event()
        self._id_ping = None
        self._dernier_envoi = 0.0
        self._derniere_reponse = 0.0
        self._actif = False
        self._ferme = False

    def __repr__(self):
        return f'<SessionPresence etat={self._etat.value}>'

    __str__ = __repr__

    @property
    def etat(self):
        return self._etat

    @property
    def numero(self):
        return self._numero

    def jeton(self):
        return self._jeton

    def _notifier(self, etat, code):
        if self._ecouteur is not None:
            self._ecouteur(etat, code)

    # ---- ouverture ----------------------------------------------------

    def ouvrir(self):
        with self._verrou_fermeture:
            if self._actif or self._etat is not Etat.FERMEE:
                raise ErreurPresence('internal_error')
            self._reinitialiser()
            self._actif = True
        try:
            self._ouvrir()
        except BaseException:
            self._arreter()
            raise
        self._notifier(Etat.OUVERTE, None)

    def _ouvrir(self):
        try:
            self._proc = self._lancer(self._commande, stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      bufsize=0)
        except (OSError, ValueError):
            raise ErreurPresence('ui_presence_ssh_echec') from None
        self._id_defi = secrets.token_hex(8)
        self._id_ouverture = secrets.token_hex(8)
        fin = time.monotonic() + self._ouverture_s
        for cible in (self._lire, self._lire_erreurs):
            fil = threading.Thread(target=cible, daemon=True)
            self._fils.append(fil)
            fil.start()
        if not self._envoyer(self._requete(self._id_defi, 'presence/session/challenge', {})):
            raise ErreurPresence('ui_presence_ssh_echec')
        if not self._defi_pret.wait(max(fin - time.monotonic(), 0)):
            raise ErreurPresence('ui_presence_delai_ouverture')
        if self._echec is not None:
            raise ErreurPresence(self._echec)
        defi, expires_s = self._defi
        reste = min(expires_s, fin - time.monotonic())
        if reste <= 0:
            raise ErreurPresence('ui_presence_defi_delai')
        limite = time.monotonic() + reste
        try:
            signe = self._signeur(defi, self._admin, signature.ESPACE, self._cle_publique,
                                  self._ssh_keygen, reste)
        except signature.ErreurSignature as erreur:
            raise ErreurPresence(erreur.code) from None
        self._defi = None
        if time.monotonic() > limite:
            raise ErreurPresence('ui_presence_defi_delai')
        if (not isinstance(signe, str) or not 0 < len(signe) <= signature.MAX_SIGNATURE
                or not signe.isascii()):
            raise ErreurPresence('ui_presence_signature_echec')
        with self._verrou:
            if self._echec is not None:
                raise ErreurPresence(self._echec)
            self._phase = 'open'
        if not self._envoyer(self._requete(self._id_ouverture, 'presence/session/open',
                                           {'signature': signe})):
            raise ErreurPresence('ui_presence_ssh_echec')
        if not self._pret.wait(max(fin - time.monotonic(), 0)):
            raise ErreurPresence('ui_presence_delai_ouverture')
        if self._echec is not None:
            raise ErreurPresence(self._echec)

    @staticmethod
    def _requete(identifiant, action, params):
        return {'proto': PROTO, 'id': identifiant, 'session': 0,
                'action': action, 'params': params}

    def _envoyer(self, objet):
        try:
            with self._ecriture:
                self._proc.stdin.write(encoder(objet))
            return True
        except (OSError, ValueError, AttributeError):
            return False

    # ---- lecture ------------------------------------------------------

    def _lire(self):
        try:
            while not self._arret.is_set():
                try:
                    ligne = lire_ligne(self._proc.stdout)
                    if ligne is None:
                        self._fin_de_flux()
                        return
                    message = decoder(ligne)
                except ErreurProtocole:
                    self._anomalie('ui_presence_reponse_invalide')
                    return
                except (OSError, ValueError):
                    self._fin_de_flux()
                    return
                if not self._traiter(message):
                    return
        finally:
            if not self._pret.is_set():
                self._echec = self._echec or 'ui_presence_ssh_echec'
                self._conclure()

    def _fin_de_flux(self):
        if self._pret.is_set():
            self._perdre('ui_presence_perdue')
        else:
            self._echec = 'ui_presence_ssh_echec'
            self._conclure()

    def _conclure(self):
        self._defi_pret.set()
        self._pret.set()

    def _anomalie(self, code):
        if self._pret.is_set():
            self._perdre(code)
        else:
            self._echec = code
            self._conclure()

    def _traiter(self, message):
        """Renvoie False quand la lecture doit s'arrêter."""
        if not self._pret.is_set():
            with self._verrou:
                phase = self._phase
            if phase == 'defi':
                return self._reponse_defi(message)
            if phase == 'open':
                return self._reponse_ouverture(message)
            self._echec = 'ui_presence_reponse_invalide'
            self._conclure()
            return False
        return self._reponse_ping(message)

    @staticmethod
    def _code_erreur(message):
        erreur = message.get('error')
        code = erreur.get('code') if isinstance(erreur, dict) else None
        return code if isinstance(code, str) and code in CODES_ERREUR else None

    def _reponse_defi(self, message):
        echec = None
        if message.get('id') != self._id_defi or type(message.get('ok')) is not bool:
            echec = 'ui_presence_reponse_invalide'
        elif not message['ok']:
            echec = self._code_erreur(message) or 'ui_presence_reponse_invalide'
        else:
            data = message.get('data')
            if (not isinstance(data, dict)
                    or set(data) != {'challenge', 'namespace', 'expires_s'}
                    or not isinstance(data['challenge'], str)
                    or not _JETON.fullmatch(data['challenge'])
                    or not isinstance(data['namespace'], str)
                    or not _delai_valide(data['expires_s'])):
                echec = 'ui_presence_reponse_invalide'
            elif data['namespace'] != signature.ESPACE:
                echec = 'ui_presence_espace_refuse'
            else:
                self._defi = (data['challenge'], data['expires_s'])
                with self._verrou:
                    self._phase = 'signature'
                self._defi_pret.set()
                return True
        self._echec = echec
        self._conclure()
        return False

    def _reponse_ouverture(self, message):
        if message.get('id') != self._id_ouverture or type(message.get('ok')) is not bool:
            self._echec = 'ui_presence_reponse_invalide'
        elif not message['ok']:
            self._echec = self._code_erreur(message) or 'ui_presence_reponse_invalide'
        else:
            data = message.get('data')
            if not isinstance(data, dict):
                data = {}
            numero, jeton = data.get('session'), data.get('token')
            battement, delai = data.get('heartbeat_s'), data.get('timeout_s')
            if (type(numero) is int and numero >= 1 and isinstance(jeton, str)
                    and _JETON.fullmatch(jeton) and _delai_valide(battement)
                    and _delai_valide(delai) and battement < delai):
                with self._verrou:
                    self._numero, self._jeton = numero, jeton
                    self.heartbeat_s, self.timeout_s = battement, delai
                    self._derniere_reponse = self._dernier_envoi = self._horloge()
                    self._etat = Etat.OUVERTE
                fil = threading.Thread(target=self._battre, daemon=True)
                self._fils.append(fil)
                self._pret.set()
                fil.start()
                return True
            self._echec = 'ui_presence_reponse_invalide'
        self._pret.set()
        return False

    def _reponse_ping(self, message):
        with self._verrou:
            attendu = self._id_ping
        if attendu is None or message.get('id') != attendu or type(message.get('ok')) is not bool:
            self._perdre('ui_presence_reponse_invalide')
            return False
        if not message['ok']:
            self._perdre(self._code_erreur(message) or 'ui_presence_reponse_invalide')
            return False
        with self._verrou:
            self._id_ping = None
            self._derniere_reponse = self._horloge()
        return True

    def _lire_erreurs(self):
        tampon = b''
        try:
            while True:
                bloc = self._proc.stderr.read(512)
                if not bloc:
                    return
                tampon = (tampon + bloc)[-_TAILLE_DIAGNOSTIC:]
                self.diagnostic = afficher(tampon.decode('utf-8', 'replace'))
        except (OSError, ValueError, AttributeError):
            return

    # ---- battement et perte -------------------------------------------

    def _battre(self):
        while not self._arret.wait(_PAS):
            maintenant = self._horloge()
            with self._verrou:
                if self._etat is not Etat.OUVERTE:
                    return
                perdue = maintenant - self._derniere_reponse >= self.timeout_s
                envoyer = (not perdue and self._id_ping is None
                           and maintenant - self._dernier_envoi >= self.heartbeat_s)
                if envoyer:
                    self._id_ping = secrets.token_hex(8)
                    self._dernier_envoi = maintenant
                    requete = {'proto': PROTO, 'id': self._id_ping, 'session': self._numero,
                               'action': 'presence/session/ping', 'params': {}}
            if perdue:
                self._perdre('ui_presence_perdue')
                return
            if envoyer and not self._envoyer(requete):
                self._perdre('ui_presence_perdue')
                return

    def _perdre(self, code):
        with self._verrou:
            if self._etat is not Etat.OUVERTE or self._arret.is_set():
                return
            self._etat = Etat.PERDUE
        self._terminer_ssh()
        self._notifier(Etat.PERDUE, code)

    def _terminer_ssh(self):
        proc = self._proc
        if proc is None:
            return
        try:
            proc.stdin.close()
        except (OSError, ValueError, AttributeError):
            pass
        try:
            proc.terminate()
        except OSError:
            pass

    # ---- fermeture ----------------------------------------------------

    def _arreter(self):
        """Arrêt ordonné ; renvoie l'état antérieur."""
        with self._verrou_fermeture:
            if self._ferme:
                return None
            self._ferme = True
            with self._verrou:
                avant = self._etat
                self._arret.set()
            proc = self._proc
            if proc is not None:
                try:
                    proc.stdin.close()
                except (OSError, ValueError, AttributeError):
                    pass
                try:
                    proc.terminate()
                    try:
                        proc.wait(_DELAI_ARRET)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                except OSError:
                    pass
            courant = threading.current_thread()
            for fil in self._fils:
                if fil is not courant:
                    fil.join(_DELAI_ARRET * 2)
            if proc is not None:
                for tube in (proc.stdout, proc.stderr):
                    try:
                        tube.close()
                    except (OSError, ValueError, AttributeError):
                        pass
            with self._verrou:
                self._etat = Etat.FERMEE
                self._jeton = None
            self._actif = False
            return avant

    def fermer(self):
        """Idempotente ; utilisable depuis n'importe quel fil."""
        avant = self._arreter()
        if avant in (Etat.OUVERTE, Etat.PERDUE):
            self._notifier(Etat.FERMEE, 'ui_presence_fermee')
