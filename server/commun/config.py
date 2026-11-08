# SPDX-License-Identifier: AGPL-3.0-or-later
# Configuration INI typée, en couches (D29) ; dépendances : bibliothèque standard.
# Suivi des versions
#   0.1.8  2026-11-07  Lecture partielle (sections et options inconnues ignorées) et uid facultatif.
#   0.1.1  2026-11-07  Extensions du socle commun.
#   3.0.0-alpha  2026-11-05  Configuration en couches : paresia.conf, conf.d, couche utilisateur, variables PARESIA_*.
#   3.0.0-alpha  2026-11-05  Durcissement et corrections du cycle de revue 1.
#   3.0.0-alpha  2026-11-05  Priorités et validation sans valeurs propres au site.
import argparse
import configparser
from dataclasses import dataclass
import os
import re
import stat

from .jumeaux import PLAFOND_LIMITE, verifier_delai


class ErreurConfiguration(ValueError):
    """Code stable et emplacement uniquement ; jamais la valeur fautive.

    fichier = nom de base du fichier fautif (facultatif, jamais un chemin complet).
    """
    def __init__(self, code, section=None, cle=None, fichier=None):
        self.code, self.section, self.cle, self.fichier = code, section, cle, fichier
        super().__init__(':'.join(part for part in (code, section, cle) if part))


@dataclass(frozen=True)
class Option:
    """Schéma fourni par chaque démon : chemin, compte, uid, duree, limite, texte.

    duree, limite, niveau et booleen peuvent avoir un défaut. Les options
    chemin, texte, compte et uid acceptent facultatif=True (absence représentée par None).
    Les chemins doivent être absolus, les durées strictement
    positives (au plus 3600 s), les limites entières de 1 à 16 Mio et les uid
    entiers positifs ou nuls.
    """
    type: str
    defaut: object = None
    facultatif: bool = False

    def __post_init__(self):
        if self.type not in {'chemin', 'compte', 'uid', 'duree', 'limite', 'texte', 'niveau', 'booleen'}:
            raise ValueError('invalid_config_type')
        if self.defaut is not None and self.type not in {'duree', 'limite', 'niveau', 'booleen'}:
            raise ValueError('config_default_forbidden')
        if self.facultatif and (self.type not in {'chemin', 'texte', 'compte', 'uid'} or self.defaut is not None):
            raise ValueError('invalid_config_optional')


def _convertir(valeur, type_option):
    if not valeur or len(valeur) > 4096 or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in valeur):
        raise ValueError()
    if type_option == 'niveau' and valeur not in ('debug', 'info', 'notice', 'warning', 'error', 'critical'):
        raise ValueError()
    if type_option == 'booleen':
        if valeur not in ('true', 'false'):
            raise ValueError()
        return valeur == 'true'
    if type_option == 'chemin' and not os.path.isabs(valeur):
        raise ValueError()
    if type_option == 'compte' and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*\$?', valeur):
        raise ValueError()
    if type_option in ('uid', 'limite'):
        if not re.fullmatch('[0-9]+', valeur):
            raise ValueError()
        nombre = int(valeur)
        if nombre < (0 if type_option == 'uid' else 1) or (type_option == 'uid' and nombre >= 2**32 - 1):
            raise ValueError()
        if type_option == 'limite' and nombre > PLAFOND_LIMITE:
            raise ValueError()
        return nombre
    if type_option == 'duree':
        nombre = float(valeur)
        verifier_delai(nombre)
        return nombre
    return valeur


RACINE_SYSTEME = '/etc/paresia'
TAILLE_MAX = 1024 * 1024
FICHIERS_MAX = 64
_NOM_CONFD = re.compile(r'[0-9]{2}-[A-Za-z0-9._-]+\.conf')
_NOM_UTILISATEUR = re.compile(r'[A-Za-z0-9._-]+\.conf')
_IDENTIFIANT = re.compile('[a-z][a-z0-9_]*')


def _ouvrir(nom, drapeaux, dir_fd=None):
    """Ouvre sans suivre de lien ; None si absent ; config_unreadable pour toute autre erreur."""
    try:
        return os.open(nom, drapeaux | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dir_fd)
    except FileNotFoundError:
        return None
    except OSError:
        raise ErreurConfiguration('config_unreadable') from None


def _controler(descripteur, dossier):
    """Contrôle sur le descripteur ouvert : type, propriétaire, droits."""
    attributs = os.fstat(descripteur)
    genre = stat.S_ISDIR if dossier else stat.S_ISREG
    if (not genre(attributs.st_mode) or attributs.st_uid not in {0, os.geteuid()}
            or attributs.st_mode & 0o022):
        raise ErreurConfiguration('config_unsafe_permissions')


