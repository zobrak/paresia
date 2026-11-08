# SPDX-License-Identifier: AGPL-3.0-or-later
# Présence Pollux ; dépendances : bibliothèque standard et server.commun.
#
# Verrous et ordre des échanges (T010, D19, D27) :
#   - Pollux._verrou (global, réentrant) ne protège que l'état en mémoire : table des
#     sessions, client Romulus, réservations d'ouverture. Aucun appel à un pair n'est
#     fait sous ce verrou (seul un appelant extérieur de _fermer peut le tenir).
#   - Session.verrou (un par session) ordonne les échanges avec Castor : un ping en cours
#     précède toujours le castor/light/close de la même session, et aucun ping ne le suit.
#   - Ordre de prise fixe : verrou global avant verrou de session, jamais l'inverse ;
#     sous un verrou de session, le verrou global n'est jamais demandé.
#   - Une fermeture se fait en deux étapes : décision sous le verrou global (_decider),
#     puis notifications hors verrou (_notifier), une seule fois par pair et par session.
#   - Les fils de notification sont bornés : au plus un fil Romulus et un fil Castor par
#     session décidée, et les sessions décidées sont limitées par `maximum`.
# Suivi des versions
#   3.0.0-alpha.41  2026-11-06  Défi puis ouverture signée SSHSIG, fermeture après refus sans réarmer l'échéance (D20, D28, D38).
#   3.0.0-alpha.32  2026-11-06  Échanges avec Romulus et Castor hors du verrou global, état et verrou par session (T010, D19, D27).
#   3.0.0-alpha  2026-11-05  Journal de fermeture protégé, umask 0o177 au démarrage (T002, cycle 2).
#   3.0.0-alpha  2026-11-05  Isolation des connexions, validation des réponses, expiration robuste (T002, cycle 1).
#   3.0.0-alpha  2026-11-05  Sessions, expiration et fermeture sûre (T002).
from dataclasses import dataclass, field
import ipaddress
import os
import re
import secrets
import threading
import time

from server.commun.client import Connexion, PairIndisponible
from server.commun.cles_ssh import autorisee
from server.commun.config import ErreurConfiguration, Option
from server.commun.journal import Journal
from server.commun.jumeaux import ErreurProtocole, MAX_LINE, reponse
from server.commun.serveur import Serveur
from server.commun.sshsig import SignatureInvalide, decoder_base64, verifier

# Actions que Pollux envoie à chacun de ses pairs.
ACTIONS_PAIRS = {
    'castor': frozenset({'castor/light/ping', 'castor/light/close'}),
    'romulus': frozenset({'presence/session/open', 'presence/session/close'}),
}

# Délai accordé à l'écriture de la réponse d'un refus avant la fermeture de la connexion.
DELAI_FERMETURE_S = 0.5

SCHEMA = {
    ('signature', 'authorized_keys'): Option('chemin'),
    ('signature', 'challenge_ttl_s'): Option('duree', 60),
    ('signature', 'namespace'): Option('texte'),
    ('signature', 'max_signature'): Option('limite', 2048),
    ('sessions', 'socket'): Option('chemin'),
    ('sessions', 'uid'): Option('uid'),
    ('sessions', 'gid'): Option('uid'),
    ('sessions', 'heartbeat_s'): Option('duree', 30),
    ('sessions', 'timeout_s'): Option('duree', 90),
    ('sessions', 'maximum'): Option('limite', 16),
    ('relay', 'socket'): Option('chemin'),
    ('relay', 'uid'): Option('uid'),
    ('relay', 'gid'): Option('uid'),
    ('romulus', 'socket'): Option('chemin'),
    ('romulus', 'uid'): Option('uid'),
    ('castor', 'socket'): Option('chemin'),
    ('castor', 'uid'): Option('uid'),
    ('transport', 'delai_s'): Option('duree', 120),
    ('transport', 'pair_delai_s'): Option('duree', 5),
    ('transport', 'max_line'): Option('limite', MAX_LINE),
    ('transport', 'max_connexions'): Option('limite', 64),
    ('sessions', 'verification_s'): Option('duree', 0.1),
}


