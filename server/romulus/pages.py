# SPDX-License-Identifier: AGPL-3.0-or-later
# Pages des greffons yang : contrôle des fichiers, génération et vérification de l'index (D148, D150).
# Dépendances : bibliothèque standard, commun (services, plugins, texte, version).
# Suivi des versions
#   0.1.9  2026-11-08  Création : index des pages des greffons livrés, ligne de commande --ecrire/--verifier.
"""Index `index.json` des pages des greffons yang livrés.

Fonction pure `construire_index(declarations, dossier)` : lit les fichiers de chaque greffon qui
déclare des pages (script, catalogues de texte) sous `<dossier>/<nom>/`, les contrôle comme des
programmes (propriétaire, droits, aucun lien symbolique, taille bornée) et retourne les octets de
l'index. Un greffon défectueux est refusé en entier : aucune sortie partielle. Les déclarations
locales ne contribuent jamais à l'index. Aucune sortie ne contient un chemin ni un contenu de fichier.
"""
import json
import os
import re
import stat
import sys

from server.commun import services
from server.commun.plugins import ErreurPlugin, ouvrir_dossier_confiance, ouvrir_fichier_controle
from server.commun.texte import filtrer
from server.commun.version import lire_version

DOSSIER_WEB = '/usr/local/share/paresia/web'
DOSSIER_GREFFONS = DOSSIER_WEB + '/greffons'
NOM_INDEX = 'index.json'
FORMAT_INDEX = 1
INDEX_MAX = 65536
FICHIER_MAX = 1048576
LANGUES = (('fr-FR', True), ('en-US', False))
MODE_INDEX = 0o644

EX_OK, EX_USAGE, EX_DATAERR, EX_IOERR, EX_CONFIG = 0, 64, 65, 74, 78
SORTIES = {'pages_invalid': EX_DATAERR, 'pages_catalog_invalid': EX_DATAERR,
           'pages_too_large': EX_DATAERR, 'pages_unsafe_permissions': EX_CONFIG}


class ErreurPages(Exception):
    """Défaut des pages d'un greffon ; `code` stable, `greffon` nom filtré (jamais un chemin)."""

    def __init__(self, code, greffon=None):
        super().__init__(code)
        self.code = code
        self.greffon = None if greffon is None else _nom_publie(greffon)


def _nom_publie(nom):
    if type(nom) is str and nom and filtrer(nom) == nom:
        return nom
    return 'invalid_name'


def nom_court(greffon):
    return greffon[len(services.PREFIXE_GREFFON):]


def _lire(descripteur):
    """Contenu d'un descripteur, FICHIER_MAX octets au plus ; ErreurPages('pages_too_large') sinon."""
    morceaux, taille = [], 0
    while True:
        bloc = os.read(descripteur, 65536)
        if not bloc:
            return b''.join(morceaux)
        taille += len(bloc)
        if taille > FICHIER_MAX:
            raise ErreurPages('pages_too_large')
        morceaux.append(bloc)


def _fichier(nom, dossier_fd, proprietaires, facultatif=False):
    """Octets du fichier `nom` ; None si facultatif et absent."""
    try:
        descripteur = ouvrir_fichier_controle(nom, dossier_fd, proprietaires)
    except ErreurPlugin as erreur:
        if erreur.code == 'plugin_incomplete':
            if facultatif:
                return None
            raise ErreurPages('pages_invalid') from None
        if erreur.code == 'plugin_unsafe_permissions':
            raise ErreurPages('pages_unsafe_permissions') from None
        raise ErreurPages('pages_invalid') from None
    try:
        return _lire(descripteur)
    except OSError:
        raise ErreurPages('pages_invalid') from None
    finally:
        os.close(descripteur)


def _sous_dossier(nom, dossier_fd, proprietaires):
    """Descripteur du sous-dossier `nom` (propriétaire, droits, aucun lien) ; None s'il est absent."""
    try:
        descripteur = os.open(nom, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                              dir_fd=dossier_fd)
    except FileNotFoundError:
        return None
    except OSError:
        raise ErreurPages('pages_unsafe_permissions') from None
    attributs = os.fstat(descripteur)
    if (not stat.S_ISDIR(attributs.st_mode) or attributs.st_uid not in proprietaires
            or attributs.st_mode & 0o022):
        os.close(descripteur)
        raise ErreurPages('pages_unsafe_permissions')
    return descripteur


