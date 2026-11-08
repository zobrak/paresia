# SPDX-License-Identifier: AGPL-3.0-or-later
# Catalogue d'actions : descripteurs, répertoire, introspection ; dépendances : texte.
# Suivi des versions
#   0.1.15  2026-11-08  Domaine kernel réservé (domaine d'administration du noyau).
#   0.1.5  2026-11-07  Descripteurs, répertoire, introspection et noms Varlink (D154).
"""Source unique des actions d'un démon enfichable.

Un Catalogue décrit les actions d'une cible et d'un domaine ; un Repertoire en
tient autant que voulu, indexés par (cible, domaine). Le module ne limite ni le
nombre de cibles ni celui de domaines : ces limites appartiennent aux démons.

L'introspection se fait par deux actions que le noyau définit par leur seul
suffixe, `<domaine>/catalog/list` et `<domaine>/catalog/describe` : lecture
seule, aucun secret, aucun chemin, aucune commande privilégiée.

Traduction en interface Varlink (sans perte de sens, sans générateur) : le
domaine est l'interface, `objet/operation` devient la méthode `ObjetOperation`
(nom_varlink), chaque paramètre est un champ typé selon TYPES_VARLINK, chaque
code d'erreur une erreur nommée `<interface>.<CodeEnCamelCase>`. Ce que l'IDL ne
porte pas (BORNES_VARLINK) reste dans le descripteur et dans `describe`.
"""
from dataclasses import dataclass
import math
import re
from types import MappingProxyType

from .texte import filtrer

PROTO_CATALOGUE = 'jumeaux/1'
FORMAT = 1
FORME_PONCTUELLE = 'ponctuel'
CIBLE_DEFAUT = 'principale'
DOMAINES_RESERVES = frozenset({'presence', 'castor', 'kernel'})
SUFFIXE_LIST = 'catalog/list'
SUFFIXE_DESCRIBE = 'catalog/describe'
MOTIF_ACTION = re.compile(r'(?=.{1,128}\Z)[a-z][a-z0-9_-]*(?:/[a-z][a-z0-9_-]*){1,3}\Z')
MOTIF_CIBLE = re.compile(r'[a-z][a-z0-9_]{0,31}\Z')
MOTIF_DOMAINE = re.compile(r'[a-z][a-z0-9_-]{0,63}\Z')
MOTIF_NOM_PARAMETRE = re.compile(r'[a-z][a-z0-9_]{0,63}\Z')
MOTIF_CODE = re.compile(r'[a-z][a-z0-9_]{0,63}\Z')
MOTIF_NOM_VARLINK = re.compile(r'[A-Z][A-Za-z0-9]*\Z')
TYPES = ('texte', 'entier', 'choix', 'hexadecimal', 'liste_entiers', 'liste_texte')
# Correspondance de chaque type avec un type d'IDL Varlink.
TYPES_VARLINK = MappingProxyType({
    'texte': 'string', 'hexadecimal': 'string', 'entier': 'int', 'choix': 'enum',
    'liste_entiers': '[]int', 'liste_texte': '[]string',
})
# Bornes obligatoires et facultatives de chaque type.
BORNES_REQUISES = MappingProxyType({
    'texte': frozenset({'motif', 'longueur_max'}),
    'entier': frozenset({'minimum', 'maximum'}),
    'choix': frozenset({'valeurs'}),
    'hexadecimal': frozenset({'longueur'}),
    'liste_entiers': frozenset({'minimum', 'maximum', 'nombre_max'}),
    'liste_texte': frozenset({'motif', 'longueur_max', 'nombre_max'}),
})
BORNES_FACULTATIVES = MappingProxyType({
    'texte': frozenset(), 'entier': frozenset(), 'choix': frozenset(),
    'hexadecimal': frozenset(),
    'liste_entiers': frozenset({'nombre_min'}), 'liste_texte': frozenset({'nombre_min'}),
})
VOCABULAIRE_BORNES = frozenset({'motif', 'longueur_max', 'minimum', 'maximum', 'valeurs',
                                'longueur', 'nombre_min', 'nombre_max'})
