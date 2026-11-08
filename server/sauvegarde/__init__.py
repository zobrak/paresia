# SPDX-License-Identifier: AGPL-3.0-or-later
# Sauvegardes de procédure : copies, relevés, rotation et restauration (C36, D83, D103) ;
# dépendances : bibliothèque standard et server.commun.
# Suivi des versions
#   3.0.0-alpha  2026-11-06  Création : jeux datés sous <dossier>/<machine>/, rotation bornée, restauration (C36, D83, D103).
#   3.0.0-alpha  2026-11-06  Chemins commençant par // refusés.
#   3.0.0-alpha.41  2026-11-06  Empreintes SHA-256 au manifeste (version 2) et vérification avant toute restauration (D113).
#   3.0.0-alpha.41  2026-11-06  Manifeste en version 3 (dossiers et liens d'un arbre), empreinte exigée à la restauration, détection de clé privée sur le fichier entier (D113).
#   3.0.0-alpha.41  2026-11-06  T066 cycle 2 : copie supprimée si le manifeste ne s'écrit pas ; clé détectée pendant la copie journalisée (backup_refused).
import datetime
import hashlib
import hmac
import json
import os
import re
import shutil
import stat
import tempfile

from server.commun.config import Option

SCHEMA = {
    ('stockage', 'actif'): Option('texte'),
    ('stockage', 'taille_max_mio'): Option('limite', 64),
    ('stockage', 'dossier'): Option('chemin'),
    ('stockage', 'machine'): Option('texte'),
}

SORTIE_OK, SORTIE_ECHEC, SORTIE_USAGE, SORTIE_LIMITE, SORTIE_CLE, SORTIE_INTROUVABLE = 0, 1, 2, 3, 4, 5

_NOM_JEU = re.compile(r'[0-9]{8}-[0-9]{6}')
_NOM_RELEVE = re.compile(r'[A-Za-z0-9._-]{1,64}')
_MACHINE = re.compile(r'[a-z][a-z0-9-]{0,31}')
_CLE_PRIVEE = re.compile(rb'-----BEGIN [A-Z0-9 ]{0,64}PRIVATE KEY-----')    # au plus 91 octets
_BLOC = 65536
_RECOUVREMENT = 128    # supérieur à la longueur maximale d'un en-tête reconnu
_MIO = 1024 * 1024
_MANIFESTE_MAX = 16 * _MIO
VERSION_MANIFESTE = 3
_EMPREINTE = re.compile(r'[0-9a-f]{64}')
MANIFESTE = 'manifeste.json'
DOSSIER_FICHIERS = 'fichiers'
DOSSIER_RELEVES = 'releves'


class ErreurSauvegarde(Exception):
    """Clé de message du catalogue, code de sortie et valeurs à insérer (jamais de secret)."""

    def __init__(self, message, sortie=SORTIE_ECHEC, **valeurs):
        self.message, self.sortie, self.valeurs = message, sortie, valeurs
        super().__init__(message)


def verifier_configuration(configuration):
    """Contrôle les valeurs lues ; retourne la section stockage."""
    stockage = configuration['stockage']
    if stockage['actif'] not in ('oui', 'non'):
        raise ErreurSauvegarde('backup_config_invalid', SORTIE_ECHEC, code='actif')
    if not _MACHINE.fullmatch(stockage['machine']):
        raise ErreurSauvegarde('backup_config_invalid', SORTIE_ECHEC, code='machine')
    dossier = stockage['dossier']
    if not os.path.isabs(dossier) or dossier.startswith('//') or os.path.normpath(dossier) != dossier:
        raise ErreurSauvegarde('backup_config_invalid', SORTIE_ECHEC, code='dossier')
    return stockage


def valider_chemin(chemin):
    """Chemin absolu, normalisé, sans caractère de contrôle ni octet nul ; sinon usage."""
    if (not isinstance(chemin, str) or not chemin or len(chemin) > 4096 or not os.path.isabs(chemin)
            or chemin.startswith('//') or os.path.normpath(chemin) != chemin or chemin == '/'
            or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in chemin)):
        raise ErreurSauvegarde('backup_path_invalid', SORTIE_USAGE)
    return chemin