def _catalogue(octets, prefixe):
    try:
        objet = json.loads(octets.decode('utf-8'))
    except (UnicodeError, ValueError, RecursionError):
        raise ErreurPages('pages_catalog_invalid') from None
    if (type(objet) is not dict
            or any(type(c) is not str or type(v) is not str or not c.startswith(prefixe)
                   for c, v in objet.items())):
        raise ErreurPages('pages_catalog_invalid')


def _controler_greffon(service, racine_greffons, proprietaires, racine_confiance):
    nom = nom_court(service.greffon)
    prefixe = 'ui_' + nom.replace('-', '_') + '_'
    ouverts = []
    try:
        try:
            dossier_fd = ouvrir_dossier_confiance(os.path.join(racine_greffons, nom),
                                                  racine_confiance, proprietaires)
        except ErreurPlugin:
            raise ErreurPages('pages_unsafe_permissions') from None
        if dossier_fd is None:
            raise ErreurPages('pages_invalid')
        ouverts.append(dossier_fd)
        for page in service.pages:
            _fichier(page.script, dossier_fd, proprietaires)
        i18n_fd = _sous_dossier('i18n', dossier_fd, proprietaires)
        if i18n_fd is None:
            raise ErreurPages('pages_invalid')
        ouverts.append(i18n_fd)
        for langue, obligatoire in LANGUES:
            octets = _fichier(langue + '.json', i18n_fd, proprietaires, facultatif=not obligatoire)
            if octets is not None:
                _catalogue(octets, prefixe)
    except ErreurPages as erreur:
        raise ErreurPages(erreur.code, nom) from None
    except OSError:
        raise ErreurPages('pages_invalid', nom) from None
    finally:
        for descripteur in ouverts:
            os.close(descripteur)
    return {'nom': nom,
            'pages': [{'id': p.id, 'titre_cle': p.titre_cle, 'script': p.script}
                      for p in sorted(service.pages, key=lambda p: p.id)]}


def construire_index(declarations, dossier, *, proprietaires=frozenset({0}), racine_confiance='/'):
    """Octets de l'index des greffons de `declarations` (services chargés) ; ErreurPages sinon."""
    proprietaires = frozenset(proprietaires)
    greffons = [_controler_greffon(s, dossier, proprietaires, racine_confiance)
                for s in declarations.services if s.pages]
    greffons.sort(key=lambda g: g['nom'])
    octets = (json.dumps({'format': FORMAT_INDEX, 'greffons': greffons}, ensure_ascii=True,
                         separators=(',', ':')) + '\n').encode('ascii')
    if len(octets) > INDEX_MAX:
        raise ErreurPages('pages_too_large')
    return octets


def charger_livrees(dossier_livre, *, proprietaires=frozenset({0}), racine_confiance='/'):
    """Déclarations livrées seules ; les déclarations locales ne sont jamais lues."""
    absent = os.path.join(os.path.abspath(dossier_livre), 'absent')
    try:
        return services.charger(dossier_livre, absent, proprietaires=proprietaires,
                                racine_confiance=racine_confiance)
    except services.ErreurService as erreur:
        raise ErreurPages('pages_invalid', erreur.fichier) from None


def _index_present(dossier, proprietaires, racine_confiance):
    try:
        dossier_fd = ouvrir_dossier_confiance(dossier, racine_confiance, proprietaires)
    except ErreurPlugin:
        raise ErreurPages('pages_unsafe_permissions') from None
    if dossier_fd is None:
        raise ErreurPages('pages_invalid')
    try:
        try:
            descripteur = ouvrir_fichier_controle(NOM_INDEX, dossier_fd, proprietaires)
        except ErreurPlugin as erreur:
            raise ErreurPages('pages_unsafe_permissions' if erreur.code
                              == 'plugin_unsafe_permissions' else 'pages_invalid') from None
        try:
            if stat.S_IMODE(os.fstat(descripteur).st_mode) != MODE_INDEX:
                raise ErreurPages('pages_unsafe_permissions')
            octets = os.read(descripteur, INDEX_MAX + 1)
        finally:
            os.close(descripteur)
    finally:
        os.close(dossier_fd)
    if len(octets) > INDEX_MAX:
        raise ErreurPages('pages_too_large')
    return octets


