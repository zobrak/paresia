# Initialisation des tests : dossier temporaire propre à chaque exécution de pytest.
# Dépendances : fcntl, os, pathlib, shutil et pytest.
#
# Chaque exécution reçoit .pytest_cache/t<pid> (chemin court : les sockets Unix
# sont limitées à 108 octets). Un verrou flock .pytest_cache/t<pid>.lock, tenu
# jusqu'à la fin du processus, marque l'exécution en cours ; au démarrage, les
# dossiers dont le verrou est libre (exécution terminée ou interrompue) sont
# supprimés, les autres sont laissés. Un verrou flock disparaît avec son
# processus : il n'a pas le défaut d'un numéro de processus réutilisé. Une
# option --basetemp passée en ligne de commande l'emporte. Le verrou (fcntl) rend ce
# mécanisme propre aux systèmes Unix.
#
# Suivi des versions
#   3.0.0-alpha.41  2026-11-06  Dossier temporaire propre à chaque exécution.
#   3.0.0-alpha     2026-11-05  Prépare le parent du basetemp sur un checkout neuf.
import fcntl
import os
import shutil
from pathlib import Path

import pytest

_verrous = []  # descripteurs gardés ouverts jusqu'à la fin du processus


def _nettoyer_et_reserver(racine: Path) -> Path:
    racine.mkdir(parents=True, exist_ok=True)
    # Verrou global : la réservation et le nettoyage ne se croisent pas.
    with open(racine / 't.lock', 'a') as global_:
        fcntl.flock(global_, fcntl.LOCK_EX)
        for verrou in racine.glob('t[0-9]*.lock'):
            with open(verrou, 'a') as autre:
                try:
                    fcntl.flock(autre, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    continue  # exécution encore en cours
                shutil.rmtree(verrou.with_suffix(''), ignore_errors=True)
                verrou.unlink(missing_ok=True)
        propre = racine / f't{os.getpid()}'
        descripteur = open(racine / f't{os.getpid()}.lock', 'a')
        fcntl.flock(descripteur, fcntl.LOCK_EX)
        _verrous.append(descripteur)
        return propre


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    if config.option.basetemp:
        Path(config.option.basetemp).parent.mkdir(parents=True, exist_ok=True)
        return
    config.option.basetemp = str(_nettoyer_et_reserver(config.rootpath / '.pytest_cache'))
