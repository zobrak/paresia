# SPDX-License-Identifier: AGPL-3.0-or-later
# Aiguillage de Romulus selon les déclarations de services greffés ; dépendances : bibliothèque standard, server.commun.
# Suivi des versions
#   0.1.15  2026-11-08  Journal d'activité : entrées de protocole du niveau 3 (envoi, réponse), sans params ni data.
#   0.1.8  2026-11-07  Code not_available du pair admis pour tout service, comme le publient les descripteurs.
#   0.1.8  2026-11-07  Destinations, paramètres, codes, ping et suivi tirés des déclarations ; introspection (D148, D150, D154).
#   3.0.0-alpha.41  2026-11-06  Constante ACTION_SUIVI importée de flux.py, sans seconde définition.
#   3.0.0-alpha.41  2026-11-06  Suivi en direct branché, plafond de flux (D85, D111).
#   3.0.0-alpha.41  2026-11-06  Six codes de signature de bunkerd dans CODES_BUNKERD (D112, codes de signature de bunkerd).
#   3.0.0-alpha.41  2026-11-06  Première version : routes bunker/* et relay/* (hors suivi), ping de session (T038, D10, D15, D57).
from dataclasses import dataclass, field
import re
import secrets
import threading
import time

from server.commun import catalogue as cat
from server.commun.client import Connexion, PairIndisponible
from server.commun.jumeaux import MAX_LINE, PROTO, ErreurProtocole, encoder
from server.commun.services import CODE_TOUJOURS_ADMIS
from .flux import FluxEvenements

# Seule action du noyau appelée par l'aiguillage : le ping de session auprès de Pollux.
ACTION_PING = 'presence/relay/ping'
ADMIS_PING = frozenset({ACTION_PING})
BORNE_FLUX_DEFAUT = 1
TEXTE, ENTIER, LISTE = 'texte', 'entier', 'liste'
# Type JSON attendu pour chaque type de descripteur ; les bornes sont publiées, non appliquées
# ici : le service reste l'autorité (D57).
TYPE_JSON = {'texte': TEXTE, 'choix': TEXTE, 'hexadecimal': TEXTE, 'entier': ENTIER,
             'liste_entiers': LISTE, 'liste_texte': LISTE}


class UidServeurAbsent(Exception):
    """Uid attendu du serveur absent : aucune connexion n'est construite sans lui."""


def _uid_requis(uid):
    if uid is None:
        raise UidServeurAbsent()
    return uid


class _PingRefuse(Exception):
    """Ping de session refusé ou impossible ; porte le code à renvoyer au client."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _type_valide(valeur, type_json):
    if type_json == TEXTE:
        return isinstance(valeur, str)
    if type_json == ENTIER:
        return type(valeur) is int
    return isinstance(valeur, list)


@dataclass(frozen=True, repr=False)
class Liaison:
    """Un service déclaré et configuré : sa section (référence vivante) et ses actions admises."""
    service: object
    section: dict = field(compare=False)
    admises: frozenset = frozenset()

    def __repr__(self):
        return '<Liaison>'

    def valeur(self, role, defaut=None):
        """Valeur de l'option qui porte `role` (sa valeur par défaut déclarée si elle manque)."""
        option = next((o for o in self.service.options if o.role == role), None)
        if option is None:
            return defaut
        valeur = self.section.get(option.nom, option.defaut)
        return defaut if valeur is None else valeur