def verifier(declarations, dossier, *, proprietaires=frozenset({0}), racine_confiance='/'):
    """L'index présent est celui que les fichiers actuels produiraient ; ErreurPages sinon."""
    attendu = construire_index(declarations, dossier, proprietaires=proprietaires,
                               racine_confiance=racine_confiance)
    if _index_present(dossier, frozenset(proprietaires), racine_confiance) != attendu:
        raise ErreurPages('pages_invalid')


def ecrire(declarations, dossier, *, proprietaires=frozenset({0}), racine_confiance='/'):
    """Construit puis écrit l'index de façon atomique (0644, propriétaire root si possible)."""
    octets = construire_index(declarations, dossier, proprietaires=proprietaires,
                              racine_confiance=racine_confiance)
    try:
        dossier_fd = ouvrir_dossier_confiance(dossier, racine_confiance, frozenset(proprietaires))
    except ErreurPlugin:
        raise ErreurPages('pages_unsafe_permissions') from None
    if dossier_fd is None:
        raise ErreurPages('pages_invalid')
    temporaire = f'.{NOM_INDEX}.{os.getpid()}.tmp'
    try:
        descripteur = os.open(temporaire, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                              | os.O_CLOEXEC, 0o600, dir_fd=dossier_fd)
        try:
            os.write(descripteur, octets)
            os.fchmod(descripteur, MODE_INDEX)
            if os.geteuid() == 0:
                os.fchown(descripteur, 0, 0)
            os.fsync(descripteur)
        finally:
            os.close(descripteur)
        os.rename(temporaire, NOM_INDEX, src_dir_fd=dossier_fd, dst_dir_fd=dossier_fd)
        os.fsync(dossier_fd)
    except OSError:
        try:
            os.unlink(temporaire, dir_fd=dossier_fd)
        except OSError:
            pass
        raise ErreurPages('pages_invalid') from None
    finally:
        os.close(dossier_fd)


# --- Ligne de commande ------------------------------------------------------------------------

def _langue(environ):
    for nom in ('LC_ALL', 'LC_MESSAGES', 'LANG'):
        valeur = environ.get(nom)
        if valeur:
            return 'en-US' if valeur.lower().startswith('en') else 'fr-FR'
    return 'fr-FR'


def _catalogue_texte(environ):
    dossier = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'i18n')
    for choix in dict.fromkeys((_langue(environ), 'fr-FR')):
        try:
            with open(os.path.join(dossier, choix + '.json'), encoding='utf-8') as flux:
                textes = json.load(flux)
        except (OSError, ValueError):
            continue
        if isinstance(textes, dict):
            return textes
    return {}


def main(argv=None, *, environ=None, erreur=None, sortie=None, proprietaires=frozenset({0}),
         racine_confiance='/', dossier_livre=services.DOSSIER_LIVRE):
    """Retourne un code sysexits. Rien en succès ; `<N>code greffon` sur l'erreur standard."""
    environ = os.environ if environ is None else environ
    erreur = sys.stderr if erreur is None else erreur
    sortie = sys.stdout if sortie is None else sortie
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments in (['--help'], ['--version']):
        textes = _catalogue_texte(environ)
        cle = 'pages_help' if arguments == ['--help'] else 'commun_version'
        modele = textes.get(cle, cle)
        print(filtrer(modele.format(daemon='romulus.pages', version=lire_version())), file=sortie)
        return EX_OK
    if len(arguments) != 2 or arguments[0] not in ('--ecrire', '--verifier') or not arguments[1]:
        print('<4>pages_usage', file=erreur)
        return EX_USAGE
    action, dossier = arguments
    try:
        declarations = charger_livrees(dossier_livre, proprietaires=proprietaires,
                                       racine_confiance=racine_confiance)
        operation = ecrire if action == '--ecrire' else verifier
        operation(declarations, dossier, proprietaires=proprietaires,
                  racine_confiance=racine_confiance)
    except ErreurPages as defaut:
        suite = f' {defaut.greffon}' if defaut.greffon else ''
        print(f'<3>{defaut.code}{suite}', file=erreur)
        return SORTIES.get(defaut.code, EX_DATAERR)
    except OSError:
        print('<3>pages_invalid', file=erreur)
        return EX_IOERR
    return EX_OK


if __name__ == '__main__':
    raise SystemExit(main())
