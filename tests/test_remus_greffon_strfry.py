# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests du greffon paresia-yin-strfry : manifestes, scripts sur un faux système, interdits.
# Suivi des versions
#   0.1.14  2026-11-08  Greffon de base : état, arbres negentropy, redémarrage (D148, D150, D154, D167).
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tomllib

import pytest

from server.commun import plugins
from server.commun.config import lire
from server.commun.sortie import interpreter_sortie
from server.remus import SCHEMA
from server.remus.sudoers import generer_sudoers
from server.remus.fonctions import regles_sudoers

RACINE = Path(__file__).resolve().parents[1]
LIVRE = RACINE / 'deploy/backend-relais/usr/local/lib/paresia/remus/fonctions'
SERVICES = RACINE / 'deploy/backend-admin/usr/local/lib/paresia/romulus/services'
NOMS = ('strfry_etat', 'strfry_arbres', 'strfry_redemarrer')
ATTENDU = {
    'strfry_etat': ('relay/state/status', ['exec', 'strfry', '/app/strfry', 'info']),
    'strfry_arbres': ('relay/sync/trees', ['exec', 'strfry', '/app/strfry', 'negentropy', 'list']),
    'strfry_redemarrer': ('relay/container/restart', ['restart', 'strfry']),
}
MOI = os.geteuid()


@pytest.fixture
def livre(tmp_path):
    tmp_path.chmod(0o755)
    cible = tmp_path / 'livre'
    shutil.copytree(LIVRE, cible)
    cible.chmod(0o755)
    for fichier in cible.iterdir():
        fichier.chmod(0o644 if fichier.suffix == '.toml' else 0o755)
    (tmp_path / 'local').mkdir(mode=0o755)
    return tmp_path


def charger(racine):
    return plugins.charger(
        'yin', 'relay', racine / 'livre', racine / 'local', codes_connus={'command_failed'},
        proprietaires={MOI}, racine_confiance=racine)


def test_manifestes_charges(livre):
    c = charger(livre)
    assert not c.rejets
    assert sorted(c.fonctions) == sorted(a for a, _ in ATTENDU.values())
    produits = {f.produit['nom'] + f.produit['version'] for f in c.fonctions.values()}
    assert produits == {'strfry4cd3cf6'}
    assert {f.greffon for f in c.fonctions.values()} == {'paresia-yin-strfry'}
    assert len(c.fonctions) == 3
    g = c.greffons['paresia-yin-strfry']
    assert g['compatible_yang'] == ('paresia-yang-strfry',)
    assert (SERVICES / 'paresia-yang-strfry.toml').is_file()


def test_configuration_d_exemple_inchangee(livre):
    f = livre / 'c.conf'
    f.write_text((RACINE / 'server/conf/paresia-relais.conf').read_text())
    f.chmod(0o644)
    conf = lire('remus', SCHEMA, argv=[], environ={'PARESIA_REMUS_CONFIG': str(f)},
                journal=True, metriques=True)
    conf['plugins'].update(fonctions=str(livre / 'livre'), locales=str(livre / 'local'))
    regles = regles_sudoers(conf, proprietaires={MOI}, racine_confiance=livre)
    texte = generer_sudoers(regles, 'chef')
    lignes = [l for l in texte.splitlines() if l and not l.startswith('#')]
    docker = conf['executor']['docker']
    assert sorted(lignes) == sorted([
        f'chef ALL=(root) NOPASSWD: {docker} exec strfry /app/strfry info',
        f'chef ALL=(root) NOPASSWD: {docker} exec strfry /app/strfry negentropy list',
        f'chef ALL=(root) NOPASSWD: {docker} restart strfry'])


def test_interdits():
    for nom in NOMS:
        brut = tomllib.loads((LIVRE / (nom + '.toml')).read_text())
        for bloc in brut['commandes_privilegiees']:
            for element in bloc['arguments']:
                assert not element.startswith('-')
                assert element not in {'add', 'build', 'stop', 'start', 'compose', 'run', 'kill',
                                       'rm', 'cp', 'inspect', 'logs', 'stats'}
    sudoers = (RACINE / 'deploy/backend-relais/etc/sudoers.d/paresia-remus').read_text()
    assert not re.search(r'\b(add|build|stop|start|compose|run|kill|rm|cp|inspect|logs|stats)\b',
                         sudoers.split('NOPASSWD', 1)[1])
    for chemin in (RACINE / 'deploy').rglob('*'):
        assert chemin.name.lower() != 'dockerfile'


def test_aucun_nom_de_produit_dans_le_code():
    for chemin in list((RACINE / 'server/remus').glob('*.py')) + [RACINE / 'server/commun/plugins.py']:
        assert not re.search(r'strfry|bunker|nisaba', chemin.read_text(), re.I), chemin


