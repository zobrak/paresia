# SPDX-License-Identifier: AGPL-3.0-or-later
# Déclarations de services greffés de Romulus : lecture, contrôle, aucune exécution.
# Dépendances : bibliothèque standard (tomllib), catalogue, config, plugins (contrôle de fichiers), jumeaux, texte.
# Suivi des versions
#   0.1.9  2026-11-08  Clés `pages` (pages d'un greffon) et `journaliser` (par action) ; greffon sans action (D148, D150).
#   0.1.8  2026-11-07  Déclarations de services (TOML) : actions typées, options par rôle, introspection (D148, D150, D154).
"""Déclarations de services greffés d'un démon de point de contact.

Une déclaration est un fichier TOML `paresia-yang-<nom>.toml` : des données, jamais du code.
Elle nomme un domaine, la section de configuration qui porte les options du service (avec le
rôle de chacune), les actions du domaine (descripteurs typés de `catalogue.py`, source unique),
les codes de retour admis du pair et quelques comportements génériques (suivi différé, export
binaire, ping de session, mode du catalogue). Ce module ne connaît le nom d'aucun greffon ni
d'aucune option : tout vient des déclarations.

Politique : un défaut d'une déclaration livrée est fatal (ErreurService) ; un défaut d'une
déclaration locale la fait ignorer (le dossier local entier s'il touche le dossier ou ses
ancêtres) et alimente la liste des rejets. Aucune déclaration locale ne remplace un domaine
déjà déclaré. Les fichiers sont contrôlés comme des programmes (propriétaire, droits, aucun
lien symbolique, taille bornée) avec les fonctions publiques de `plugins.py`.
"""
from dataclasses import dataclass
import math
import os
import re
import stat
import tomllib
from types import MappingProxyType

from . import catalogue as cat
from .config import ErreurConfiguration, Option
from .jumeaux import CODES_ERREUR, PLAFOND_DELAI, PLAFOND_LIMITE
from .plugins import (MANIFESTE_MAX, ErreurPlugin, ouvrir_dossier_confiance,
                      ouvrir_fichier_controle)
from .texte import filtrer

COTE = 'yang'
FORMAT = cat.FORMAT
FORME = cat.FORME_PONCTUELLE
DOSSIER_LIVRE = '/usr/local/lib/paresia/romulus/services'
DOSSIER_LOCAL = '/etc/paresia/romulus/services.d'
MOTIF_GREFFON = re.compile(r'paresia-yang-[a-z][a-z0-9-]{0,31}\Z')
MOTIF_FICHIER = re.compile(r'(paresia-yang-[a-z][a-z0-9-]{0,31})\.toml\Z')
MOTIF_DOMAINE = re.compile(r'[a-z][a-z0-9_]{0,31}\Z')
MOTIF_IDENTIFIANT = re.compile(r'[a-z][a-z0-9_]*\Z')
MOTIF_DESTINATION = re.compile(r'[a-z][a-z0-9_-]{0,31}\Z')
# Sections de configuration du démon qui ne peuvent pas être celles d'un service.
SECTIONS_RESERVEES = frozenset({'general', 'presence', 'http', 'plugins', 'journal', 'metriques'})
CATALOGUES = ('aucun', 'declaration', 'pair')
TYPES_OPTION = ('chemin', 'uid', 'duree', 'limite')
# Rôle d'une option -> type d'option attendu. Le démon lit une option par son rôle, jamais
# par son nom.
ROLES_OPTION = MappingProxyType({
    'socket': 'chemin', 'uid': 'uid', 'delai': 'duree', 'max_line': 'limite',
    'flux_max': 'limite', 'battement': 'duree', 'ping_delai': 'duree',
    'ping_socket': 'chemin', 'ping_uid': 'uid',
})
ROLES_BASE = frozenset({'socket', 'uid'})
ROLES_FACULTATIFS = frozenset({'delai', 'max_line'})
ROLES_SUIVI = frozenset({'flux_max', 'battement', 'ping_delai'})
ROLES_PING = frozenset({'ping_socket', 'ping_uid', 'ping_delai', 'battement'})
CLES_DECLARATION = frozenset({
    'format', 'forme', 'greffon', 'cible', 'domaine', 'section', 'options', 'obligatoire',
    'sans_destination', 'destination', 'ping', 'ping_oubli', 'actions', 'codes', 'catalogue',
    'pages'})
