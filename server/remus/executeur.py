# SPDX-License-Identifier: AGPL-3.0-or-later
# Remus : exécuteur contrôlé des commandes (table fermée, sudo -n, sortie bornée) ;
# dépendances : bibliothèque standard, server.commun (config, journal, texte).
# Suivi des versions
#   0.1.7  2026-11-07  Voie « script » : contrat de sortie, paramètres sur l'entrée standard (D148, D154).
#   3.0.0-alpha  2026-11-05  Création (T022, D55 à D57, D59, D60).
#   3.0.0-alpha  2026-11-05  Cycle 2 : commentaires (horloge, program_missing, bornes, repli waitid).
#   3.0.0-alpha  2026-11-05  Cycle 1 : gabarits immuables, tiret et espace refusés, SIGKILL au groupe, ménage.
"""Exécuteur contrôlé des commandes de Remus.

Table fermée : chaque commande est un argv complet fait d'éléments fixes et de
paramètres validés par gabarit. Jamais de shell, jamais de chaîne reconstituée.

Forme de sudo confirmée dans sudo(8) (paquet Debian 13, page datée du 9 août 2023) :
  « -n, --non-interactive : Avoid prompting the user for input of any kind. If a
  password is required for the command to run, sudo will display an error message
  and exit. »
  « -- : is used to delimit the end of the sudo options. Subsequent options are
  passed to the command. »
Signaux (même page, « Signal handling ») : sudo relaie à la commande les signaux
qu'il reçoit, hormis SIGSTOP et SIGKILL, qui ne peuvent être interceptés ; si la
commande meurt d'un signal, sudo s'envoie ce même signal. Limite connue : un
processus lancé sous un autre compte n'est atteint que par l'intermédiaire de sudo
(à reprendre dans la tâche d'installation).
"""
from dataclasses import dataclass, field
import json
import os
import re
import signal
import subprocess
import threading
import time
from types import MappingProxyType

from server.commun.config import Option
from server.commun.jumeaux import PLAFOND_DELAI, PLAFOND_LIMITE
from server.commun.journal import Journal
from server.commun.sortie import interpreter_sortie
from server.commun.texte import filtrer

CODES_EXECUTEUR = ('command_failed', 'command_timeout', 'command_busy')
VARIABLE_PRIVILEGE = 'PARESIA_PRIVILEGE'
PREFIXE = ('sudo', '-n', '--', 'docker')
SORTIES = ('stdout', 'stderr', 'les_deux')
ELEMENT_MAX = 4096
IDENTIFIANT_MAX = 128
ENTREE_MAX = PLAFOND_LIMITE
ERREUR_SCRIPT_MAX = 4096

SCHEMA_EXECUTEUR = {
    ('executor', 'sudo'): Option('chemin'),
    ('executor', 'docker'): Option('chemin'),
    ('executor', 'delai_s'): Option('duree', 60),
    ('executor', 'kill_grace_s'): Option('duree', 5),
    ('executor', 'sortie_max'): Option('limite', 65536),
    ('executor', 'simultanes'): Option('limite', 4),
    ('executor', 'attente_s'): Option('duree', 5),
}

_NOM_COMMANDE = re.compile('[a-z][a-z0-9_]{0,63}')
_NOM_PARAMETRE = re.compile('[a-z][a-z0-9_]*')


class ErreurGabarit(ValueError):
    """Valeur refusée par un gabarit : aucune valeur ni message libre."""

    def __init__(self):
        super().__init__('invalid_parameter')


def _controle_element(texte):
    """Règles communes à tout élément d'argv rendu (exigence 5)."""
    if (type(texte) is not str or not 0 < len(texte) <= ELEMENT_MAX or texte.startswith('-')
            or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in texte)):
        raise ErreurGabarit()
    return texte


def _entier(valeur, minimum, maximum):
    if type(valeur) is not int or not minimum <= valeur <= maximum:
        raise ErreurGabarit()
    return valeur


