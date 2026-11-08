# Tests de l'unité du tunnel paresia-tunnel.service (D61, D62) : forme, isolation,
# dossiers tmpfiles, absence de donnée en dur, directives connues des pages de manuel.
# Les tests communs aux trois unités sont dans test_installation_relais_unites.py ; ce fichier
# vérifie l'unité du tunnel seule, indépendamment de la procédure de backend-relais.
# Hors ligne : aucun root, aucun systemd actif. Dépendances : bibliothèque standard, pytest.
# SPDX-License-Identifier: AGPL-3.0-or-later
# Suivi des versions
#   0.1.1  2026-11-07  Dossiers tmpfiles, parent réservé à root et écriture limitée aux deux sous-dossiers.
#   3.0.0-alpha.42  2026-11-07  Exception de lecture propre à Pollux, absente du tunnel.
#   3.0.0-alpha.34  2026-11-06  Première version (T024).
#   0.1.0  2026-11-07  Comptes hors /home et paramètres sans invite.
import re
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
UNITE = RACINE / 'deploy' / 'backend-admin' / 'etc' / 'systemd' / 'system' / 'paresia-tunnel.service'
POLLUX = UNITE.with_name('pollux.service')
TMPFILES = RACINE / 'deploy/backend-admin/etc/tmpfiles.d/paresia-tunnel.conf'


def cles(chemin):
    return [tuple(l.strip().split('=', 1)) for l in chemin.read_text(encoding='utf-8').splitlines()
            if '=' in l and not l.strip().startswith(('#', '['))]


def test_tunnel_isolation_comme_pollux():
    tunnel, pollux = dict(cles(UNITE)), dict(cles(POLLUX))
    for cle in ('LimitCORE', 'NoNewPrivileges', 'CapabilityBoundingSet', 'AmbientCapabilities', 'ProtectSystem',
                'PrivateTmp', 'PrivateDevices', 'ProtectProc', 'RestrictNamespaces',
                'SystemCallFilter', 'SystemCallArchitectures', 'LockPersonality', 'RestrictSUIDSGID'):
        assert tunnel[cle] == pollux[cle], cle
    assert tunnel['RestrictAddressFamilies'] == 'AF_UNIX AF_INET AF_INET6'
    assert tunnel['ProtectHome'] == 'yes' and pollux['ProtectHome'] == 'yes'
    assert 'BindReadOnlyPaths' not in tunnel
    assert 'BindReadOnlyPaths' not in pollux
    assert tunnel['ProtectSystem'] == 'strict'
    assert [v for k, v in cles(UNITE) if k == 'ReadWritePaths'] == [
        '/run/paresia-tunnel/romulus /run/paresia-tunnel/pollux']


def test_tunnel_dossiers_independants_du_service():
    texte = UNITE.read_text(encoding='utf-8')
    assert not re.search(r'setfacl|RuntimeDirectory|\bACL\b', texte, re.I)
    assert not any(k in ('ExecStartPre', 'ExecStartPost') for k, _ in cles(UNITE))
    assert len(re.findall(r'(?m)^ExecStart=', texte)) == 1
    assert dict(cles(UNITE))['Type'] == 'simple'
    assert dict(cles(UNITE))['User'] == 'paresia-tunnel'
    assert dict(cles(UNITE))['Group'] == 'paresia-tunnel'
    assert dict(cles(UNITE))['Restart'] == 'always'
    assert dict(cles(UNITE))['RestartSec'] == '5'


def test_tunnel_tmpfiles_modes_et_groupes():
    texte = TMPFILES.read_text(encoding='utf-8')
    lignes = [l.split() for l in texte.splitlines() if l.strip() and not l.lstrip().startswith('#')]
    assert lignes == [
        ['d', '/run/paresia-tunnel', '0711', 'root', 'root', '-', '-'],
        ['d', '/run/paresia-tunnel/romulus', '0710', 'paresia-tunnel', 'paresia-romulus', '-', '-'],
        ['d', '/run/paresia-tunnel/pollux', '0710', 'paresia-tunnel', 'paresia-pollux', '-', '-'],
    ]
    assert 'SPDX-License-Identifier: AGPL-3.0-or-later' in texte
