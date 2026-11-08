# SPDX-License-Identifier: AGPL-3.0-or-later
# Outils communs aux tests de Romulus : injection des déclarations de services livrées du dépôt ; bibliothèque standard, server.
# Suivi des versions
#   0.1.8  2026-11-07  Chargeur d'injection et schéma assemblé à partir des déclarations livrées.
import os
from pathlib import Path

from server.romulus import declarations, schema_complet

RACINE = Path(__file__).resolve().parents[1]
DOSSIER_SERVICES = RACINE / 'deploy/backend-admin/usr/local/lib/paresia/romulus/services'
# En production : propriétaire root, racine de confiance « / », dossiers par défaut. Les tests
# lisent les déclarations du dépôt, qui appartiennent à l'utilisateur du test ; le dossier local
# est un dossier qui n'existe pas.
CHARGEUR = {'livrees': str(DOSSIER_SERVICES), 'locales': str(RACINE / 'absent-services.d'),
            'proprietaires': frozenset({os.geteuid()}), 'racine_confiance': str(RACINE)}


def declarations_livrees():
    return declarations({}, None, CHARGEUR)


def schema_romulus():
    """Schéma complet de Romulus : socle plus sections des quatre déclarations livrées."""
    return schema_complet(declarations_livrees())
