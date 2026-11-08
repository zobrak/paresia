# SPDX-License-Identifier: AGPL-3.0-or-later
# Démarrage des cinq démons à classe sous le socle commun : sous-processus réels, socket de
# notification d'écoute (sd_notify(3)), signal réel, codes de sysexits.h. Aucun systemd, aucun réseau.
# Dépendances : bibliothèque standard, pytest.
# Suivi des versions
#   0.1.8  2026-11-07  Romulus démarré sans section de service (les sections viennent des déclarations installées).
#   0.1.5  2026-11-07  Sorties du démon conservées en cas d'expiration du test de prêt.
#   0.1.5  2026-11-07  Version installée, environnement d'unité et sockets prêtes.
#   0.1.1  2026-11-07  Première version : READY=1, STOPPING=1, 78, 64, --check, --version.
import os
import json
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile

import pytest

from server.commun.version import lire_version

RACINE = Path(__file__).resolve().parents[1]
DEMONS = ('romulus', 'pollux', 'castor', 'remus', 'nisaba')


def configuration(demon, d):
    """Configuration minimale valide ; sockets dans d (chemins AF_UNIX courts), compte courant."""
    uid, gid = os.getuid(), os.getgid()
    s = lambda nom: str(d / nom)
    sections = {
        'romulus': {'presence': {'socket': s('rp.sock'), 'uid_pollux': uid, 'gid': gid},
                    'http': {'socket': s('rh.sock'), 'uid_lighttpd': uid, 'gid': gid,
                             'client_ip_header': 'X-Client-IP', 'fallback_ip': '192.0.2.1'}},
        'pollux': {'signature': {'authorized_keys': s('cles'), 'namespace': 'paresia-presence'},
                   'sessions': {'socket': s('ps.sock'), 'uid': uid, 'gid': gid},
                   'relay': {'socket': s('pr.sock'), 'uid': uid, 'gid': gid},
                   'romulus': {'socket': s('rp.sock'), 'uid': uid},
                   'castor': {'socket': s('cs.sock'), 'uid': uid}},
        'castor': {'tunnel': {'socket': s('ct.sock'), 'uid': uid, 'gid': gid},
                   'state': {'socket': s('cs.sock'), 'uid': uid, 'gid': gid}},
        'remus': {'server': {'socket': s('re.sock'), 'uid': uid, 'gid': gid},
                  'castor': {'socket': s('cs.sock'), 'uid': uid},
                  'executor': {'sudo': '/usr/bin/sudo', 'docker': '/usr/bin/docker'}},
        'nisaba': {'socket': {'socket': s('ns.sock'), 'uid_romulus': uid, 'gid': gid},
                   'ctl': {'socket': s('nc.sock'), 'uid': 0},
                   'journal': {'dossier': s('legal'), 'compte_acl': 'paresia-romulus',
                               'lsattr': '/usr/bin/lsattr', 'chattr': '/usr/bin/chattr'},
                   'horaire': {'scellement': '03:23', 'purge': '03:47'},
                   'etat': {'dossier': s('etat')},
                   'source': {'source': 'archive@backup.example.org:/journal/', 'cle_ssh': s('cle'),
                              'rsync': '/usr/bin/rsync', 'ssh': '/usr/bin/ssh'},
                   'ots': {'ots': '/usr/bin/ots'},
                   'droits': {'chattr': '/usr/bin/chattr', 'setfacl': '/usr/bin/setfacl',
                              'getfacl': '/usr/bin/getfacl', 'compte': 'paresia-romulus'}},
    }[demon]
    texte = ''.join(f'[{demon}.{domaine}]\n' + ''.join(f'{cle} = {valeur}\n' for cle, valeur in valeurs.items())
                    for domaine, valeurs in sections.items())
    fichier = d / 'paresia.conf'
    fichier.write_text(texte, encoding='utf-8')
    fichier.chmod(0o600)
    (d / 'etat').mkdir(mode=0o700)
    return fichier


@pytest.fixture
def banc():
    # Les chemins AF_UNIX tiennent en 108 octets : dossier court hors du worktree.
    with tempfile.TemporaryDirectory(prefix='paresia-') as nom:
        d = Path(nom)
        yield d


def lancer(demon, arguments, env_ajout=None, *, racine=RACINE, stdout=subprocess.PIPE):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('PARESIA_', 'NOTIFY_', 'JOURNAL_'))}
    env.update(env_ajout or {})
    env['PYTHONPATH'] = str(racine)
    return subprocess.Popen([sys.executable, '-P', '-s', '-B', '-m', 'server.' + demon, *arguments],
                            cwd=racine, env=env, stdout=stdout, stderr=subprocess.PIPE, text=True)


