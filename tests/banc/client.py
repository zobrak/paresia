#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Client de présence d'essai ; dépendances : stdlib, ssh, ssh-keygen et agent SSH.
# Suivi des versions
#   3.0.0-alpha.42  2026-11-07  Défi SSHSIG, battements, fermeture et jeton en mémoire.
"""Session SSH persistante ; aucun secret transmis dans les arguments ou les journaux.

SessionPresence de l'application ouvre sans défi et ne fournit pas d'interface
pour insérer la preuve : cet outil utilise son propre échange NDJSON.
server.commun.texte ne fournit qu'un filtre, pas de catalogue pour cette CLI :
les textes de cet outil d'essai sont en français, filtrés de la même manière.
"""
import argparse
import base64
import binascii
import json
import math
import os
from pathlib import Path
import re
import secrets
import select
import subprocess
import sys
import threading
import time
import unicodedata

PROTO = 'jumeaux/1'
ESPACE = 'paresia-presence'
MAX_LIGNE = 1048576
MAX_SIGNATURE = 2048
_HEXA = re.compile(r'[0-9a-f]{64}')
_ADMIN = re.compile(r'[A-Za-z0-9._@-]{1,64}')
_CODES = frozenset({'bad_request', 'unknown_action', 'internal_error', 'peer_unavailable',
                    'session_closed', 'session_limit', 'challenge_required', 'challenge_expired',
                    'signature_invalid', 'auth_info_unavailable', 'not_available',
                    'line_too_long', 'protocol_version_mismatch'})
_MESSAGES = {
    'arguments': 'Arguments invalides ; consultez --aide.',
    'agent': 'Agent SSH absent : vérifiez SSH_AUTH_SOCK et la clé publique choisie.',
    'signature': 'Signature impossible avec la clé publique et l’agent SSH.',
    'namespace': 'Espace de noms du défi refusé.',
    'protocole': 'Réponse de présence invalide.',
    'delai': 'Délai de présence dépassé.',
    'transport': 'Connexion SSH interrompue ou impossible.',
    'terminal': 'La commande jeton exige une sortie vers un terminal.',
    'commande': 'Commande inconnue ; utilisez jeton ou fermer.',
}


def filtrer(texte):
    """Même catégories Unicode que server.commun.texte.filtrer, sans dépendance."""
    return ''.join('\ufffd' if unicodedata.category(c) in {'Cc', 'Cf', 'Zl', 'Zp', 'Cs', 'Co'}
                   else c for c in texte)


def message(texte, sortie=None):
    print(filtrer(texte), file=sys.stderr if sortie is None else sortie, flush=True)


class ErreurClient(Exception):
    """Code uniquement : aucune réponse brute ni donnée de signature dans l'erreur."""
    def __init__(self, code):
        self.code = code if code in _CODES or code in _MESSAGES else 'protocole'
        super().__init__(self.code)


def _duree(valeur):
    return (type(valeur) in (int, float) and math.isfinite(valeur) and 0 < valeur <= 3600)


def message_defi(defi, admin, namespace=ESPACE):
    if namespace != ESPACE:
        raise ErreurClient('namespace')
    if (not isinstance(defi, str) or _HEXA.fullmatch(defi) is None
            or not isinstance(admin, str) or _ADMIN.fullmatch(admin) is None):
        raise ErreurClient('protocole')
    return f'paresia-presence/1\n{defi}\n{admin}\n'.encode('utf-8')


def extraire_signature(enveloppe):
    """Retire seulement l'armure OpenSSH ; refuse tout préfixe, suffixe ou bruit."""
    if not isinstance(enveloppe, bytes) or len(enveloppe) > MAX_SIGNATURE + 256:
        raise ErreurClient('signature')
    lignes = enveloppe.splitlines()
    if (len(lignes) < 3 or lignes[0] != b'-----BEGIN SSH SIGNATURE-----'
            or lignes[-1] != b'-----END SSH SIGNATURE-----'):
        raise ErreurClient('signature')
    contenu = b''.join(lignes[1:-1])
    try:
        if not 0 < len(contenu) <= MAX_SIGNATURE:
            raise ValueError()
        blob = base64.b64decode(contenu, validate=True)
        if not blob.startswith(b'SSHSIG\x00\x00\x00\x01'):
            raise ValueError()
        return contenu.decode('ascii')
    except (ValueError, UnicodeError, binascii.Error):
        raise ErreurClient('signature') from None


