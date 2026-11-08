# Dossier temporaire propre à chaque exécution de pytest : deux exécutions
# simultanées ne se vident pas l'une l'autre, les dossiers d'exécutions terminées
# sont nettoyés au démarrage suivant, --basetemp en ligne de commande l'emporte.
# Dépendances : pytest ; sous-processus Python isolés (python -I) dans un dossier de
# travail à part, qui reçoit une copie de conftest.py et pytest.ini.
# Suivi des versions
#   3.0.0-alpha.41  2026-11-06  Première version.
import shutil
import subprocess
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

LONG = '''
import time
from pathlib import Path

def test_long(tmp_path, tmp_path_factory):
    (tmp_path / 'marque').write_text('x')
    Path('base-long').write_text(str(tmp_path_factory.getbasetemp()))
    for _ in range(300):
        if Path('stop').exists():
            break
        time.sleep(0.05)
    assert (tmp_path / 'marque').exists()
'''

COURT = '''
from pathlib import Path

def test_court(tmp_path, tmp_path_factory):
    (tmp_path / 'marque').write_text('x')
    Path('base-court').write_text(str(tmp_path_factory.getbasetemp()))
'''


def monter(dossier):
    dossier.mkdir()
    for nom in ('conftest.py', 'pytest.ini'):
        shutil.copy(RACINE / nom, dossier / nom)
    (dossier / 'test_long.py').write_text(LONG)
    (dossier / 'test_court.py').write_text(COURT)


def lancer(dossier, *args):
    return subprocess.Popen(
        [sys.executable, '-I', '-m', 'pytest', '-q', '-p', 'no:cacheprovider', *args],
        cwd=dossier, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def attendre(chemin, delai=30):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if chemin.exists() and chemin.read_text():
            return Path(chemin.read_text())
        time.sleep(0.05)
    raise AssertionError(f'{chemin} absent')


def test_executions_independantes_et_nettoyage(tmp_path):
    w = tmp_path / 'w'
    monter(w)
    long = lancer(w, 'test_long.py')
    base_long = attendre(w / 'base-long')
    court = lancer(w, 'test_court.py')
    sortie_court = court.communicate(timeout=60)[0]
    assert court.returncode == 0, sortie_court
    base_court = Path((w / 'base-court').read_text())
    assert base_court != base_long
    assert base_long.exists()  # le second pytest n'a pas vidé le dossier du premier
    (w / 'stop').write_text('1')
    sortie_long = long.communicate(timeout=60)[0]
    assert long.returncode == 0, sortie_long
    assert base_long.parent == base_court.parent == w / '.pytest_cache'
    assert base_court.exists() and base_long.exists()  # conservés après la fin
    # Une exécution en cours est épargnée par le nettoyage d'une autre.
    (w / 'stop').unlink()
    (w / 'base-long').unlink()
    long2 = lancer(w, 'test_long.py')
    base_long2 = attendre(w / 'base-long')
    assert not base_long.exists() and not base_court.exists()  # terminées : nettoyées
    court2 = lancer(w, 'test_court.py')
    court2.communicate(timeout=60)
    assert court2.returncode == 0 and base_long2.exists()
    (w / 'stop').write_text('1')
    long2.communicate(timeout=60)
    assert long2.returncode == 0


def test_basetemp_ligne_de_commande_prioritaire(tmp_path):
    w = tmp_path / 'w'
    monter(w)
    voulu = tmp_path / 'b'
    court = lancer(w, 'test_court.py', f'--basetemp={voulu}')
    sortie = court.communicate(timeout=60)[0]
    assert court.returncode == 0, sortie
    assert Path((w / 'base-court').read_text()) == voulu.resolve()
    assert not (w / '.pytest_cache').exists() or not list((w / '.pytest_cache').glob('t[0-9]*'))
