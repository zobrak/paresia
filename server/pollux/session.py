# Relais SSH de présence ; dépendances : bibliothèque standard et server.commun.
# Suivi des versions
#   0.1.1  2026-11-07  Niveau de journal lu dans la configuration de couches ([pollux-session.journal]).
#   3.0.0-alpha.41  2026-11-06  Relais de challenge, signature relayée sans vérification, analyse partagée (D20, D28).
#   3.0.0-alpha  2026-11-05  Relais borné, identité SSH et échéances indépendantes.
#   3.0.0-alpha  2026-11-05  Environnement restreint, échéance d'ouverture, lecture par blocs, journal de session.
#   3.0.0-alpha  2026-11-05  Échéance d'ouverture absolue depuis le démarrage, sans réarmement.
#   3.0.0-alpha  2026-11-05  connect borné par l'échéance restante (open_timeout_s comprise).
#   3.0.0-alpha  2026-11-05  Configuration en couches (D29) : ni --config ni variable lue, environnement ignoré.
#   3.0.0-alpha  2026-11-05  D18 : code 3 si Pollux ferme la connexion avec une requête en attente, 0 à la fin de l'entrée.
import base64
import binascii
import ipaddress
import os
import re
import select
import socket
import sys
import syslog
import time

from server.commun.cles_ssh import _champ, _lignes
from server.commun.sshsig import decoder_base64, SignatureInvalide
from server.commun.config import Option, lire, ErreurConfiguration
from server.commun.journal import Journal
from server.commun.jumeaux import (MAX_LINE, ErreurProtocole, decoder, encoder,
                                   valider, reponse, CODES_ERREUR)
from server.commun.texte import filtrer

SCHEMA = {
    ('transport', 'socket'): Option('chemin'),
    ('auth', 'authorized_keys'): Option('chemin'),
    ('auth', 'max_signature'): Option('limite', 2048),
    ('transport', 'timeout_s'): Option('duree', 90),
    ('transport', 'open_timeout_s'): Option('duree', 30),
    ('transport', 'max_line'): Option('limite', MAX_LINE),
}
ACTIONS = frozenset('presence/session/' + nom for nom in ('challenge', 'open', 'ping', 'close'))

BLOC = 65536


def configuration(argv=None, *, racine_systeme=None):
    """Couches fichier seulement (D29) : aucun argument, aucune variable d'environnement.

    L'environnement vient du client SSH : il n'agit sur aucune option, y compris
    PARESIA_POLLUX_SESSION_*. racine_systeme sert aux tests.
    """
    if argv:
        raise ErreurConfiguration('config_invalid_arguments')
    return lire('pollux-session', SCHEMA, argv=[], environnement=False,
                racine_systeme=racine_systeme, journal=True)


def identite(chemin, environ):
    try:
        euid = os.geteuid()
        cles = [ligne.split() for ligne in _lignes(environ['SSH_USER_AUTH'], {euid})
                if ligne.split() and ligne.split()[0] == 'publickey']
        if len(cles) != 1 or len(cles[0]) != 3:
            raise ValueError()
        _, type_cle, cle = cles[0]
        brut = base64.b64decode(cle, validate=True)
        taille = int.from_bytes(brut[:4], 'big')
        if not brut or brut[4:4 + taille] != type_cle.encode('ascii'):
            raise ValueError()
        admins = []
        for ligne in _lignes(chemin, {euid, 0}):
            if not ligne.strip() or ligne.lstrip().startswith('#'):
                continue
            premier, suite = _champ(ligne)
            if premier != type_cle:
                premier, suite = _champ(suite)
            if premier != type_cle:
                continue
            candidate, commentaire = _champ(suite)
            try:
                trouvee = base64.b64decode(candidate, validate=True) == brut
            except binascii.Error:
                continue
            if trouvee:
                commentaire = commentaire.rstrip(' \t')
                if not re.fullmatch(r'[A-Za-z0-9._@-]{1,64}', commentaire):
                    raise ValueError()
                admins.append(commentaire)
        if len(admins) != 1:
            raise ValueError()
        source = environ['SSH_CONNECTION'].split()[0]
        if '%' in source:
            raise ValueError()
        source = str(ipaddress.ip_address(source))
        return {'admin': admins[0], 'source': source}
    except (OSError, ValueError, UnicodeError, KeyError, IndexError, binascii.Error):
        raise ErreurProtocole('auth_info_unavailable', fermer=True) from None


