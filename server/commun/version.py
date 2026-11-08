# SPDX-License-Identifier: AGPL-3.0-or-later
# Suivi des versions
#   0.1.2  2026-11-07  Lecture unique et contrôlée de la version du code installé.
#   0.1.1  2026-11-07  Version commune du produit.
# GNU Coding Standards, § 4.7 : version annoncée par --version.
from functools import cache
from pathlib import Path
import re


@cache
def _charger_version(racine):
    """Mémorise aussi les échecs : aucune relecture pendant la vie du processus."""
    try:
        with (racine / 'VERSION').open('rb') as entree:
            contenu = entree.read(129)
    except OSError:
        return None, 'version_unreadable'
    if len(contenu) > 128:
        return None, 'version_invalid'
    try:
        version = contenu.decode('ascii').removesuffix('\n')
    except UnicodeError:
        return None, 'version_invalid'
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        return None, 'version_invalid'
    return version, None


def lire_version(racine=None):
    """Version à la racine du code, parent de server/ ; racine injectable en test.

    Le résultat est mémorisé par racine, sans numéro de version de repli.
    RuntimeError ne porte ni le chemin ni le contenu du fichier ; le lanceur
    la traduit en EX_SOFTWARE et startup_failed avant l'entrée en service.
    """
    racine = Path(__file__).resolve().parents[2] if racine is None else Path(racine)
    version, erreur = _charger_version(racine)
    if erreur is not None:
        raise RuntimeError(erreur)
    return version
