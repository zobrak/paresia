# SPDX-License-Identifier: AGPL-3.0-or-later
# Entrée du démon Nisaba : python3 -P -s -B -m server.nisaba ; dépendances : bibliothèque standard et server.commun.
# Suivi des versions
#   0.1.1  2026-11-07  Raccordement au socle commun : Type=notify, options, codes sysexits.
#   3.0.0-alpha.40  2026-11-06  Création (T031) : configuration en couches, arrêt ordonné sur signal.
import sys

from server.commun.demon import Demon, lancer
from server.commun.version import lire_version
from . import Nisaba, SCHEMA, configuration


def _configurer(*, argv, environ):
    return configuration(argv=argv, environ=environ)


DEMON = Demon('nisaba', lire_version, SCHEMA, Demon.depuis_contexte(Nisaba), _configurer)


def main(argv=None):
    return lancer(DEMON, argv)


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
