# Sessions en mémoire ; dépendances : bibliothèque standard, server.commun.
# Suivi des versions
#   0.1.15  2026-11-08  Journal d'activité : ouverture et fermeture de session, identité et nombre de sessions.
#   3.0.0-alpha.41  2026-11-06  Abonnement à la fermeture de session, rappels hors verrou (D111).
#   3.0.0-alpha  2026-11-05  Création et révocation des jetons liés à Pollux.
#   3.0.0-alpha  2026-11-05  Plafond de sessions, close étranger = session_closed, fermeture sûre.
#   3.0.0-alpha  2026-11-05  Source refusée si elle contient '%' (identifiant de zone IPv6).
from dataclasses import dataclass, field
import hmac
import ipaddress
import re
import secrets
import threading

from server.commun.jumeaux import reponse


@dataclass(repr=False)
class Session:
    connexion: object = field(repr=False)
    admin: str
    source: str
    token: str = field(repr=False)


class Sessions:
    def __init__(self, journal, max_sessions=1024, activite=None):
        self.journal = journal
        self.activite = activite
        self.max_sessions = max_sessions
        self._sessions = {}
        self._abonnes = {}
        self._suivante = 1
        self._verrou = threading.RLock()

    def traiter(self, requete, connexion):
        identifiant, params = requete['id'], requete['params']
        with self._verrou:
            if requete['action'] == 'presence/session/open':
                if (requete['session'] != 0 or set(params) != {'admin', 'source'}
                        or not isinstance(params['admin'], str)
                        or not re.fullmatch(r'[A-Za-z0-9._@-]{1,64}', params['admin'])
                        or not isinstance(params['source'], str)
                        or len(params['source']) > 64
                        or '%' in params['source']):
                    return reponse(identifiant, code='bad_request')
                try:
                    source = str(ipaddress.ip_address(params['source']))
                except ValueError:
                    return reponse(identifiant, code='bad_request')
                if sum(1 for s in self._sessions.values()
                       if s.connexion is connexion) >= self.max_sessions:
                    return reponse(identifiant, code='session_limit')
                numero = self._suivante
                self._suivante += 1
                session = Session(connexion, params['admin'], source, secrets.token_hex(32))
                self._sessions[numero] = session
                self._journaliser('session_opened', numero, session)
                return reponse(identifiant, {'session': numero, 'token': session.token})
            if requete['action'] != 'presence/session/close':
                return reponse(identifiant, code='unknown_action')
            if params:
                return reponse(identifiant, code='bad_request')
            numero = requete['session']
            session = self._sessions.get(numero)
            if session is None or session.connexion is not connexion:
                # Même réponse qu'une session inconnue : rien révélé ni détruit.
                return reponse(identifiant, code='session_closed')
        self._detruire(numero)
        return reponse(identifiant)

    def _journaliser(self, evenement, numero, session):
        self.journal.ecrire('info', evenement, session=numero,
                            admin=session.admin, source=session.source)
        if self.activite is not None:
            try:
                self.activite.session(
                    'session_open' if evenement == 'session_opened' else 'session_close',
                    numero, session.admin, session.source)
            except Exception:
                pass

    def nombre(self):
        with self._verrou:
            return len(self._sessions)

    def identite(self, numero):
        """(admin, source) de la session, ou None si elle n'existe plus."""
        with self._verrou:
            session = self._sessions.get(numero)
            return None if session is None else (session.admin, session.source)

    def _detruire(self, numero):
        with self._verrou:
            session = self._sessions.pop(numero, None)
            if session is None:
                return
            session.token = ''  # détruit avant tout rappel et toute écriture au journal
            rappels = self._abonnes.pop(numero, ())
        try:
            self._journaliser('session_closed', numero, session)
        finally:
            for rappel in rappels:
                self._notifier(rappel)

    @staticmethod
    def _notifier(rappel):
        try:
            rappel()
        except Exception:
            pass

    def abonner(self, numero, rappel):
        """Notifie aussi une session déjà détruite, sans fenêtre de perte du rappel."""
        with self._verrou:
            if numero in self._sessions:
                self._abonnes.setdefault(numero, set()).add(rappel)
                return
        self._notifier(rappel)

    def desabonner(self, numero, rappel):
        with self._verrou:
            rappels = self._abonnes.get(numero)
            if rappels is not None:
                rappels.discard(rappel)
                if not rappels:
                    self._abonnes.pop(numero, None)

    def fermeture(self, connexion):
        with self._verrou:
            numeros = [n for n, s in self._sessions.items() if s.connexion is connexion]
        echec = False
        for numero in numeros:
            try:
                self._detruire(numero)
            except Exception:
                echec = True
        try:
            self.journal.ecrire('info', 'pollux_disconnected', sessions=len(numeros))
        except Exception:
            echec = True
        if echec:
            # Tous les jetons sont déjà détruits ; l'appelant journalise l'échec.
            raise RuntimeError('cleanup_failed')

    def verifier(self, token):
        # Même parcours complet pour un jeton connu, inconnu ou mal formé.
        candidat = token.encode('utf-8')
        numero = None
        with self._verrou:
            for n, session in self._sessions.items():
                correspond = hmac.compare_digest(candidat, session.token.encode('ascii'))
                if correspond:
                    numero = n
        return numero