def requete(action, session=0, params=None):
    return {'proto': 'jumeaux/1', 'id': secrets.token_hex(8),
            'session': session, 'action': action, 'params': params or {}}


@dataclass
class Session:
    numero: int
    admin: str
    source: str
    dernier_ping: float
    connexion: object
    # ouverte, en_fermeture, fermee ; modifié sous le verrou global (ouverte vers
    # en_fermeture) ou sous le verrou de la session (en_fermeture vers fermee).
    etat: str = 'ouverte'
    verrou: object = field(default_factory=threading.Lock, repr=False, compare=False)


@dataclass
class Fermeture:
    """Décision de fermeture prise sous le verrou global ; client Romulus à notifier ou None."""
    session: Session
    client: object = None


class Pollux:
    """Verrou global réduit à l'état en mémoire, verrou par session pour Castor.

    Aucun jeton n'est conservé dans l'état ; il traverse seulement la réponse.
    """
    def __init__(self, configuration, *, journal=None):
        sessions = configuration['sessions']
        if sessions['heartbeat_s'] >= sessions['timeout_s']:
            raise ErreurConfiguration('config_invalid', 'sessions', 'heartbeat_s')
        if sessions['verification_s'] > sessions['timeout_s']:
            raise ErreurConfiguration('config_invalid', 'sessions', 'verification_s')
        self.config = configuration
        self.journal = journal if journal is not None else Journal('pollux')
        self.sessions = {}
        self._defis = set()
        self._fermetures = {}
        self._verrou = threading.RLock()
        self._arret = threading.Event()
        self._romulus = None
        self._reservations = 0
        self._fil = None
        self._fils_notification = set()
        self._verrou_fils = threading.Lock()
        transport = configuration['transport']
        self.serveurs = []
        for section, actions, traitement in (
            ('sessions', {'presence/session/' + a for a in ('challenge', 'open', 'ping', 'close')}, self._application),
            ('relay', {'presence/relay/ping'}, self._relais),
        ):
            options = configuration[section]
            self.serveurs.append(Serveur(
                options['socket'], {options['uid']}, actions, traitement,
                gid=options['gid'], max_line=transport['max_line'],
                delai=transport['delai_s'], max_connexions=transport['max_connexions'],
                journal=self.journal,
                fermeture=self._deconnexion if section == 'sessions' else None))

    def _client(self, pair, **options):
        return Connexion(self.config[pair]['socket'],
                         self.config['transport']['pair_delai_s'],
                         max_line=self.config['transport']['max_line'],
                         uid_serveur=self.config[pair]['uid'],
                         actions=ACTIONS_PAIRS[pair], **options)

    def _castor(self, action, numero):
        try:
            with self._client('castor') as client:
                resultat = client.appeler(requete(action, numero))
            if resultat['ok']:
                return True
        except (PairIndisponible, ErreurProtocole):
            pass
        self.journal.ecrire('warning', 'peer_unavailable', peer='castor',
                            action=action, session=numero)
        return False

    # --- fils de notification -------------------------------------------------

    def _lancer(self, cible, *args):
        """Lance un fil suivi, qui intercepte ses exceptions ; renvoie le fil (ou None si exécuté ici)."""
        def corps():
            try:
                cible(*args)
            except Exception:
                self._echec_expiration()
            finally:
                with self._verrou_fils:
                    self._fils_notification.discard(threading.current_thread())

        fil = threading.Thread(target=corps, daemon=True)
        with self._verrou_fils:
            self._fils_notification.add(fil)
        try:
            fil.start()
        except RuntimeError:
            with self._verrou_fils:
                self._fils_notification.discard(fil)
            try:
                cible(*args)
            except Exception:
                self._echec_expiration()
            return None
        return fil

    def _notifier(self, fermetures, *, attendre=True):
        """Étape (b) : notifications hors verrou global, Romulus et Castor indépendants.

        Un seul fil vers Romulus (ordre des numéros), un fil Castor par session.
        """
        fermetures = sorted((f for f in fermetures if f is not None),
                            key=lambda f: f.session.numero)
        if not fermetures:
            return
        fils = []
        a_romulus = [f for f in fermetures if f.client is not None]
        if a_romulus:
            fils.append(self._lancer(self._notifier_romulus, a_romulus))
        for fermeture in fermetures:
            fils.append(self._lancer(self._notifier_castor, fermeture.session))
        if attendre:
            for fil in fils:
                if fil is not None:
                    fil.join()

    def _notifier_castor(self, session):
        with session.verrou:
            try:
                self._castor('castor/light/close', session.numero)
            finally:
                session.etat = 'fermee'

    def _notifier_romulus(self, fermetures):
        for fermeture in fermetures:
            numero, client = fermeture.session.numero, fermeture.client
            try:
                resultat = client.appeler(requete('presence/session/close', numero))
                if not resultat['ok']:
                    self.journal.ecrire('warning', 'peer_unavailable', peer='romulus',
                                        action='presence/session/close', session=numero)
            except (PairIndisponible, ErreurProtocole):
                self.journal.ecrire('warning', 'peer_unavailable', peer='romulus',
                                    action='presence/session/close', session=numero)
                self._lancer(self._perte_romulus, client)  # sans le verrou global ici
            except Exception:
                self._echec_expiration()

    # --- décisions, sous le verrou global ---------------------------------------

    def _decider(self, numero, motif, *, notifier_romulus=True):
        """Étape (a) : retire la session de la table et ferme sa connexion si besoin."""
        with self._verrou:
            session = self.sessions.pop(numero, None)
            if session is None:
                return None
            session.etat = 'en_fermeture'
            if session.connexion.etat.get('session') == numero:
                session.connexion.etat.pop('session', None)
            if motif != 'close':
                session.connexion.fermer()
            try:
                self.journal.ecrire('info', 'session_closed', session=numero,
                                    admin=session.admin, source=session.source, reason=motif)
            except Exception:
                pass  # un journal défaillant ne doit pas empêcher les notifications
            return Fermeture(session, self._romulus if notifier_romulus else None)

    def _decider_perte(self, client):
        with self._verrou:
            if client is not self._romulus:
                return []
            client.fermer()
            self._romulus = None
            # Fermer tous les transports avant les appels Castor potentiellement lents.
            for session in self.sessions.values():
                session.connexion.fermer()
            return [self._decider(numero, 'romulus_lost', notifier_romulus=False)
                    for numero in sorted(self.sessions)]

    def _decider_expirees(self):
        decisions = []
        with self._verrou:
            maintenant = time.monotonic()
            for numero, session in sorted(self.sessions.items()):
                if maintenant - session.dernier_ping >= self.config['sessions']['timeout_s']:
                    try:
                        decisions.append(self._decider(numero, 'timeout'))
                    except Exception:
                        self._echec_expiration()
        return decisions

    def _decider_preliminaires(self):
        """Perte de Romulus constatée puis expirations, sous le verrou global."""
        with self._verrou:
            decisions = []
            if self._romulus is not None and self._romulus.rompue:
                decisions += self._decider_perte(self._romulus)
            return decisions + self._decider_expirees()

    def _perte_romulus(self, client):
        with self._verrou:
            decisions = self._decider_perte(client)
        self._notifier(decisions, attendre=False)

    def _fermer(self, numero, motif, *, notifier_romulus=True):
        """Décision puis notifications, de façon synchrone (appelable en tenant _verrou)."""
        self._notifier([self._decider(numero, motif, notifier_romulus=notifier_romulus)])

    def _deconnexion(self, contexte):
        with self._verrou:
            self._defis.discard(contexte)
            self._fermetures.pop(contexte, None)
            contexte.etat.pop('defi', None)
            numero = contexte.etat.get('session')
            session = self.sessions.get(numero)
            if session is not None and session.connexion is contexte:
                decision = self._decider(numero, 'disconnect')
            else:
                decision = None
                if numero is None and contexte.etat.get('reservation'):
                    contexte.etat['deconnecte'] = True  # ouverture en cours : fermée à l'insertion
        self._notifier([decision])

    def _echec_expiration(self):
        try:
            self.journal.ecrire('error', 'expiry_failed')
        except Exception:
            pass

    def _surveiller(self):
        while not self._arret.wait(self.config['sessions']['verification_s']):
            try:
                with self._verrou:
                    maintenant = time.monotonic()
                    for contexte, echeance in list(self._fermetures.items()):
                        if maintenant >= echeance:
                            del self._fermetures[contexte]
                            contexte.fermer()
                    for contexte in list(self._defis):
                        if time.monotonic() >= contexte.etat['defi']['echeance']:
                            self._defis.discard(contexte)
                            contexte.etat.pop('defi', None)
                            contexte.etat['auth_terminee'] = True
                            self.journal.ecrire('info', 'auth_failed', reason='expired',
                                                connexion=contexte.etat['connexion'])
                            contexte.fermer()
                self._notifier(self._decider_expirees(), attendre=False)
            except Exception:
                self._echec_expiration()

    # --- ouverture ----------------------------------------------------------------

    def _valider_identite(self, q, champs):
        """Contrôle de forme commun au défi et à l'ouverture."""
        params = q['params']
        if (q['session'] != 0 or set(params) != champs
                or not isinstance(params['admin'], str)
                or re.fullmatch(r'[A-Za-z0-9._@-]{1,64}', params['admin']) is None
                or not isinstance(params['source'], str) or len(params['source']) > 128):
            return reponse(q['id'], code='bad_request')
        # Adresse seule : ni identifiant de zone IPv6 ('%'), ni espace, ni saut de ligne.
        if re.fullmatch(r'[0-9A-Fa-f:.]{2,45}', params['source']) is None:
            return reponse(q['id'], code='bad_request')
        try:
            ipaddress.ip_address(params['source'])
        except ValueError:
            return reponse(q['id'], code='bad_request')
        return None

    def _valider_ouverture(self, q, contexte):
        """La forme est contrôlée avant de consommer le défi ; aucun accès au fichier ici."""
        erreur = self._valider_identite(q, {'admin', 'source', 'signature'})
        if erreur is not None:
            return erreur
        try:
            decoder_base64(q['params']['signature'], self.config['signature']['max_signature'])
        except SignatureInvalide:
            return reponse(q['id'], code='bad_request')
        if 'session' in contexte.etat or contexte.etat.get('reservation'):
            return reponse(q['id'], code='bad_request')
        return None

    def _refuser_auth(self, q, contexte, code, cause):
        with self._verrou:
            self._defis.discard(contexte)
            contexte.etat.pop('defi', None)
            contexte.etat['auth_terminee'] = True
            # Le serveur commun écrit la réponse après le retour du traitement : la
            # surveillance ferme la connexion un court instant plus tard.
            # Échéance posée au premier refus seulement : un refus répété ne la repousse pas.
            self._fermetures.setdefault(contexte, time.monotonic() + DELAI_FERMETURE_S)
        self.journal.ecrire('info', 'auth_failed', reason=cause,
                            connexion=contexte.etat.get('connexion'))
        return reponse(q['id'], code=code)

    def _defier(self, q, contexte):
        erreur = self._valider_identite(q, {'admin', 'source'})
        if erreur is not None:
            return erreur
        with self._verrou:
            if contexte.etat.get('defi_emis') or contexte.etat.get('auth_terminee'):
                return self._refuser_auth(q, contexte, 'challenge_required', 'no_challenge')
            if 'session' in contexte.etat or contexte.etat.get('reservation'):
                return reponse(q['id'], code='bad_request')
            options = self.config['signature']
            defi = dict(q['params'], valeur=secrets.token_hex(32),
                        echeance=time.monotonic() + options['challenge_ttl_s'])
            contexte.etat.update(defi=defi, defi_emis=True, connexion=secrets.token_hex(8))
            self._defis.add(contexte)
        self.journal.ecrire('info', 'challenge_issued', **q['params'],
                            connexion=contexte.etat['connexion'])
        return reponse(q['id'], {'challenge': defi['valeur'], 'namespace': options['namespace'],
                                'expires_s': options['challenge_ttl_s']})

    def _authentifier(self, q, contexte):
        with self._verrou:
            defi = contexte.etat.pop('defi', None)
            self._defis.discard(contexte)
        if defi is None:
            return self._refuser_auth(q, contexte, 'challenge_required', 'no_challenge')
        if time.monotonic() >= defi['echeance']:
            return self._refuser_auth(q, contexte, 'challenge_expired', 'expired')
        params, options = q['params'], self.config['signature']
        if any(params[champ] != defi[champ] for champ in ('admin', 'source')):
            return self._refuser_auth(q, contexte, 'signature_invalid', 'bad_signature')
        message = f"paresia-presence/1\n{defi['valeur']}\n{defi['admin']}\n".encode('utf-8')
        try:
            verifier(params['signature'], message, options['namespace'],
                     lambda genre, cle: autorisee(options['authorized_keys'], params['admin'],
                         genre, cle, self.config['sessions']['uid'], self.journal),
                     maximum=options['max_signature'])
        except ImportError:
            return self._refuser_auth(q, contexte, 'not_available', 'not_available')
        except SignatureInvalide as erreur:
            return self._refuser_auth(q, contexte, 'signature_invalid', erreur.cause)
        self.journal.ecrire('info', 'auth_ok', admin=params['admin'], source=params['source'],
                            connexion=contexte.etat['connexion'])
        return None

    def _liberer(self, contexte):
        with self._verrou:
            if contexte.etat.pop('reservation', None):
                self._reservations -= 1

    def _ouvrir(self, q, contexte):
        invalide = self._valider_ouverture(q, contexte)
        if invalide is not None:
            return invalide
        invalide = self._authentifier(q, contexte)
        if invalide is not None:
            return invalide
        with self._verrou:
            if len(self.sessions) + self._reservations >= self.config['sessions']['maximum']:
                return reponse(q['id'], code='session_limit')
            if self._romulus is None:
                self._romulus = self._client('romulus', rupture=self._perte_romulus)
            client = self._romulus
            self._reservations += 1
            contexte.etat['reservation'] = True
        try:
            return self._ouvrir_chez_romulus(q, contexte, client)
        finally:
            self._liberer(contexte)
            contexte.etat.pop('deconnecte', None)

    def _ouvrir_chez_romulus(self, q, contexte, client):
        params = {champ: q['params'][champ] for champ in ('admin', 'source')}
        try:
            resultat = client.appeler(requete('presence/session/open', params=params))
        except (PairIndisponible, ErreurProtocole):
            self._perte_romulus(client)
            return reponse(q['id'], code='peer_unavailable')
        if not resultat['ok']:
            return reponse(q['id'], code=resultat['error']['code'])
        data = resultat.get('data')
        # Vérification structurelle seulement : Pollux n'authentifie aucun jeton.
        recu = data.get('session') if isinstance(data, dict) else None
        forme_valide = (isinstance(data, dict) and set(data) == {'session', 'token'}
                        and type(recu) is int and recu >= 1
                        and isinstance(data['token'], str)
                        and re.fullmatch(r'[A-Za-z0-9_-]{16,256}', data['token']) is not None)
        with self._verrou:
            libre = type(recu) is int and recu >= 1 and recu not in self.sessions
            if forme_valide and libre and client is self._romulus:
                self._liberer(contexte)
                numero = recu
                contexte.etat['session'] = numero
                self.sessions[numero] = Session(numero, params['admin'], params['source'],
                                                time.monotonic(), contexte)
                self.journal.ecrire('info', 'session_opened', session=numero,
                                    admin=params['admin'], source=params['source'])
                if contexte.etat.get('deconnecte'):
                    fermeture = self._decider(numero, 'disconnect')
                    reponse_finale = reponse(q['id'], code='session_closed')
                else:
                    fermeture = None
                    reponse_finale = reponse(q['id'], {**data,
                        'heartbeat_s': self.config['sessions']['heartbeat_s'],
                        'timeout_s': self.config['sessions']['timeout_s']})
            else:
                fermeture = reponse_finale = None
        if reponse_finale is not None:
            self._notifier([fermeture])
            return reponse_finale
        if client is not self._romulus:
            # Romulus perdu pendant l'ouverture : la connexion rompue détruit le jeton (D9).
            return reponse(q['id'], code='peer_unavailable')
        if libre and not forme_valide:
            try:
                client.appeler(requete('presence/session/close', recu))
            except (PairIndisponible, ErreurProtocole):
                pass
        self._perte_romulus(client)
        return reponse(q['id'], code='peer_unavailable')

    # --- requêtes -------------------------------------------------------------------

    def _rafraichir(self, q, contexte, recu):
        """Ping à la réception, avant l'attente du verrou (sans fausse expiration)."""
        if q['action'] != 'presence/session/ping' or q['params']:
            return
        numero = contexte.etat.get('session')
        session = self.sessions.get(numero)
        if (session is None or q['session'] != numero or session.connexion is not contexte
                or recu - session.dernier_ping >= self.config['sessions']['timeout_s']):
            return
        session.dernier_ping = max(session.dernier_ping, recu)

    def _application(self, q, contexte):
        self._rafraichir(q, contexte, time.monotonic())
        with self._verrou:
            if self._arret.is_set():
                return reponse(q['id'], code='peer_unavailable')
            preliminaires = self._decider_preliminaires()
            propres = []
            if q['action'] in ('presence/session/open', 'presence/session/challenge'):
                resultat = None
            else:
                resultat = self._traiter_session(q, contexte, propres)
        self._notifier(preliminaires, attendre=False)
        self._notifier(propres)
        if resultat is None:
            if q['action'] == 'presence/session/challenge':
                return self._defier(q, contexte)
            return self._ouvrir(q, contexte)
        return resultat

    def _traiter_session(self, q, contexte, decisions):
        """Ping ou close, sous le verrou global ; ajoute la décision éventuelle à decisions."""
        if q['params']:
            return reponse(q['id'], code='bad_request')
        numero = contexte.etat.get('session')
        if numero is not None and q['session'] != numero:
            return reponse(q['id'], code='bad_request')
        session = self.sessions.get(numero)
        if session is None or session.connexion is not contexte:
            return reponse(q['id'], code='session_closed')
        if q['action'] == 'presence/session/ping':
            session.dernier_ping = max(session.dernier_ping, time.monotonic())
        else:
            decisions.append(self._decider(numero, 'close'))
        return reponse(q['id'])

    def _relais(self, q, _):
        with self._verrou:
            if q['params']:
                return reponse(q['id'], code='bad_request')
            decisions = self._decider_preliminaires()
            session = self.sessions.get(q['session'])
            if session is not None and session.etat != 'ouverte':
                session = None
        self._notifier(decisions, attendre=False)
        if session is None:
            return reponse(q['id'], code='session_closed')
        with session.verrou:
            if session.etat != 'ouverte':
                return reponse(q['id'], code='session_closed')
            if not self._castor('castor/light/ping', q['session']):
                return reponse(q['id'], code='peer_unavailable')
        return reponse(q['id'])

    def demarrer(self):
        try:
            for serveur in self.serveurs:
                # Umask 0o177 pendant bind() ; le serveur applique ensuite chmod 0660 et chown.
                ancien = os.umask(0o177)
                try:
                    serveur.demarrer()
                finally:
                    os.umask(ancien)
            self._fil = threading.Thread(target=self._surveiller, daemon=True)
            self._fil.start()
        except BaseException:
            self.arreter()
            raise
        return self

    def arreter(self):
        self._arret.set()
        for serveur in self.serveurs:
            serveur.arreter()
        if self._fil is not None:
            self._fil.join()
        with self._verrou:
            decisions = [self._decider(numero, 'disconnect') for numero in sorted(self.sessions)]
        self._notifier(decisions, attendre=False)
        # Attente bornée des notifications en cours : au plus pair_delai_s au total.
        echeance = time.monotonic() + self.config['transport']['pair_delai_s']
        while True:
            with self._verrou_fils:
                fils = list(self._fils_notification)
            restant = echeance - time.monotonic()
            if not fils or restant <= 0:
                break
            for fil in fils:
                try:
                    fil.join(max(0.0, echeance - time.monotonic()))
                except RuntimeError:
                    pass  # fil pas encore démarré : il sera repris au tour suivant
        with self._verrou:
            if self._romulus is not None:
                self._romulus.fermer()
                self._romulus = None

    def __enter__(self):
        return self.demarrer()

    def __exit__(self, *_):
        self.arreter()