def _reponse_pollux(objet, attentes):
    """Ne laisse passer que les réponses corrélées ; nettoie le détail affiché."""
    identifiant = objet.get('id')
    if (not isinstance(identifiant, str) or identifiant not in attentes
            or type(objet.get('ok')) is not bool
            or set(objet) - {'id', 'ok', 'data', 'error'}):
        raise ErreurProtocole(fermer=True)
    if objet['ok']:
        if 'error' in objet or ('data' in objet and not isinstance(objet['data'], dict)):
            raise ErreurProtocole(fermer=True)
    else:
        erreur = objet.get('error')
        if (not isinstance(erreur, dict) or set(erreur) - {'code', 'detail'}
                or not isinstance(erreur.get('code'), str)
                or erreur['code'] not in CODES_ERREUR or 'data' in objet):
            raise ErreurProtocole(fermer=True)
        if 'detail' in erreur:
            if not isinstance(erreur['detail'], str):
                raise ErreurProtocole(fermer=True)
            erreur['detail'] = filtrer(erreur['detail'])
    return objet


_RESULTATS = {0: 'normal', 1: 'timeout', 2: 'peer_unavailable', 3: 'error'}


class _Relais:
    def __init__(self, config, entree, sortie, env, journal):
        transport = config['transport']
        self.config, self.entree, self.sortie, self.env, self.journal = config, entree, sortie, env, journal
        self.delai, self.limite = transport['timeout_s'], transport['max_line']
        self.delai_ouverture = transport['open_timeout_s']
        self.attentes = {}
        self.tampons = {entree: bytearray()}
        self.vers_pollux, self.vers_app = bytearray(), bytearray()
        self.ping = None
        self.ouverture = time.monotonic() + self.delai_ouverture
        self.fin = None
        self.sortie_depuis = None
        self.sock = None

    def echeances(self):
        dates = [date + self.delai for _, date, _ in self.attentes.values()]
        if self.ping is not None:
            dates.append(self.ping + self.delai)
        else:
            dates.append(self.ouverture)
        if self.sortie_depuis is not None:
            dates.append(self.sortie_depuis + self.delai)
        return dates

    def boucle(self):
        entree, sortie, limite = self.entree, self.sortie, self.limite
        while True:
            maintenant = time.monotonic()
            echeances = self.echeances()
            if min(echeances) <= maintenant:
                self.journal.ecrire('warning', 'session_timeout')
                return 1
            if self.fin is not None and not self.vers_app:
                return self.fin
            lectures = [] if self.fin is not None else [entree]
            if self.sock is not None and self.fin is None:
                lectures.append(self.sock.fileno())
            # Contre-pression : aucune accumulation non bornée de réponses.
            if len(self.vers_app) >= limite:
                lectures = []
            ecritures = [sortie] if self.vers_app else []
            if self.sock is not None and self.vers_pollux and self.fin is None:
                ecritures.append(self.sock.fileno())
            prets, inscriptibles, _ = select.select(
                lectures, ecritures, [], max(0, min(echeances) - maintenant))
            for fd in inscriptibles:
                tampon = self.vers_app if fd == sortie else self.vers_pollux
                try:
                    taille = os.write(fd, tampon)
                except BlockingIOError:
                    continue
                del tampon[:taille]
                if fd == sortie and not tampon:
                    self.sortie_depuis = None
            for fd in prets:
                if self.fin is not None:
                    break
                try:
                    bloc = os.read(fd, BLOC)
                except BlockingIOError:
                    continue
                if not bloc:
                    # D18 : fermeture par Pollux avec une requête sans réponse = panne (3).
                    self.fin = 3 if self.attentes and fd != entree else 0
                    break
                self.traiter_bloc(fd, bloc)
            if self.vers_app and self.sortie_depuis is None:
                self.sortie_depuis = time.monotonic()

    def traiter_bloc(self, fd, bloc):
        tampon = self.tampons[fd]
        position = 0
        while position < len(bloc) and self.fin is None:
            lf = bloc.find(b'\n', position)
            suivant = len(bloc) if lf < 0 else lf + 1
            total = len(tampon) + suivant - position
            try:
                if total > self.limite or (lf < 0 and total >= self.limite):
                    raise ErreurProtocole('line_too_long', fermer=True)
                tampon.extend(bloc[position:suivant])
                position = suivant
                if lf < 0:
                    return
                ligne = bytes(tampon)
                tampon.clear()
                self.ligne(fd, decoder(ligne))
            except ErreurProtocole as erreur:
                tampon.clear()
                self.vers_app.extend(encoder(reponse(erreur.identifiant, code=erreur.code)))
                self.journal.ecrire('warning', 'request_rejected', result=erreur.code)
                if erreur.fermer or fd != self.entree:
                    self.fin = 3

    def ligne(self, fd, objet):
        if fd != self.entree:
            self.de_pollux(objet)
        else:
            self.de_app(objet)

    def de_pollux(self, objet):
        objet = _reponse_pollux(objet, self.attentes)
        action, _, identite_ouverte = self.attentes.pop(objet['id'])
        if action.endswith('/open'):
            if objet['ok'] and self.ping is None:
                self.ping = time.monotonic()
                data = objet.get('data', {})
                session = data.get('session')
                champs = dict(identite_ouverte)
                if type(session) is int:
                    champs['session'] = session
                self.journal.ecrire('info', 'session_opened', **champs)
        self.vers_app.extend(encoder(objet))
        if action.endswith('/close') and objet['ok']:
            self.fin = 0

    def de_app(self, objet):
        valider(objet, ACTIONS)
        action, identifiant = objet['action'], objet['id']
        if identifiant in self.attentes or len(self.attentes) >= 128 or len(self.vers_pollux) >= self.limite:
            raise ErreurProtocole(identifiant=identifiant)
        auteur = {}
        if action.endswith(('/challenge', '/open')):
            signature = objet['params'].get('signature')
            presente = action.endswith('/open') and 'signature' in objet['params']
            if presente:
                try:
                    decoder_base64(signature, self.config['auth']['max_signature'])
                except SignatureInvalide:
                    raise ErreurProtocole(identifiant=identifiant) from None
            try:
                auteur = identite(self.config['auth']['authorized_keys'], self.env)
            except ErreurProtocole as erreur:
                erreur.identifiant = identifiant
                raise
            objet['params'] = dict(auteur)
            if presente:
                objet['params']['signature'] = signature
        elif objet['params']:
            raise ErreurProtocole(identifiant=identifiant)
        if self.sock is None:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.setblocking(False)
            # Délai de connexion borné par le délai et par la plus proche échéance
            # (dont open_timeout_s absolue tant qu'aucun open n'a réussi).
            limite_connexion = min([time.monotonic() + self.delai] + self.echeances())
            try:
                while True:
                    try:
                        sock.connect(self.config['transport']['socket'])
                        break
                    except (BlockingIOError, InterruptedError):
                        reste = limite_connexion - time.monotonic()
                        if reste <= 0:
                            raise OSError('connect timeout')
                        time.sleep(min(.02, reste))
            except OSError:
                sock.close()
                self.vers_app.extend(encoder(reponse(identifiant, code='peer_unavailable')))
                self.fin = 2
                self.journal.ecrire('error', 'peer_unavailable')
                return
            sock.setblocking(False)
            self.sock = sock
            self.tampons[sock.fileno()] = bytearray()
        self.vers_pollux.extend(encoder(objet))
        self.attentes[identifiant] = (action, time.monotonic(), auteur)
        if action.endswith('/ping') and self.ping is not None:
            self.ping = time.monotonic()