def valider_nom_jeu(nom):
    if not isinstance(nom, str) or not _NOM_JEU.fullmatch(nom):
        raise ErreurSauvegarde('backup_set_invalid', SORTIE_USAGE)
    return nom


def valider_nom_releve(nom):
    if not isinstance(nom, str) or not _NOM_RELEVE.fullmatch(nom):
        raise ErreurSauvegarde('backup_name_invalid', SORTIE_USAGE)
    return nom


def verifier_composants(chemin):
    """Refuse un chemin dont un composant existant est un lien symbolique."""
    courant = '/'
    for partie in chemin.split('/'):
        if not partie:
            continue
        courant = os.path.join(courant, partie)
        try:
            attributs = os.lstat(courant)
        except FileNotFoundError:
            return
        except OSError:
            raise ErreurSauvegarde('backup_failed', SORTIE_ECHEC, code='lstat') from None
        if stat.S_ISLNK(attributs.st_mode):
            raise ErreurSauvegarde('backup_symlink_refused', SORTIE_ECHEC)


def _chown_si_permis(chemin, attributs):
    try:
        os.chown(chemin, attributs.st_uid, attributs.st_gid, follow_symlinks=False)
    except OSError:
        pass    # propriétaire inchangé quand le droit manque (exécution hors root)


def _integrite_refusee(chemin):
    return ErreurSauvegarde('backup_integrity_failed', SORTIE_ECHEC, chemin=chemin)


def _empreinte_valide(valeur):
    return isinstance(valeur, str) and _EMPREINTE.fullmatch(valeur) is not None


def _empreinte_fichier(chemin):
    """SHA-256 (hexadécimal) du contenu d'un fichier régulier, sans suivre de lien ; None si illisible."""
    try:
        descripteur = os.open(chemin, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(descripteur).st_mode):
            return None
        condensat = hashlib.sha256()
        with os.fdopen(os.dup(descripteur), 'rb') as entree:
            for bloc in iter(lambda: entree.read(65536), b''):
                condensat.update(bloc)
        return condensat.hexdigest()
    except OSError:
        return None
    finally:
        os.close(descripteur)


def _balayer_cle(queue, bloc):
    """(clé trouvée, nouvelle queue) : recherche de l'en-tête dans queue + bloc, avec recouvrement entre blocs."""
    donnees = queue + bloc
    return _CLE_PRIVEE.search(donnees) is not None, donnees[-_RECOUVREMENT:]


def _copier_fichier(source, destination, descripteur=None, attendu=None, *, verifier=False):
    """Copie atomique (fichier temporaire du même dossier puis rename) ; modes, dates, propriétaire conservés.

    Retourne l'empreinte SHA-256 du contenu copié. Sauvegarde (verifier faux) : le contenu copié est refusé s'il
    contient un en-tête de clé privée (code 4). Restauration (verifier vrai) : une empreinte attendue valide et
    égale à celle de la copie est obligatoire, sinon rien n'est écrit en place (D113).
    """
    ferme = descripteur is None
    if descripteur is None:
        descripteur = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        attributs = os.fstat(descripteur)
        if not stat.S_ISREG(attributs.st_mode):
            raise ErreurSauvegarde('backup_unsupported_type', SORTIE_ECHEC)
        if verifier and not _empreinte_valide(attendu):
            raise _integrite_refusee(destination)
        sortie, temporaire = tempfile.mkstemp(dir=os.path.dirname(destination), prefix='.paresia-')
        try:
            condensat = hashlib.sha256()
            queue = b''
            with os.fdopen(sortie, 'wb') as fichier, os.fdopen(os.dup(descripteur), 'rb') as entree:
                entree.seek(0)
                for bloc in iter(lambda: entree.read(_BLOC), b''):
                    if not verifier:
                        trouvee, queue = _balayer_cle(queue, bloc)
                        if trouvee:
                            raise ErreurSauvegarde('backup_key_refused', SORTIE_CLE)
                    condensat.update(bloc)
                    fichier.write(bloc)
            empreinte = condensat.hexdigest()
            if verifier and not hmac.compare_digest(attendu, empreinte):
                raise _integrite_refusee(destination)
            _chown_si_permis(temporaire, attributs)
            os.chmod(temporaire, stat.S_IMODE(attributs.st_mode))
            os.utime(temporaire, ns=(attributs.st_atime_ns, attributs.st_mtime_ns))
            os.replace(temporaire, destination)
            return empreinte
        except BaseException:
            try:
                os.unlink(temporaire)
            except OSError:
                pass
            raise
    finally:
        if ferme:
            os.close(descripteur)


