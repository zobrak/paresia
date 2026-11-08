# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests de la signature du défi de présence ; dépendances : bibliothèque standard, pytest,
# ssh-keygen, ssh-agent et ssh-add pour l'interopérabilité.
# Suivi des versions
#   0.1.12  2026-11-08  Message, armure, erreurs et interopérabilité avec le serveur.
import base64
import secrets
import shutil
import stat
import subprocess
import time

import pytest

from admin.app import signature
from admin.app.signature import ErreurSignature
from server.commun.sshsig import SignatureInvalide, verifier

DEFI = 'ab' * 32
BLOB = base64.b64encode(b'SSHSIG\x00\x00\x00\x01' + b'x' * 40)


def armure(contenu=BLOB, largeur=70):
    lignes = [contenu[i:i + largeur] for i in range(0, len(contenu), largeur)]
    return b'\n'.join([b'-----BEGIN SSH SIGNATURE-----', *lignes, b'-----END SSH SIGNATURE-----']) + b'\n'


def code(fonction, *args):
    with pytest.raises(ErreurSignature) as e:
        fonction(*args)
    return e.value.code


def test_message():
    defi = secrets.token_hex(32)
    assert signature.message_defi(defi, 'Alice@site') == (
        b'paresia-presence/1\n' + defi.encode('ascii') + b'\nAlice@site\n')


@pytest.mark.parametrize('defi,admin', [
    ('a' * 63, 'x'), ('A' * 64, 'x'), (DEFI + 'a', 'x'), (5, 'x'), (DEFI, ''), (DEFI, 'a b'),
    (DEFI, 'a\n'), (DEFI, 'a' * 65), (DEFI, 'é'), (DEFI, None),
])
def test_message_refuse(defi, admin):
    assert code(signature.message_defi, defi, admin) == 'ui_presence_defi_invalide'


def test_armure_valide():
    assert signature.extraire_signature(armure()) == BLOB.decode()
    assert signature.extraire_signature(armure(largeur=10)) == BLOB.decode()


@pytest.mark.parametrize('enveloppe', [
    b'bruit\n' + armure(),
    armure() + b'bruit\n',
    armure().replace(b'BEGIN', b'BEGINN'),
    armure().replace(b'-----END SSH SIGNATURE-----', b'-----END SSH SIGNATURE----'),
    b'-----BEGIN SSH SIGNATURE-----\n-----END SSH SIGNATURE-----\n',
    armure(b'!!!!'),
    armure(base64.b64encode(b'AUTRE\x00\x00\x00\x01' + b'x' * 40)),
    armure(b'A' * 2049),
    armure(b'A' * 4000),
    'texte',
    None,
])
def test_armure_refusee(enveloppe):
    assert code(signature.extraire_signature, enveloppe) == 'ui_presence_signature_echec'


def test_armure_limite_2048():
    contenu = base64.b64encode(b'SSHSIG\x00\x00\x00\x01' + b'x' * 1526)
    assert len(contenu) == 2048
    assert signature.extraire_signature(armure(contenu)) == contenu.decode()


@pytest.fixture
def agent_present(monkeypatch):
    monkeypatch.setenv('SSH_AUTH_SOCK', '/inexistant/agent')


def test_cle_non_pub(agent_present):
    assert code(signature.signer, DEFI, 'a', signature.ESPACE, '/c/cle', '/usr/bin/ssh-keygen',
                5) == 'ui_presence_signature_echec'


def test_espace_refuse_sans_lancement(agent_present, monkeypatch):
    def interdit(*a, **k):
        raise AssertionError('lancement')
    monkeypatch.setattr(subprocess, 'run', interdit)
    assert code(signature.signer, DEFI, 'a', 'autre', '/c/cle.pub', 'ssh-keygen',
                5) == 'ui_presence_espace_refuse'


def test_agent_absent_sans_lancement(monkeypatch):
    monkeypatch.delenv('SSH_AUTH_SOCK', raising=False)

    def interdit(*a, **k):
        raise AssertionError('lancement')
    monkeypatch.setattr(subprocess, 'run', interdit)
    assert code(signature.signer, DEFI, 'a', signature.ESPACE, '/c/cle.pub', 'ssh-keygen',
                5) == 'ui_presence_signature_echec'


@pytest.mark.parametrize('delai', [0, -1, float('nan'), float('inf'), True, '5', None])
def test_delai_invalide(agent_present, delai):
    assert code(signature.signer, DEFI, 'a', signature.ESPACE, '/c/cle.pub', 'ssh-keygen',
                delai) == 'ui_presence_defi_delai'


def test_defi_invalide_sans_lancement(agent_present):
    assert code(signature.signer, 'x', 'a', signature.ESPACE, '/c/cle.pub', 'ssh-keygen',
                5) == 'ui_presence_defi_invalide'


