# SPDX-License-Identifier: AGPL-3.0-or-later
# Démarrage de bunkerd sous le socle commun : sous-processus réels, socket de notification
# d'écoute (sd_notify(3)), signaux réels, codes de sysexits.h. Aucun systemd, aucun réseau.
# Dépendances : bibliothèque standard, pytest.
# Suivi des versions
#   0.1.1  2026-11-07  Première version : READY=1, STOPPING=1, 78, 65, 64, --check, --version, arrêt sous charge.
import json
import os
from pathlib import Path
import pwd
import signal
import socket
import subprocess
import sys
import tempfile
import time

import pytest

from server.commun.version import lire_version

RACINE = Path(__file__).resolve().parents[1]


@pytest.fixture
def banc():
    with tempfile.TemporaryDirectory(prefix='paresia-') as nom:
        yield Path(nom)


def configuration(d):
    compte = pwd.getpwuid(os.getuid()).pw_name
    (d / 'home').mkdir(mode=0o700)
    sections = {
        'bunkerd': {'relay_identity': '(none)'},
        'bunkerd.etat': {'home': d / 'home'},
        'bunkerd.outils': {'nak': '/bin/true', 'setfacl': '/bin/true'},
        'bunkerd.controle': {'socket': d / 'c.sock'},
        'bunkerd.web': {'socket': '(none)', 'user': compte},
        'bunkerd.admin': {'socket': d / 'a.sock', 'romulus_user': compte},
    }
    fichier = d / 'paresia.conf'
    fichier.write_text(''.join(f'[{nom}]\n' + ''.join(f'{k} = {v}\n' for k, v in valeurs.items())
                               for nom, valeurs in sections.items()), encoding='utf-8')
    fichier.chmod(0o600)
    return fichier


def lancer(arguments, env_ajout=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('PARESIA_', 'NOTIFY_', 'JOURNAL_'))}
    env.update(env_ajout or {})
    env['PYTHONPATH'] = str(RACINE)
    return subprocess.Popen([sys.executable, '-P', '-s', '-B', '-m', 'server.bunkerd', *arguments],
                            cwd=RACINE, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def test_pret_puis_arret(banc):
    fichier = configuration(banc)
    adresse = str(banc / 'notify')
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as ecoute:
        ecoute.bind(adresse)
        ecoute.settimeout(15)
        processus = lancer(['--config', str(fichier)], {'NOTIFY_SOCKET': adresse})
        try:
            assert b'READY=1' in ecoute.recv(8192)
            assert (banc / 'c.sock').exists()
            processus.send_signal(signal.SIGTERM)
            assert ecoute.recv(8192) == b'STOPPING=1'
            assert processus.wait(timeout=20) == 0
            sortie = processus.stdout.read()
            assert '"event":"bunkerd_ready"' in sortie and '"event":"bunkerd_stopped"' in sortie
        except (TimeoutError, subprocess.TimeoutExpired):
            processus.kill()
            sortie, erreur = processus.communicate(timeout=5)
            pytest.fail(f'stdout={sortie!r}, stderr={erreur!r}')
        finally:
            if processus.poll() is None:
                processus.kill()
            processus.communicate()


def test_arret_sous_charge(banc):
    """Huit démarrages parallèles : chaque SIGTERM arrête le démon sans attente indéfinie."""
    lots = []
    for i in range(8):
        d = banc / str(i)
        d.mkdir()
        lots.append((d, configuration(d)))
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as ecoute:
        processus = []
        for d, fichier in lots:
            adresse = str(d / 'n')
            ecoute = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            ecoute.bind(adresse)
            ecoute.settimeout(30)
            processus.append((lancer(['--config', str(fichier)], {'NOTIFY_SOCKET': adresse}), ecoute))
        try:
            for p, e in processus:
                assert b'READY=1' in e.recv(8192)
            for p, _ in processus:
                p.send_signal(signal.SIGTERM)
            debut = time.monotonic()
            assert [p.wait(timeout=30) for p, _ in processus] == [0] * 8
            assert time.monotonic() - debut < 30
        finally:
            for p, e in processus:
                if p.poll() is None:
                    p.kill()
                p.communicate()
                e.close()


def test_configuration_invalide(banc):
    fichier = banc / 'vide.conf'
    fichier.write_text('[inconnue.section]\nx = 1\n', encoding='utf-8')
    fichier.chmod(0o600)
    processus = lancer(['--config', str(fichier)])
    sortie, _ = processus.communicate(timeout=20)
    assert processus.returncode == 78
    assert '"event":"startup_failed"' in sortie


def test_etat_illisible(banc):
    fichier = configuration(banc)
    (banc / 'home' / 'bunker.json').write_bytes(b'[]')
    processus = lancer(['--config', str(fichier)])
    sortie, erreur = processus.communicate(timeout=20)
    assert processus.returncode == 65
    assert json.loads(sortie.splitlines()[0])['event'] == 'state_unreadable'
    assert erreur.strip()
    assert not (banc / 'c.sock').exists()


def test_check_sans_socket(banc):
    fichier = configuration(banc)
    avant = set(os.listdir(banc))
    processus = lancer(['--check', '--config', str(fichier)])
    processus.communicate(timeout=20)
    assert processus.returncode == 0
    assert set(os.listdir(banc)) == avant


def test_option_inconnue():
    processus = lancer(['--inconnue'])
    _, erreur = processus.communicate(timeout=20)
    assert processus.returncode == 64
    assert erreur


def test_version():
    processus = lancer(['--version'])
    sortie, _ = processus.communicate(timeout=20)
    assert processus.returncode == 0
    assert lire_version() in sortie
