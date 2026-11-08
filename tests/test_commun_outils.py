# SPDX-License-Identifier: AGPL-3.0-or-later
# Outils en ligne de commande sous le socle commun : --help, --version, codes conservés,
# journal sur la sortie d'erreur, aucune écriture de pollux-session sur sa sortie standard.
# Dépendances : bibliothèque standard, pytest.
# Suivi des versions
#   0.1.1  2026-11-07  Première version.
import os
from pathlib import Path
import subprocess
import sys

import pytest

from server.commun.version import lire_version

RACINE = Path(__file__).resolve().parents[1]
OUTILS = {'sauvegarde': 'server.sauvegarde', 'nisaba-ctl': 'server.nisaba.ctl'}


def lancer(module, arguments, env_ajout=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('PARESIA_', 'NOTIFY_', 'JOURNAL_'))}
    env.update(env_ajout or {})
    env['PYTHONPATH'] = str(RACINE)
    return subprocess.run([sys.executable, '-P', '-s', '-B', '-m', module, *arguments], cwd=RACINE,
                          env=env, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)


@pytest.mark.parametrize('outil', OUTILS)
def test_help_et_version(outil):
    aide = lancer(OUTILS[outil], ['--help'])
    assert aide.returncode == 0 and outil in aide.stdout and aide.stderr == ''
    version = lancer(OUTILS[outil], ['--version'])
    assert version.returncode == 0 and lire_version() in version.stdout and version.stderr == ''


def test_codes_conserves():
    assert lancer(OUTILS['sauvegarde'], ['--inconnue']).returncode == 2
    assert lancer(OUTILS['sauvegarde'], []).returncode == 2
    assert lancer(OUTILS['nisaba-ctl'], ['--inconnue']).returncode == 2
    assert lancer(OUTILS['nisaba-ctl'], []).returncode == 2


def test_aucun_prefixe_hors_flux_du_journal(tmp_path):
    fichier = tmp_path / 'vide.conf'
    fichier.write_text('[inconnue.section]\nx = 1\n', encoding='utf-8')
    fichier.chmod(0o600)
    for outil, arguments in (('sauvegarde', ['--config', str(fichier), 'lister']),
                             ('nisaba-ctl', ['--config', str(fichier), 'status'])):
        resultat = lancer(OUTILS[outil], arguments, {'JOURNAL_STREAM': '1:1'})
        assert resultat.returncode != 0
        assert '<' not in resultat.stdout[:1] and not resultat.stderr.startswith('<')


def test_pollux_session_sans_ecriture_stdout():
    resultat = lancer('server.pollux.session', [], {'PARESIA_POLLUX_SESSION_X': '1'})
    assert resultat.returncode == 3
    assert resultat.stdout == ''