@pytest.mark.parametrize('demon', DEMONS)
def test_pret_puis_arret(demon, banc):
    fichier = configuration(demon, banc)
    adresse = str(banc / 'notify')
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as ecoute:
        ecoute.bind(adresse)
        ecoute.settimeout(10)
        processus = lancer(demon, ['--config', str(fichier)], {'NOTIFY_SOCKET': adresse})
        try:
            recu = ecoute.recv(8192)
            assert b'READY=1' in recu
            # Un seul connect, sans attente préalable ni nouvelle tentative.
            service = {'romulus': 'rh.sock', 'pollux': 'ps.sock', 'castor': 'cs.sock',
                       'remus': 're.sock', 'nisaba': 'ns.sock'}[demon]
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(2)
                client.connect(str(banc / service))
            processus.send_signal(signal.SIGTERM)
            assert ecoute.recv(8192) == b'STOPPING=1'
            assert processus.wait(timeout=20) == 0
        except (TimeoutError, subprocess.TimeoutExpired):
            processus.kill()
            sortie, erreur = processus.communicate(timeout=5)
            pytest.fail(f'demon={demon}, stdout={sortie!r}, stderr={erreur!r}')
        finally:
            if processus.poll() is None:
                processus.kill()
            processus.communicate()


def test_castor_version_installee(banc):
    """Reproduit l'image incomplète puis le démarrage avec VERSION.

    Le compte et les groupes sont ceux du lanceur non privilégié ; les sockets
    lui appartiennent. Le contrôle des COPY dans test_banc_ci échoue si la
    correction des images est retirée ; la première phase ici garde le code 70
    comme témoin du défaut, même après correction.
    """
    installe = banc / 'code'
    shutil.copytree(RACINE / 'server', installe / 'server',
                    ignore=shutil.ignore_patterns('__pycache__', 'conf'))
    execution = banc / 'run'
    execution.mkdir(mode=0o711)
    execution.chmod(0o711)
    fichier = configuration('castor', execution)
    adresse = str(banc / 'notify')
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as ecoute, tempfile.TemporaryFile() as journal:
        ecoute.bind(adresse)
        ecoute.settimeout(10)
        st = os.fstat(journal.fileno())
        env = {'NOTIFY_SOCKET': adresse, 'JOURNAL_STREAM': f'{st.st_dev}:{st.st_ino}',
               'RUNTIME_DIRECTORY': str(execution), 'LANG': 'C.UTF-8'}
        arguments = ['--config', str(fichier)]
        processus = lancer('castor', arguments, env, racine=installe, stdout=journal)
        try:
            processus.communicate(timeout=10)
            assert processus.returncode == 70
        finally:
            if processus.poll() is None:
                processus.kill()
            processus.communicate(timeout=5)
        journal.seek(0)
        lignes = journal.read().decode().splitlines()
        assert len(lignes) == 1 and lignes[0].startswith('<3>')
        evenement = json.loads(lignes[0][3:])
        assert {k: v for k, v in evenement.items() if k not in ('ts', 'level', 'component')} == {
            'event': 'startup_failed', 'cause': 'internal_error',
            'section': None, 'option': None, 'errno': None}
        assert not list(execution.glob('*.sock'))
        shutil.copyfile(RACINE / 'VERSION', installe / 'VERSION')
        processus = lancer('castor', arguments, env, racine=installe, stdout=journal)
        try:
            assert b'READY=1' in ecoute.recv(8192).splitlines()
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(2)
                client.connect(str(execution / 'cs.sock'))
            processus.send_signal(signal.SIGTERM)
            assert ecoute.recv(8192) == b'STOPPING=1'
            assert processus.wait(timeout=10) == 0
        finally:
            if processus.poll() is None:
                processus.kill()
            processus.communicate(timeout=5)


@pytest.mark.parametrize('demon', DEMONS)
def test_configuration_invalide(demon, banc):
    fichier = banc / 'vide.conf'
    fichier.write_text('[inconnue.section]\nx = 1\n', encoding='utf-8')
    fichier.chmod(0o600)
    processus = lancer(demon, ['--config', str(fichier)])
    sortie, _ = processus.communicate(timeout=20)
    assert processus.returncode == 78
    assert '"event":"startup_failed"' in sortie


@pytest.mark.parametrize('demon', DEMONS)
def test_check_sans_socket(demon, banc):
    fichier = configuration(demon, banc)
    avant = set(os.listdir(banc))
    processus = lancer(demon, ['--check', '--config', str(fichier)])
    processus.communicate(timeout=20)
    assert processus.returncode == 0
    assert set(os.listdir(banc)) == avant
    assert not [n for n in os.listdir(banc) if n.endswith('.sock')]


@pytest.mark.parametrize('demon', DEMONS)
def test_option_inconnue(demon):
    processus = lancer(demon, ['--inconnue'])
    _, erreur = processus.communicate(timeout=20)
    assert processus.returncode == 64
    assert erreur


@pytest.mark.parametrize('demon', DEMONS)
def test_version(demon):
    processus = lancer(demon, ['--version'])
    sortie, _ = processus.communicate(timeout=20)
    assert processus.returncode == 0
    assert lire_version() in sortie
