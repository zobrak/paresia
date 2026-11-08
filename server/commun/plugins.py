# SPDX-License-Identifier: AGPL-3.0-or-later
# Chargeur de fonctions : manifestes TOML, contrôle des fichiers, aucune exécution.
# Dépendances : bibliothèque standard (tomllib), catalogue, privileges, jumeaux, sortie.
# Suivi des versions
#   0.1.5  2026-11-07  Chargeur contrôlé, rejets typés et dossiers atomiques (D148, D154).
"""Chargeur de fonctions d'un démon enfichable.

Une fonction = deux fichiers de même nom dans un dossier : `<nom>` (script
exécutable) et `<nom>.toml` (manifeste). Le chargeur lit et contrôle, il
n'exécute rien et n'importe aucun code de fonction : un script est un
exécutable séparé, lancé hors processus par le démon.

Politique : tout défaut d'un élément livré est fatal (ErreurPlugin) ; tout
défaut d'un élément local fait ignorer cet élément (le dossier entier si le
défaut touche le dossier ou ses ancêtres ; aucune de ses fonctions n'est gardée)
et alimente la liste des rejets. Exception unique :
une condition de chargement non remplie écarte la fonction sans erreur.

Limite assumée : le champ `privilege` est une étiquette publiée, non appliquée à
l'appel ; avec sudo, les droits sont ceux du compte du démon.
"""
from dataclasses import dataclass, field
import math
import os
import re
import stat
import tomllib
from types import MappingProxyType

from . import catalogue as cat
from .catalogue import Catalogue, Parametre, creer_descripteur, nom_varlink
from .jumeaux import PLAFOND_DELAI, PLAFOND_LIMITE
from .privileges import valeurs_choix_valides, valider_commandes, vers_sudo
from .sortie import SORTIE_MAX_DEFAUT
from .texte import filtrer

COTES = ('yin', 'yang')
FORMAT = cat.FORMAT
FORME = cat.FORME_PONCTUELLE
PRIVILEGES_CONNUS = frozenset({'utilisateurs'})
CLES_MANIFESTE = frozenset({'format', 'forme', 'greffon', 'nom', 'action', 'privilege', 'delai_s',
                            'sortie_max', 'flux', 'journaliser', 'erreurs', 'parametres',
                            'commandes_privilegiees', 'requiert', 'produit', 'compatible_yang'})
CLES_PRODUIT = frozenset({'nom', 'source', 'version', 'empreinte'})
COMPATIBLES_MAX = 16
CLAUSE_VERSION = re.compile(r'(>=|<=|>|<)[0-9][0-9A-Za-z.+-]{0,31}\Z')
VERSION_EXACTE = re.compile(r'[0-9A-Za-z][0-9A-Za-z.+_-]{0,63}\Z')
CLAUSES_MAX = 4
CLES_PARAMETRE = frozenset({'nom', 'type', 'obligatoire'}) | cat.VOCABULAIRE_BORNES
CLES_REQUIERT = frozenset({'binaires', 'fichiers'})
TYPES_MANIFESTE = tuple(t for t in cat.TYPES if t != 'liste_texte')
MOTIF_NOM = re.compile(r'[a-z][a-z0-9_]{0,63}\Z')
FONCTIONS_MAX = 256
MANIFESTE_MAX = 65536
PARAMETRES_MAX = 16
CHEMINS_MAX = 8
CHEMIN_LONGUEUR_MAX = 4096
ERREURS_MAX = 64


class ErreurPlugin(Exception):
    """Défaut fatal ; `str()` et `code` donnent un code stable, `fichier` un nom de base."""

    def __init__(self, code, fichier=None):
        super().__init__(code)
        self.code = code
        self.fichier = None if fichier is None else _nom_publie(fichier)


@dataclass(frozen=True)
class Rejet:
    code: str
    scope: str
    file: str


@dataclass(frozen=True)
class Fonction:
    """Ce dont le démon a besoin pour exécuter ; jamais publié par l'introspection."""
    nom: str
    greffon: str
    script: str
    descripteur: object
    journaliser: tuple
    sortie_max: int
    commandes: tuple
    produit: object = field(default=None, repr=False)
    compatible_yang: tuple = field(default=(), repr=False)