def _ouvrir_dossier(chemin, dir_fd=None):
    descripteur = _ouvrir(chemin, os.O_RDONLY | os.O_DIRECTORY, dir_fd)
    if descripteur is not None:
        try:
            _controler(descripteur, True)
        except BaseException:
            os.close(descripteur)
            raise
    return descripteur


def _lire_fichier(nom, dir_fd=None, obligatoire=False):
    """Retourne (ConfigParser, nom de base), ou None si le fichier est absent (couches seulement)."""
    base = os.path.basename(nom)
    try:
        descripteur = _ouvrir(nom, os.O_RDONLY | os.O_NONBLOCK, dir_fd)
        if descripteur is None:
            if obligatoire:
                raise ErreurConfiguration('config_unreadable')
            return None
        try:
            _controler(descripteur, False)
            with os.fdopen(descripteur, 'rb') as entree:
                descripteur = None
                contenu = entree.read(TAILLE_MAX + 1)
        finally:
            if descripteur is not None:
                os.close(descripteur)
        if len(contenu) > TAILLE_MAX:
            raise ErreurConfiguration('config_too_large')
        fichier = configparser.ConfigParser(interpolation=None, strict=True)
        try:
            fichier.read_string(contenu.decode('utf-8'))
        except (UnicodeError, configparser.Error, ValueError):
            raise ErreurConfiguration('config_unreadable') from None
        if fichier.defaults():
            raise ErreurConfiguration('config_defaults_forbidden')
        return fichier, base
    except ErreurConfiguration as erreur:
        erreur.fichier = base
        raise
    except OSError:
        raise ErreurConfiguration('config_unreadable', fichier=base) from None


def _fichiers_dossier(chemin, motif, dir_fd=None):
    """Fichiers (ConfigParser) d'un dossier de couche, dans l'ordre lexical des noms."""
    dossier = _ouvrir_dossier(chemin, dir_fd)
    if dossier is None:
        return []
    try:
        try:
            noms = sorted(nom for nom in os.listdir(dossier) if motif.fullmatch(nom))
        except OSError:
            raise ErreurConfiguration('config_unreadable', fichier=os.path.basename(chemin)) from None
        if len(noms) > FICHIERS_MAX:
            raise ErreurConfiguration('config_too_large', fichier=os.path.basename(chemin))
        return [f for f in (_lire_fichier(nom, dossier) for nom in noms) if f is not None]
    finally:
        os.close(dossier)


def _dossier_utilisateur(env, repertoire):
    """<répertoire>/paresia ; XDG_CONFIG_HOME absolu, sinon $HOME/.config ; None sans base."""
    base = repertoire
    if base is None:
        xdg, home = env.get('XDG_CONFIG_HOME'), env.get('HOME')
        if xdg and os.path.isabs(xdg):
            base = xdg
        elif home and os.path.isabs(home):
            base = os.path.join(home, '.config')
    return None if base is None else os.path.join(os.fspath(base), 'paresia')


def _couches_fichier(racine, utilisateur, env, repertoire):
    fichiers = []
    dossier_racine = _ouvrir_dossier(racine)
    if dossier_racine is not None:
        try:
            fichier = _lire_fichier('paresia.conf', dossier_racine)
            if fichier is not None:
                fichiers.append(fichier)
            fichiers += _fichiers_dossier('conf.d', _NOM_CONFD, dossier_racine)
        finally:
            os.close(dossier_racine)
    if utilisateur:
        chemin = _dossier_utilisateur(env, repertoire)
        if chemin is not None:
            fichiers += _fichiers_dossier(chemin, _NOM_UTILISATEUR)
    return fichiers


def _convertir_option(valeur, option, domaine, cle):
    try:
        return _convertir(valeur, option.type)
    except (ValueError, TypeError):
        raise ErreurConfiguration('config_invalid', domaine, cle) from None


def _valeurs_fichier(fichier, demon, schema, domaines, partielle=False):
    """{(domaine, cle): valeur typée} des sections du composant ; les autres sont ignorées.

    En lecture partielle, une section ou une option absente du schéma est ignorée.
    """
    valeurs = {}
    for section in fichier.sections():
        if section == demon:
            domaine = 'general'
        elif section.startswith(demon + '.'):
            domaine = section[len(demon) + 1:]
        else:
            continue
        if domaine not in domaines:
            if partielle:
                continue
            raise ErreurConfiguration('config_unknown_section',
                                      domaine if _IDENTIFIANT.fullmatch(domaine) else None)
        for cle, valeur in fichier[section].items():
            if (domaine, cle) not in schema:
                if partielle:
                    continue
                raise ErreurConfiguration('config_unknown_option', domaine,
                                          cle if _IDENTIFIANT.fullmatch(cle) else None)
            valeurs[(domaine, cle)] = _convertir_option(valeur, schema[(domaine, cle)], domaine, cle)
    return valeurs