def _entrees_arbre(racine):
    """[(chemin relatif, genre)] d'un arbre sans suivre les liens ; genre d, f ou l ; autre type refusé."""
    resultat = []

    def parcourir(relatif):
        dossier = os.path.join(racine, relatif) if relatif else racine
        with os.scandir(dossier) as entrees:
            for entree in sorted(entrees, key=lambda e: e.name):
                chemin = os.path.join(relatif, entree.name)
                attributs = entree.stat(follow_symlinks=False)
                if stat.S_ISLNK(attributs.st_mode):
                    resultat.append((chemin, 'l'))
                elif stat.S_ISDIR(attributs.st_mode):
                    resultat.append((chemin, 'd'))
                    parcourir(chemin)
                elif stat.S_ISREG(attributs.st_mode):
                    resultat.append((chemin, 'f'))
                else:
                    raise ErreurSauvegarde('backup_unsupported_type', SORTIE_ECHEC)

    parcourir('')
    return resultat


def _structure_conforme(copie, entree):
    """Entrées de la copie d'un arbre, après égalité exacte avec le manifeste (fichiers, dossiers, liens) ; sinon refus."""
    attendues, dossiers, liens = entree.get('empreintes'), entree.get('dossiers'), entree.get('liens')
    if (not isinstance(attendues, dict) or not isinstance(dossiers, list) or not isinstance(liens, dict)
            or not all(isinstance(d, str) for d in dossiers)
            or not all(isinstance(k, str) and isinstance(v, str) for k, v in liens.items())):
        raise _integrite_refusee(copie)
    try:
        entrees = _entrees_arbre(copie)
        presents_liens = {r: os.readlink(os.path.join(copie, r)) for r, g in entrees if g == 'l'}
    except OSError:
        raise _integrite_refusee(copie) from None
    if ({r for r, g in entrees if g == 'f'} != set(attendues)
            or sorted(r for r, g in entrees if g == 'd') != sorted(dossiers)
            or presents_liens != liens):
        raise _integrite_refusee(copie)
    return entrees


def _copier_arbre(source, destination, *, restauration=None):
    """Copie récursive sans suivre les liens ; destination ne doit pas exister.

    Sauvegarde (restauration absent) : retourne (empreintes, dossiers, liens) de l'arbre copié, les fichiers étant
    refusés s'ils contiennent une clé privée. Restauration (restauration = entrée du manifeste) : tout fichier,
    dossier ou lien absent du manifeste ou différent de lui est refusé (D113).
    """
    attributs = os.lstat(source)
    if restauration is None:
        entrees = _entrees_arbre(source)
    else:
        entrees = _structure_conforme(source, restauration)
    os.mkdir(destination, 0o700)
    empreintes, liens = {}, {}
    for relatif, genre in entrees:
        origine, cible = os.path.join(source, relatif), os.path.join(destination, relatif)
        if genre == 'd':
            os.mkdir(cible, 0o700)
        elif genre == 'l':
            lien = os.readlink(origine)
            if restauration is not None and restauration['liens'].get(relatif) != lien:
                raise _integrite_refusee(origine)
            os.symlink(lien, cible)
            _chown_si_permis(cible, os.lstat(origine))
            liens[relatif] = lien
        elif restauration is None:
            empreintes[relatif] = _copier_fichier(origine, cible)
        else:
            empreintes[relatif] = _copier_fichier(
                origine, cible, attendu=restauration['empreintes'].get(relatif), verifier=True)
    dossiers = sorted(relatif for relatif, genre in entrees if genre == 'd')
    for relatif in reversed(dossiers):
        _finir_dossier(os.path.join(source, relatif), os.path.join(destination, relatif))
    _finir_dossier(source, destination, attributs)
    return empreintes, dossiers, liens