CLES_OPTION = frozenset({'nom', 'type', 'defaut', 'maximum', 'inferieure_a', 'role'})
CLES_ACTION = frozenset({'nom', 'suivi', 'export', 'params_transmis', 'erreurs', 'parametres',
                         'journaliser'})
CLES_PAGE = frozenset({'id', 'titre_cle', 'script'})
MOTIF_PAGE_ID = re.compile(r'[a-z][a-z0-9-]{0,31}\Z')
MOTIF_TITRE_CLE = re.compile(r'ui_[a-z0-9_]{1,100}\Z')
MOTIF_SCRIPT = re.compile(r'[a-z0-9][a-z0-9._-]{0,63}\.js\Z')
PREFIXE_GREFFON = 'paresia-yang-'
PAGES_MAX = 16
CLES_PARAMETRE = frozenset({'nom', 'type', 'obligatoire', 'bornes'})
FICHIERS_MAX = 64
ACTIONS_MAX = 256
OPTIONS_MAX = 32
PARAMETRES_MAX = 16
CODES_MAX = 64
# Un pair qui ne connaît pas l'action répond unknown_action, converti en not_available :
# ce code est donc toujours un retour possible d'une action.
CODE_TOUJOURS_ADMIS = 'not_available'


class ErreurService(Exception):
    """Défaut d'une déclaration ; `code` est stable, `fichier` un nom de base filtré."""

    def __init__(self, code, fichier=None):
        super().__init__(code)
        self.code = code
        self.fichier = None if fichier is None else _nom_publie(fichier)


def _nom_publie(nom):
    """Nom de base publié : filtré (I7) ; substitut neutre s'il change ou est vide."""
    if type(nom) is str and nom and filtrer(nom) == nom:
        return nom
    return 'invalid_name'


@dataclass(frozen=True)
class Rejet:
    code: str
    scope: str
    file: str


@dataclass(frozen=True)
class OptionService:
    nom: str
    type: str
    defaut: object
    maximum: object
    inferieure_a: object
    role: object


@dataclass(frozen=True)
class ActionService:
    """Une action du domaine : `action` porte le domaine ; `descripteur` est publié."""
    action: str
    suivi: bool
    export: bool
    params_transmis: bool
    descripteur: object
    journaliser: tuple = ()


@dataclass(frozen=True)
class PageService:
    """Une page déclarée par un greffon : identifiant, clé de titre, nom du script."""
    id: str
    titre_cle: str
    script: str


@dataclass(frozen=True, repr=False)
class Service:
    """Une déclaration validée. Jamais décrite par son contenu (aucun chemin, aucune option)."""
    greffon: str
    cible: str
    domaine: str
    section: object
    options: tuple
    obligatoire: bool
    sans_destination: bool
    destination: str
    ping: bool
    ping_oubli: frozenset
    actions: tuple
    codes: frozenset
    catalogue_mode: str
    catalogue: object
    pages: tuple = ()

    def __repr__(self):
        return '<Service>'

    def roles(self):
        """{rôle: nom de l'option}."""
        return {o.role: o.nom for o in self.options if o.role is not None}

    def option(self, nom):
        for option in self.options:
            if option.nom == nom:
                return option
        return None

    def actions_routables(self):
        """Actions déclarées plus, si le domaine publie un catalogue, les deux actions de catalogue."""
        routables = {a.action for a in self.actions}
        if self.catalogue_mode != 'aucun':
            routables |= {cat.action_catalogue(self.domaine, 'list'),
                          cat.action_catalogue(self.domaine, 'describe')}
        return frozenset(routables)

    def schema(self):
        """{(section, option): Option} ; vide pour un service sans destination."""
        if self.section is None:
            return {}
        schema = {}
        for option in self.options:
            facultatif = (not self.obligatoire and option.type in ('chemin', 'uid')
                          and option.defaut is None)
            schema[(self.section, option.nom)] = Option(option.type, option.defaut, facultatif)
        return schema