def test_ssh_keygen_absent(agent_present, tmp_path):
    assert code(signature.signer, DEFI, 'a', signature.ESPACE, '/c/cle.pub',
                str(tmp_path / 'absent'), 5) == 'ui_presence_signature_echec'


def faux_outil(tmp_path, corps):
    chemin = tmp_path / 'faux-ssh-keygen'
    chemin.write_text('#!/bin/sh\n' + corps)
    chemin.chmod(chemin.stat().st_mode | stat.S_IXUSR)
    return str(chemin)


def test_sortie_non_nulle_sans_fuite(agent_present, tmp_path):
    outil = faux_outil(tmp_path, 'echo SECRET-SORTIE\necho SECRET-ERREUR >&2\nexit 3\n')
    with pytest.raises(ErreurSignature) as e:
        signature.signer(DEFI, 'a', signature.ESPACE, '/c/cle.pub', outil, 5)
    assert e.value.code == 'ui_presence_signature_echec'
    assert 'SECRET' not in repr(e.value) + str(e.value)
    assert e.value.__cause__ is None


def test_sortie_hors_armure_sans_fuite(agent_present, tmp_path):
    outil = faux_outil(tmp_path, 'echo SECRET-SORTIE\n')
    with pytest.raises(ErreurSignature) as e:
        signature.signer(DEFI, 'a', signature.ESPACE, '/c/cle.pub', outil, 5)
    assert e.value.code == 'ui_presence_signature_echec'
    assert 'SECRET' not in repr(e.value) + str(e.value)


def test_arguments_et_entree(agent_present, tmp_path):
    sortie = tmp_path / 'vu'
    outil = faux_outil(tmp_path, f'printf "%s\\n" "$@" > {sortie}\ncat > {sortie}.in\n'
                       'printf -- "-----BEGIN SSH SIGNATURE-----\\n'
                       + BLOB.decode() + '\\n-----END SSH SIGNATURE-----\\n"\n')
    assert signature.signer(DEFI, 'alice', signature.ESPACE, '/c/cle.pub', outil, 5) == BLOB.decode()
    assert sortie.read_text().split() == ['-Y', 'sign', '-n', 'paresia-presence', '-f', '/c/cle.pub']
    assert (tmp_path / 'vu.in').read_bytes() == signature.message_defi(DEFI, 'alice')


def test_delai_depasse(agent_present, tmp_path):
    outil = faux_outil(tmp_path, 'sleep 5\n')
    debut = time.monotonic()
    assert code(signature.signer, DEFI, 'a', signature.ESPACE, '/c/cle.pub', outil,
                0.3) == 'ui_presence_defi_delai'
    assert time.monotonic() - debut < 4


@pytest.fixture
def cle_agent(tmp_path, monkeypatch):
    for outil in ('ssh-keygen', 'ssh-agent', 'ssh-add'):
        if shutil.which(outil) is None:
            pytest.skip(f'{outil} absent : interopérabilité SSHSIG ignorée')
    # Chemin relatif court : la socket reste dans tmp_path, même dans un worktree profond.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('SSH_AUTH_SOCK', 'a')
    agent = subprocess.Popen(['ssh-agent', '-D', '-a', 'a'], cwd=tmp_path,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    privee, publique = tmp_path / 'jetable', tmp_path / 'jetable.pub'
    try:
        fin = time.monotonic() + 3
        while not (tmp_path / 'a').exists():
            assert agent.poll() is None and time.monotonic() < fin, 'Agent éphémère indisponible'
            time.sleep(0.01)
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(privee)],
                       check=True, timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        privee.chmod(0o600)
        subprocess.run(['ssh-add', str(privee)], check=True, timeout=5,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        privee.unlink()  # seul l'agent peut signer ensuite
        yield publique
    finally:
        if agent.poll() is None:
            agent.terminate()
        try:
            agent.wait(timeout=3)
        except subprocess.TimeoutExpired:
            agent.kill()
            agent.wait(timeout=3)
        privee.unlink(missing_ok=True)
        publique.unlink(missing_ok=True)
        (tmp_path / 'a').unlink(missing_ok=True)


def test_interoperabilite(cle_agent):
    defi = secrets.token_hex(32)
    message = signature.message_defi(defi, 'essai')
    signe = signature.signer(defi, 'essai', signature.ESPACE, cle_agent, 'ssh-keygen', 10)
    genre, b64 = cle_agent.read_bytes().split()[:2]
    blob = base64.b64decode(b64)
    autoriser = lambda t, b: t == genre and b == blob
    verifier(signe, message, signature.ESPACE, autoriser)
    for autre, espace in ((message, 'autre'),
                          (signature.message_defi(defi, 'autre'), signature.ESPACE),
                          (signature.message_defi(secrets.token_hex(32), 'essai'), signature.ESPACE)):
        with pytest.raises(SignatureInvalide):
            verifier(signe, autre, espace, autoriser)