def _finir_dossier(origine, cible, attributs=None):
    attributs = attributs or os.lstat(origine)
    _chown_si_permis(cible, attributs)
    os.chmod(cible, stat.S_IMODE(attributs.st_mode))
    os.utime(cible, ns=(attributs.st_atime_ns, attributs.st_mtime_ns))


def _contient_cle_privee(descripteur):
    """Vrai si le fichier entier contient un en-tête de clé privée (lecture par blocs avec recouvrement)."""
    position, queue = 0, b''
    while True:
        bloc = os.pread(descripteur, _BLOC, position)
        if not bloc:
            return False
        position += len(bloc)
        trouvee, queue = _balayer_cle(queue, bloc)
        if trouvee:
            return True


def _verifier_sans_cle(chemin, arbre):
    """Refuse (code 4) un fichier, ou un fichier de l'arbre, dont l'en-tête est une clé privée."""
    fichiers = [chemin] if not arbre else [os.path.join(chemin, r) for r, g in _entrees_arbre(chemin) if g == 'f']
    for fichier in fichiers:
        try:
            descripteur = os.open(fichier, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        except OSError:
            raise ErreurSauvegarde('backup_failed', SORTIE_ECHEC, code='open') from None
        try:
            if _contient_cle_privee(descripteur):
                raise ErreurSauvegarde('backup_key_refused', SORTIE_CLE)
        finally:
            os.close(descripteur)


def _taille_dossier(dossier):
    total = 0
    for racine, _, fichiers in os.walk(dossier, followlinks=False):
        for nom in fichiers:
            try:
                attributs = os.lstat(os.path.join(racine, nom))
            except OSError:
                continue
            if stat.S_ISREG(attributs.st_mode):
                total += attributs.st_size
    return total


def _supprimer_arbre(chemin):
    """Suppression récursive sans suivre les liens, y compris sous des dossiers sans droit d'écriture."""
    for racine, dossiers, _ in os.walk(chemin, followlinks=False):
        for nom in dossiers:
            try:
                os.chmod(os.path.join(racine, nom), 0o700, follow_symlinks=False)
            except OSError:
                pass
    shutil.rmtree(chemin)


def rotation(dossier_machine, limite_octets, protegés=(), journal=None):
    """Supprime les jeux les plus anciens tant que la taille dépasse la limite.

    Jamais un jeu protégé ni le plus récent. Retourne (taille restante, jeux supprimés).
    """
    jeux = sorted(n for n in os.listdir(dossier_machine) if _NOM_JEU.fullmatch(n)
                  and stat.S_ISDIR(os.lstat(os.path.join(dossier_machine, n)).st_mode))
    total = _taille_dossier(dossier_machine)
    supprimes = []
    intacts = set(protegés) | set(jeux[-1:])
    for nom in jeux:
        if total <= limite_octets:
            break
        if nom in intacts:
            continue
        chemin = os.path.join(dossier_machine, nom)
        total -= _taille_dossier(chemin)
        _supprimer_arbre(chemin)
        supprimes.append(nom)
        if journal is not None:
            journal.ecrire('info', 'backup_rotated', jeu=nom)
    return max(total, 0), supprimes


class Stockage:
    """Dossier <dossier>/<machine>/ et ses jeux AAAAMMJJ-HHMMSS."""

    def __init__(self, configuration, journal, horloge=None):
        stockage = verifier_configuration(configuration)
        self.actif = stockage['actif'] == 'oui'
        self.limite_octets = stockage['taille_max_mio'] * _MIO
        self.base = stockage['dossier']
        self.machine = stockage['machine']
        self.dossier_machine = os.path.join(self.base, self.machine)
        self.journal = journal
        self.horloge = horloge or (lambda: datetime.datetime.now(datetime.timezone.utc))

    # -- dossiers ---------------------------------------------------------------------------
    def _controler_dossier(self, chemin):
        attributs = os.lstat(chemin)
        if (stat.S_ISLNK(attributs.st_mode) or not stat.S_ISDIR(attributs.st_mode)
                or attributs.st_uid not in {0, os.geteuid()} or attributs.st_mode & 0o022):
            raise ErreurSauvegarde('backup_unsafe_directory', SORTIE_ECHEC)

    def _preparer(self, creer):
        """Dossier de la machine ; créé en 0700 root:root si creer ; None s'il manque et que creer est faux."""
        verifier_composants(self.dossier_machine)
        for chemin in (self.base, self.dossier_machine):
            if os.path.lexists(chemin):
                self._controler_dossier(chemin)
                continue
            if not creer:
                return None
            if chemin == self.base:
                os.makedirs(os.path.dirname(chemin), mode=0o755, exist_ok=True)
            os.mkdir(chemin, 0o700)
            os.chmod(chemin, 0o700)
            try:
                os.chown(chemin, 0, 0)
            except OSError:
                pass
        return self.dossier_machine

    def jeux(self):
        machine = self._preparer(False)
        if machine is None:
            return []
        return sorted(n for n in os.listdir(machine) if _NOM_JEU.fullmatch(n)
                      and stat.S_ISDIR(os.lstat(os.path.join(machine, n)).st_mode))

    def nom_prochain_jeu(self):
        return self.horloge().astimezone(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S')

    def nouveau_jeu(self):
        machine = self._preparer(True)
        instant = self.horloge().astimezone(datetime.timezone.utc)
        while True:
            nom = instant.strftime('%Y%m%d-%H%M%S')
            try:
                os.mkdir(os.path.join(machine, nom), 0o700)
            except FileExistsError:
                instant += datetime.timedelta(seconds=1)
                continue
            os.chmod(os.path.join(machine, nom), 0o700)
            try:
                os.chown(os.path.join(machine, nom), 0, 0)
            except OSError:
                pass
            return nom

    def _jeu_pour_ecriture(self, nom):
        if nom is None:
            return self.nouveau_jeu()
        valider_nom_jeu(nom)
        machine = self._preparer(False)
        if machine is None or nom not in self.jeux():
            raise ErreurSauvegarde('backup_set_invalid', SORTIE_ECHEC)
        return nom

    def dossier_jeu(self, nom):
        return os.path.join(self.dossier_machine, nom)

    # -- manifeste --------------------------------------------------------------------------
    def _lire_manifeste(self, nom):
        """(entrées, relevés) du manifeste ; une version autre que la courante est refusée (D113)."""
        chemin = os.path.join(self.dossier_jeu(nom), MANIFESTE)
        try:
            descripteur = os.open(chemin, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        except FileNotFoundError:
            return {}, {}
        except OSError:
            raise ErreurSauvegarde('backup_failed', SORTIE_ECHEC, code='manifest') from None
        try:
            with os.fdopen(descripteur, 'rb') as entree:
                contenu = entree.read(_MANIFESTE_MAX + 1)
            donnees = json.loads(contenu.decode('utf-8')) if len(contenu) <= _MANIFESTE_MAX else None
        except (ValueError, OSError):
            donnees = None
        entrees = donnees.get('entrees') if isinstance(donnees, dict) else None
        if not isinstance(entrees, dict):
            raise ErreurSauvegarde('backup_failed', SORTIE_ECHEC, code='manifest')
        if donnees.get('version') != VERSION_MANIFESTE:
            raise _integrite_refusee(nom)
        releves = donnees.get('releves', {})
        if not isinstance(releves, dict):
            raise ErreurSauvegarde('backup_failed', SORTIE_ECHEC, code='manifest')
        for cle, valeur in entrees.items():
            if (not isinstance(cle, str) or not isinstance(valeur, dict)
                    or valeur.get('type') not in ('fichier', 'arbre', 'absent')):
                raise ErreurSauvegarde('backup_failed', SORTIE_ECHEC, code='manifest')
            if valeur['type'] == 'arbre':
                dossiers, liens = valeur.get('dossiers'), valeur.get('liens')
                if (not isinstance(dossiers, list) or not all(isinstance(d, str) for d in dossiers)
                        or not isinstance(liens, dict)
                        or not all(isinstance(k, str) and isinstance(v, str) for k, v in liens.items())):
                    raise _integrite_refusee(nom)
        return entrees, releves

    def _ecrire_manifeste(self, nom, entrees, releves):
        dossier = self.dossier_jeu(nom)
        contenu = json.dumps({'version': VERSION_MANIFESTE, 'entrees': entrees, 'releves': releves},
                             sort_keys=True, ensure_ascii=True).encode('ascii')
        if len(contenu) > _MANIFESTE_MAX:
            raise ErreurSauvegarde('backup_failed', SORTIE_ECHEC, code='manifest')
        sortie, temporaire = tempfile.mkstemp(dir=dossier, prefix='.paresia-')
        try:
            with os.fdopen(sortie, 'wb') as fichier:
                fichier.write(contenu)
            os.chmod(temporaire, 0o600)
            os.replace(temporaire, os.path.join(dossier, MANIFESTE))
        except BaseException:
            try:
                os.unlink(temporaire)
            except OSError:
                pass
            raise

    @staticmethod
    def chemin_copie(dossier_jeu, chemin):
        return os.path.join(dossier_jeu, DOSSIER_FICHIERS, chemin.lstrip('/'))

    # -- écriture ---------------------------------------------------------------------------
    def _limite(self, jeu):
        """Rotation puis contrôle de la limite ; retourne (taille, dépassement)."""
        taille, _ = rotation(self.dossier_machine, self.limite_octets, {jeu}, self.journal)
        return taille, taille > self.limite_octets

    def copier(self, chemins, *, arbre=False, si_absent=False, jeu=None):
        """Copie des chemins dans un jeu ; retourne (jeu, nombre copié, dépassement, taille)."""
        chemins = [valider_chemin(c) for c in chemins]
        plan = []
        try:
            for chemin in chemins:
                verifier_composants(chemin)
                try:
                    attributs = os.lstat(chemin)
                except FileNotFoundError:
                    if not si_absent:
                        raise ErreurSauvegarde('backup_source_missing', SORTIE_ECHEC, chemin=chemin) from None
                    plan.append((chemin, 'absent'))
                    continue
                if stat.S_ISREG(attributs.st_mode):
                    _verifier_sans_cle(chemin, False)
                    plan.append((chemin, 'fichier'))
                elif stat.S_ISDIR(attributs.st_mode):
                    if not arbre:
                        raise ErreurSauvegarde('backup_directory_refused', SORTIE_ECHEC, chemin=chemin)
                    _verifier_sans_cle(chemin, True)
                    plan.append((chemin, 'arbre'))
                else:
                    raise ErreurSauvegarde('backup_unsupported_type', SORTIE_ECHEC, chemin=chemin)
        except ErreurSauvegarde as erreur:
            self.journal.ecrire('warning', 'backup_refused', reason=erreur.message)
            raise
        nom = self._jeu_pour_ecriture(jeu)
        dossier = self.dossier_jeu(nom)
        entrees, releves = self._lire_manifeste(nom)
        copies = 0
        for chemin, genre in plan:
            if chemin in entrees:
                continue    # un rejeu ne remplace jamais la première sauvegarde
            for autre in entrees:
                if autre.startswith(chemin + '/') or chemin.startswith(autre + '/'):
                    raise ErreurSauvegarde('backup_conflict', SORTIE_ECHEC, chemin=chemin)
            entree = {'type': genre, 'arbre': bool(arbre)} if genre == 'absent' else {'type': genre}
            destination = None
            if genre != 'absent':
                destination = self.chemin_copie(dossier, chemin)
                os.makedirs(os.path.dirname(destination), mode=0o700, exist_ok=True)
                try:
                    if genre == 'fichier':
                        entree['sha256'] = _copier_fichier(chemin, destination)
                    else:
                        entree['empreintes'], entree['dossiers'], entree['liens'] = _copier_arbre(chemin, destination)
                except BaseException as erreur:
                    if genre == 'arbre' and os.path.lexists(destination):
                        _supprimer_arbre(destination)
                    if isinstance(erreur, ErreurSauvegarde) and erreur.message == 'backup_key_refused':
                        self.journal.ecrire('warning', 'backup_refused', reason=erreur.message)
                    raise
            entrees[chemin] = entree
            try:
                self._ecrire_manifeste(nom, entrees, releves)
            except BaseException:
                del entrees[chemin]
                if destination is not None and os.path.lexists(destination):
                    if genre == 'arbre':
                        _supprimer_arbre(destination)
                    else:
                        os.unlink(destination)
                raise
            copies += 1
        taille, depasse = self._limite(nom)
        self.journal.ecrire('info', 'backup_written', jeu=nom, elements=copies, octets=taille)
        return nom, copies, depasse, taille

    def releve(self, nom_releve, flux, *, jeu=None):
        """Enregistre le flux binaire sous releves/<nom> ; retourne (jeu, octets, dépassement, taille)."""
        valider_nom_releve(nom_releve)
        nom = self._jeu_pour_ecriture(jeu)
        dossier = os.path.join(self.dossier_jeu(nom), DOSSIER_RELEVES)
        os.makedirs(dossier, mode=0o700, exist_ok=True)
        sortie, temporaire = tempfile.mkstemp(dir=dossier, prefix='.paresia-')
        octets = 0
        condensat = hashlib.sha256()
        try:
            with os.fdopen(sortie, 'wb') as fichier:
                while True:
                    bloc = flux.read(65536)
                    if not bloc:
                        break
                    octets += len(bloc)
                    condensat.update(bloc)
                    fichier.write(bloc)
            os.chmod(temporaire, 0o600)
            os.replace(temporaire, os.path.join(dossier, nom_releve))
            entrees, releves = self._lire_manifeste(nom)
            releves[nom_releve] = condensat.hexdigest()
            self._ecrire_manifeste(nom, entrees, releves)
        except BaseException:
            try:
                os.unlink(temporaire)
            except OSError:
                pass
            raise
        taille, depasse = self._limite(nom)
        self.journal.ecrire('info', 'backup_written', jeu=nom, elements=1, octets=taille)
        return nom, octets, depasse, taille

    def nettoyer(self):
        """Rotation manuelle ; retourne (jeux supprimés, taille, dépassement)."""
        if self._preparer(False) is None:
            return [], 0, False
        taille, supprimes = rotation(self.dossier_machine, self.limite_octets, (), self.journal)
        return supprimes, taille, taille > self.limite_octets

    def taille(self):
        return 0 if self._preparer(False) is None else _taille_dossier(self.dossier_machine)

    def taille_jeu(self, nom):
        return _taille_dossier(self.dossier_jeu(nom))

    # -- restauration -----------------------------------------------------------------------
    def retrouver(self, chemin=None, *, releve=None, jeu=None):
        """Dernière sauvegarde d'un chemin (ou d'un relevé) : (jeu, genre, chemin de la copie ou None)."""
        if (chemin is None) == (releve is None):
            raise ErreurSauvegarde('backup_usage', SORTIE_USAGE)
        if releve is not None:
            valider_nom_releve(releve)
            cible = releve
        else:
            valider_chemin(chemin)
            verifier_composants(chemin)
            cible = chemin
        if jeu is not None:
            valider_nom_jeu(jeu)
        existants = self.jeux()
        candidats = [jeu] if jeu is not None else sorted(existants, reverse=True)
        for nom in candidats:
            if nom not in existants:
                continue
            dossier = self.dossier_jeu(nom)
            if releve is not None:
                fichier = os.path.join(dossier, DOSSIER_RELEVES, releve)
                try:
                    if not stat.S_ISREG(os.lstat(fichier).st_mode):
                        continue
                except OSError:
                    continue
                attendu = self._lire_manifeste(nom)[1].get(releve)
                if not _empreinte_valide(attendu) or _empreinte_fichier(fichier) != attendu:
                    raise _integrite_refusee(fichier)
                return nom, 'releve', fichier, {}
            entree = self._lire_manifeste(nom)[0].get(chemin)
            if entree is None:
                continue
            copie = None if entree['type'] == 'absent' else self.chemin_copie(dossier, chemin)
            if copie is not None:
                self._verifier_copie(entree, copie)
            return nom, entree['type'], copie, entree
        raise ErreurSauvegarde('backup_not_found', SORTIE_INTROUVABLE, chemin=cible)

    @staticmethod
    def _verifier_copie(entree, copie):
        """Recalcule et compare les empreintes de toute la copie (fichier ou arbre) avant la moindre écriture."""
        if entree['type'] == 'fichier':
            attendu = entree.get('sha256')
            if not _empreinte_valide(attendu) or _empreinte_fichier(copie) != attendu:
                raise _integrite_refusee(copie)
            return
        _structure_conforme(copie, entree)
        attendues = entree['empreintes']
        for relatif, attendu in attendues.items():
            if not _empreinte_valide(attendu) or _empreinte_fichier(os.path.join(copie, relatif)) != attendu:
                raise _integrite_refusee(os.path.join(copie, relatif))

    def restaurer(self, chemin, *, jeu=None):
        """Rétablit un chemin sauvegardé ; ne supprime qu'un fichier dont la copie ou la marque existe."""
        valider_chemin(chemin)
        verifier_composants(chemin)
        nom, genre, copie, entree = self.retrouver(chemin, jeu=jeu)
        parent = os.path.dirname(chemin)
        try:
            actuel = os.lstat(chemin)
        except FileNotFoundError:
            actuel = None
        if genre == 'absent':
            if actuel is not None:
                if stat.S_ISDIR(actuel.st_mode):
                    if not entree.get('arbre'):
                        raise ErreurSauvegarde('backup_directory_refused', SORTIE_ECHEC, chemin=chemin)
                    _supprimer_arbre(chemin)
                else:
                    os.unlink(chemin)
            self.journal.ecrire('info', 'backup_restored', jeu=nom, genre='absent')
            return nom, genre
        if not os.path.isdir(parent):
            raise ErreurSauvegarde('backup_failed', SORTIE_ECHEC, code='parent')
        if genre == 'fichier':
            if actuel is not None and stat.S_ISDIR(actuel.st_mode):
                raise ErreurSauvegarde('backup_directory_refused', SORTIE_ECHEC, chemin=chemin)
            _copier_fichier(copie, chemin, attendu=entree.get('sha256'), verifier=True)
        else:
            self._restaurer_arbre(copie, chemin, actuel, entree)
        self.journal.ecrire('info', 'backup_restored', jeu=nom, genre=genre)
        return nom, genre

    @staticmethod
    def _restaurer_arbre(copie, chemin, actuel, entree):
        parent = os.path.dirname(chemin)
        neuf = tempfile.mkdtemp(dir=parent, prefix='.paresia-restaure-')
        os.rmdir(neuf)
        ecarte = None
        try:
            _copier_arbre(copie, neuf, restauration=entree)
            if actuel is not None:
                ecarte = tempfile.mkdtemp(dir=parent, prefix='.paresia-ancien-')
                os.rmdir(ecarte)
                os.rename(chemin, ecarte)
            try:
                os.rename(neuf, chemin)
            except BaseException:
                if ecarte is not None:
                    os.rename(ecarte, chemin)
                raise
        except BaseException:
            if os.path.lexists(neuf):
                _supprimer_arbre(neuf)
            raise
        if ecarte is not None:
            if stat.S_ISDIR(actuel.st_mode):
                _supprimer_arbre(ecarte)
            else:
                os.unlink(ecarte)