@dataclass(frozen=True, repr=False)
class Declarations:
    """Services chargés (livrés puis locaux) et rejets locaux ; une seule cible."""
    services: tuple
    rejets: tuple
    cible: str

    def __repr__(self):
        return '<Declarations>'

    def schema(self):
        schema = {}
        for service in self.services:
            schema.update(service.schema())
        return schema

    def actions_routables(self):
        routables = set()
        for service in self.services:
            routables |= service.actions_routables()
        return frozenset(routables)

    def exports(self):
        return frozenset(a.action for s in self.services for a in s.actions if a.export)

    def suivis(self):
        return frozenset(a.action for s in self.services for a in s.actions if a.suivi)

    def repertoire(self):
        """Catalogues des seuls domaines publiés par déclaration."""
        return cat.Repertoire([s.catalogue for s in self.services
                               if s.catalogue_mode == 'declaration'])


# --- Validation d'une déclaration --------------------------------------------------------

def _invalide():
    return ErreurService('service_declaration_invalid')


def _booleen(table, cle, defaut=False):
    valeur = table.get(cle, defaut)
    if type(valeur) is not bool:
        raise _invalide()
    return valeur


def _liste_codes(valeur, maximum=CODES_MAX):
    if (type(valeur) is not list or len(valeur) > maximum
            or any(type(c) is not str or c not in CODES_ERREUR for c in valeur)
            or len(set(valeur)) != len(valeur)):
        raise _invalide()
    return tuple(valeur)


def _nombre_borne(valeur, plafond):
    return (type(valeur) in (int, float) and math.isfinite(valeur) and 0 < valeur <= plafond)


def _options(brutes, obligatoire):
    if type(brutes) is not list or not 1 <= len(brutes) <= OPTIONS_MAX:
        raise _invalide()
    noms = {}
    for brute in brutes:
        if type(brute) is not dict or not set(brute) <= CLES_OPTION:
            raise _invalide()
        nom = brute.get('nom')
        if type(nom) is not str or not MOTIF_IDENTIFIANT.match(nom) or nom in noms:
            raise _invalide()
        noms[nom] = brute
    options, roles = [], set()
    for nom, brute in noms.items():
        type_ = brute.get('type')
        if type_ not in TYPES_OPTION or type(type_) is not str:
            raise _invalide()
        defaut = brute.get('defaut')
        if defaut is not None:
            if type_ == 'duree':
                valide = _nombre_borne(defaut, PLAFOND_DELAI)
            elif type_ == 'limite':
                valide = type(defaut) is int and 1 <= defaut <= PLAFOND_LIMITE
            else:
                valide = False
            if not valide:
                raise _invalide()
        elif not obligatoire and type_ in ('duree', 'limite'):
            # Sans section, la valeur vient du défaut : il est donc exigé.
            raise _invalide()
        maximum = brute.get('maximum')
        if maximum is not None and (type_ != 'limite' or type(maximum) is not int
                                     or not 1 <= maximum <= PLAFOND_LIMITE):
            raise _invalide()
        inferieure = brute.get('inferieure_a')
        if inferieure is not None:
            autre = noms.get(inferieure) if type(inferieure) is str else None
            if (type_ != 'duree' or autre is None or inferieure == nom
                    or autre.get('type') != 'duree'):
                raise _invalide()
        role = brute.get('role')
        if role is not None:
            if (type(role) is not str or role not in ROLES_OPTION or role in roles
                    or ROLES_OPTION[role] != type_):
                raise _invalide()
            roles.add(role)
        options.append(OptionService(nom, type_, defaut, maximum, inferieure, role))
    return tuple(options)


def _parametre(table):
    if type(table) is not dict or not set(table) <= CLES_PARAMETRE:
        raise _invalide()
    try:
        return cat.Parametre(table.get('nom'), table.get('type'), table.get('bornes', {}),
                             table.get('obligatoire', True))
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise _invalide() from None