def _borne_entiere(valeur, plancher, plafond):
    # bornes incluses ; `type(...) is int` écarte les booléens (sous-classe d'int)
    if type(valeur) is not int or not plancher <= valeur <= plafond:
        raise ValueError('invalid_template')
    return valeur


class _Gabarit:
    """Base des gabarits : attributs figés après construction (aucune dérive en cours de vie)."""

    def _fixer(self, **champs):
        for nom, valeur in champs.items():
            object.__setattr__(self, nom, valeur)

    def __setattr__(self, nom, valeur):
        raise AttributeError('immutable_template')

    def __delattr__(self, nom):
        raise AttributeError('immutable_template')


class Entier(_Gabarit):
    """Entier JSON strict (booléen refusé), rendu décimal, minimum >= 0."""

    def __init__(self, minimum, maximum):
        self._fixer(minimum=_borne_entiere(minimum, 0, 2**63),
                    maximum=_borne_entiere(maximum, minimum, 2**63))

    def valider(self, valeur):
        return str(_entier(valeur, self.minimum, self.maximum))


class Hexadecimal(_Gabarit):
    """Chaîne [0-9a-f] de longueur exacte (minuscules seules)."""

    def __init__(self, longueur):
        self._fixer(longueur=_borne_entiere(longueur, 1, ELEMENT_MAX))

    def valider(self, valeur):
        if (type(valeur) is not str or len(valeur) != self.longueur
                or not re.fullmatch('[0-9a-f]+', valeur)):
            raise ErreurGabarit()
        return valeur


class Choix(_Gabarit):
    """Égalité exacte avec l'une des valeurs fournies.

    Une valeur commençant par « - » est refusée par le gabarit lui-même. L'espace est
    interdit par défaut (les valeurs deviennent des éléments de sudoers : un espace y
    séparerait deux arguments) ; `espace=True` l'autorise explicitement.
    """

    def __init__(self, *valeurs, espace=False):
        if not valeurs or type(espace) is not bool:
            raise ValueError('invalid_template')
        for valeur in valeurs:
            try:
                _controle_element(valeur)
            except ErreurGabarit:
                raise ValueError('invalid_template') from None
            if not espace and ' ' in valeur:
                raise ValueError('invalid_template')
        self._fixer(valeurs=tuple(valeurs), espace=espace)

    def valider(self, valeur):
        if (type(valeur) is not str or valeur.startswith('-') or valeur not in self.valeurs):
            raise ErreurGabarit()
        return valeur


class Texte(_Gabarit):
    """Chaîne ASCII imprimable, motif complet, longueur bornée, jamais vide.

    Une valeur commençant par « - » est refusée par le gabarit lui-même, quel que soit
    le motif. L'espace est interdit par défaut (valeurs de sudoers sûres) ; `espace=True`
    l'autorise explicitement, sous la responsabilité de l'auteur de la commande.
    """

    def __init__(self, motif, longueur_max, *, espace=False):
        if type(motif) is not str or type(espace) is not bool:
            raise ValueError('invalid_template')
        try:
            regex = re.compile(motif)
        except re.error:
            raise ValueError('invalid_template') from None
        self._fixer(motif=motif, longueur_max=_borne_entiere(longueur_max, 1, ELEMENT_MAX),
                    espace=espace, _regex=regex)

    def valider(self, valeur):
        if (type(valeur) is not str or not 0 < len(valeur) <= self.longueur_max
                or valeur.startswith('-')
                or any(not 32 <= ord(c) <= 126 for c in valeur)
                or (not self.espace and ' ' in valeur)
                or self._regex.fullmatch(valeur) is None):
            raise ErreurGabarit()
        return valeur


