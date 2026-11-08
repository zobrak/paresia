# SPDX-License-Identifier: AGPL-3.0-or-later
# Format et migration de bunker.json ; dépendances : bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha.32  2026-11-06  T007 : validation, sauvegarde vérifiée et migration avant écoute.
import datetime
import json
import os
from pathlib import Path
import re
import stat

from server.commun.texte import filtrer
from .formats import HEX64_RE, IDENTITY_RE, MAX_MINUTES, MIN_MINUTES, relais_valide

FORMAT = 1


class ErreurEtat(ValueError):
    """Cause stable, sans donnée issue du fichier."""

    def __init__(self, cause, code='state_unreadable'):
        super().__init__(cause)
        self.cause = cause
        self.code = code


def message(code):
    """Catalogue français jusqu'à l'introduction d'une langue configurée."""
    try:
        chemin = Path(__file__).resolve().parents[2] / 'i18n' / 'fr-FR.json'
        texte = json.loads(chemin.read_text(encoding='utf-8')).get(code, code)
        return filtrer(texte if isinstance(texte, str) else code)
    except (OSError, ValueError):
        return filtrer(code)


def valider(identites):
    if not isinstance(identites, dict):
        raise ErreurEtat('identities_not_object')
    for nom, entree in identites.items():
        if not isinstance(nom, str) or not IDENTITY_RE.fullmatch(nom):
            raise ErreurEtat('invalid_identity')
        if not isinstance(entree, dict):
            raise ErreurEtat('entry_not_object')
        if 'pubkey' in entree and (not isinstance(entree['pubkey'], str)
                                  or not HEX64_RE.fullmatch(entree['pubkey'])):
            raise ErreurEtat('invalid_pubkey')
        if 'timeout' in entree and (type(entree['timeout']) is not int
                                   or not MIN_MINUTES * 60 <= entree['timeout'] <= MAX_MINUTES * 60):
            raise ErreurEtat('invalid_timeout')
    return identites


def _objet(paires):
    objet = {}
    for cle, valeur in paires:
        if cle in objet:
            raise ErreurEtat('duplicate_key')
        objet[cle] = valeur
    return objet


def decoder(octets):
    try:
        objet = json.loads(octets, object_pairs_hook=_objet,
                           parse_constant=lambda _: (_ for _ in ()).throw(ErreurEtat('invalid_json')))
    except (ValueError, UnicodeError, RecursionError) as erreur:
        if isinstance(erreur, ErreurEtat):
            raise
        raise ErreurEtat('invalid_json') from None
    if not isinstance(objet, dict):
        raise ErreurEtat('not_object')
    # Une entrée objet nommée « format » appartient au format historique.
    if 'format' in objet and not isinstance(objet['format'], dict):
        version = objet['format']
        if type(version) is not int or version != FORMAT:
            raise ErreurEtat('unsupported_format')
        if set(objet) != {'format', 'identities'}:
            raise ErreurEtat('invalid_envelope')
        return version, valider(objet['identities'])
    return 0, valider(objet)


def lire(chemin):
    try:
        return Path(chemin).read_bytes()
    except FileNotFoundError:
        return None
    except OSError:
        raise ErreurEtat('read_failed') from None


def _horodatage():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def _sauvegarder(chemin, octets, version):
    sauvegarde = f'{chemin}.bak-format{version}-{_horodatage()}'
    fd = os.open(sauvegarde, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as flux:
        os.fchmod(flux.fileno(), 0o600)
        flux.write(octets)
        flux.flush()
        os.fsync(flux.fileno())
    fd = os.open(sauvegarde, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as flux:
        if flux.read() != octets:
            raise ErreurEtat('backup_mismatch', 'state_migration_failed')
    dossier = os.open(os.path.dirname(chemin), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(dossier)
    finally:
        os.close(dossier)
    return sauvegarde


def _elaguer(chemin, nouvelle):
    chemin = Path(chemin)
    motif = re.compile(re.escape(chemin.name) + r'\.bak-format[0-9]+-([0-9]{8}T[0-9]{6}Z)')
    anciennes = []
    for fichier in chemin.parent.iterdir():
        trouve = motif.fullmatch(fichier.name)
        if trouve and stat.S_ISREG(fichier.lstat().st_mode) and str(fichier) != nouvelle:
            anciennes.append((trouve[1], fichier))
    for _, fichier in sorted(anciennes, reverse=True)[2:]:
        fichier.unlink()


def migrer(depot, journal):
    """Appel sous le verrou du superviseur, avant tout service ou thread."""
    octets = lire(depot.state_file)
    if octets is None:
        return
    version, identites = decoder(octets)
    if version == FORMAT:
        return
    try:
        sauvegarde = _sauvegarder(depot.state_file, octets, version)
        depot.save_state(identites)
    except OSError:
        raise ErreurEtat('migration_io_failed', 'state_migration_failed') from None
    journal.ecrire('info', 'state_migrated', source_format=version, target_format=FORMAT)
    try:
        _elaguer(depot.state_file, sauvegarde)
    except OSError:
        journal.ecrire('warning', 'state_backup_cleanup_failed')
    for identite in depot.identities():
        try:
            profil = depot.read_profile(identite)
        except (OSError, ValueError, UnicodeError):
            continue
        relais = profil.get('relays', []) if isinstance(profil, dict) else []
        if isinstance(relais, list):
            for indice, relais in enumerate(relais):
                if not relais_valide(relais):
                    journal.ecrire('warning', 'relay_nonconforming', identity=identite, relay_index=indice)