def _pages(brutes, greffon):
    if type(brutes) is not list or len(brutes) > PAGES_MAX:
        raise _invalide()
    prefixe = 'ui_' + greffon[len(PREFIXE_GREFFON):].replace('-', '_') + '_'
    pages, identifiants = [], set()
    for brute in brutes:
        if type(brute) is not dict or set(brute) != CLES_PAGE:
            raise _invalide()
        identifiant, titre, script = brute['id'], brute['titre_cle'], brute['script']
        if (type(identifiant) is not str or not MOTIF_PAGE_ID.match(identifiant)
                or identifiant in identifiants
                or type(titre) is not str or not MOTIF_TITRE_CLE.match(titre)
                or not titre.startswith(prefixe) or len(titre) == len(prefixe)
                or type(script) is not str or not MOTIF_SCRIPT.match(script) or '..' in script):
            raise _invalide()
        identifiants.add(identifiant)
        pages.append(PageService(identifiant, titre, script))
    return tuple(pages)


def _journaliser(brut, parametres):
    if (type(brut) is not list or len(brut) > PARAMETRES_MAX
            or any(type(n) is not str for n in brut) or len(set(brut)) != len(brut)
            or not set(brut) <= {p.nom for p in parametres}):
        raise _invalide()
    return tuple(brut)


def _actions(brutes, domaine, greffon, codes, catalogue_mode, vide_admis=False):
    if type(brutes) is not list or len(brutes) > ACTIONS_MAX or (not brutes and not vide_admis):
        raise _invalide()
    actions = []
    for brute in brutes:
        if type(brute) is not dict or not set(brute) <= CLES_ACTION:
            raise _invalide()
        nom = brute.get('nom')
        action = f'{domaine}/{nom}' if type(nom) is str else None
        if not cat.action_valide(action) or cat.est_suffixe_catalogue(action):
            raise _invalide()
        suivi, export = _booleen(brute, 'suivi'), _booleen(brute, 'export')
        transmis = _booleen(brute, 'params_transmis')
        erreurs = brute.get('erreurs', [])
        brutes_parametres = brute.get('parametres', [])
        if (suivi and export or type(erreurs) is not list
                or type(brutes_parametres) is not list or len(brutes_parametres) > PARAMETRES_MAX):
            raise _invalide()
        parametres = tuple(_parametre(p) for p in brutes_parametres)
        journaliser = _journaliser(brute.get('journaliser', []), parametres)
        if transmis and (catalogue_mode != 'pair' or parametres):
            raise _invalide()
        try:
            descripteur = cat.creer_descripteur(
                action, plugin=greffon, parametres=parametres, erreurs=erreurs,
                codes_connus=codes | {CODE_TOUJOURS_ADMIS})
        except (ValueError, TypeError):
            raise _invalide() from None
        actions.append(ActionService(action, suivi, export, transmis, descripteur, journaliser))
    if sum(a.suivi for a in actions) > 1:
        raise _invalide()
    return tuple(actions)