@dataclass(frozen=True)
class Chargement:
    catalogue: object
    rejets: tuple
    fonctions: object
    greffons: object = MappingProxyType({})   # {greffon: {'produit': ..., 'compatible_yang': ...}}


def _journal(rappel, evenement, niveau, **champs):
    if rappel is None:
        return
    try:
        rappel(evenement, niveau, **champs)
    except Exception:
        # Un rappel défaillant ne doit pas interrompre le chargement.
        pass


# --- Contrôle des fichiers (réutilisable) -----------------------------------------------

def _ouvrir(nom, drapeaux, dir_fd=None):
    try:
        return os.open(nom, drapeaux | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dir_fd)
    except FileNotFoundError:
        return None
    except OSError as erreur:
        if erreur.errno in (40, 20):  # ELOOP, ENOTDIR : lien symbolique ou type inattendu
            raise ErreurPlugin('plugin_unsafe_permissions') from None
        raise ErreurPlugin('plugin_unreadable') from None


def _dossier_sur(descripteur, proprietaires):
    attributs = os.fstat(descripteur)
    if (not stat.S_ISDIR(attributs.st_mode) or attributs.st_uid not in proprietaires
            or attributs.st_mode & 0o022):
        raise ErreurPlugin('plugin_unsafe_permissions')


def ouvrir_dossier_confiance(dossier, racine_confiance, proprietaires):
    """Ouvre `dossier` en contrôlant chaque ancêtre jusqu'à `racine_confiance` incluse.

    Retourne un descripteur de dossier, ou None si le dossier (ou un ancêtre) est absent.
    Propriétaire dans `proprietaires`, aucune écriture groupe ou autres (même « sticky »),
    aucun lien symbolique. ErreurPlugin('plugin_unsafe_permissions') sinon.
    """
    dossier = os.path.abspath(os.fspath(dossier))
    racine = os.path.abspath(os.fspath(racine_confiance))
    if dossier != racine and not dossier.startswith(racine.rstrip('/') + '/'):
        raise ErreurPlugin('plugin_unsafe_permissions')
    composants = [c for c in dossier[len(racine):].split('/') if c]
    courant = _ouvrir(racine, os.O_RDONLY | os.O_DIRECTORY)
    if courant is None:
        return None
    try:
        _dossier_sur(courant, proprietaires)
        for composant in composants:
            suivant = _ouvrir(composant, os.O_RDONLY | os.O_DIRECTORY, courant)
            os.close(courant)
            courant = suivant
            if courant is None:
                return None
            _dossier_sur(courant, proprietaires)
        resultat, courant = courant, None
        return resultat
    finally:
        if courant is not None:
            os.close(courant)


def ouvrir_fichier_controle(nom, dir_fd, proprietaires, *, executable=False):
    """Ouvre un fichier ordinaire du dossier `dir_fd` et le contrôle sur le descripteur.

    Propriétaire dans `proprietaires`, `mode & 0o022 == 0`, `mode & 0o6000 == 0`, et pour un
    script au moins un bit d'exécution du propriétaire. Retourne le descripteur (à fermer).
    """
    descripteur = _ouvrir(nom, os.O_RDONLY | os.O_NONBLOCK, dir_fd)
    if descripteur is None:
        raise ErreurPlugin('plugin_incomplete', nom)
    try:
        attributs = os.fstat(descripteur)
        if not stat.S_ISREG(attributs.st_mode):
            raise ErreurPlugin('plugin_unexpected_entry', nom)
        if (attributs.st_uid not in proprietaires or attributs.st_mode & 0o022
                or attributs.st_mode & 0o6000
                or (executable and not attributs.st_mode & 0o100)):
            raise ErreurPlugin('plugin_unsafe_permissions', nom)
    except BaseException:
        os.close(descripteur)
        raise
    return descripteur


# --- Manifeste ----------------------------------------------------------------------------

def _invalide():
    return ErreurPlugin('plugin_manifest_invalid')


