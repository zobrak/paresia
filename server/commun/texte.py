# Filtrage des textes ; dépendances : bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha  2026-11-05  Durcissement et corrections du cycle de revue 1.
#   3.0.0-alpha  2026-11-05  Filtrage Cc et contrôles bidirectionnels.
import unicodedata


def filtrer(texte: str) -> str:
    """Remplace les caractères de contrôle sans supprimer les caractères voisins."""
    return ''.join(
        '\ufffd' if unicodedata.category(c) in {'Cc', 'Cf', 'Zl', 'Zp', 'Cs', 'Co'} else c
        for c in texte
    )
