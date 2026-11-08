# SPDX-License-Identifier: AGPL-3.0-or-later
# Bloc de privilèges neutre et son unique traducteur ; dépendances : catalogue.
# Suivi des versions
#   0.1.5  2026-11-07  Création : bloc neutre des commandes privilégiées, vers_sudo (D153).
"""Commandes privilégiées décrites de façon abstraite.

Une entrée du manifeste : `operation` (verbe de la commande privilégiée, `exec`
ou `restart`) et `arguments` (éléments fixes, ou `{parametre = "nom"}` désignant
un paramètre déclaré de type `choix`, `hexadecimal` ou `entier`). Aucune syntaxe
de l'outil d'élévation n'y figure. `vers_sudo` est le seul endroit du noyau qui
nomme sudo : la bascule vers une socket par fonction le remplacera sans toucher
au manifeste.

Limite assumée : avec sudo, les droits sont ceux du compte du démon, non de la
fonction ; le champ `privilege` du manifeste est une étiquette publiée, non
appliquée. La condition de chargement n'est jamais lue ici.
"""
from dataclasses import dataclass
import re

OPERATIONS = ('exec', 'restart')
COMMANDES_MAX = 16
ARGUMENTS_MAX = 16
TYPES_VARIABLES = ('choix', 'hexadecimal', 'entier')
ELEMENT_FIXE = re.compile(r'[A-Za-z0-9/._+\-]{1,4096}', re.ASCII)
# Un nom entièrement en capitales est un mot-clé ou un alias de l'outil : refusé.
MOT_RESERVE = re.compile(r'[A-Z][A-Z0-9]*\Z')
HEXADECIMAL_MAX = 128
CHOIX_MAX = 256
CODE = 'plugin_manifest_invalid'


@dataclass(frozen=True)
class VariablePrivilegiee:
    """Élément variable : paramètre désigné, type et bornes copiés de sa déclaration."""
    nom: str
    type: str
    bornes: object


@dataclass(frozen=True)
class CommandePrivilegiee:
    operation: str
    elements: tuple


def _fixe_valide(element):
    return (type(element) is str and ELEMENT_FIXE.fullmatch(element) is not None
            and MOT_RESERVE.match(element) is None and not element.startswith('-'))


def _variable_valide(parametre):
    bornes = parametre.bornes
    if parametre.type == 'choix':
        return (len(bornes['valeurs']) <= CHOIX_MAX
                and all(ELEMENT_FIXE.fullmatch(v) and not v.startswith('-')
                        for v in bornes['valeurs']))
    if parametre.type == 'hexadecimal':
        return bornes['longueur'] <= HEXADECIMAL_MAX
    return bornes['minimum'] >= 0


def valeurs_choix_valides(parametres):
    """Aucune valeur de choix ne commence par « - » (pas d'argument d'option forgé)."""
    return all(not v.startswith('-') for p in parametres if p.type == 'choix'
               for v in p.bornes['valeurs'])


def valider_commandes(bloc, parametres):
    """Valide `[[commandes_privilegiees]]` ; retourne un tuple de CommandePrivilegiee.

    `parametres` : paramètres déclarés (catalogue.Parametre). ValueError(CODE) si
    le bloc est défectueux.
    """
    if type(bloc) is not list or len(bloc) > COMMANDES_MAX:
        raise ValueError(CODE)
    declares = {p.nom: p for p in parametres}
    resultat = []
    for entree in bloc:
        if type(entree) is not dict or set(entree) != {'operation', 'arguments'}:
            raise ValueError(CODE)
        operation, arguments = entree['operation'], entree['arguments']
        if (operation not in OPERATIONS or type(arguments) is not list
                or not 1 <= len(arguments) <= ARGUMENTS_MAX):
            raise ValueError(CODE)
        elements = []
        for argument in arguments:
            if type(argument) is dict:
                nom = argument.get('parametre')
                parametre = declares.get(nom) if type(nom) is str else None
                if (set(argument) != {'parametre'} or parametre is None
                        or parametre.type not in TYPES_VARIABLES
                        or not _variable_valide(parametre)):
                    raise ValueError(CODE)
                elements.append(VariablePrivilegiee(nom, parametre.type, dict(parametre.bornes)))
            elif _fixe_valide(argument):
                elements.append(argument)
            else:
                raise ValueError(CODE)
        variables = any(not isinstance(e, str) for e in elements)
        if operation == 'restart':
            if len(elements) != 1 or variables:
                raise ValueError(CODE)
        elif len(elements) < (3 if variables else 2) or variables and any(
                not isinstance(e, str) for e in elements[:2]):
            raise ValueError(CODE)
        resultat.append(CommandePrivilegiee(operation, tuple(elements)))
    return tuple(resultat)


def vers_sudo(commandes):
    """Seul traducteur vers sudo : description simple, sans importer le démon.

    Retourne une liste de {'verbe': str, 'elements': [str | {'nom', 'type', 'bornes'}]}.
    """
    sortie = []
    for commande in commandes:
        elements = []
        for element in commande.elements:
            if isinstance(element, str):
                elements.append(element)
            else:
                elements.append({'nom': element.nom, 'type': element.type,
                                 'bornes': dict(element.bornes)})
        sortie.append({'verbe': commande.operation, 'elements': elements})
    return sortie