def _analyser(octets):
    """Analyse TOML isolée : seule fonction qui connaît le format du manifeste."""
    try:
        return tomllib.loads(octets.decode('utf-8'))
    except (tomllib.TOMLDecodeError, UnicodeError, RecursionError, ValueError):
        raise _invalide() from None


def _lire_manifeste(descripteur):
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


def _nombre_positif(valeur, plafond):
    return (type(valeur) in (int, float) and math.isfinite(valeur) and 0 < valeur <= plafond)


def _chemins(valeur):
    if (type(valeur) is not list or len(valeur) > CHEMINS_MAX
            or any(type(c) is not str or not c.startswith('/') or '\0' in c
                   or len(c) > CHEMIN_LONGUEUR_MAX for c in valeur)):
        raise _invalide()
    return tuple(valeur)


def _parametre(table):
    if type(table) is not dict or not set(table) <= CLES_PARAMETRE:
        raise _invalide()
    if table.get('type') not in TYPES_MANIFESTE or 'nom' not in table:
        raise _invalide()
    bornes = {c: v for c, v in table.items() if c in cat.VOCABULAIRE_BORNES}
    try:
        return Parametre(table['nom'], table['type'], bornes, table.get('obligatoire', True))
    except ValueError:
        raise _invalide() from None


@dataclass(frozen=True)
class _Manifeste:
    descripteur: object
    journaliser: tuple
    sortie_max: int
    commandes: tuple
    requiert: tuple
    produit: object = None
    compatible_yang: tuple = ()


def version_valide(version):
    """Grammaire fermée : version exacte, ou 1 à 4 clauses `>=`, `<=`, `>`, `<` séparées par `,`."""
    if type(version) is not str or not version or len(version) > 160:
        return False
    if ',' not in version and not version.startswith(('>', '<')):
        return VERSION_EXACTE.match(version) is not None
    clauses = version.split(',')
    return len(clauses) <= CLAUSES_MAX and all(CLAUSE_VERSION.match(c) for c in clauses)


def _produit(table):
    if (type(table) is not dict or not set(table) <= CLES_PRODUIT
            or not {'nom', 'source', 'version'} <= set(table)):
        raise _invalide()
    nom, source, version = table['nom'], table['source'], table['version']
    if (type(nom) is not str or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,31}', nom)
            or type(source) is not str or not 1 <= len(source) <= 256
            or not source.isascii() or not source.isprintable() or ' ' in source
            or not version_valide(version)):
        raise _invalide()
    empreinte = table.get('empreinte')
    if empreinte is not None and (type(empreinte) is not str
                                  or not re.fullmatch(r'sha256:[0-9a-f]{64}', empreinte)):
        raise _invalide()
    return MappingProxyType({'nom': nom, 'source': source, 'version': version,
                             'empreinte': empreinte})


def _compatibles(valeur):
    if (type(valeur) is not list or len(valeur) > COMPATIBLES_MAX
            or len(set(valeur)) != len(valeur)
            or any(type(n) is not str
                   or not re.fullmatch(r'paresia-yang-[a-z][a-z0-9-]{0,31}', n) for n in valeur)):
        raise _invalide()
    return tuple(valeur)


