# SPDX-License-Identifier: AGPL-3.0-or-later
# Suivi des versions : 3.0.0-alpha — 2026-11-06, tests T023 ; sauvegardes par l'outil (C36, D83, D103).
#   0.1.0  2026-11-07  Comptes hors /home et paramètres sans invite.
import configparser
import os
from pathlib import Path
import shutil
import subprocess

import pytest

DEPLOY = Path(__file__).resolve().parents[1] / 'deploy/backend-relais'
NFT = DEPLOY / 'etc/nftables/paresia-relais.nft'
UNITE = DEPLOY / 'etc/systemd/system/paresia-nftables.service'


def test_nftables_regle():
    lignes = [l.strip() for l in NFT.read_text().splitlines() if l.strip() and not l.startswith('#')]
    assert lignes == ['add table inet paresia_relais', 'flush table inet paresia_relais',
                      'table inet paresia_relais {', 'chain output {',
                      'type filter hook output priority filter; policy accept;',
                      'meta skuid "tunnel" ct state new reject', '}', '}']
    assert 'flush ruleset' not in NFT.read_text()


def test_nftables_verification():
    outil = shutil.which('nft', path='/usr/bin:/usr/sbin:/bin:/sbin')
    if not outil:
        pytest.skip('nft absent')
    try:
        p = subprocess.run([outil, '-c', '-f', str(NFT)], capture_output=True, text=True, timeout=10)
    except PermissionError:
        pytest.skip('nft non lançable (permissions du bac à sable)')
    if p.returncode and any(m in p.stderr.lower() for m in ('operation not permitted', 'permission denied',
                                                           'netlink', 'could not parse userid')):
        pytest.skip('nft -c : droits netlink insuffisants ou compte tunnel absent sur ce poste : ' + p.stderr.strip())
    assert p.returncode == 0, p.stderr


def test_nftables_unite():
    # ConfigParser strict refuse tout doublon ; cette unité n'a aucune clé répétée.
    c = configparser.ConfigParser(interpolation=None, strict=True)
    c.optionxform = str
    c.read(UNITE)
    assert dict(c['Service']) == {
        'Type': 'oneshot', 'RemainAfterExit': 'yes',
        'ExecStart': '/usr/sbin/nft -f /etc/nftables/paresia-relais.nft',
        'ExecStop': '-/usr/sbin/nft delete table inet paresia_relais',
        'CapabilityBoundingSet': 'CAP_NET_ADMIN'}
    assert c['Unit']['Wants'] == 'network-pre.target'
    assert c['Unit']['DefaultDependencies'] == 'no'
    assert c['Unit']['Conflicts'] == 'shutdown.target'
    assert sorted(c['Unit']['Before'].split()) == ['network-pre.target', 'shutdown.target']
    assert c['Install']['WantedBy'] == 'multi-user.target'
    outil = shutil.which('systemd-analyze')
    if not outil:
        pytest.skip('systemd-analyze absent')
    try:
        p = subprocess.run([outil, 'verify', str(UNITE)], capture_output=True, text=True, timeout=10,
                           env={**os.environ, 'LC_ALL': 'C'})
    except PermissionError:
        pytest.skip('systemd-analyze non lançable dans le bac à sable')
    if p.returncode and 'SO_PASSCRED failed: Operation not permitted' in p.stderr:
        pytest.skip('systemd-analyze verify : SO_PASSCRED interdit par le bac à sable')
    assert p.returncode == 0, p.stderr


SCRIPT = DEPLOY / 'installer-backend-relais.sh'


def test_procedure_nftables():
    t = SCRIPT.read_text()
    assert t.index('nft -c -f') < t.index('systemctl start paresia-nftables.service')
    assert t.index('runuser -u tunnel --') < t.index('systemctl enable paresia-nftables.service')
    for m in ('nft list ruleset | releve nft-avant', 'nft list ruleset | releve nft-apres',
              'retrouver --releve nft-avant', 'retrouver --releve nft-apres',
              'nft list table inet paresia_relais', 'nft delete table inet paresia_relais',
              'ConnectionRefusedError', 'runuser -u nobody --', 'Docker'):
        assert m in t
    # comparaison sur deux sorties normalisées : compteurs neutralisés, toute règle retirée est comptée
    ligne = next(l for l in t.splitlines() if 'retires=$(' in l)
    assert ligne.count("sed -E 's/counter packets [0-9]+ bytes [0-9]+/counter/'") == 2
    assert 'diff -u <(' in ligne and '"$avant"' in ligne and '"$apres"' in ligne
    assert "grep -c -E '^-[^-]'" in ligne


def test_procedure_essai_tcp():
    t = SCRIPT.read_text()
    essai = t[t.index('essai_tcp_local() {'):t.index('wait "$pid"')]
    assert 'localhost' not in essai
    assert essai.count('127.0.0.1') == 3
    assert essai.index('ss -H -ltn') < essai.index('runuser -u tunnel')
    assert 'PORT_ESSAI="${PORT_ESSAI:-49152}"' in t       # défaut posé avant le contrôle de la plage


def test_unite_arret_propre():
    texte = UNITE.read_text()
    for citation in ('systemd.special(7)', 'systemd.unit(5)', 'systemd.service(5)'):
        assert citation in texte