# Correspondance de chaque borne avec l'IDL : aucune n'y a d'équivalent, sauf `valeurs`
# (énumération). Elles restent portées par le descripteur et par `describe`.
BORNES_VARLINK = MappingProxyType({
    'motif': 'descripteur', 'longueur_max': 'descripteur', 'minimum': 'descripteur',
    'maximum': 'descripteur', 'valeurs': 'enumeration', 'longueur': 'descripteur',
    'nombre_min': 'descripteur', 'nombre_max': 'descripteur',
})
LONGUEUR_TEXTE_MAX = 65536
LONGUEUR_HEXA_MAX = 4096
NOMBRE_ELEMENTS_MAX = 4096
VALEURS_CHOIX_MAX = 256
LONGUEUR_VALEUR_MAX = 256
LONGUEUR_MOTIF_MAX = 512
BORNE_ENTIER = 2 ** 63


class ErreurCatalogue(Exception):
    """Réponse d'introspection refusée ; `code` est un code de protocole existant."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _entier(valeur):
    return type(valeur) is int


def _bornes_valides(type_, bornes):
    """Retourne les bornes normalisées (tuples) ou lève ValueError('invalid_catalog')."""
    if type(bornes) is not dict and not isinstance(bornes, MappingProxyType):
        raise ValueError('invalid_catalog')
    requises, facultatives = BORNES_REQUISES[type_], BORNES_FACULTATIVES[type_]
    cles = set(bornes)
    if not requises <= cles or not cles <= requises | facultatives:
        raise ValueError('invalid_catalog')
    sortie = {}
    for cle, valeur in bornes.items():
        if cle == 'motif':
            if (type(valeur) is not str or not 1 <= len(valeur) <= LONGUEUR_MOTIF_MAX
                    or filtrer(valeur) != valeur):
                raise ValueError('invalid_catalog')
            try:
                re.compile(valeur)
            except (re.error, RecursionError, OverflowError):
                raise ValueError('invalid_catalog') from None
        elif cle == 'longueur_max':
            if not _entier(valeur) or not 1 <= valeur <= LONGUEUR_TEXTE_MAX:
                raise ValueError('invalid_catalog')
        elif cle == 'longueur':
            if not _entier(valeur) or not 1 <= valeur <= LONGUEUR_HEXA_MAX:
                raise ValueError('invalid_catalog')
        elif cle in ('minimum', 'maximum'):
            if not _entier(valeur) or not -BORNE_ENTIER <= valeur < BORNE_ENTIER:
                raise ValueError('invalid_catalog')
        elif cle in ('nombre_min', 'nombre_max'):
            if not _entier(valeur) or not 0 <= valeur <= NOMBRE_ELEMENTS_MAX:
                raise ValueError('invalid_catalog')
        elif cle == 'valeurs':
            if (not isinstance(valeur, (list, tuple)) or not 1 <= len(valeur) <= VALEURS_CHOIX_MAX
                    or len(set(valeur)) != len(valeur)
                    or any(type(v) is not str or not 1 <= len(v) <= LONGUEUR_VALEUR_MAX
                           or filtrer(v) != v for v in valeur)):
                raise ValueError('invalid_catalog')
            valeur = tuple(valeur)
        else:
            raise ValueError('invalid_catalog')
        sortie[cle] = valeur
    if 'minimum' in sortie and sortie['minimum'] > sortie['maximum']:
        raise ValueError('invalid_catalog')
    if 'nombre_max' in sortie and sortie.get('nombre_min', 0) > sortie['nombre_max']:
        raise ValueError('invalid_catalog')
    if 'nombre_max' in sortie and sortie['nombre_max'] < 1:
        raise ValueError('invalid_catalog')
    return MappingProxyType(sortie)


@dataclass(frozen=True)
class Parametre:
    """Paramètre typé et borné ; toutes les bornes du type sont obligatoires."""
    nom: str
    type: str
    bornes: object
    obligatoire: bool = True

    def __post_init__(self):
        if (type(self.nom) is not str or not MOTIF_NOM_PARAMETRE.match(self.nom)
                or self.type not in TYPES or type(self.obligatoire) is not bool):
            raise ValueError('invalid_catalog')
        object.__setattr__(self, 'bornes', _bornes_valides(self.type, self.bornes))

    def publier(self):
        bornes = {cle: (list(v) if isinstance(v, tuple) else v) for cle, v in self.bornes.items()}
        return {'name': self.nom, 'type': self.type, 'required': self.obligatoire,
                'bounds': bornes}


def action_valide(action):
    return type(action) is str and MOTIF_ACTION.match(action) is not None


def action_catalogue(domaine, operation):
    """Action d'introspection d'un domaine ; operation : 'list' ou 'describe'."""
    if (type(domaine) is not str or not MOTIF_DOMAINE.match(domaine)
            or operation not in ('list', 'describe')):
        raise ValueError('invalid_catalog')
    return f'{domaine}/catalog/{operation}'


def est_suffixe_catalogue(action):
    return action.endswith('/' + SUFFIXE_LIST) or action.endswith('/' + SUFFIXE_DESCRIBE)


def _camel(parties):
    return ''.join(p[:1].upper() + p[1:] for p in parties)


def nom_varlink(action):
    """`domaine/objet/operation` devient `ObjetOperation` (le domaine est l'interface)."""
    if not action_valide(action):
        raise ValueError('invalid_catalog')
    parties = []
    for segment in action.split('/')[1:]:
        morceaux = re.split(r'[-_]', segment)
        if '' in morceaux:
            raise ValueError('invalid_catalog')
        parties.extend(morceaux)
    nom = _camel(parties)
    if not MOTIF_NOM_VARLINK.match(nom):
        raise ValueError('invalid_catalog')
    return nom


def nom_erreur_varlink(domaine, code):
    """Erreur nommée `<interface>.<CodeEnCamelCase>` ; le domaine fait l'interface."""
    if (type(domaine) is not str or not MOTIF_DOMAINE.match(domaine)
            or type(code) is not str or not MOTIF_CODE.match(code)):
        raise ValueError('invalid_catalog')
    nom = _camel(code.split('_'))
    if not MOTIF_NOM_VARLINK.match(nom):
        raise ValueError('invalid_catalog')
    return f'{domaine}.{nom}'


@dataclass(frozen=True)
class Descripteur:
    """Description d'une action ; `plugin` nomme seulement le greffon qui répond."""
    action: str
    plugin: object = None
    privilege: object = None
    forme: str = FORME_PONCTUELLE
    delai_s: object = None
    parametres: tuple = ()
    erreurs: tuple = ()

    def __post_init__(self):
        if not action_valide(self.action) or self.forme != FORME_PONCTUELLE:
            raise ValueError('invalid_catalog')
        if self.plugin is not None and (type(self.plugin) is not str or not self.plugin):
            raise ValueError('invalid_catalog')
        if self.privilege is not None and (type(self.privilege) is not str or not self.privilege):
            raise ValueError('invalid_catalog')
        if self.delai_s is not None and (
                type(self.delai_s) not in (int, float) or not math.isfinite(self.delai_s)
                or self.delai_s <= 0):
            raise ValueError('invalid_catalog')
        parametres = tuple(self.parametres)
        erreurs = tuple(self.erreurs)
        if (any(type(p) is not Parametre for p in parametres)
                or len({p.nom for p in parametres}) != len(parametres)
                or any(type(c) is not str or not MOTIF_CODE.match(c) for c in erreurs)
                or len(set(erreurs)) != len(erreurs)):
            raise ValueError('invalid_catalog')
        object.__setattr__(self, 'parametres', parametres)
        object.__setattr__(self, 'erreurs', erreurs)

    def publier(self):
        return {'action': self.action, 'plugin': self.plugin, 'privilege': self.privilege,
                'delay_s': self.delai_s,
                'parameters': [p.publier() for p in self.parametres],
                'errors': list(self.erreurs)}


def creer_descripteur(action, *, plugin=None, privilege=None, delai_s=None, parametres=(),
                      erreurs=(), codes_connus=None):
    """Construit un descripteur ; si codes_connus est fourni, `erreurs` doit y figurer."""
    if codes_connus is not None and not set(erreurs) <= set(codes_connus):
        raise ValueError('invalid_catalog')
    return Descripteur(action, plugin, privilege, FORME_PONCTUELLE, delai_s,
                       tuple(parametres), tuple(erreurs))


def _descripteurs_catalogue(domaine):
    parametre = Parametre('action', 'texte',
                          {'motif': MOTIF_ACTION.pattern, 'longueur_max': 128})
    return (Descripteur(action_catalogue(domaine, 'list')),
            Descripteur(action_catalogue(domaine, 'describe'), parametres=(parametre,)))


class Catalogue:
    """Descripteurs d'une cible et d'un domaine, immuable après construction.

    Les deux actions de catalogue y sont ajoutées d'office. Les noms de méthode
    Varlink dérivés des actions sont uniques, sinon le catalogue est refusé.
    """

    def __init__(self, cible, domaine, descripteurs=()):
        if type(cible) is not str or not MOTIF_CIBLE.match(cible):
            raise ValueError('invalid_catalog')
        if type(domaine) is not str or not MOTIF_DOMAINE.match(domaine):
            raise ValueError('invalid_catalog')
        self._cible, self._domaine = cible, domaine
        tous = _descripteurs_catalogue(domaine) + tuple(descripteurs)
        par_action, noms = {}, set()
        for descripteur in tous:
            if (type(descripteur) is not Descripteur
                    or descripteur.action.split('/')[0] != domaine
                    or descripteur.action in par_action):
                raise ValueError('invalid_catalog')
            nom = nom_varlink(descripteur.action)
            if nom in noms:
                raise ValueError('invalid_catalog')
            noms.add(nom)
            par_action[descripteur.action] = descripteur
        self._action_list = action_catalogue(domaine, 'list')
        self._action_describe = action_catalogue(domaine, 'describe')
        self._par_action = MappingProxyType(par_action)

    cible = property(lambda self: self._cible)
    domaine = property(lambda self: self._domaine)
    actions = property(lambda self: frozenset(self._par_action))
    descripteurs = property(lambda self: self._par_action)

    def __setattr__(self, nom, valeur):
        if '_par_action' not in self.__dict__:
            object.__setattr__(self, nom, valeur)
            return
        raise AttributeError('immutable_catalog')

    def descripteur(self, action):
        return self._par_action.get(action)

    def est_catalogue(self, action):
        return action in (self._action_list, self._action_describe)

    def reponse(self, action, params):
        """Données de `list` ou `describe` ; lève ErreurCatalogue (bad_request, unknown_action)."""
        if action == self._action_list:
            if not isinstance(params, dict) or params:
                raise ErreurCatalogue('bad_request')
            return {'proto': PROTO_CATALOGUE, 'target': self._cible, 'domain': self._domaine,
                    'format': FORMAT,
                    'actions': [{'action': a, 'plugin': self._par_action[a].plugin}
                                for a in sorted(self._par_action)]}
        if action == self._action_describe:
            if (not isinstance(params, dict) or set(params) != {'action'}
                    or not action_valide(params['action'])):
                raise ErreurCatalogue('bad_request')
            descripteur = self._par_action.get(params['action'])
            if descripteur is None:
                raise ErreurCatalogue('unknown_action')
            return descripteur.publier()
        raise ErreurCatalogue('unknown_action')


class Repertoire:
    """Catalogues indexés par (cible, domaine), en nombre quelconque."""

    def __init__(self, catalogues=()):
        table = {}
        for catalogue in catalogues:
            cle = (catalogue.cible, catalogue.domaine)
            if type(catalogue) is not Catalogue or cle in table:
                raise ValueError('invalid_catalog')
            table[cle] = catalogue
        self._table = MappingProxyType(table)

    def obtenir(self, cible, domaine):
        return self._table.get((cible, domaine))

    def cles(self):
        return sorted(self._table)

    def actions(self, cible, domaine):
        catalogue = self._table.get((cible, domaine))
        return catalogue.actions if catalogue is not None else frozenset()

    def reponse(self, cible, domaine, action, params):
        catalogue = self._table.get((cible, domaine))
        if catalogue is None:
            raise ErreurCatalogue('unknown_action')
        return catalogue.reponse(action, params)


__all__ = ['Catalogue', 'Descripteur', 'ErreurCatalogue', 'Parametre', 'Repertoire',
           'MOTIF_ACTION', 'action_catalogue', 'creer_descripteur', 'nom_varlink']