def test_scripts_sans_sudo_ni_interpreteur():
    for nom in NOMS:
        t = (LIVRE / nom).read_text()
        assert 'shell=True' not in t and 'os.system' not in t and 'eval(' not in t
        assert 'PARESIA_PRIVILEGE' in t and "'sudo'" not in t
        assert not re.search(r"['\"]/usr/bin/(sudo|docker)['\"]", t)


@pytest.fixture
def faux(tmp_path):
    """Faux sudo : consigne son argv ; le faux docker ne sert qu'à nommer le préfixe."""
    trace = tmp_path / 'trace'
    sortie = tmp_path / 'sortie'
    code = tmp_path / 'code'
    sudo = tmp_path / 'sudo'
    sudo.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" > {trace}\ncat {sortie}\n'
                    f'exit "$(cat {code})"\n')
    sudo.chmod(0o755)
    code.write_text('0')
    return {'trace': trace, 'sortie': sortie, 'code': code,
            'prefixe': json.dumps([str(sudo), '-n', '--', '/opt/outils/docker'])}


def lancer(nom, faux, sortie='', code=0, entree='{}', prefixe=True):
    Path(faux['sortie']).write_text(sortie)
    Path(faux['code']).write_text(str(code))
    env = {'LC_ALL': 'C'}
    if prefixe:
        env['PARESIA_PRIVILEGE'] = faux['prefixe']
    p = subprocess.run([str(LIVRE / nom)], input=entree.encode(), capture_output=True,
                       env=env, timeout=30)
    return p


def test_etat(faux):
    p = lancer('strfry_etat', faux, 'DB version: 3\n')
    assert p.returncode == 0 and p.stderr == b''
    assert json.loads(p.stdout) == {'ok': True, 'data': {'db_version': 3}}
    assert faux['trace'].read_text().split('\n')[0] == '-n -- /opt/outils/docker exec strfry /app/strfry info'


@pytest.mark.parametrize('sortie,code', [('autre\n', 0), ('DB version: 3\n', 1), ('', 0),
                                        ('DB version: 3\nDB version: 4\n', 0),
                                        ('DB version: ' + '9' * 40 + '\n', 0),
                                        ('x' * 70000, 0), ('DB version: \x1b3\n', 0)])
def test_etat_echecs(faux, sortie, code):
    p = lancer('strfry_etat', faux, sortie, code)
    assert p.returncode == 1 and p.stderr == b''
    assert json.loads(p.stdout) == {'ok': False, 'error': {'code': 'command_failed'}}


def test_entree_non_vide_et_prefixe_absent(faux):
    for nom in NOMS:
        assert lancer(nom, faux, 'DB version: 3\n', entree='{"a":1}').returncode == 1
        assert lancer(nom, faux, 'DB version: 3\n', prefixe=False).returncode == 1


def test_arbres(faux):
    texte = 'tree abc123\n  filter: {"kinds":[1]}\n  size: 12\n  fingerprint: 00ff\n'
    p = lancer('strfry_arbres', faux, texte)
    assert p.returncode == 0
    d = json.loads(p.stdout)['data']
    assert d['lines'][0] == 'tree abc123' and len(d['lines']) == 4
    assert faux['trace'].read_text().split('\n')[0] == (
        '-n -- /opt/outils/docker exec strfry /app/strfry negentropy list')
    assert json.loads(lancer('strfry_arbres', faux, '').stdout)['data'] == {'lines': []}
    for mauvais in ('n importe quoi\n', 'tree a\n' * 70, 'tree \x1b\n'):
        assert lancer('strfry_arbres', faux, mauvais).returncode == 1


def test_redemarrer(faux):
    p = lancer('strfry_redemarrer', faux, 'strfry\n')
    assert p.returncode == 0 and json.loads(p.stdout)['ok'] is True
    assert faux['trace'].read_text().split('\n')[0] == '-n -- /opt/outils/docker restart strfry'
    assert lancer('strfry_redemarrer', faux, 'autre\n').returncode == 1
    assert lancer('strfry_redemarrer', faux, 'strfry\n', 1).returncode == 1


def test_contrat_de_sortie(livre, faux):
    c = charger(livre)
    for nom, (action, _) in ATTENDU.items():
        f = c.fonctions[action]
        sortie = {'strfry_etat': 'DB version: 3\n', 'strfry_arbres': '',
                  'strfry_redemarrer': 'strfry\n'}[nom]
        p = lancer(nom, faux, sortie)
        r = interpreter_sortie(p.stdout, p.returncode, f.descripteur, sortie_max=f.sortie_max)
        assert r.statut == 'ok' and r.contrat == 'ok'
        assert f.descripteur.delai_s > {'strfry_etat': 20, 'strfry_arbres': 30,
                                        'strfry_redemarrer': 140}[nom]


def test_scripts_executables():
    for nom in NOMS:
        assert (LIVRE / nom).stat().st_mode & stat.S_IXUSR
        assert (LIVRE / nom).read_text().startswith('#!/usr/bin/python3\n# SPDX-License-Identifier')