def _service(table, nom_base):
    """Valide le contenu analysé ; ErreurService sinon. Format et forme d'abord."""
    if type(table.get('format')) is not int:
        raise _invalide()
    if table['format'] != FORMAT:
        raise ErreurService('service_format_unsupported')
    forme = table.get('forme', FORME)
    if type(forme) is not str:
        raise _invalide()
    if forme != FORME:
        raise ErreurService('service_form_unsupported')
    if not set(table) <= CLES_DECLARATION or not {'greffon', 'domaine'} <= set(table):
        raise _invalide()
    if 'actions' not in table and not (table.get('sans_destination') is True):
        raise _invalide()
    greffon, domaine = table['greffon'], table['domaine']
    if (type(greffon) is not str or not MOTIF_GREFFON.match(greffon) or greffon != nom_base
            or type(domaine) is not str or not MOTIF_DOMAINE.match(domaine)
            or domaine in cat.DOMAINES_RESERVES):
        raise _invalide()
    cible = table.get('cible', cat.CIBLE_DEFAUT)
    if type(cible) is not str or not cat.MOTIF_CIBLE.match(cible):
        raise _invalide()
    obligatoire = _booleen(table, 'obligatoire', True)
    sans_destination = _booleen(table, 'sans_destination')
    ping = _booleen(table, 'ping')
    destination = table.get('destination', domaine)
    if type(destination) is not str or not MOTIF_DESTINATION.match(destination):
        raise _invalide()
    mode = table.get('catalogue', 'aucun')
    if type(mode) is not str or mode not in CATALOGUES:
        raise _invalide()
    codes = frozenset(_liste_codes(table.get('codes', [])))
    ping_oubli = frozenset(_liste_codes(table.get('ping_oubli', [])))
    if ping_oubli and not ping:
        raise _invalide()
    actions = _actions(table.get('actions', []), domaine, greffon, codes, mode,
                       vide_admis=sans_destination)
    pages = _pages(table.get('pages', []), greffon)
    suivi = any(a.suivi for a in actions)
    if sans_destination:
        if ('section' in table or 'options' in table or ping or suivi or mode != 'aucun'):
            raise _invalide()
        section, options = None, ()
    else:
        section = table.get('section')
        if (type(section) is not str or not MOTIF_IDENTIFIANT.match(section)
                or section in SECTIONS_RESERVEES):
            raise _invalide()
        options = _options(table.get('options'), obligatoire)
        roles = {o.role for o in options if o.role is not None}
        requis = ROLES_BASE | (ROLES_SUIVI if suivi else frozenset()) \
            | (ROLES_PING if ping else frozenset())
        if not requis <= roles or not roles <= requis | ROLES_FACULTATIFS:
            raise _invalide()
    try:
        catalogue = cat.Catalogue(cible, domaine, [a.descripteur for a in actions])
    except ValueError:
        raise _invalide() from None
    return Service(greffon, cible, domaine, section, options, obligatoire, sans_destination,
                   destination, ping, ping_oubli, actions, codes, mode, catalogue, pages)


def _analyser(octets):
    try:
        table = tomllib.loads(octets.decode('utf-8'))
    except (tomllib.TOMLDecodeError, UnicodeError, RecursionError, ValueError):
        raise _invalide() from None
    return table


def _lire_octets(descripteur):
    morceaux, taille = [], 0
    while True:
        bloc = os.read(descripteur, 8192)
        if not bloc:
            break
        taille += len(bloc)
        if taille > MANIFESTE_MAX:
            raise _invalide()
        morceaux.append(bloc)
    return b''.join(morceaux)


def _charger_fichier(entree, dossier_fd, proprietaires):
    """Lit, contrôle et valide un fichier ; ErreurService sinon (code stable, nom de base)."""
    base = entree[:-len('.toml')]
    try:
        attributs = os.stat(entree, dir_fd=dossier_fd, follow_symlinks=False)
        if stat.S_ISLNK(attributs.st_mode):
            raise ErreurService('plugin_unsafe_permissions')
        if not stat.S_ISREG(attributs.st_mode):
            raise ErreurService('plugin_unexpected_entry')
        descripteur = ouvrir_fichier_controle(entree, dossier_fd, proprietaires)
        try:
            octets = _lire_octets(descripteur)
        finally:
            os.close(descripteur)
        return _service(_analyser(octets), base)
    except ErreurService as erreur:
        raise ErreurService(erreur.code, entree) from None
    except ErreurPlugin as erreur:
        raise ErreurService(erreur.code, entree) from None
    except Exception:
        # Frontière du fichier : tout défaut inattendu est typé, jamais propagé tel quel.
        raise ErreurService('plugin_unreadable', entree) from None


def _compatible(service, deja, cible):
    """Contrôles croisés avec les services déjà acceptés ; ErreurService sinon."""
    if cible is not None and service.cible != cible:
        raise _invalide()
    for autre in deja:
        if (autre.domaine == service.domaine or autre.greffon == service.greffon
                or (service.section is not None and autre.section == service.section)):
            raise _invalide()
    comportements = [s for s in (*deja, service)
                     if s.ping or any(a.suivi for a in s.actions)]
    if len(comportements) > 1:
        raise _invalide()


def _evenement(rappel, evenement, niveau, **champs):
    if rappel is None:
        return
    try:
        rappel(evenement, niveau, **champs)
    except Exception:
        # Un rappel défaillant ne doit pas interrompre le chargement.
        pass