def relayer(config, *, entree=0, sortie=1, environ=None, journal=None):
    env = os.environ if environ is None else environ
    journal = journal or Journal('pollux-session', destination='syslog')
    relais = _Relais(config, entree, sortie, env, journal)
    modes = {fd: os.get_blocking(fd) for fd in {entree, sortie}}
    try:
        for fd in modes:
            os.set_blocking(fd, False)
        code = relais.boucle()
    except (BrokenPipeError, ConnectionResetError):
        code = 3 if relais.attentes else 0
    except OSError:
        journal.ecrire('error', 'transport_error')
        code = 3
    finally:
        if relais.sock is not None:
            relais.sock.close()
        for fd, mode in modes.items():
            os.set_blocking(fd, mode)
    journal.ecrire('info', 'session_ended', result=_RESULTATS[code], exit_code=code)
    return code


def main(argv=None):
    journal = Journal('pollux-session', destination='syslog')
    try:
        syslog.openlog('pollux-session')
        config = configuration(argv)
        journal.definir_niveau(config['journal']['niveau'])
        return relayer(config, journal=journal)
    except ErreurConfiguration as erreur:
        champs = {nom: valeur for nom, valeur in
                  (('cause', erreur.code), ('section', erreur.section), ('option', erreur.cle)) if valeur}
        _journaliser(journal, 'configuration_error', **champs)
        return 3
    except Exception:
        _journaliser(journal, 'internal_error')
        return 3


def _journaliser(journal, evenement, **champs):
    try:
        journal.ecrire('error', evenement, **champs)
    except Exception:
        pass


if __name__ == '__main__':
    sys.exit(main())