class ListeEntiers(_Gabarit):
    """Liste JSON d'entiers bornés, rendus joints par des virgules en un seul élément."""

    def __init__(self, minimum, maximum, nombre_max):
        self._fixer(minimum=_borne_entiere(minimum, 0, 2**63),
                    maximum=_borne_entiere(maximum, minimum, 2**63),
                    nombre_max=_borne_entiere(nombre_max, 1, 1024))

    def valider(self, valeur):
        if type(valeur) is not list or not 0 < len(valeur) <= self.nombre_max:
            raise ErreurGabarit()
        return ','.join(str(_entier(v, self.minimum, self.maximum)) for v in valeur)


@dataclass(frozen=True)
class Param:
    nom: str
    gabarit: object
    journalisable: bool = False


@dataclass(frozen=True)
class ParamOption:
    drapeau: str
    nom: str
    gabarit: object
    journalisable: bool = False


@dataclass(frozen=True)
class Commande:
    nom: str
    argv: tuple
    delai_s: object = None
    sortie_max: object = None
    sortie: str = 'stdout'
    codes_sortie: object = field(default_factory=dict)
    entree: object = None

    def __post_init__(self):
        object.__setattr__(self, 'argv', tuple(self.argv))
        object.__setattr__(self, 'codes_sortie', MappingProxyType(dict(self.codes_sortie)))


@dataclass(frozen=True)
class Variable:
    nom: str
    gabarit: object
    drapeau: object = None


@dataclass(frozen=True)
class RenduSudo:
    nom: str
    elements: tuple


@dataclass(frozen=True)
class Resultat:
    ok: bool
    code: str
    data: object = None
    exit_code: object = None


@dataclass(frozen=True)
class Script:
    """Fonction exécutable par la voie « script ».

    Le chemin, le descripteur et les gabarits ne figurent jamais dans `repr` ni dans
    `str`. gabarits : {nom: (gabarit, obligatoire)}. journaliser : noms de paramètres
    dont la valeur peut figurer au journal.
    """
    nom: str
    chemin: str = field(repr=False)
    delai_s: float
    sortie_max: int
    descripteur: object = field(repr=False)
    journaliser: tuple = ()
    gabarits: object = field(default_factory=dict, repr=False)

    def __post_init__(self):
        object.__setattr__(self, 'journaliser', tuple(self.journaliser))
        object.__setattr__(self, 'gabarits', MappingProxyType(dict(self.gabarits)))

    def verifier(self, params):
        """Motif de refus (unknown_parameter, missing_parameter, invalid_parameter) ou None.

        Un gabarit contrôle le type puis la longueur avant tout motif d'expression régulière.
        """
        if type(params) is not dict or set(params) - set(self.gabarits):
            return 'unknown_parameter'
        for nom, (gabarit, obligatoire) in self.gabarits.items():
            if nom not in params:
                if obligatoire:
                    return 'missing_parameter'
                continue
            try:
                gabarit.valider(params[nom])
            except (ErreurGabarit, ValueError, TypeError):
                return 'invalid_parameter'
        return None


def construire_table(*groupes):
    """Fusionne des groupes {nom: Commande} ; refuse un nom en double."""
    table = {}
    for groupe in groupes:
        for nom, commande in groupe.items():
            if nom in table:
                raise ValueError('duplicate_command')
            table[nom] = commande
    return table


def _nombre(valeur, plancher_exclu, plafond):
    return type(valeur) in (int, float) and plancher_exclu < valeur <= plafond


def _element_fixe_valide(element):
    return (type(element) is str and 0 < len(element) <= ELEMENT_MAX
            and not any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in element))


