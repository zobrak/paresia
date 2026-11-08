# SPDX-License-Identifier: AGPL-3.0-or-later
# Suivi des versions : 3.0.0-alpha — 2026-11-06, tests de citations T023.
import os
from pathlib import Path
import re
import shutil
import subprocess
import unicodedata

import pytest

DOCUMENT = Path(__file__).resolve().parents[1] / 'deploy/backend-relais/isolation-remus.md'
DIRECTIVES = '''LimitCORE NoNewPrivileges CapabilityBoundingSet AmbientCapabilities ProtectSystem ProtectHome
PrivateTmp PrivateDevices ProtectKernelTunables ProtectKernelModules ProtectKernelLogs ProtectControlGroups
ProtectClock ProtectHostname ProtectProc RestrictAddressFamilies RestrictNamespaces RestrictRealtime
RestrictSUIDSGID LockPersonality SystemCallArchitectures SystemCallFilter UMask MemoryDenyWriteExecute
PrivateUsers ReadWritePaths ReadOnlyPaths'''.split()


def lignes():
    return [[c.strip() for c in l.strip('|').split('|')]
            for l in DOCUMENT.read_text().splitlines() if l.startswith('| ')][2:]


def test_isolation_tableau():
    tableau = lignes()
    noms = [r[0] for r in tableau]
    assert set(DIRECTIVES) <= set(noms) and len(noms) == len(set(noms))
    for n, decision, valeur, source, compensation in tableau:
        assert decision in ('conservée', 'retirée', 'adaptée')
        assert valeur and source and compensation
        assert '« ' in source and ' »' in source
    assert next(r for r in tableau if r[0] == 'NoNewPrivileges')[1] == 'retirée'
    texte = DOCUMENT.read_text()
    assert all(m in texte for m in ('SIGTERM', 'SIGKILL', 'Essais réels', 'NoNewPrivs',
                                   'arguments fixes fusionnés', 'première commande réelle', 'non confirmée'))
    # Chaque ligne indécidable doit avoir un essai réel qui la nomme.
    essais = texte.split('## Essais réels', 1)[1]
    for n, _, _, _, compensation in tableau:
        if 'à vérifier sur la cible' in compensation:
            assert n in essais


def normaliser(t):
    t = unicodedata.normalize('NFKC', t)
    t = re.sub('.\x08', '', t)
    t = t.translate(str.maketrans({'‐': '-', '‑': '-', '–': '-', '−': '-', '’': "'", '‘': "'", '`': "'", '“': '"', '”': '"'}))
    # Coupure de mot de nroff en fin de ligne ; les traits d'union ne distinguent pas une citation.
    return re.sub(r'\s+', ' ', t.replace('-\n', '').replace('-', '')).strip()


def test_isolation_citations():
    if not shutil.which('man'):
        pytest.skip('man absent : vérification des citations impossible')
    pages = {}
    for _, _, _, source, _ in lignes():
        m = re.fullmatch(r'([\w.]+)\((\d\w*)\) : « (.+) »', source)
        assert m, source
        page, section, extrait = m.groups()
        if (page, section) not in pages:
            p = subprocess.run(['man', section, page], capture_output=True, text=True,
                               env={**os.environ, 'LC_ALL': 'C', 'MANWIDTH': '120', 'MANPAGER': 'cat'}, timeout=15)
            if p.returncode or not p.stdout.strip():
                pytest.skip(f'page {page}({section}) ou outil de rendu absent : {p.stderr.strip()}')
            pages[page, section] = normaliser(p.stdout)
        assert normaliser(extrait) in pages[page, section], (page, extrait)
