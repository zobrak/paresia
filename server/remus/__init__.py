# SPDX-License-Identifier: AGPL-3.0-or-later
# Remus : socle du démon d'administration du relais, sans opération métier ; dépendances : bibliothèque standard et server.commun.
# Suivi des versions
#   0.1.7  2026-11-07  Liste fermée par catalogue, introspection, options [remus.plugins] (D148, D150, D154).
#   3.0.0-alpha.32  2026-11-06  Transmission et fermeture des flux sur le fil (T035).
#   3.0.0-alpha  2026-11-05  Socle : attente du feu de Castor, table d'actions, opération menée à terme, flux (T021).
#   3.0.0-alpha  2026-11-06  SCHEMA fusionne le socle et l'exécuteur (T022).
from dataclasses import dataclass, field
import copy
import math
import os
import secrets
import threading
import time

from server.commun.catalogue import (DOMAINES_RESERVES, ErreurCatalogue, Repertoire,
                                     action_valide, est_suffixe_catalogue)
from server.commun.client import Connexion, PairIndisponible
from server.commun.config import ErreurConfiguration, Option
from server.commun.journal import Journal
from server.commun.jumeaux import CODES_ERREUR, MAX_LINE, ErreurProtocole, Flux, reponse
from server.commun.serveur import Serveur
from server.remus.executeur import SCHEMA_EXECUTEUR

SCHEMA_SOCLE = {
    ('server', 'socket'): Option('chemin'),
    ('server', 'uid'): Option('uid'),
    ('server', 'gid'): Option('uid'),
    ('server', 'stop_s'): Option('duree', 120),
    ('castor', 'socket'): Option('chemin'),
    ('castor', 'uid'): Option('uid'),
    ('castor', 'delai_s'): Option('duree', 2),
    ('light', 'wait_s'): Option('duree', 5),
    ('light', 'poll_s'): Option('duree', 0.25),
    ('light', 'check_s'): Option('duree', 5),
    ('transport', 'delai_s'): Option('duree', 600),
    ('transport', 'max_line'): Option('limite', MAX_LINE),
    ('transport', 'max_connexions'): Option('limite', 16),
}
# Fonctions enfichées : dossiers des fonctions livrées et locales (valeurs par défaut
# documentées dans server.remus.fonctions), domaine servi et nom de la cible.
SCHEMA_PLUGINS = {
    ('plugins', 'fonctions'): Option('chemin', facultatif=True),
    ('plugins', 'locales'): Option('chemin', facultatif=True),
    ('plugins', 'domaine'): Option('texte', facultatif=True),
    ('plugins', 'cible'): Option('texte', facultatif=True),
}
SCHEMA = {**SCHEMA_SOCLE, **SCHEMA_EXECUTEUR, **SCHEMA_PLUGINS}

# Attente maximale de l'arrêt du serveur commun une fois les opérations terminées ou abandonnées.
_FERMETURE_SERVEUR_S = 2.0