def _manifeste(table, nom, cote, domaine, codes_connus):
    """Valide le contenu analysé ; ErreurPlugin sinon. Format et forme d'abord."""
    if type(table.get('format')) is not int:
        raise _invalide()
    if table['format'] != FORMAT:
        raise ErreurPlugin('plugin_format_unsupported')
    forme = table.get('forme', FORME)
    if type(forme) is not str:
        raise _invalide()
    if forme != FORME:
        raise ErreurPlugin('plugin_form_unsupported')
    if (not set(table) <= CLES_MANIFESTE
            or not {'greffon', 'nom', 'action', 'delai_s'} <= set(table)):
        raise _invalide()
    greffon, action = table['greffon'], table['action']
    if (type(greffon) is not str
            or not re.fullmatch(rf'paresia-{cote}-[a-z][a-z0-9-]{{0,31}}', greffon)
            or table['nom'] != nom):
        raise _invalide()
    parties = action.split('/') if type(action) is str else []
    if (not cat.action_valide(action) or parties[0] != domaine
            or cat.est_suffixe_catalogue(action)):
        raise _invalide()
    privilege = table.get('privilege')
    if privilege is not None and privilege not in PRIVILEGES_CONNUS:
        raise _invalide()
    if not _nombre_positif(table['delai_s'], PLAFOND_DELAI):
        raise _invalide()
    sortie_max = table.get('sortie_max', SORTIE_MAX_DEFAUT)
    if type(sortie_max) is not int or not 1 <= sortie_max <= PLAFOND_LIMITE:
        raise _invalide()
    if table.get('flux', False) is not False:
        raise _invalide()
    brutes = table.get('parametres', [])
    if type(brutes) is not list or len(brutes) > PARAMETRES_MAX:
        raise _invalide()
    parametres = tuple(_parametre(p) for p in brutes)
    if len({p.nom for p in parametres}) != len(parametres) or not valeurs_choix_valides(parametres):
        raise _invalide()
    journaliser = table.get('journaliser', [])
    if (type(journaliser) is not list
            or any(type(j) is not str for j in journaliser)
            or len(set(journaliser)) != len(journaliser)
            or any(j not in {p.nom for p in parametres} for j in journaliser)):
        raise _invalide()
    erreurs = table.get('erreurs', ['command_failed'])
    if (type(erreurs) is not list or len(erreurs) > ERREURS_MAX
            or any(type(e) is not str for e in erreurs)
            or (table.get('erreurs') is not None and not set(erreurs) <= set(codes_connus))):
        raise _invalide()
    try:
        descripteur = creer_descripteur(action, plugin=greffon, privilege=privilege,
                                        delai_s=table['delai_s'], parametres=parametres,
                                        erreurs=erreurs)
        commandes = valider_commandes(table.get('commandes_privilegiees', []), parametres)
    except ValueError:
        raise _invalide() from None
    requiert = table.get('requiert', {})
    if type(requiert) is not dict or not set(requiert) <= CLES_REQUIERT:
        raise _invalide()
    conditions = tuple((cle, _chemins(requiert[cle])) for cle in sorted(requiert))
    produit = _produit(table['produit']) if 'produit' in table else None
    compatibles = _compatibles(table['compatible_yang']) if 'compatible_yang' in table else ()
    return _Manifeste(descripteur, tuple(journaliser), sortie_max, commandes, conditions,
                      produit, compatibles)


def _condition_remplie(cle, chemins):
    """`stat` seulement : ni exécution ni ouverture."""
    for chemin in chemins:
        try:
            attributs = os.stat(chemin)
        except (OSError, ValueError):
            return False
        if cle == 'binaires' and not (
                stat.S_ISREG(attributs.st_mode) and attributs.st_mode & 0o111):
            return False
    return True


# --- Chargeur ---------------------------------------------------------------------------

def _entrees(dossier_fd):
    """Regroupe les entrées d'un dossier en {nom: {'script', 'manifeste'}}."""
    entrees = os.listdir(dossier_fd)
    if len(entrees) > 2 * FONCTIONS_MAX:
        raise ErreurPlugin('plugin_too_many')
    groupes, inattendues = {}, []
    for entree in sorted(entrees):
        base = entree[:-5] if entree.endswith('.toml') else entree
        if not MOTIF_NOM.match(base):
            inattendues.append(entree)
            continue
        groupes.setdefault(base, set()).add('manifeste' if entree.endswith('.toml') else 'script')
    if len(groupes) > FONCTIONS_MAX:
        raise ErreurPlugin('plugin_too_many')
    return groupes, inattendues


def _verifier_type(entree, dossier_fd):
    attributs = os.stat(entree, dir_fd=dossier_fd, follow_symlinks=False)
    if stat.S_ISLNK(attributs.st_mode):
        raise ErreurPlugin('plugin_unsafe_permissions', entree)
    if not stat.S_ISREG(attributs.st_mode):
        raise ErreurPlugin('plugin_unexpected_entry', entree)