def signer_defi(defi, admin, namespace, cle_publique, *, delai_s=10, ssh_keygen='ssh-keygen'):
    """ssh-keygen(1), -Y sign : clé publique dont la partie privée est dans l'agent.

    Le chemin fourni DOIT être celui d'une clé publique .pub. Aucun chargement
    de clé dans l'agent, aucune lecture de clé privée, aucune signature sur disque.
    """
    contenu = message_defi(defi, admin, namespace)
    if not _duree(delai_s) or Path(cle_publique).suffix != '.pub':
        raise ErreurClient('arguments')
    if not os.environ.get('SSH_AUTH_SOCK'):
        raise ErreurClient('agent')
    try:
        resultat = subprocess.run(
            [ssh_keygen, '-Y', 'sign', '-n', ESPACE, '-f', str(Path(cle_publique).absolute())],
            input=contenu, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=delai_s, check=False)
    except subprocess.TimeoutExpired:
        raise ErreurClient('delai') from None
    except OSError:
        raise ErreurClient('signature') from None
    if resultat.returncode:
        raise ErreurClient('signature')
    return extraire_signature(resultat.stdout)


def _objet(paires):
    resultat = {}
    for cle, valeur in paires:
        if cle in resultat:
            raise ValueError()
        resultat[cle] = valeur
    return resultat