class Aiguillage:
    """Destinations des actions des services déclarés, ping de session et suivi différé.

    Chaque appel ouvre sa connexion, vérifie l'uid du pair avant l'envoi et la ferme dans
    tous les cas. Aucun params, data, secret ni texte de pair n'est journalisé. Les tables
    de destinations et de catalogues sont indexées par (cible, domaine).
    """

    def __init__(self, config, declarations, journal, *, horloge=time.monotonic, activite=None):
        self.journal, self.declarations = journal, declarations
        self.activite = activite
        self._horloge = horloge
        self._verrou = threading.Lock()
        self._pings = {}
        self._en_cours = {}
        self.repertoire = declarations.repertoire()
        self.destinations = {}
        for service in declarations.services:
            section = config.get(service.section) if service.section is not None else None
            if section is None or section.get(service.roles()['socket']) is None:
                continue
            self.destinations[(service.cible, service.domaine)] = Liaison(
                service, section, service.actions_routables())
        # Au plus un service déclare le suivi ou le ping : un seul plafond de flux.
        self._comportement = next(
            (l for l in self.destinations.values()
             if l.service.ping or any(a.suivi for a in l.service.actions)), None)
        maximum = BORNE_FLUX_DEFAUT if self._comportement is None else int(
            self._comportement.valeur('flux_max', BORNE_FLUX_DEFAUT))
        self._places_flux = threading.BoundedSemaphore(maximum)

    def destination(self, cible, domaine):
        return self.destinations.get((cible, domaine))

    def actions(self):
        """{action: traiter(params, session)}, y compris le suivi différé (D85)."""
        resultat = {}
        for liaison in self.destinations.values():
            service = liaison.service
            for declaree in service.actions:
                if declaree.suivi:
                    resultat[declaree.action] = self._lier(self._suivre, liaison, declaree)
                else:
                    resultat[declaree.action] = self._lier(self._transmettre, liaison, declaree)
            for operation in ('list', 'describe'):
                action = cat.action_catalogue(service.domaine, operation)
                if service.catalogue_mode == 'declaration':
                    resultat[action] = self._lier_catalogue(liaison, action)
                elif service.catalogue_mode == 'pair':
                    declaree = _Declaree(action, service.catalogue.descripteur(action))
                    resultat[action] = self._lier(self._transmettre, liaison, declaree)
        return resultat

    @staticmethod
    def _lier(methode, liaison, declaree):
        return lambda params, session: methode(liaison, declaree, params, session)

    def _lier_catalogue(self, liaison, action):
        return lambda params, session: self._introspecter(liaison, action, params)

    def _introspecter(self, liaison, action, params):
        """Réponse de `list` ou `describe` depuis les descripteurs, sans appeler le service."""
        service = liaison.service
        try:
            data = self.repertoire.reponse(service.cible, service.domaine, action, params)
        except cat.ErreurCatalogue as erreur:
            raise ErreurProtocole(erreur.code) from None
        return {'ok': True, 'data': data}

    # -- validation -----------------------------------------------------------------

    @staticmethod
    def _valider_params(descripteur, params):
        champs = {p.nom: p for p in descripteur.parametres}
        if set(params) - champs.keys():
            raise ErreurProtocole('bad_request')
        for nom, parametre in champs.items():
            if nom not in params:
                if parametre.obligatoire:
                    raise ErreurProtocole('bad_request')
            elif not _type_valide(params[nom], TYPE_JSON[parametre.type]):
                raise ErreurProtocole('bad_request')

    # -- services -------------------------------------------------------------------

    def _connexion(self, liaison):
        uid = _uid_requis(liaison.valeur('uid'))
        return Connexion(liaison.valeur('socket'), liaison.valeur('delai', 30),
                         max_line=liaison.valeur('max_line', MAX_LINE),
                         uid_serveur=uid, actions=liaison.admises)

    def _suivre(self, liaison, declaree, params, session):
        if not declaree.params_transmis:
            self._valider_params(declaree.descripteur, params)
        return FluxEvenements(self, params, session, liaison, declaree.action)

    def _delai_ping(self, session):
        battement = self._comportement.valeur('battement')
        with self._verrou:
            return max(0, self._pings.get(session, self._horloge())
                       + battement - self._horloge())

    def _transmettre(self, liaison, declaree, params, session):
        service, action = liaison.service, declaree.action
        debut = self._horloge()
        code = 'ok'
        try:
            if not declaree.params_transmis:
                self._valider_params(declaree.descripteur, params)
            connexion = self._connexion(liaison)
            rappel = (lambda: self._pinguer(session)) if service.ping else None
            try:
                resultat = self._appeler(connexion, action, params, session,
                                         service.codes | {CODE_TOUJOURS_ADMIS},
                                         apres_envoi=rappel)
            except ErreurProtocole as erreur:
                if erreur.code in service.ping_oubli:
                    with self._verrou:
                        self._pings.pop(session, None)
                raise
            return resultat
        except ErreurProtocole as erreur:
            code = erreur.code
            raise
        except Exception:
            code = 'internal_error'
            raise
        finally:
            self._journaliser(service.destination, session, action, code, debut)

    def _pinguer(self, session):
        """Rappel d'envoi : ping au plus une fois par battement et par session.

        Le ping est réservé sous _verrou avant l'appel réseau ; une commande concurrente de la
        même session attend son issue et en reprend le refus éventuel (aucun second ping).
        Sans service qui déclare le ping, rien n'est fait.
        """
        liaison = self._comportement
        if liaison is None or not liaison.service.ping:
            return
        maintenant = self._horloge()
        battement = liaison.valeur('battement')
        with self._verrou:
            for numero in [n for n, t in self._pings.items() if maintenant - t >= battement]:
                del self._pings[numero]
            if session in self._pings:
                return
            reservation = self._en_cours.get(session)
            if reservation is None:
                reservation = self._en_cours[session] = {'fin': threading.Event(), 'code': None}
                proprietaire = True
            else:
                proprietaire = False
        if not proprietaire:
            if not reservation['fin'].wait(liaison.valeur('ping_delai') + 1):
                raise _PingRefuse('peer_unavailable')
            if reservation['code'] is not None:
                raise _PingRefuse(reservation['code'])
            return
        code = 'internal_error'
        try:
            code = self._ping_pair(liaison, session)
            if code is None:
                with self._verrou:
                    self._pings[session] = self._horloge()
                return
        finally:
            reservation['code'] = code
            with self._verrou:
                self._en_cours.pop(session, None)
            reservation['fin'].set()
        self.journal.ecrire('warning', 'relay_ping_failed', session=session, code=code)
        raise _PingRefuse(code)

    def _ping_pair(self, liaison, session):
        """Un appel de ping ; None si le pair répond ok, sinon le code à renvoyer au client."""
        uid = _uid_requis(liaison.valeur('ping_uid'))
        try:
            connexion = Connexion(liaison.valeur('ping_socket'), liaison.valeur('ping_delai'),
                                  max_line=liaison.valeur('max_line', MAX_LINE),
                                  uid_serveur=uid, actions=ADMIS_PING)
            try:
                reponse = connexion.appeler(self._enveloppe(ACTION_PING, {}, session))
            finally:
                connexion.fermer()
            if reponse['ok']:
                return None
            erreur = reponse['error']['code']
            return 'session_closed' if erreur == 'session_closed' else 'peer_unavailable'
        except PairIndisponible:
            return 'peer_unavailable'
        except ErreurProtocole:
            return 'internal_error'

    # -- commun ---------------------------------------------------------------------

    @staticmethod
    def _enveloppe(action, params, session):
        return {'proto': PROTO, 'id': secrets.token_hex(8), 'session': session,
                'action': action, 'params': params}

    def _trace(self, connexion, enveloppe, etape, session, **champs):
        """Entrée `protocol` du niveau 3 : jamais de params, de data ni de texte du pair."""
        if self.activite is None:
            return
        try:
            self.activite.protocole(request_id=enveloppe['id'], step=etape, session=session,
                                    peer_uid=connexion.uid_serveur, **champs)
        except Exception:
            pass

    def _appeler(self, connexion, action, params, session, admis, *, apres_envoi=None):
        enveloppe = self._enveloppe(action, params, session)
        try:
            try:
                self._trace(connexion, enveloppe, 'sent', session, bytes=len(encoder(enveloppe)))
                if apres_envoi is None:
                    resultat = connexion.appeler(enveloppe)
                else:
                    resultat = connexion.appeler(enveloppe, apres_envoi=apres_envoi)
            finally:
                connexion.fermer()
        except _PingRefuse as refus:
            self._trace(connexion, enveloppe, 'received', session, ok=False, code=refus.code)
            raise ErreurProtocole(refus.code) from None
        except PairIndisponible:
            self._trace(connexion, enveloppe, 'received', session, ok=False,
                        code='peer_unavailable')
            raise ErreurProtocole('peer_unavailable') from None
        except ErreurProtocole:
            # Réponse invalide, ligne trop longue : aucun texte du pair n'est propagé.
            self._trace(connexion, enveloppe, 'received', session, ok=False,
                        code='internal_error')
            raise ErreurProtocole('internal_error') from None
        if resultat['ok']:
            self._trace(connexion, enveloppe, 'received', session, ok=True,
                        bytes=len(encoder(resultat)))
        else:
            self._trace(connexion, enveloppe, 'received', session, ok=False,
                        code=_code_trace(resultat['error']['code']), bytes=len(encoder(resultat)))
        if resultat['ok']:
            return {'ok': True, 'data': resultat['data']} if 'data' in resultat else {'ok': True}
        code = resultat['error']['code']
        if code == 'unknown_action':
            code = 'not_available'
        elif code not in admis:
            code = 'internal_error'
        raise ErreurProtocole(code)

    def _journaliser(self, destination, session, action, code, debut):
        duree = max(0, int((self._horloge() - debut) * 1000))
        self.journal.ecrire('info' if code == 'ok' else 'warning', 'action_routed',
                            session=session, action=action, destination=destination,
                            result=code, duration_ms=duree)


def _code_trace(code):
    """Code du pair, seulement s'il a la forme d'un code ; jamais un texte quelconque."""
    return code if isinstance(code, str) and re.fullmatch(r'[a-z][a-z0-9_]{0,47}', code) else 'internal_error'


@dataclass(frozen=True)
class _Declaree:
    """Action de catalogue transmise au pair : descripteur de catalogue.py, paramètres prévalidés."""
    action: str
    descripteur: object
    params_transmis: bool = False
    suivi: bool = False