def _valider_commande(cle, commande):
    """Retourne True si la commande respecte les règles de la table (exigence 2)."""
    if (not isinstance(commande, Commande) or cle != commande.nom
            or type(cle) is not str or not _NOM_COMMANDE.fullmatch(cle)):
        return False
    argv = commande.argv
    if len(argv) <= len(PREFIXE) or argv[:len(PREFIXE)] != PREFIXE:
        return False
    # Aucune valeur variable avant le sous-programme de docker : le premier élément
    # suivant « docker » est fixe (les options appartiennent à ce qui suit, cahier).
    if len(argv) > len(PREFIXE) and type(argv[len(PREFIXE)]) is not str:
        return False
    noms = set()
    for element in argv:
        if isinstance(element, (Param, ParamOption)):
            if (not isinstance(element.nom, str) or not _NOM_PARAMETRE.fullmatch(element.nom)
                    or element.nom in noms or not callable(getattr(element.gabarit, 'valider', None))
                    or type(element.journalisable) is not bool):
                return False
            noms.add(element.nom)
            if isinstance(element, ParamOption) and not _element_fixe_valide(element.drapeau):
                return False
        elif not _element_fixe_valide(element):
            return False
    if commande.sortie not in SORTIES:
        return False
    if commande.delai_s is not None and not _nombre(commande.delai_s, 0, PLAFOND_DELAI):
        return False
    if commande.sortie_max is not None and (
            type(commande.sortie_max) is not int or not 1 <= commande.sortie_max <= PLAFOND_LIMITE):
        return False
    for code, stable in commande.codes_sortie.items():
        if type(code) is not int or not 1 <= code <= 255 or stable not in CODES_EXECUTEUR:
            return False
    return commande.entree is None or (
        type(commande.entree) is int and 1 <= commande.entree <= ENTREE_MAX)


class _Collecteur:
    """Conserve au plus `maximum` octets ; le surplus est lu puis jeté."""

    def __init__(self, maximum):
        self.maximum = maximum
        self.tampon = bytearray()
        self.tronque = False
        self.total = 0
        self._verrou = threading.Lock()

    def ajouter(self, bloc):
        with self._verrou:
            self.total += len(bloc)
            libre = self.maximum - len(self.tampon)
            if libre > 0:
                self.tampon += bloc[:libre]
            if len(bloc) > libre:
                self.tronque = True


def _lire(flux, collecteur):
    # Lecture en continu : un flux non lu bloquerait le processus (interblocage).
    try:
        while True:
            bloc = os.read(flux.fileno(), 65536)
            if not bloc:
                break
            if collecteur is not None:
                collecteur.ajouter(bloc)
    except OSError:
        pass
    finally:
        try:
            flux.close()
        except OSError:
            pass


def _ecrire(flux, donnees):
    try:
        flux.write(donnees)
        flux.flush()
    except OSError:
        pass
    finally:
        try:
            flux.close()
        except OSError:
            pass


def _lignes(octets):
    """Lignes filtrées une à une ; jamais str.splitlines, jamais filtrer sur le texte entier."""
    lignes = octets.decode('utf-8', errors='replace').split('\n')
    if lignes and lignes[-1] == '':
        lignes.pop()
    return [filtrer(ligne[:-1] if ligne.endswith('\r') else ligne) for ligne in lignes]


class _Place:
    """Emplacement de simultanéité, libéré une seule fois ; peut être confié à un fil de ménage."""

    def __init__(self, semaphore):
        self._semaphore = semaphore
        self._verrou = threading.Lock()
        self._libre = False
        self.confiee = False

    def liberer(self):
        with self._verrou:
            if not self._libre:
                self._libre = True
                self._semaphore.release()


def _attendre_fin(pid, echeance):
    """Attend la mort du processus `pid` sans le réaper (waitid + WNOWAIT) ; False à l'échéance.

    Tant que le chef de groupe n'est pas réaperçu, son pid reste alloué : le groupe
    de processus du même numéro ne peut être attribué à un autre, et le signaler est sûr.
    """
    while True:
        try:
            if os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None:
                return True
        except ChildProcessError:
            # déjà réaperçu ailleurs : plus rien à attendre
            return True
        if time.monotonic() >= echeance:
            return False
        time.sleep(0.005)