class Session:
    """ouvrir(), jeton(), verifier(), fermer() ; les pings sont automatiques.

    Délais bornés, un seul échange à la fois. L'objet ne révèle jamais le jeton
    dans sa représentation. Le consommateur est responsable de toute copie
    obtenue par jeton() ou obtenir_jeton().
    """
    def __init__(self, hote, compte, cle_publique, admin, *, delai_s=10,
                 ouverture_s=30, ssh='ssh', ssh_keygen='ssh-keygen', diagnostic=False):
        if (not isinstance(hote, str) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.:-]{0,252}', hote) is None
                or not isinstance(compte, str) or re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', compte) is None
                or not isinstance(admin, str) or _ADMIN.fullmatch(admin) is None
                or Path(cle_publique).suffix != '.pub'
                or not _duree(delai_s) or not _duree(ouverture_s)):
            raise ErreurClient('arguments')
        self.admin, self.cle_publique = admin, str(Path(cle_publique).absolute())
        self.commande = [ssh, '-T', '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
                         '-i', self.cle_publique, '--', f'{compte}@{hote}']
        self.ssh_keygen = ssh_keygen
        self.diagnostic, self.derniere_ligne = bool(diagnostic), None
        self.delai_s, self.ouverture_s = delai_s, ouverture_s
        self.numero, self.heartbeat_s, self.timeout_s = 0, None, None
        self._jeton, self._proc, self._fil, self._erreur = None, None, None, None
        self._arret = threading.Event()
        self._verrou = threading.Lock()

    def __repr__(self):
        return f'<Session numero={self.numero}>'

    def _attendre(self, fd, ecriture, fin):
        reste = fin - time.monotonic()
        if reste <= 0:
            raise ErreurClient('delai')
        r, w, _ = select.select([] if ecriture else [fd], [fd] if ecriture else [], [], reste)
        if not (r or w):
            raise ErreurClient('delai')

    def _echanger(self, action, params=None, *, fin=None):
        fin = time.monotonic() + self.delai_s if fin is None else fin
        if not self._verrou.acquire(timeout=max(0, fin - time.monotonic())):
            raise ErreurClient('delai')
        try:
            identifiant = secrets.token_hex(8)
            q = {'proto': PROTO, 'id': identifiant, 'session': self.numero,
                 'action': 'presence/session/' + action, 'params': params or {}}
            donnees = memoryview((json.dumps(q, separators=(',', ':')) + '\n').encode())
            fd = self._proc.stdin.fileno()
            while donnees:
                self._attendre(fd, True, fin)
                try:
                    ecrits = os.write(fd, donnees)
                except BlockingIOError:
                    continue
                if not ecrits:
                    raise ErreurClient('transport')
                donnees = donnees[ecrits:]
            tampon = bytearray()
            fd = self._proc.stdout.fileno()
            while b'\n' not in tampon:
                self._attendre(fd, False, fin)
                try:
                    bloc = os.read(fd, min(65536, MAX_LIGNE + 1 - len(tampon)))
                except BlockingIOError:
                    continue
                if not bloc:
                    raise ErreurClient('transport')
                tampon.extend(bloc)
                if len(tampon) > MAX_LIGNE:
                    raise ErreurClient('protocole')
            if tampon.count(b'\n') != 1 or tampon[-1:] != b'\n':
                raise ErreurClient('protocole')
            r = json.loads(tampon.decode('utf-8'), object_pairs_hook=_objet)
            if (not isinstance(r, dict) or r.get('id') != identifiant
                    or type(r.get('ok')) is not bool):
                raise ErreurClient('protocole')
            if not r['ok']:
                erreur = r.get('error')
                if (set(r) != {'id', 'ok', 'error'} or not isinstance(erreur, dict)
                        or set(erreur) - {'code', 'detail'} or not isinstance(erreur.get('code'), str)
                        or erreur['code'] not in _CODES):
                    raise ErreurClient('protocole')
                raise ErreurClient(erreur['code'])
            if set(r) - {'id', 'ok', 'data'} or not isinstance(r.get('data', {}), dict):
                raise ErreurClient('protocole')
            return r.get('data', {})
        except (OSError, ValueError, UnicodeError, RecursionError):
            raise ErreurClient('protocole') from None
        finally:
            self._verrou.release()

    def ouvrir(self):
        if self._proc is not None or self._arret.is_set():
            raise ErreurClient('arguments')
        fin = time.monotonic() + self.ouverture_s
        try:
            self._proc = subprocess.Popen(self.commande, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE if self.diagnostic else subprocess.DEVNULL,
                                          bufsize=0)
            if self.diagnostic:
                os.set_blocking(self._proc.stderr.fileno(), False)
            os.set_blocking(self._proc.stdin.fileno(), False)
            os.set_blocking(self._proc.stdout.fileno(), False)
            defi = self._echanger('challenge', fin=fin)
            if set(defi) != {'challenge', 'namespace', 'expires_s'} or not _duree(defi['expires_s']):
                raise ErreurClient('protocole')
            fin = min(fin, time.monotonic() + defi['expires_s'])
            reste = min(self.delai_s, fin - time.monotonic())
            if reste <= 0:
                raise ErreurClient('delai')
            signature = signer_defi(defi['challenge'], self.admin, defi['namespace'], self.cle_publique,
                                    delai_s=reste, ssh_keygen=self.ssh_keygen)
            resultat = self._echanger('open', {'signature': signature}, fin=fin)
            if (set(resultat) != {'session', 'token', 'heartbeat_s', 'timeout_s'}
                    or type(resultat['session']) is not int or resultat['session'] < 1
                    or not isinstance(resultat['token'], str) or not _HEXA.fullmatch(resultat['token'])
                    or not _duree(resultat['heartbeat_s']) or not _duree(resultat['timeout_s'])
                    or resultat['heartbeat_s'] >= resultat['timeout_s']):
                raise ErreurClient('protocole')
            self.numero, self._jeton = resultat['session'], resultat['token']
            self.heartbeat_s, self.timeout_s = resultat['heartbeat_s'], resultat['timeout_s']
            self._fil = threading.Thread(target=self._battre, daemon=True)
            self._fil.start()
            return self
        except OSError:
            self._terminer()
            raise ErreurClient('transport') from None
        except BaseException:
            self._terminer()
            raise

    def _battre(self):
        while not self._arret.wait(self.heartbeat_s):
            try:
                if self._echanger('ping'):
                    raise ErreurClient('protocole')
            except ErreurClient as erreur:
                self._erreur = erreur.code
                self._jeton = None
                self._arret.set()
                return

    def verifier(self):
        if self._erreur:
            raise ErreurClient(self._erreur)
        if self._proc is None or self._proc.poll() is not None or self._jeton is None:
            self._jeton = None
            raise ErreurClient('transport')

    def jeton(self):
        self.verifier()
        return self._jeton

    def _terminer(self):
        self._jeton = None
        self.numero = 0
        if self._proc is None:
            return
        if self.diagnostic and self._proc.stderr is not None:
            # Dernière ligne d'erreur de ssh seulement (jamais de contenu de session : stdout reste muet).
            try:
                brut = os.read(self._proc.stderr.fileno(), 4096)
            except OSError:
                brut = b''
            lignes = [l for l in brut.decode('utf-8', 'replace').splitlines() if l.strip()]
            self.derniere_ligne = filtrer(lignes[-1])[:200] if lignes else None
            self._proc.stderr.close()
        for flux in (self._proc.stdin, self._proc.stdout):
            flux.close()
        try:
            self._proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=1)
        self._proc = None

    def fermer(self):
        self._arret.set()
        if self._fil is not None:
            self._fil.join(timeout=self.delai_s + 1)
        try:
            if self._proc is not None and self._jeton is not None and self._proc.poll() is None:
                if self._echanger('close'):
                    raise ErreurClient('protocole')
        finally:
            self._terminer()

    def __enter__(self):
        return self.ouvrir()

    def __exit__(self, *_):
        self.fermer()