def _charger_fonction(nom, parties, dossier, dossier_fd, cote, domaine, codes_connus,
                      proprietaires, verifier_privileges):
    if parties != {'script', 'manifeste'}:
        raise ErreurPlugin('plugin_incomplete', nom)
    for entree in (nom, nom + '.toml'):
        _verifier_type(entree, dossier_fd)
    descripteur = ouvrir_fichier_controle(nom, dossier_fd, proprietaires, executable=True)
    os.close(descripteur)
    descripteur = ouvrir_fichier_controle(nom + '.toml', dossier_fd, proprietaires)
    try:
        octets = _lire_manifeste(descripteur)
    except ErreurPlugin as erreur:
        raise ErreurPlugin(erreur.code, nom) from None
    finally:
        os.close(descripteur)
    try:
        manifeste = _manifeste(_analyser(octets), nom, cote, domaine, codes_connus)
        if verifier_privileges is not None and manifeste.commandes:
            try:
                accepte = verifier_privileges(vers_sudo(manifeste.commandes))
            except Exception:
                accepte = False
            if accepte is not True:
                raise ErreurPlugin('plugin_privileges_rejected')
    except ErreurPlugin as erreur:
        raise ErreurPlugin(erreur.code, nom) from None
    return manifeste, os.path.join(dossier, nom)


def _nom_publie(nom):
    """Nom de base publié : filtré (I7) ; substitut neutre s'il change ou est vide."""
    if type(nom) is str and nom and filtrer(nom) == nom:
        return nom
    return 'invalid_name'


def charger(cote, domaine, dossier_livre, dossier_local, *, cible=cat.CIBLE_DEFAUT, codes_connus,
            proprietaires=frozenset({0}), racine_confiance='/', rappel=None,
            verifier_privileges=None):
    """Charge les fonctions des deux dossiers ; retourne un Chargement (aucune exécution).

    cote : 'yin' ou 'yang'. rappel(evenement, niveau, **champs) : journalisation du démon
    (`plugin_rejected` error, `plugin_skipped` warning, `plugin_loaded` debug), sans chemin
    ni valeur fautive. verifier_privileges(description) : rendu d'essai fourni par le démon ;
    seul le retour True accepte ; toute autre valeur ou exception refuse.
    """
    if (cote not in COTES or type(domaine) is not str or not cat.MOTIF_DOMAINE.match(domaine)
            or domaine in cat.DOMAINES_RESERVES or type(cible) is not str
            or not cat.MOTIF_CIBLE.match(cible)):
        raise ValueError('invalid_loader_config')
    proprietaires, codes_connus = frozenset(proprietaires), frozenset(codes_connus)
    noms, actions, varlink = set(), set(), {}
    descripteurs, fonctions, rejets = [], {}, []
    catalogue = Catalogue(cible, domaine, descripteurs)
    for scope, dossier in (('livre', dossier_livre), ('local', dossier_local)):
        local = scope == 'local'
        base = 'invalid_name'

        noms_dossier, actions_dossier = noms.copy(), actions.copy()
        varlink_dossier = varlink.copy()
        descripteurs_dossier, fonctions_dossier = [], {}
        rejets_dossier, evenements = [], []

        def journal_dossier(evenement, niveau, **champs):
            evenements.append((evenement, niveau, champs))

        def rejeter(erreur, fichier, _local=local):
            if not _local:
                raise erreur
            code, fichier = erreur.code, _nom_publie(fichier)
            rejets_dossier.append(Rejet(code, 'local', fichier))
            journal_dossier('plugin_rejected', 'error', code=code, scope='local', file=fichier)

        try:
            base = os.path.basename(os.path.abspath(os.fspath(dossier)))
            dossier_fd = ouvrir_dossier_confiance(dossier, racine_confiance, proprietaires)
            if dossier_fd is None:
                continue
            try:
                groupes, inattendues = _entrees(dossier_fd)
                for entree in inattendues:
                    rejeter(ErreurPlugin('plugin_unexpected_entry', entree), entree)
                for nom in sorted(groupes):
                    _charger_une(nom, groupes[nom], dossier, dossier_fd, scope, cote, domaine,
                                 cible, codes_connus, proprietaires, verifier_privileges,
                                 journal_dossier, rejeter, noms_dossier, actions_dossier,
                                 varlink_dossier, descripteurs_dossier, fonctions_dossier)
            finally:
                os.close(dossier_fd)
            fusion_descripteurs = descripteurs + descripteurs_dossier
            fusion_fonctions = fonctions | fonctions_dossier
            fusion_rejets = rejets + rejets_dossier
            _verifier_coherence(fusion_fonctions)
            catalogue_dossier = Catalogue(cible, domaine, fusion_descripteurs)
        except ErreurPlugin as erreur:
            if not local:
                raise ErreurPlugin(erreur.code, erreur.fichier or base) from None
            rejets.append(Rejet(erreur.code, 'local', _nom_publie(base)))
            _journal(rappel, 'plugin_rejected', 'error', code=erreur.code, scope='local',
                     file=_nom_publie(base))
        except Exception:
            # Frontière du dossier : aucun défaut inattendu ne publie un état partiel.
            erreur = ErreurPlugin('plugin_unreadable', base)
            if not local:
                raise erreur from None
            rejets.append(Rejet(erreur.code, 'local', _nom_publie(base)))
            _journal(rappel, 'plugin_rejected', 'error', code=erreur.code, scope='local',
                     file=_nom_publie(base))
        else:
            catalogue = catalogue_dossier
            noms, actions, varlink = noms_dossier, actions_dossier, varlink_dossier
            descripteurs, fonctions, rejets = fusion_descripteurs, fusion_fonctions, fusion_rejets
            for evenement, niveau, champs in evenements:
                _journal(rappel, evenement, niveau, **champs)
    greffons = {}
    for f in fonctions.values():
        greffons.setdefault(f.greffon, MappingProxyType(
            {'produit': f.produit, 'compatible_yang': f.compatible_yang}))
    return Chargement(catalogue, tuple(rejets), MappingProxyType(fonctions),
                      MappingProxyType(greffons))


