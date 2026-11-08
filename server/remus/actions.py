# SPDX-License-Identifier: AGPL-3.0-or-later
# Table des actions de Remus : les fonctions enfichées ; dépendances : server.remus.fonctions.
# Suivi des versions
#   0.1.7  2026-11-07  Les actions sont les fonctions chargées par le chargeur du noyau (D148, D154).
#   3.0.0-alpha  2026-11-05  Table vide : le lot 6 y enregistre ses actions (T021).


def construire_actions(configuration, journal, **chargeur):
    """Retourne {nom: Action} : les fonctions chargées, un dossier vide ou absent donnant {}."""
    from .fonctions import charger_fonctions
    return charger_fonctions(configuration, journal, **chargeur).actions