class Executeur:
    """Les délais (attente, grâce, échéance) se mesurent toujours avec `time.monotonic`.
    `horloge` (injectable) ne sert qu'aux durées journalisées. Limite assumée : les
    délais ne sont donc pas pilotables par une horloge factice (à noter pour T023 / lot 6)."""

    def __init__(self, configuration, table, *, journal=None, horloge=time.monotonic):
        for commande_cle, commande in table.items():
            if not _valider_commande(commande_cle, commande):
                raise ValueError('invalid_command_table')
        self.configuration = dict(configuration)
        self.table = dict(table)
        self.journal = Journal('remus') if journal is None else journal
        self.horloge = horloge
        self._places = threading.Semaphore(self.configuration['simultanes'])

    # -- rendu pour sudoers (D60) ------------------------------------------------
    def commandes_sudo(self):
        docker = self.configuration['docker']
        rendus = []
        for nom, commande in self.table.items():
            elements = [docker]
            for element in commande.argv[len(PREFIXE):]:
                if isinstance(element, Param):
                    elements.append(Variable(element.nom, element.gabarit, None))
                elif isinstance(element, ParamOption):
                    elements.append(Variable(element.nom, element.gabarit, element.drapeau))
                else:
                    elements.append(element)
            rendus.append(RenduSudo(nom, tuple(elements)))
        return tuple(rendus)

    # -- journal -------------------------------------------------------------------
    def _ecrire(self, niveau, evenement, **champs):
        self.journal.ecrire(niveau, evenement, **champs)

    def _refuser(self, commande, session, identifiant, raison, code):
        champs = {'session': session, 'id': identifiant, 'reason': raison}
        if commande is not None:
            champs['command'] = commande.nom
        self._ecrire('warning', 'command_refused', **champs)
        return Resultat(False, code)

    # -- validation des paramètres -------------------------------------------------
    def _plan(self, commande, params):
        """Valide params ; retourne (éléments variables, args journalisables) ou un motif."""
        declares = {e.nom for e in commande.argv if isinstance(e, (Param, ParamOption))}
        if set(params) - declares:
            return 'unknown_parameter', None
        valeurs, args = [], {}
        for element in commande.argv:
            if isinstance(element, Param):
                if element.nom not in params:
                    return 'missing_parameter', None
                prefixe = ()
            elif isinstance(element, ParamOption):
                if element.nom not in params:
                    valeurs.append(None)
                    continue
                prefixe = (element.drapeau,)
            else:
                valeurs.append(element)
                continue
            try:
                rendu = _controle_element(element.gabarit.valider(params[element.nom]))
            except (ErreurGabarit, ValueError, TypeError):
                return 'invalid_parameter', None
            valeurs.append(prefixe + (rendu,))
            if element.journalisable:
                args[element.nom] = rendu
        return valeurs, args

    def _verifier_final(self, commande, params, argv_variable):
        """Exigence 7 : revalidation de l'argv final avant Popen."""
        attendu = []
        for element in commande.argv[len(PREFIXE):]:
            if isinstance(element, (Param, ParamOption)):
                if element.nom not in params:
                    continue
                if isinstance(element, ParamOption):
                    attendu.append(element.drapeau)
                try:
                    rendu = _controle_element(element.gabarit.valider(params[element.nom]))
                except (ErreurGabarit, ValueError, TypeError):
                    return False
                attendu.append(rendu)
            else:
                attendu.append(element)
        return (attendu == argv_variable and all(
            _element_fixe_valide(e) and len(e) <= ELEMENT_MAX for e in argv_variable))

    # -- exécution -----------------------------------------------------------------
    def lancer(self, nom, params, *, session=0, identifiant=None, entree=None):
        if type(nom) is not str or type(params) is not dict:
            raise TypeError('invalid_argument')
        if type(session) is not int or (identifiant is not None and type(identifiant) not in (int, str)):
            raise TypeError('invalid_argument')
        if entree is not None and type(entree) is not bytes:
            raise TypeError('invalid_argument')
        if type(identifiant) is str and len(identifiant) > IDENTIFIANT_MAX:
            raise TypeError('invalid_argument')
        commande = self.table.get(nom)
        if commande is None:
            return self._refuser(None, session, identifiant, 'unknown_command', 'not_available')
        plan, args = self._plan(commande, params)
        if isinstance(plan, str):
            return self._refuser(commande, session, identifiant, plan, 'bad_request')
        if entree is not None and commande.entree is None:
            return self._refuser(commande, session, identifiant, 'input_not_allowed', 'bad_request')
        if entree is not None and len(entree) > commande.entree:
            return self._refuser(commande, session, identifiant, 'input_too_large', 'bad_request')
        variable = []
        for morceau in plan[len(PREFIXE):]:
            if isinstance(morceau, tuple):
                variable.extend(morceau)
            elif morceau is not None:
                variable.append(morceau)
        if not self._verifier_final(commande, params, variable):
            return self._refuser(commande, session, identifiant, 'argv_check_failed', 'bad_request')
        sudo, docker = self.configuration['sudo'], self.configuration['docker']
        for programme in (sudo, docker):
            if not (os.path.isfile(programme) and os.access(programme, os.X_OK)):
                # exigence 16 : command_finished est écrit dans tous les cas, programme absent compris
                champs = {'command': commande.nom, 'session': session, 'id': identifiant}
                debut = self.horloge()
                self._ecrire('info', 'command_started', **champs)
                self._ecrire('error', 'program_missing', **champs)
                self._ecrire('info', 'command_finished', **champs, code='command_failed',
                             exit_code=None, duration_ms=int((self.horloge() - debut) * 1000),
                             truncated=False)
                return Resultat(False, 'command_failed')
        argv = [sudo, '-n', '--', docker] + variable
        if not self._places.acquire(timeout=self.configuration['attente_s']):
            return self._refuser(commande, session, identifiant, 'busy', 'command_busy')
        place = _Place(self._places)
        try:
            return self._executer(commande, argv, args, entree, session, identifiant, place)
        finally:
            if not place.confiee:
                place.liberer()

    def _executer(self, commande, argv, args, entree, session, identifiant, place):
        debut = self.horloge()
        delai = commande.delai_s if commande.delai_s is not None else self.configuration['delai_s']
        maximum = commande.sortie_max if commande.sortie_max is not None else self.configuration['sortie_max']
        champs = {'command': commande.nom, 'session': session, 'id': identifiant}
        if args:
            champs['args'] = args
        self._ecrire('info', 'command_started', **champs)
        champs.pop('args', None)
        collecteur = _Collecteur(maximum)
        code, code_sortie, tronque, data = 'command_failed', None, False, None
        try:
            # Environnement minimal : LC_ALL=C (sortie des programmes stable, non localisée) ;
            # ni PATH, ni HOME, ni variable du démon. Les chemins sont ceux de la configuration.
            processus = subprocess.Popen(
                argv, shell=False,
                stdin=subprocess.DEVNULL if commande.entree is None else subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={'LC_ALL': 'C'},
                cwd='/', close_fds=True, start_new_session=True)
        except OSError:
            self._ecrire('error', 'program_missing', **champs)
            self._ecrire('info', 'command_finished', **champs, code=code, exit_code=None,
                         duration_ms=int((self.horloge() - debut) * 1000), truncated=False)
            return Resultat(False, code)
        fils = []
        flux_choisis = {'stdout': ('stdout',), 'stderr': ('stderr',),
                        'les_deux': ('stdout', 'stderr')}[commande.sortie]
        for nom_flux in ('stdout', 'stderr'):
            fils.append(threading.Thread(
                target=_lire, daemon=True,
                args=(getattr(processus, nom_flux), collecteur if nom_flux in flux_choisis else None)))
        if commande.entree is not None:
            fils.append(threading.Thread(target=_ecrire, daemon=True,
                                         args=(processus.stdin, entree or b'')))
        for fil in fils:
            fil.start()
        echeance = time.monotonic() + delai
        depasse = not _attendre_fin(processus.pid, echeance)
        if not depasse:
            for fil in fils:
                fil.join(max(0.0, echeance - time.monotonic()))
            depasse = any(fil.is_alive() for fil in fils)
        if depasse:
            code = 'command_timeout'
            self._terminer(processus, fils, champs, place)
            tronque = collecteur.tronque
        else:
            retour = processus.wait()
            tronque = collecteur.tronque
            if retour == 0:
                code, code_sortie = 'ok', 0
                data = {'lines': _lignes(bytes(collecteur.tampon)), 'truncated': tronque}
            elif retour > 0:
                code, code_sortie = commande.codes_sortie.get(retour, 'command_failed'), retour
        self._ecrire('info', 'command_finished', **champs, code=code, exit_code=code_sortie,
                     duration_ms=int((self.horloge() - debut) * 1000), truncated=tronque)
        return Resultat(code == 'ok', code, data, code_sortie)

    # -- voie « script » : contrat de sortie ------------------------------------------
    def lancer_script(self, script, params, *, session=0, identifiant=None):
        """Exécute un script : paramètres en JSON sur l'entrée standard, résultat selon le contrat.

        Le script est lancé par son chemin absolu seul, sans interpréteur dans l'argv ni
        variable d'environnement propre à un langage. Sa sortie d'erreur n'est ni transmise
        ni journalisée (seul son nombre d'octets l'est).
        """
        if type(script) is not Script or type(params) is not dict:
            raise TypeError('invalid_argument')
        if type(session) is not int or (identifiant is not None and type(identifiant) not in (int, str)):
            raise TypeError('invalid_argument')
        if type(identifiant) is str and len(identifiant) > IDENTIFIANT_MAX:
            raise TypeError('invalid_argument')
        raison = script.verifier(params)
        if raison is not None:
            return self._refuser(script, session, identifiant, raison, 'bad_request')
        try:
            entree = (json.dumps(params, ensure_ascii=True, allow_nan=False,
                                 separators=(',', ':')) + '\n').encode('ascii')
        except (TypeError, ValueError):
            return self._refuser(script, session, identifiant, 'invalid_parameter', 'bad_request')
        if len(entree) > ENTREE_MAX:
            return self._refuser(script, session, identifiant, 'input_too_large', 'bad_request')
        if not self._places.acquire(timeout=self.configuration['attente_s']):
            return self._refuser(script, session, identifiant, 'busy', 'command_busy')
        place = _Place(self._places)
        try:
            return self._executer_script(script, params, entree, session, identifiant, place)
        finally:
            if not place.confiee:
                place.liberer()

    def _environnement_script(self):
        """Environnement minimal d'un script plus le préfixe de privilège fourni par le noyau.

        PARESIA_PRIVILEGE : l'argv du préfixe (sudo, -n, --, docker), liste JSON.
        Un script ne nomme jamais sudo : le mécanisme de privilège reste l'affaire de Remus.
        """
        return {'LC_ALL': 'C', VARIABLE_PRIVILEGE: json.dumps(
            [self.configuration['sudo'], '-n', '--', self.configuration['docker']])}

    def _executer_script(self, script, params, entree, session, identifiant, place):
        debut = self.horloge()
        champs = {'command': script.nom, 'function': script.nom, 'session': session,
                  'id': identifiant}
        visibles = {n: params[n] for n in script.journaliser if n in params}
        self._ecrire('info', 'command_started', **champs, **({'args': visibles} if visibles else {}))
        sortie, erreur = _Collecteur(script.sortie_max), _Collecteur(ERREUR_SCRIPT_MAX)

        def terminer(code, code_sortie, contrat):
            self._ecrire('info', 'command_finished', **champs, code=code, result=code,
                         exit_code=code_sortie, duration_ms=int((self.horloge() - debut) * 1000),
                         truncated=sortie.tronque, stdout_bytes=sortie.total,
                         stderr_bytes=erreur.total, contract=contrat)

        try:
            processus = subprocess.Popen(
                [script.chemin], shell=False, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=self._environnement_script(), cwd='/',
                close_fds=True, start_new_session=True)
        except OSError:
            self._ecrire('error', 'program_missing', **champs)
            terminer('command_failed', None, 'violated')
            return Resultat(False, 'command_failed')
        fils = [threading.Thread(target=_lire, daemon=True, args=(processus.stdout, sortie)),
                threading.Thread(target=_lire, daemon=True, args=(processus.stderr, erreur)),
                threading.Thread(target=_ecrire, daemon=True, args=(processus.stdin, entree))]
        for fil in fils:
            fil.start()
        echeance = time.monotonic() + script.delai_s
        etat = 'fin'
        while True:
            if sortie.tronque:
                etat = 'trop_long'
                break
            if _attendre_fin(processus.pid, min(echeance, time.monotonic() + 0.05)):
                break
            if time.monotonic() >= echeance:
                etat = 'delai'
                break
        if etat == 'fin':
            for fil in fils:
                fil.join(max(0.0, echeance - time.monotonic()))
            if any(fil.is_alive() for fil in fils):
                etat = 'delai'
            elif sortie.tronque:
                etat = 'trop_long'
        if etat != 'fin':
            code = 'command_timeout' if etat == 'delai' else 'command_failed'
            self._terminer(processus, fils, champs, place)
            terminer(code, None, 'violated')
            return Resultat(False, code)
        retour = processus.wait()
        interprete = interpreter_sortie(bytes(sortie.tampon), retour, script.descripteur,
                                        sortie_max=script.sortie_max)
        if interprete.statut == 'ok':
            terminer('ok', retour, interprete.contrat)
            return Resultat(True, 'ok', interprete.valeur, retour)
        terminer(interprete.valeur, retour, interprete.contrat)
        return Resultat(False, interprete.valeur, None, retour)

    def _signaler(self, pid, signal_envoye, champs):
        """Signale le groupe de processus ; un refus est journalisé, sans contenu."""
        try:
            os.killpg(pid, signal_envoye)
        except ProcessLookupError:
            pass
        except PermissionError:
            self._ecrire('error', 'kill_denied', **champs, signal=signal_envoye.name)

    def _terminer(self, processus, fils, champs, place):
        """Seul cas où l'exécuteur tue : dépassement du délai (SIGTERM, grâce, SIGKILL).

        Le SIGKILL final vise toujours le groupe entier, même si le chef est déjà mort
        après SIGTERM (petits-fils). Le chef n'est réaperçu qu'après, de sorte que son
        pid, donc le numéro du groupe, reste réservé : pas de signal vers un tiers.
        """
        grace = self.configuration['kill_grace_s']
        fin_grace = time.monotonic() + grace
        self._signaler(processus.pid, signal.SIGTERM, champs)
        _attendre_fin(processus.pid, fin_grace)
        reste = fin_grace - time.monotonic()
        if reste > 0:
            time.sleep(reste)
        self._signaler(processus.pid, signal.SIGKILL, champs)
        try:
            processus.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            self._ecrire('error', 'process_not_reaped', **champs)
            # L'emplacement reste occupé tant que le processus n'est pas réaperçu.
            place.confiee = True
            threading.Thread(target=self._menage, args=(processus, fils, place, grace),
                             daemon=True).start()
            return
        echeance = time.monotonic() + grace
        for fil in fils:
            fil.join(max(0.0, echeance - time.monotonic()))

    @staticmethod
    def _menage(processus, fils, place, grace):
        """Fil de ménage : réaper le processus, laisser finir les fils de lecture, libérer."""
        try:
            processus.wait()
            echeance = time.monotonic() + grace
            for fil in fils:
                fil.join(max(0.0, echeance - time.monotonic()))
        finally:
            place.liberer()
