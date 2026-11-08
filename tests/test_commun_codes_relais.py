# SPDX-License-Identifier: AGPL-3.0-or-later
# Suivi des versions
#   3.0.0-alpha  2026-11-06  Clés backup_* du catalogue admises (outil de sauvegarde, C36).
#   3.0.0-alpha.39  2026-11-06  T036 : balayage des fichiers non ignorés par Git.
#   3.0.0-alpha.32  2026-11-06  T007 : admission des clés de démarrage dans les catalogues.
#   3.0.0-alpha.29  2026-11-06  Codes du relais et catalogues BCP 47 (T027).
import json
import socket
import subprocess
from pathlib import Path

import pytest

from server.commun.client import Connexion
from server.commun.jumeaux import CODES_ERREUR, DETAILS, encoder, reponse
from test_jumeaux_transport import SocketMemoire, requete

RACINE = Path(__file__).resolve().parents[1]
CODES = {'command_failed': 'Command failed', 'command_timeout': 'Command timed out',
         'command_busy': 'Too many concurrent commands'}


def test_codes_relais_details():
    for code, detail in CODES.items():
        assert code in CODES_ERREUR and DETAILS[code] == detail
        assert reponse(requete()['id'], code=code) == {
            'id': requete()['id'], 'ok': False, 'error': {'code': code, 'detail': detail}}


@pytest.mark.parametrize('code', CODES)
@pytest.mark.parametrize('flux', [False, True])
def test_codes_relais_client(monkeypatch, code, flux):
    attendu = reponse(requete()['id'], code=code)
    entree = dict(attendu, error={'code': code, 'detail': 'detail distant ignore'})
    sock = SocketMemoire(encoder(entree))
    monkeypatch.setattr(socket, 'socket', lambda *_: sock)
    with Connexion('transport-memoire') as client:
        if flux:
            assert list(client.appeler_flux(requete())) == [attendu]
        else:
            assert client.appeler(requete()) == attendu


def test_not_available_present():
    assert DETAILS['not_available'] == 'Operation unavailable'
    assert 'not_available' in CODES_ERREUR


def test_codes_relais_catalogues():
    fr = json.loads((RACINE / 'i18n/fr-FR.json').read_text())
    en = json.loads((RACINE / 'i18n/en-US.json').read_text())
    assert fr.keys() == en.keys()
    assert DETAILS.keys() <= fr.keys()
    assert {code: en[code] for code in CODES} == CODES
    assert [fr[code] for code in CODES] == [
        'Commande en échec', 'Délai de la commande dépassé', 'Trop de commandes simultanées']


def test_catalogues_bcp47():
    for langue in ('fr-FR', 'en-US'):
        assert json.loads((RACINE / 'i18n' / (langue + '.json')).read_text())
        assert not (RACINE / 'i18n' / (langue.replace('-', '_') + '.json')).exists()


def test_aucun_nom_posix_residuel():
    anciens = [a + '_' + b for a, b in [('fr', 'FR'), ('en', 'US')]]
    dossiers = ('server', 'tests', 'tools', 'deploy', 'i18n')
    try:
        resultat = subprocess.run(
            ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
            cwd=RACINE, check=True, capture_output=True)
        candidats = [RACINE / nom for nom in resultat.stdout.decode(
            'utf-8', errors='surrogateescape').split('\0') if nom]
        candidats = [p for p in candidats if p.relative_to(RACINE).parts[0] in dossiers]
    except (FileNotFoundError, subprocess.CalledProcessError):
        candidats = [p for dossier in dossiers for p in (RACINE / dossier).rglob('*')
                     if not {'.venv', '.pytest_cache', '.worktrees'}.intersection(
                         p.relative_to(RACINE).parts)]
    fichiers = [p for p in candidats if p.is_file()
                and '__pycache__' not in p.parts and p.suffix not in ('.key', '.pyc')
                and p.name != '.env' and 'secrets' not in p.parts]
    fichiers += [p for p in RACINE.iterdir() if p.is_file()
                 and p.name not in {'AGENTS.md', 'CHANGELOG.md', 'TODO.md', 'README.md', '.env'}]
    for p in fichiers:
        assert not any(nom.encode() in p.read_bytes() for nom in anciens), p.relative_to(RACINE)


def test_socle_sans_execution_ni_reseau_ip():
    for p in (RACINE / 'server/commun').glob('*.py'):
        assert not any(motif in p.read_text() for motif in ('AF_INET', 'shell=True', 'eval(', 'exec('))
