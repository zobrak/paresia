# SPDX-License-Identifier: AGPL-3.0-or-later
# Nisaba : lancement borné des programmes externes (rsync, ots, chattr, lsattr, setfacl, getfacl) par argv,
# sans interpréteur de commandes (N8, D87, C38) ; dépendances : bibliothèque standard et server.commun.texte.
# Suivi des versions
#   3.0.0-alpha.41  2026-11-06  Création (T033, N8) : environnement vide hors PATH fixe, délai, sorties bornées.
import os
import signal
import subprocess
from collections import namedtuple

from server.commun.texte import filtrer

PATH_OUTILS = '/usr/sbin:/usr/bin:/sbin:/bin'
MAX_SORTIE = 16 * 1024      # sortie standard conservée (octets)
MAX_ERREUR = 300            # erreur standard conservée (caractères, après filtrage)
LIMITE_LECTURE = 64 * 1024  # lecture maximale de chaque flux (la suite est écartée)
Resultat = namedtuple('Resultat', 'code sortie erreur')


def _borner(octets, maximum):
    texte = octets[:maximum].decode('utf-8', 'replace')
    return '\n'.join(filtrer(ligne) for ligne in texte.split('\n'))


def lancer(argv, delai=10):
    """Lance un programme par argv ; Resultat(code, sortie, erreur), sorties filtrées et bornées.

    Aucun shell ; entrée standard fermée ; environnement réduit à PATH. Un programme introuvable ou qui
    dépasse le délai (arrêté, lui et ses descendants) donne le code 127. L'erreur standard est ramenée
    sur une ligne de MAX_ERREUR caractères au plus.
    """
    try:
        processus = subprocess.Popen(list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, env={'PATH': PATH_OUTILS},
                                     start_new_session=True)
    except (OSError, ValueError, subprocess.SubprocessError):
        return Resultat(127, '', '')
    try:
        sortie, erreur = processus.communicate(timeout=delai)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(processus.pid, signal.SIGKILL)
        except OSError:
            pass
        processus.communicate()
        return Resultat(127, '', '')
    except BaseException:
        try:
            os.killpg(processus.pid, signal.SIGKILL)
        except OSError:
            pass
        processus.wait()
        raise
    ligne = ' '.join(_borner(erreur[:LIMITE_LECTURE], LIMITE_LECTURE).split())
    return Resultat(processus.returncode, _borner(sortie[:LIMITE_LECTURE], MAX_SORTIE), ligne[:MAX_ERREUR])