def lire(demon, schema, *, argv=None, environ=None, utilisateur=False, environnement=True,
         racine_systeme=None, repertoire_utilisateur=None, journal=False, metriques=False,
         partielle=False):
    """Configuration en couches (D29) ; retourne {domaine: {cle: valeur typée}}.

    schema = {('transport', 'socket'): Option('chemin'), ...} ; le domaine
    'general' désigne la section nue [<demon>], les autres [<demon>.<domaine>].
    Couches par priorité croissante : <racine>/paresia.conf, <racine>/conf.d/NN-*.conf
    (ordre lexical), si utilisateur=True <XDG_CONFIG_HOME ou ~/.config>/paresia/*.conf,
    puis, si environnement=True, PARESIA_<DEMON>_<DOMAINE>_<CLE> (majuscules, tirets en
    '_'). Aucune couche n'est obligatoire. --config ou PARESIA_<DEMON>_CONFIG désigne un
    fichier unique qui remplace les couches fichier (--config prime). Les sections des
    autres composants sont ignorées. Chaque valeur rencontrée est contrôlée, même si une
    couche supérieure la masque. Aucun chemin, compte ni uid implicite, aucune lecture de
    secret. Chaque fichier et dossier lu : sans lien symbolique final, régulier ou
    dossier, propriétaire root ou uid effectif, sans écriture groupe/autres, au plus
    1 Mio et 64 fichiers par dossier.
    argv ne contient que --config (les autres arguments sont refusés). environ remplace
    os.environ ; HOME et XDG_CONFIG_HOME (couche utilisateur) en sont lus même si
    environnement=False, qui n'écarte que les variables PARESIA_*.
    partielle=True : les sections et options du composant absentes du schéma sont ignorées
    (sans config_unknown_section ni config_unknown_option) ; celles du schéma sont validées
    comme d'habitude. Par défaut, lecture stricte.
    """
    schema = dict(schema)
    if journal:
        schema[('journal', 'niveau')] = Option('niveau', 'info')
    if metriques:
        schema.update({('metriques', 'actif'): Option('booleen', False),
                       ('metriques', 'dossier'): Option('chemin', facultatif=True),
                       ('metriques', 'periode_s'): Option('duree', 15)})
    if not re.fullmatch('[a-z][a-z0-9_-]*', demon):
        raise ErreurConfiguration('config_invalid_daemon')
    brut = os.environ if environ is None else environ
    env = brut if environnement else {}
    prefixe = 'PARESIA_' + demon.upper().replace('-', '_')
    parseur = argparse.ArgumentParser(add_help=False, exit_on_error=False)
    parseur.add_argument('--config')
    try:
        args, autres = parseur.parse_known_args(argv)
    except argparse.ArgumentError:
        raise ErreurConfiguration('config_invalid_arguments') from None
    if autres:
        raise ErreurConfiguration('config_invalid_arguments')
    for domaine, cle in schema:
        if not all(_IDENTIFIANT.fullmatch(nom) for nom in (domaine, cle)):
            raise ErreurConfiguration('config_invalid_schema')
    domaines = {domaine for domaine, _ in schema}
    if args.config is not None and not args.config:
        raise ErreurConfiguration('config_path_missing')
    explicite = args.config if args.config is not None else env.get(prefixe + '_CONFIG')
    if explicite:
        fichiers = [_lire_fichier(explicite, obligatoire=True)]
    else:
        racine = RACINE_SYSTEME if racine_systeme is None else os.fspath(racine_systeme)
        fichiers = _couches_fichier(racine, utilisateur, brut, repertoire_utilisateur)
    valeurs = {}
    for fichier, base in fichiers:
        try:
            valeurs.update(_valeurs_fichier(fichier, demon, schema, domaines, partielle))
        except ErreurConfiguration as erreur:
            erreur.fichier = base
            raise
    resultat = {}
    for (domaine, cle), option in schema.items():
        valeur = valeurs.get((domaine, cle))
        brute = env.get(f'{prefixe}_{domaine.upper()}_{cle.upper()}')
        if brute is not None:
            valeur = _convertir_option(brute, option, domaine, cle)
        if valeur is None:
            if option.defaut is None and not option.facultatif:
                raise ErreurConfiguration('config_missing', domaine, cle)
            if option.defaut is not None:
                brut_defaut = str(option.defaut).lower() if option.type == 'booleen' else str(option.defaut)
                valeur = _convertir_option(brut_defaut, option, domaine, cle)
        resultat.setdefault(domaine, {})[cle] = valeur
    return resultat