def charger(dossier_livre, dossier_local, *, proprietaires=frozenset({0}),
            racine_confiance='/', rappel=None):
    """Charge les déclarations des deux dossiers ; retourne Declarations (aucune exécution).

    rappel(evenement, niveau, **champs) : journalisation du démon (`service_declaration_rejected`
    au niveau error, avec code, scope et file), sans chemin ni valeur fautive.
    Livré défectueux : ErreurService. Local défectueux : ignoré et journalisé.
    """
    proprietaires = frozenset(proprietaires)
    services, rejets = [], []
    for scope, dossier in (('livre', dossier_livre), ('local', dossier_local)):
        local = scope == 'local'
        base = 'invalid_name'
        acceptes, rejets_dossier, evenements = [], [], []
        defaut = None
        try:
            base = os.path.basename(os.path.abspath(os.fspath(dossier)))
            dossier_fd = ouvrir_dossier_confiance(dossier, racine_confiance, proprietaires)
            if dossier_fd is None:
                continue
            try:
                entrees = sorted(os.listdir(dossier_fd))
                if len(entrees) > FICHIERS_MAX:
                    raise ErreurService('plugin_too_many')
                cible = services[0].cible if services else None
                for entree in entrees:
                    try:
                        if not MOTIF_FICHIER.match(entree):
                            raise ErreurService('plugin_unexpected_entry', entree)
                        service = _charger_fichier(entree, dossier_fd, proprietaires)
                        _compatible(service, [*services, *acceptes], cible)
                        if cible is None:
                            cible = service.cible
                        acceptes.append(service)
                    except ErreurService as erreur:
                        if not local:
                            raise ErreurService(erreur.code, erreur.fichier or entree) from None
                        fichier = _nom_publie(erreur.fichier or entree)
                        rejets_dossier.append(Rejet(erreur.code, 'local', fichier))
                        evenements.append(('service_declaration_rejected', 'error',
                                           {'code': erreur.code, 'scope': 'local',
                                            'file': fichier}))
            finally:
                os.close(dossier_fd)
        except ErreurPlugin as erreur:
            defaut = ErreurService(erreur.code, erreur.fichier or base)
        except ErreurService as erreur:
            defaut = erreur
        except Exception:
            # Frontière du dossier : aucun défaut inattendu ne publie un état partiel.
            defaut = ErreurService('plugin_unreadable', base)
        else:
            services += acceptes
            rejets += rejets_dossier
            for evenement, niveau, champs in evenements:
                _evenement(rappel, evenement, niveau, **champs)
            continue
        if not local:
            raise ErreurService(defaut.code, defaut.fichier or base) from None
        fichier = _nom_publie(base)
        rejets.append(Rejet(defaut.code, 'local', fichier))
        _evenement(rappel, 'service_declaration_rejected', 'error', code=defaut.code,
                   scope='local', file=fichier)
    cible = services[0].cible if services else cat.CIBLE_DEFAUT
    return Declarations(tuple(services), tuple(rejets), cible)


def verifier_options(declarations, config):
    """Contrôles croisés déclarés (`maximum`, `inferieure_a`) sur la configuration lue.

    ErreurConfiguration('config_invalid', section, option) ; une section ou une valeur absente
    (service facultatif non configuré) n'est pas contrôlée. Un chemin de socket sans uid attendu
    (ou l'inverse), pour le service comme pour son ping, est refusé : l'uid du serveur est toujours
    vérifié.
    """
    for service in declarations.services:
        section = config.get(service.section) if service.section is not None else None
        if not section:
            continue
        for role_chemin, role_uid in (('socket', 'uid'), ('ping_socket', 'ping_uid')):
            noms = {o.role: o.nom for o in service.options
                    if o.role in (role_chemin, role_uid)}
            if len(noms) == 2 and ((section.get(noms[role_chemin]) is None)
                                   != (section.get(noms[role_uid]) is None)):
                raise ErreurConfiguration('config_invalid', service.section, noms[role_uid])
        for option in service.options:
            valeur = section.get(option.nom)
            if valeur is None:
                continue
            if option.maximum is not None and valeur > option.maximum:
                raise ErreurConfiguration('config_invalid', service.section, option.nom)
            autre = section.get(option.inferieure_a) if option.inferieure_a else None
            if autre is not None and not valeur < autre:
                raise ErreurConfiguration('config_invalid', service.section, option.nom)