def obtenir_jeton(session):
    """Interface importable : renvoie le secret en mémoire, sans affichage."""
    return session.jeton()


def commande(session, texte, *, sortie=None, erreurs=None):
    sortie = sys.stdout if sortie is None else sortie
    erreurs = sys.stderr if erreurs is None else erreurs
    if texte == 'fermer':
        return False
    if texte == 'jeton':
        if not sortie.isatty():
            raise ErreurClient('terminal')
        message('ATTENTION : secret de session, détruit à la fermeture ; ne pas enregistrer le terminal.', erreurs)
        message(obtenir_jeton(session), sortie)
    else:
        message(_MESSAGES['commande'], erreurs)
    return True


class _Arguments(argparse.ArgumentParser):
    def error(self, _):
        raise ErreurClient('arguments')


def main(argv=None):
    session = None
    try:
        analyseur = _Arguments(add_help=False, usage='client.py --hote HOTE --compte COMPTE --cle-publique CLE.pub --admin NOM')
        analyseur.add_argument('--aide', action='store_true')
        analyseur.add_argument('--version', action='store_true')
        analyseur.add_argument('--diagnostic', action='store_true')
        analyseur.add_argument('--hote')
        analyseur.add_argument('--compte', default='app')
        analyseur.add_argument('--cle-publique')
        analyseur.add_argument('--admin')
        analyseur.add_argument('--delai', type=float, default=10)
        analyseur.add_argument('--ouverture', type=float, default=30)
        args = analyseur.parse_args(argv)
        if args.aide:
            message('Usage : client.py --hote HOTE --compte COMPTE --cle-publique CLE.pub --admin NOM', sys.stdout)
            message('Options : --delai SECONDES (10), --ouverture SECONDES (30), --diagnostic (dernière ligne d’erreur de ssh), --version, --aide.', sys.stdout)
            message('SSH_AUTH_SOCK doit désigner votre agent SSH. Aucune clé privée n’est chargée par ce client.', sys.stdout)
            message('Commandes : jeton (affichage explicite sur terminal), fermer ; fin d’entrée ou Ctrl-C ferme la session.', sys.stdout)
            message('Sorties : 0 fermeture normale ; 1 erreur ; 2 arguments invalides ; 130 interruption.', sys.stdout)
            return 0
        if args.version:
            version = (Path(__file__).resolve().parents[2] / 'VERSION').read_text(encoding='ascii').strip()
            message(version, sys.stdout)
            return 0
        if not all((args.hote, args.cle_publique, args.admin)):
            raise ErreurClient('arguments')
        session = Session(args.hote, args.compte, args.cle_publique, args.admin,
                          delai_s=args.delai, ouverture_s=args.ouverture,
                          diagnostic=args.diagnostic)
        session.ouvrir()
        message(f'Session {session.numero} ouverte ; jeton reçu et contrôlé (64 caractères hexadécimaux).')
        tampon = bytearray()
        continuer = True
        while continuer:
            session.verifier()
            if not select.select([sys.stdin.fileno()], [], [], min(1, session.heartbeat_s))[0]:
                continue
            bloc = os.read(sys.stdin.fileno(), 65)
            if not bloc:
                break
            tampon.extend(bloc)
            while b'\n' in tampon:
                ligne, _, suite = tampon.partition(b'\n')
                tampon = bytearray(suite)
                if len(ligne) > 64:
                    raise ErreurClient('arguments')
                continuer = commande(session, ligne.decode('utf-8').strip())
                if not continuer:
                    break
            if len(tampon) > 64:
                raise ErreurClient('arguments')
        session.fermer()
        return 0
    except KeyboardInterrupt:
        return 130
    except ErreurClient as erreur:
        message(_MESSAGES.get(erreur.code, 'Présence refusée : ' + erreur.code))
        if session is not None and session.derniere_ligne:
            message('ssh : ' + session.derniere_ligne)
        return 2 if erreur.code == 'arguments' else 1
    except (OSError, UnicodeError, ValueError):
        message(_MESSAGES['transport'])
        return 1
    finally:
        if session is not None:
            try:
                session.fermer()
            except (ErreurClient, OSError, subprocess.TimeoutExpired):
                message(_MESSAGES['transport'])


if __name__ == '__main__':
    raise SystemExit(main())
