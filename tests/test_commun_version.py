# SPDX-License-Identifier: AGPL-3.0-or-later
# Suivi des versions
#   0.1.2  2026-11-07  Source unique, lecture mémorisée et erreurs de démarrage.
#   0.1.1  2026-11-07  Format numérique de la version du produit.
#   0.1.1  2026-11-07  Vérification du socle commun.
from pathlib import Path
import json
import os
import re
import secrets

import pytest

from server.commun.demon import Demon, lancer
from server.commun.version import lire_version

def test_version():
    assert lire_version() == (Path(__file__).resolve().parents[1] / 'VERSION').read_text().strip()


def test_version_format():
    assert re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', lire_version())


@pytest.mark.parametrize('numero', ['1.2.3', '9.10.11'])
def test_version_lue_une_seule_fois(tmp_path, numero):
    fichier = tmp_path / 'VERSION'
    fichier.write_text(numero + '\n', encoding='ascii')
    assert lire_version(tmp_path) == numero
    fichier.unlink()
    assert lire_version(tmp_path) == numero


@pytest.mark.parametrize('contenu', [None, b'', b'1.2', b'1.2.3.4', b'v1.2.3', b'1.2.3-alpha',
                                    b'1.2.3\n\n', b' 1.2.3', b'1.2.3\x00', b'\xff', b'1' * 129])
def test_version_absente_ou_mal_formee(tmp_path, contenu):
    fichier = tmp_path / 'VERSION'
    if contenu is not None:
        fichier.write_bytes(contenu)
    attendu = 'version_unreadable' if contenu is None else 'version_invalid'
    with pytest.raises(RuntimeError, match='^' + attendu + '$'):
        lire_version(tmp_path)
    # Même un échec est mémorisé ; un déploiement corrigé exige un redémarrage.
    fichier.write_text('1.2.3\n', encoding='ascii')
    with pytest.raises(RuntimeError, match='^' + attendu + '$'):
        lire_version(tmp_path)


@pytest.mark.parametrize('absent', [False, True])
@pytest.mark.parametrize('arguments', [[], ['--check'], ['--version']])
def test_version_refusee_au_demarrage(tmp_path, capsys, absent, arguments):
    valeur = secrets.token_urlsafe(24)
    if not absent:
        (tmp_path / 'VERSION').write_text(valeur, encoding='ascii')

    def interdit(*args, **kwargs):
        pytest.fail('démarrage poursuivi malgré la version invalide')

    demon = Demon('test', lambda: lire_version(tmp_path), {}, interdit, interdit)
    assert lancer(demon, arguments, {}) == os.EX_SOFTWARE
    sortie = capsys.readouterr()
    evenement = json.loads(sortie.out)
    assert evenement['event'] == 'startup_failed'
    assert evenement['cause'] == 'internal_error'
    assert valeur not in sortie.out + sortie.err
    assert str(tmp_path) not in sortie.out + sortie.err


def test_version_du_depot_annoncee(capsys):
    demon = Demon('test', lire_version, {}, None)
    assert lancer(demon, ['--version'], {}) == 0
    attendu = (Path(__file__).resolve().parents[1] / 'VERSION').read_text().strip()
    assert capsys.readouterr().out == f'test (Paresia) {attendu}\n'


def test_version_du_depot_dans_les_metriques(tmp_path):
    def configurer(**kwargs):
        return {'metriques': {'actif': True, 'dossier': str(tmp_path)}}

    demon = Demon('test', lire_version, {}, lambda *args: None, configurer)
    assert lancer(demon, [], {}) == 0
    attendu = (Path(__file__).resolve().parents[1] / 'VERSION').read_text().strip()
    assert f'paresia_info{{daemon="test",version="{attendu}"}} 1\n' in (tmp_path / 'test.prom').read_text()