def _verifier_coherence(fonctions):
    """Toutes les fonctions d'un greffon déclarent le même produit et les mêmes yang."""
    vus = {}
    for f in fonctions.values():
        marque = (f.produit, f.compatible_yang)
        if vus.setdefault(f.greffon, marque) != marque:
            raise ErreurPlugin('plugin_manifest_invalid', f.nom)


def _charger_une(nom, parties, dossier, dossier_fd, scope, cote, domaine, cible, codes_connus,
                 proprietaires, verifier_privileges, rappel, rejeter, noms, actions, varlink,
                 descripteurs, fonctions):
    try:
        manifeste, script = _charger_fonction(nom, parties, dossier, dossier_fd, cote, domaine,
                                              codes_connus, proprietaires, verifier_privileges)
        action = manifeste.descripteur.action
        derive = nom_varlink(action)
        if nom in noms or action in actions or derive in varlink:
            raise ErreurPlugin('plugin_duplicate', nom)
        # Préparer entièrement la fonction avant de modifier les collections du dossier.
        condition_absente = None
        for cle, chemins in manifeste.requiert:
            if not _condition_remplie(cle, chemins):
                condition_absente = cle
                break
        fonction = None
        if condition_absente is None:
            fonction = Fonction(nom, manifeste.descripteur.plugin, script, manifeste.descripteur,
                                manifeste.journaliser, manifeste.sortie_max, manifeste.commandes,
                                manifeste.produit, manifeste.compatible_yang)
    except Exception as erreur:
        # Frontière de la fonction : conserver les codes connus, typer tout défaut inattendu.
        if isinstance(erreur, ErreurPlugin):
            code = erreur.code
        elif isinstance(erreur, OSError):
            code = 'plugin_unreadable'
        else:
            code = 'plugin_manifest_invalid'
        rejeter(ErreurPlugin(code, nom), nom)
        return
    # Le nom et l'action d'une fonction écartée comptent pour les doublons.
    noms.add(nom)
    actions.add(action)
    varlink[derive] = action
    if condition_absente is not None:
        _journal(rappel, 'plugin_skipped', 'warning', code='plugin_requirement_unmet',
                 scope=scope, file=_nom_publie(nom), requirement=condition_absente)
        return
    descripteurs.append(manifeste.descripteur)
    fonctions[action] = fonction
    _journal(rappel, 'plugin_loaded', 'debug', file=_nom_publie(nom), scope=scope)
