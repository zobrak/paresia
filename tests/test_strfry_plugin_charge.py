# SPDX-License-Identifier: AGPL-3.0-or-later
# Essai de charge du plugin writePolicy (T040) : ignoré sauf si PARESIA_ESSAI_CHARGE=1 ; lancé par l'utilisateur.
# Variables : PARESIA_ESSAI_CHARGE=1 ; PARESIA_ESSAI_PLUGIN (autre plugin au même protocole) ;
# PARESIA_ESSAI_N (nombre de requêtes, 100000 par défaut) ; PARESIA_ESSAI_MELANGE (pourcentages
# "20001:70,20000:15,1059:8,1:3,1401:2,5:1,banni:1" par défaut ; "1:100" pour le pire cas journalisé).
# Suivi des versions
#   3.0.0-alpha.40  2026-11-06  Création (T040).
import json
import os
import random
import select
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parent.parent / 'server/strfry/journal_legal.py'
MELANGE_DEFAUT = '20001:70,20000:15,1059:8,1:3,1401:2,5:1,banni:1'

pytestmark = pytest.mark.skipif(os.environ.get('PARESIA_ESSAI_CHARGE') != '1',
                                reason='essai de charge : PARESIA_ESSAI_CHARGE=1')


def percentile(valeurs, p):
    if not valeurs:
        return float('nan')
    s = sorted(valeurs)
    return s[min(len(s) - 1, int(len(s) * p / 100))]


def test_essai_charge():
    n = int(os.environ.get('PARESIA_ESSAI_N', '100000'))
    melange = []
    for part in os.environ.get('PARESIA_ESSAI_MELANGE', MELANGE_DEFAUT).split(','):
        nom, poids = part.split(':')
        melange.append((nom, float(poids)))
    plugin = os.environ.get('PARESIA_ESSAI_PLUGIN', str(MODULE))
    alea = random.Random(2026)

    def hexa(k):
        return '%0*x' % (k, alea.getrandbits(4 * k))

    with tempfile.TemporaryDirectory() as dossier:
        journal = Path(dossier) / 'journal'
        journal.mkdir()
        liste = Path(dossier) / 'blocklist.txt'
        banni = hexa(64)
        liste.write_text(banni + '\n')
        env = dict(os.environ, JOURNAL_DIR=str(journal), BLOCKLIST_FILE=str(liste))
        noms = [m[0] for m in melange]
        poids = [m[1] for m in melange]
        p = subprocess.Popen([sys.executable if plugin.endswith('.py') else plugin]
                             + ([plugin] if plugin.endswith('.py') else []),
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env)
        delais = {'rapide': [], 'journalise': [], 'refuse': []}
        debut = time.perf_counter()
        for _ in range(n):
            choix = alea.choices(noms, poids)[0]
            kind = 1 if choix == 'banni' else int(choix)
            auteur = banni if choix == 'banni' else hexa(64)
            r = {'type': 'new', 'event': {'id': hexa(64), 'pubkey': auteur, 'created_at': 1700000000,
                                           'kind': kind, 'tags': [], 'content': 'x', 'sig': hexa(128)},
                 'receivedAt': 1700000001, 'sourceType': 'IP4', 'sourceInfo': '203.0.113.7'}
            chemin = ('refuse' if choix == 'banni'
                      else 'rapide' if kind in (20001, 22242, 23194, 23195, 24133, 24242, 27235) else 'journalise')
            t0 = time.perf_counter()
            p.stdin.write(json.dumps(r).encode() + b'\n')
            p.stdin.flush()
            assert select.select([p.stdout], [], [], 30)[0], 'plugin sans réponse en 30 s'
            assert p.stdout.readline()
            delais[chemin].append(time.perf_counter() - t0)
        total = time.perf_counter() - debut
        p.stdin.close()
        p.wait(timeout=30)
    print('\nplugin : %s ; requêtes : %d ; débit global : %.0f/s' % (plugin, n, n / total))
    print('%-10s %8s %10s %10s %10s %10s' % ('chemin', 'n', 'p50 ms', 'p95 ms', 'p99 ms', 'max ms'))
    for chemin, d in delais.items():
        print('%-10s %8d %10.3f %10.3f %10.3f %10.3f ; débit %.0f/s' % (
            chemin, len(d), percentile(d, 50) * 1e3, percentile(d, 95) * 1e3,
            percentile(d, 99) * 1e3, (max(d) if d else float('nan')) * 1e3,
            (len(d) / sum(d)) if d and sum(d) else float('nan')))