class ErreurOperation(Exception):
    """Échec d'une opération : code stable seulement, aucun texte."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


@dataclass(eq=False)
class ContexteOperation:
    """Ce que reçoit une action : paramètres validés (copie) ; arret et raison() pour un flux."""
    session: int
    identifiant: str
    action: str
    params: dict
    arret: threading.Event = field(default_factory=threading.Event)
    _raison: object = field(default=None, init=False, repr=False)

    def raison(self):
        """relay_light_red, session_closed ou peer_unavailable une fois arret positionné."""
        return self._raison


@dataclass(frozen=True)
class Action:
    """Seule frontière entre le socle et les opérations (lot 6).

    valider(params) retourne les paramètres validés ou lève ErreurOperation('bad_request') ;
    executer(contexte) retourne un dictionnaire (ou None) ou lève ErreurOperation(code) ;
    journaliser : noms de paramètres dont la valeur peut figurer au journal (vide : aucun).
    Avec flux=True, executer retourne un itérable de dictionnaires, éventuellement vide.
    Son itérateur rend la main à chaque événement et observe contexte.arret.
    Pour un flux, si executer ou son itérateur lève une exception, son code (ou internal_error) est prioritaire
    sur la raison d'arrêt du flux (relay_light_red, session_closed, peer_unavailable).
    """
    nom: str
    executer: object
    valider: object
    delai_max_s: float
    flux: bool = False
    journaliser: tuple = ()

    def __post_init__(self):
        if (not action_valide(self.nom) or self.nom.split('/')[0] in DOMAINES_RESERVES
                or est_suffixe_catalogue(self.nom) or not callable(self.executer)
                or not callable(self.valider) or type(self.flux) is not bool
                or type(self.delai_max_s) not in (int, float) or isinstance(self.delai_max_s, bool)
                or not math.isfinite(self.delai_max_s) or self.delai_max_s <= 0
                or not isinstance(self.journaliser, tuple)
                or not all(isinstance(n, str) for n in self.journaliser)):
            raise ValueError('invalid_action')


@dataclass(frozen=True)
class _FluxOperation(Flux):
    """Flux dont la fermeture libère aussi le registre et le compteur Remus."""
    fermeture: object

    def close(self):
        try:
            super().close()
        finally:
            self.fermeture()


def _requete_etat(session):
    return {'proto': 'jumeaux/1', 'id': secrets.token_hex(8), 'session': session,
            'action': 'castor/light/state', 'params': {}}


class Remus:
    """Exécute les actions enregistrées, seulement sur feu vert de la session de la commande.

    Aucun cache du feu : chaque exécution suit une interrogation de Castor qui a vu vert
    pour sa session. Une opération commencée est toujours menée à terme et journalisée.
    horloge et attente sont injectables pour les tests.
    """

    def __init__(self, configuration, *, actions=None, horloge=time.monotonic,
                 attente=time.sleep, journal=None, chargeur=None):
        """actions : injection (tests) ; sinon les fonctions des dossiers configurés sont chargées,
        avant toute écoute. chargeur : paramètres du chargeur (proprietaires, racine_confiance)."""
        self.config = configuration
        self.horloge, self.attente = horloge, attente
        self.journal = journal if journal is not None else Journal('remus')
        from . import fonctions
        options = fonctions.options_plugins(configuration)
        if actions is None:
            charge = fonctions.charger_fonctions(configuration, self.journal, **(chargeur or {}))
            actions, catalogue = charge.actions, charge.catalogue
        else:
            if (not isinstance(actions, dict)
                    or any(not isinstance(a, Action) or nom != a.nom
                           for nom, a in actions.items())):
                raise ValueError('invalid_actions')
            catalogue = fonctions.catalogue_injecte(options.cible, options.domaine, actions)
        self.actions = dict(actions)
        self.cible = options.cible
        self.domaine = catalogue.domaine if catalogue is not None else None
        self.repertoire = Repertoire([] if catalogue is None else [catalogue])
        lumiere, castor = configuration['light'], configuration['castor']
        transport = configuration['transport']
        if lumiere['poll_s'] > lumiere['wait_s']:
            raise ErreurConfiguration('config_invalid', 'light', 'poll_s')
        if castor['delai_s'] > lumiere['wait_s']:
            raise ErreurConfiguration('config_invalid', 'castor', 'delai_s')
        maximum = max((a.delai_max_s for a in self.actions.values()), default=0)
        if transport['delai_s'] < lumiere['wait_s'] + maximum:
            raise ErreurConfiguration('config_invalid', 'transport', 'delai_s')
        self._cond = threading.Condition()
        self._en_cours = 0
        self._arretee = threading.Event()
        self._fin_surveillance = threading.Event()
        self._flux = {}          # session -> liste de ContexteOperation de flux ouverts
        self._fil = None
        self._demarre = False
        options = configuration['server']
        admises = frozenset() if catalogue is None else frozenset(catalogue.actions)
        self.serveur = Serveur(
            options['socket'], {options['uid']}, admises, self.traiter,
            gid=options['gid'], max_line=transport['max_line'],
            delai=transport['delai_s'], max_connexions=transport['max_connexions'],
            journal=self.journal)

    # -- journal ------------------------------------------------------------------
    def _ecrire(self, niveau, nom, **champs):
        try:
            self.journal.ecrire(niveau, nom, **champs)
        except Exception:
            # Valeur non journalisable : on retombe sur les champs de base seuls.
            champs.pop('parametres', None)
            try:
                self.journal.ecrire(niveau, nom, **champs)
            except Exception:
                pass

    def _refuser(self, q, raison):
        self._ecrire('warning', 'operation_refused', action=q['action'],
                     session=q['session'], reason=raison)
        return reponse(q['id'], code=raison)

    # -- feu de Castor ------------------------------------------------------------
    def _etat_feu(self, session):
        """'green', 'red', 'session_closed' ou 'unavailable' ; toute forme inattendue = unavailable."""
        try:
            castor = self.config['castor']
            with Connexion(castor['socket'], castor['delai_s'],
                           max_line=self.config['transport']['max_line'],
                           uid_serveur=castor['uid'],
                           actions=frozenset({'castor/light/state'})) as client:
                resultat = client.appeler(_requete_etat(session))
        except (PairIndisponible, ErreurProtocole, ValueError, OSError):
            return 'unavailable'
        if not resultat['ok']:
            return 'session_closed' if resultat['error']['code'] == 'session_closed' else 'unavailable'
        data = resultat.get('data')
        if (not isinstance(data, dict) or data.get('state') not in ('green', 'red')
                or set(data) - {'state', 'remaining_s'}):
            return 'unavailable'
        if 'remaining_s' in data and (type(data['remaining_s']) is not int
                                      or data['remaining_s'] < 0):
            return 'unavailable'
        return data['state']

    def _attendre_feu(self, session):
        """Retourne 'green' ou le code de refus ; au plus wait_s (horloge injectable)."""
        lumiere = self.config['light']
        debut = self.horloge()
        dernier = 'peer_unavailable'
        while True:
            etat = self._etat_feu(session)
            if etat == 'green':
                return 'green'
            if etat == 'session_closed':
                return 'session_closed'
            dernier = 'relay_light_red' if etat == 'red' else 'peer_unavailable'
            restant = lumiere['wait_s'] - (self.horloge() - debut)
            if restant <= 0:
                return dernier
            self.attente(min(lumiere['poll_s'], restant))

    # -- traitement ---------------------------------------------------------------
    def traiter(self, q, _contexte=None):
        """Traite une requête dont l'action appartient au catalogue ; retourne la réponse."""
        with self._cond:
            if self._arretee.is_set():
                return self._refuser(q, 'peer_unavailable')
            self._en_cours += 1
        resultat = None
        try:
            resultat = self._traiter(q)
            return resultat
        finally:
            if not isinstance(resultat, Flux):
                self._terminer_operation()

    def _terminer_operation(self):
        with self._cond:
            self._en_cours -= 1
            self._cond.notify_all()

    def _introspection(self, q):
        """Réponse des deux actions de catalogue : lecture seule, aucune attente du feu."""
        try:
            data = self.repertoire.reponse(self.cible, self.domaine, q['action'],
                                           copy.deepcopy(q['params']))
        except ErreurCatalogue as erreur:
            return self._refuser(q, erreur.code)
        return reponse(q['id'], data)

    def _traiter(self, q):
        catalogue = self.repertoire.obtenir(self.cible, self.domaine)
        if catalogue is not None and catalogue.est_catalogue(q['action']):
            return self._introspection(q)
        action = self.actions.get(q['action'])
        if action is None:
            return self._refuser(q, 'unknown_action')
        if q['session'] == 0:
            return self._refuser(q, 'bad_request')
        try:
            params = action.valider(copy.deepcopy(q['params']))
            if not isinstance(params, dict):
                raise ValueError()
        except Exception:
            return self._refuser(q, 'bad_request')
        debut = self.horloge()
        etat = self._attendre_feu(q['session'])
        self._ecrire('info', 'light_wait', action=q['action'], session=q['session'],
                     waited_ms=int((self.horloge() - debut) * 1000), result=etat)
        if etat != 'green':
            return self._refuser(q, etat)
        return self._executer(q, action, params)

    def _executer(self, q, action, params):
        contexte = ContexteOperation(q['session'], q['id'], q['action'], params)
        if action.flux:
            with self._cond:
                self._flux.setdefault(q['session'], []).append(contexte)
                if self._arretee.is_set():      # arrêt levé entre l'admission et l'inscription
                    contexte._raison = 'peer_unavailable'
                    contexte.arret.set()
        champs = {'action': q['action'], 'session': q['session'], 'id': q['id']}
        visibles = {n: params[n] for n in action.journaliser if n in params}
        if visibles:
            champs['parametres'] = visibles
        self._ecrire('info', 'operation_started', **champs)
        debut = self.horloge()
        if action.flux:
            return self._ouvrir_flux(q, action, contexte, debut)
        donnees, code = None, None
        try:
            donnees = action.executer(contexte)
            if donnees is not None and not isinstance(donnees, dict):
                code = 'internal_error'
        except ErreurOperation as erreur:
            code = erreur.code if erreur.code in CODES_ERREUR else 'internal_error'
        except Exception:
            code = 'internal_error'
        finally:
            self._liberer_flux(contexte)
        if action.flux and code is None and contexte.arret.is_set() and contexte.raison():
            code = contexte.raison()
        self._ecrire('info', 'operation_finished', action=q['action'], session=q['session'],
                     id=q['id'], result='ok' if code is None else code,
                     duration_ms=int((self.horloge() - debut) * 1000))
        if code is not None:
            return reponse(q['id'], code=code)
        return reponse(q['id'], donnees)

    def _ouvrir_flux(self, q, action, contexte, debut):
        """La fermeture du transport possède la durée de vie de l'opération."""
        bilan = {'code': None, 'lignes': 0}
        verrou = threading.Lock()
        ferme = False
        iterateur = None

        def produire():
            nonlocal iterateur
            try:
                iterateur = iter(action.executer(contexte))
                while True:
                    try:
                        element = next(iterateur)
                    except StopIteration:
                        if contexte.arret.is_set():
                            bilan['code'] = contexte.raison()
                        break
                    if not isinstance(element, dict):
                        raise ValueError()
                    if contexte.arret.is_set():
                        bilan['code'] = contexte.raison()
                        break
                    bilan['lignes'] += 1
                    yield reponse(q['id'], data=element, stream='line')
            except ErreurOperation as erreur:
                bilan['code'] = (erreur.code if isinstance(erreur.code, str)
                                 and erreur.code in CODES_ERREUR else 'internal_error')
            except Exception:
                bilan['code'] = 'internal_error'
            if bilan['code'] is not None:
                yield reponse(q['id'], code=bilan['code'])

        def fermer():
            nonlocal ferme
            with verrou:
                if ferme:
                    return
                ferme = True
            try:
                fermer_iterateur = getattr(iterateur, 'close', None)
                if fermer_iterateur is not None:
                    fermer_iterateur()
            except Exception:
                bilan['code'] = 'internal_error'
            finally:
                self._liberer_flux(contexte)
                self._ecrire('info', 'operation_finished', action=q['action'],
                             session=q['session'], id=q['id'],
                             result=bilan['code'] or contexte.raison() or 'ok',
                             duration_ms=int((self.horloge() - debut) * 1000),
                             lines=bilan['lignes'])
                self._terminer_operation()

        return _FluxOperation(q['id'], produire(), fermer)

    # -- flux continus ------------------------------------------------------------
    def _liberer_flux(self, contexte):
        """Retire un flux du registre de sa session ; idempotent."""
        with self._cond:
            ouverts = self._flux.get(contexte.session)
            if ouverts is not None:
                if contexte in ouverts:
                    ouverts.remove(contexte)
                if not ouverts:
                    del self._flux[contexte.session]

    def _arreter_flux(self, session, raison):
        with self._cond:
            contextes = list(self._flux.get(session, ()))
        for contexte in contextes:
            if contexte._raison is None:
                contexte._raison = raison
            contexte.arret.set()

    def flux_ouverts(self):
        """Nombre de flux ouverts, par session."""
        with self._cond:
            return {s: len(c) for s, c in self._flux.items()}

    def verifier_flux(self):
        """Une passe : interroge Castor pour chaque session ayant un flux ouvert."""
        with self._cond:
            sessions = list(self._flux)
        for session in sessions:
            etat = self._etat_feu(session)
            if etat != 'green':
                self._arreter_flux(session, {'red': 'relay_light_red',
                                             'session_closed': 'session_closed'}.get(
                                                 etat, 'peer_unavailable'))

    def _surveiller(self):
        while not self._fin_surveillance.wait(self.config['light']['check_s']):
            try:
                self.verifier_flux()
            except Exception:
                self._ecrire('error', 'monitor_failed')

    # -- cycle de vie -------------------------------------------------------------
    def demarrer(self):
        self._arretee.clear()
        self._fin_surveillance.clear()
        ancien = os.umask(0o177)
        try:
            self.serveur.demarrer()
        except BaseException:
            self.serveur.arreter()
            raise
        finally:
            os.umask(ancien)
        self._fil = threading.Thread(target=self._surveiller, daemon=True)
        self._fil.start()
        self._demarre = True
        self._ecrire('info', 'startup')
        return self

    def arreter(self):
        """Refuse les nouvelles opérations, attend les opérations en cours (stop_s au plus)."""
        with self._cond:
            self._arretee.set()
        for session in self.flux_ouverts():
            self._arreter_flux(session, 'peer_unavailable')
        fin = time.monotonic() + self.config['server']['stop_s']
        with self._cond:
            while self._en_cours > 0:
                restant = fin - time.monotonic()
                if restant <= 0:
                    break
                self._cond.wait(restant)
            restantes = self._en_cours
        self._fin_surveillance.set()
        if self._fil is not None:
            self._fil.join(timeout=_FERMETURE_SERVEUR_S)
            self._fil = None
        if self._demarre:
            self._demarre = False
            champs = {'remaining': restantes} if restantes else {}
            self._ecrire('warning' if restantes else 'info', 'shutdown', **champs)
        # Le serveur commun attend ses fils jusqu'à transport.delai_s : borné ici pour
        # ne jamais bloquer le fil de signal ; une opération abandonnée reste un fil démon.
        fil = threading.Thread(target=self.serveur.arreter, daemon=True)
        fil.start()
        fil.join(timeout=_FERMETURE_SERVEUR_S)

    def __enter__(self):
        return self.demarrer()

    def __exit__(self, *_):
        self.arreter()
