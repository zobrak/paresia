# SPDX-License-Identifier: AGPL-3.0-or-later
# Catalogues et affichage sûr ; dépendances : bibliothèque standard et server.commun.
# Suivi des versions
#   3.0.0-alpha.40  2026-11-06  Chargement borné, traduction des codes et filtrage.
#   3.0.0-alpha.40  2026-11-06  Repli vide pour les clés non textuelles.
import json
import os
from pathlib import Path
import re
import stat

from server.commun.jumeaux import CODES_ERREUR
from server.commun.texte import filtrer


def afficher(texte):
    """Filtre toute chaîne extérieure avant son affichage."""
    return filtrer(texte) if isinstance(texte, str) else ''


def diagnostic(detail):
    """Texte filtré et borné, réservé à la zone de diagnostic."""
    return afficher(detail)[:200]


class Catalogue:
    """Libellés locaux ; les codes distants ne deviennent jamais des messages."""

    def __init__(self, libelles):
        self._libelles = dict(libelles)

    def libelle(self, cle):
        """Repli sur la clé absente, avec filtrage dans les deux cas (D91)."""
        if not isinstance(cle, str):
            return ''
        return afficher(self._libelles.get(cle, cle))

    def erreur(self, code):
        """Traduit les seuls codes admis ; ignore tout détail distant (D5)."""
        if not (isinstance(code, str) and (
                code in CODES_ERREUR or (code.startswith('ui_') and code in self._libelles))):
            code = 'internal_error'
        return self.libelle(code)


def _lire_catalogue(chemin):
    """Lecture d'un fichier régulier, sans lien final et limitée à un Mio."""
    plafond = 1024 * 1024
    descripteur = os.open(chemin, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        attributs = os.fstat(descripteur)
        if not stat.S_ISREG(attributs.st_mode) or attributs.st_size > plafond:
            raise ValueError('catalogue_invalid')
        with os.fdopen(descripteur, 'rb') as entree:
            descripteur = None
            contenu = entree.read(plafond + 1)
    finally:
        if descripteur is not None:
            os.close(descripteur)
    if len(contenu) > plafond:
        raise ValueError('catalogue_invalid')
    try:
        libelles = json.loads(contenu.decode('utf-8'))
    except (UnicodeError, ValueError, RecursionError):
        raise ValueError('catalogue_invalid') from None
    if not isinstance(libelles, dict) or not all(isinstance(v, str) for v in libelles.values()):
        raise ValueError('catalogue_invalid')
    return Catalogue(libelles)


def charger(langue, dossier):
    """Charge une langue BCP 47 ; une langue absente se replie sur fr-FR."""
    if not isinstance(langue, str) or not re.fullmatch(r'[a-z]{2}-[A-Z]{2}', langue):
        raise ValueError('catalogue_invalid_language')
    try:
        try:
            return _lire_catalogue(Path(dossier) / (langue + '.json'))
        except FileNotFoundError:
            if langue == 'fr-FR':
                raise
            return _lire_catalogue(Path(dossier) / 'fr-FR.json')
    except OSError:
        raise ValueError('catalogue_unreadable') from None
