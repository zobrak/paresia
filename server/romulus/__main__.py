# SPDX-License-Identifier: AGPL-3.0-or-later
# Point d'entrée Romulus ; dépendances : bibliothèque standard, paquet romulus.
# Suivi des versions
#   0.1.1  2026-11-07  Raccordement au socle commun : Type=notify, options, codes sysexits.
#   3.0.0-alpha  2026-11-05  Lancement configurable et arrêt sur signal.
#   3.0.0-alpha  2026-11-05  Cause de l'échec de démarrage journalisée sans valeur ni message.
import sys

from server.commun.demon import Demon, lancer
from server.commun.version import lire_version
from . import Romulus, SCHEMA, configuration


def _configurer(*, argv, environ):
    # configuration est lue dans l'espace de noms au moment de l'appel.
    return configuration(argv=argv, environ=environ)


def _corps(config, journal, cycle):
    with Romulus(config, journal=journal):
        journal.ecrire('info', 'started')
        cycle.pret()
        cycle.attendre()
    journal.ecrire('info', 'stopped')
    return 0


DEMON = Demon('romulus', lire_version, SCHEMA, _corps, _configurer)


def main(argv=None):
    return lancer(DEMON, argv)


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
