# SPDX-License-Identifier: AGPL-3.0-or-later
# Contrat de sortie d'une fonction ; dépendances : jumeaux (JSON strict), texte.
# Suivi des versions
#   0.1.5  2026-11-07  Création : interprétation pure de la sortie d'une fonction (D154).
"""Contrat de sortie : le JSON porte seul le résultat, le code de sortie le recoupe.

Fonction pure : elle ne manipule que des octets, un code de sortie et du JSON ;
elle ne suppose rien du processus qui les a produits. Sortie standard : un objet
`{"ok": true, "data": {...}}` ou `{"ok": false, "error": {"code": "..."}}`, rien
d'autre. Codes de sortie : 0 succès, 1 refus ou échec attendu, 2 prérequis
indisponible, tout autre code ou signal = erreur interne. Toute violation donne
`command_failed`. Ni la sortie brute ni un message du script ne sont retournés.
"""
import math

from .jumeaux import PLAFOND_LIMITE, charger_json_strict
from .texte import filtrer

SORTIE_MAX_DEFAUT = 65536
PROFONDEUR_MAX = 8
CODE_ECHEC = 'command_failed'
CODE_INDISPONIBLE = 'not_available'


class Resultat(tuple):
    """Couple ('ok', data) ou ('erreur', code) ; `contrat` vaut 'ok' ou 'violated'."""

    def __new__(cls, statut, valeur, contrat):
        objet = super().__new__(cls, (statut, valeur))
        objet.contrat = contrat
        return objet

    statut = property(lambda self: self[0])
    valeur = property(lambda self: self[1])


def _violation():
    return Resultat('erreur', CODE_ECHEC, 'violated')


def _filtrer_valeur(valeur, profondeur):
    """Copie filtrée ; ValueError si type, profondeur ou texte inadmissible."""
    if profondeur > PROFONDEUR_MAX:
        raise ValueError('invalid_output')
    if isinstance(valeur, str):
        if filtrer(valeur) != valeur:
            raise ValueError('invalid_output')
        return valeur
    if valeur is None or type(valeur) in (bool, int):
        return valeur
    if type(valeur) is float:
        if not math.isfinite(valeur):
            raise ValueError('invalid_output')
        return valeur
    if type(valeur) is list:
        return [_filtrer_valeur(v, profondeur + 1) for v in valeur]
    if type(valeur) is dict:
        return {_filtrer_valeur(c, profondeur + 1): _filtrer_valeur(v, profondeur + 1)
                for c, v in valeur.items()}
    raise ValueError('invalid_output')


def interpreter_sortie(sortie_standard, code_sortie, descripteur, *, sortie_max):
    """Retourne Resultat : ('ok', data) ou ('erreur', code) ; sortie_max est obligatoire.

    Un sortie_max invalide est une violation du contrat, non une exception.
    """
    try:
        return _interpreter(sortie_standard, code_sortie, descripteur, sortie_max)
    except (ValueError, TypeError, AttributeError):
        return _violation()


def _interpreter(sortie, code, descripteur, sortie_max):
    if type(code) is not int or code not in (0, 1, 2):
        return _violation()
    if (type(sortie) is not bytes or type(sortie_max) is not int
            or not 1 <= sortie_max <= PLAFOND_LIMITE or len(sortie) > sortie_max):
        return _violation()
    objet = charger_json_strict(sortie)
    if type(objet) is not dict:
        return _violation()
    if set(objet) == {'ok', 'data'} and objet['ok'] is True:
        if code != 0 or type(objet['data']) is not dict:
            return _violation()
        return Resultat('ok', _filtrer_valeur(objet['data'], 1), 'ok')
    if set(objet) == {'ok', 'error'} and objet['ok'] is False:
        erreur = objet['error']
        if code == 0 or type(erreur) is not dict or set(erreur) != {'code'}:
            return _violation()
        valeur = erreur['code']
        if type(valeur) is not str or filtrer(valeur) != valeur:
            return _violation()
        if code == 1 and valeur in tuple(descripteur.erreurs):
            return Resultat('erreur', valeur, 'ok')
        if code == 2 and valeur == CODE_INDISPONIBLE:
            return Resultat('erreur', valeur, 'ok')
    return _violation()
