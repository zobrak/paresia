# SPDX-License-Identifier: AGPL-3.0-or-later
# Entrée du démon Castor ; dépendances : bibliothèque standard et server.commun.
# Suivi des versions
#   0.1.1  2026-11-07  Raccordement au socle commun : Type=notify, options, codes sysexits.
#   3.0.0-alpha  2026-11-05  Configuration en couches et arrêt sur signal (T020).
import sys

from server.commun.demon import Demon, lancer
from server.commun.version import lire_version
from . import Castor, SCHEMA

DEMON = Demon('castor', lire_version, SCHEMA, Demon.depuis_contexte(Castor))


def main(argv=None):
    return lancer(DEMON, argv)


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
