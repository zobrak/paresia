# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests hors réseau du client ; dépendances : pytest, cryptography, OpenSSH, stdlib.
# Suivi des versions
#   3.0.0-alpha.42  2026-11-07  Interopérabilité réelle, protocole, limites et non-divulgation.
import base64
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time

import pytest

from banc import client
from server.commun.sshsig import SignatureInvalide, verifier
from server.commun.texte import filtrer


@pytest.fixture
def cle_agent(tmp_path, monkeypatch):
    for outil in ('ssh-keygen', 'ssh-agent', 'ssh-add'):
        if shutil.which(outil) is None:
            pytest.skip(f'{outil} absent : interopérabilité SSHSIG ignorée')
    # Chemin relatif court : le fichier reste dans tmp_path, même dans un worktree profond.
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
        privee.chmod(0o600)  # ACL par défaut possible sur le dossier : ssh-add refuse une clé ouverte
        subprocess.run(['ssh-add', str(privee)], check=True, timeout=5,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        privee.unlink()  # prouve que seul l'agent peut signer ensuite
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


def test_agent(cle_agent, capsys):
    defi = secrets.token_hex(32)
    message = client.message_defi(defi, 'essai')
    signature = client.signer_defi(defi, 'essai', client.ESPACE, cle_agent)
    genre, b64 = cle_agent.read_bytes().split()[:2]
    blob = base64.b64decode(b64)
    autoriser = lambda t, b: t == genre and b == blob
    verifier(signature, message, client.ESPACE, autoriser)
    for autre_message, espace in ((message, 'autre'),
                                  (client.message_defi(defi, 'autre'), client.ESPACE),
                                  (client.message_defi(secrets.token_hex(32), 'essai'), client.ESPACE)):
        with pytest.raises(SignatureInvalide):
            verifier(signature, autre_message, espace, autoriser)
    with pytest.raises(client.ErreurClient, match='namespace'):
        client.signer_defi(defi, 'essai', 'autre', cle_agent)
    assert capsys.readouterr() == ('', '')


def test_message():
    defi = secrets.token_hex(32)
    assert client.message_defi(defi, 'Alice@site') == (
        b'paresia-presence/1\n' + defi.encode('ascii') + b'\nAlice@site\n')
    for mauvais in ('', defi + '\n', 'z' * 64, 1, None):
        with pytest.raises(client.ErreurClient):
            client.message_defi(mauvais, 'essai')
    with pytest.raises(client.ErreurClient):
        client.message_defi(defi, 'essai\n')


def test_armure():
    b64 = base64.b64encode(b'SSHSIG\0\0\0\1' + secrets.token_bytes(25))
    armure = b'-----BEGIN SSH SIGNATURE-----\n' + b64[:20] + b'\n' + b64[20:] + b'\n-----END SSH SIGNATURE-----\n'
    assert client.extraire_signature(armure) == b64.decode()
    for mauvais in (b'', b'x\n' + armure, armure + b'x', armure.replace(b64[:20], b'!!!'),
                    b'x' * 10000, armure.replace(b'SIGNATURE', b'CLE', 1)):
        with pytest.raises(client.ErreurClient):
            client.extraire_signature(mauvais)


def test_filtrage():
    texte = 'avant\x1b[31m\x00\n\r\t\u202e\u2028\u2029\ud800\ue000après'
    assert client.filtrer(texte) == filtrer(texte)
    sortie = io.StringIO()
    client.message(texte, sortie)
    assert sortie.getvalue() == filtrer(texte) + '\n'


# Faux transport SSH : vrais tubes et vrai processus, aucun réseau ni sshd.
_FAUX = r'''
import json, pathlib, secrets, sys, time
mode, chemin = sys.argv[1:]
for ligne in sys.stdin.buffer:
    q = json.loads(ligne)
    action = q['action'].rsplit('/', 1)[1]
    with open(chemin, 'a') as trace:
        trace.write(action + '\n')
    if mode == 'silence':
        time.sleep(30)
    if mode == 'coupe':
        break
    if mode == 'longue':
        print('x' * 1048577, flush=True)
        continue
    if mode == 'json':
        print('[]', flush=True)
        continue
    if mode == 'code_invalide':
        print(json.dumps({'id': q['id'], 'ok': False, 'error': {'code': []}}), flush=True)
        continue
    r = {'id': q['id'], 'ok': True}
    if action == 'challenge':
        r['data'] = {'challenge': secrets.token_hex(32), 'namespace': 'paresia-presence', 'expires_s': 20}
        if mode == 'namespace':
            r['data']['namespace'] = 'autre'
    elif action == 'open':
        r['data'] = {'session': 7, 'token': secrets.token_hex(32), 'heartbeat_s': 0.04, 'timeout_s': 2}
        if mode == 'token':
            r['data']['token'] = 'incorrect'
    elif action == 'ping' and mode == 'ping_refuse':
        r = {'id': q['id'], 'ok': False, 'error': {'code': 'session_closed'}}
    if mode == 'id':
        r['id'] = 'invalide'
    print(json.dumps(r), flush=True)
'''


@pytest.fixture
def faux(tmp_path, monkeypatch):
    original = subprocess.Popen
    lancements = []
    processus = []
    trace = tmp_path / 'actions'
    mode = ['normal']

    def lancer(args, **kwargs):
        lancements.append(args)
        proc = original([sys.executable, '-u', '-c', _FAUX, mode[0], str(trace)], **kwargs)
        processus.append(proc)
        return proc

    def signer(defi, admin, namespace, *args, **kwargs):
        client.message_defi(defi, admin, namespace)
        return 'YQ=='

    monkeypatch.setattr(client.subprocess, 'Popen', lancer)
    monkeypatch.setattr(client, 'signer_defi', signer)
    yield mode, trace, lancements
    for proc in processus:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=3)


def test_session(faux, capsys):
    _, trace, lancements = faux
    s = client.Session('backend-admin.example.org', 'app', 'publique.pub', 'essai')
    with s:
        jeton = client.obtenir_jeton(s)
        assert len(jeton) == 64 and s.numero == 7
        assert jeton not in repr(s)
        fin = time.monotonic() + 2
        while 'ping' not in trace.read_text():
            assert time.monotonic() < fin
            time.sleep(0.01)
    actions = trace.read_text().splitlines()
    assert actions[:2] == ['challenge', 'open'] and actions[-1] == 'close'
    assert capsys.readouterr() == ('', '')
    assert s._jeton is None and s._proc is None
    assert lancements[0] == ['ssh', '-T', '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
                             '-i', str(Path('publique.pub').absolute()), '--', 'app@backend-admin.example.org']


@pytest.mark.parametrize('mode', ['namespace', 'token', 'id', 'longue', 'json', 'code_invalide', 'coupe', 'silence'])
def test_reponse_refusee(faux, mode, capsys):
    faux[0][0] = mode
    s = client.Session('backend-admin', 'app', 'publique.pub', 'essai', ouverture_s=0.4)
    with pytest.raises(client.ErreurClient):
        s.ouvrir()
    assert s._proc is None and s._jeton is None
    assert capsys.readouterr() == ('', '')


def test_ping_refuse(faux):
    faux[0][0] = 'ping_refuse'
    with client.Session('backend-admin', 'app', 'publique.pub', 'essai') as s:
        fin = time.monotonic() + 2
        while s._erreur is None:
            assert time.monotonic() < fin
            time.sleep(0.01)
        with pytest.raises(client.ErreurClient, match='session_closed'):
            client.obtenir_jeton(s)
        assert s._jeton is None


def test_affichage_explicite(faux):
    class Terminal(io.StringIO):
        def isatty(self):
            return True
    with client.Session('backend-admin', 'app', 'publique.pub', 'essai') as s:
        sortie, erreurs = Terminal(), io.StringIO()
        jeton = s.jeton()
        assert client.commande(s, 'inconnue\x1b', sortie=sortie, erreurs=erreurs)
        assert not sortie.getvalue() and jeton not in erreurs.getvalue()
        assert client.commande(s, 'jeton', sortie=sortie, erreurs=erreurs)
        assert sortie.getvalue() == jeton + '\n'
        assert 'ATTENTION' in erreurs.getvalue() and jeton not in erreurs.getvalue()
        with pytest.raises(client.ErreurClient, match='terminal'):
            client.commande(s, 'jeton', sortie=io.StringIO(), erreurs=erreurs)
        assert not client.commande(s, 'fermer', sortie=sortie, erreurs=erreurs)


@pytest.mark.parametrize('arguments', [('--aide',), ('--version',)])
def test_cli(arguments, capsys):
    assert client.main(arguments) == 0
    sortie = capsys.readouterr()
    assert sortie.out and not sortie.err


def test_arguments_et_erreurs_sans_echo(capsys):
    secret = secrets.token_hex(32)
    assert client.main(['--inconnue', secret]) == 2
    capture = capsys.readouterr()
    assert secret not in capture.out + capture.err
    for nom, valeur in (('hote', '-oProxyCommand=x'), ('compte', 'app@autre'),
                        ('admin', 'a\n'), ('cle_publique', 'privee'), ('delai_s', float('nan'))):
        args = dict(hote='backend-admin', compte='app', cle_publique='publique.pub', admin='essai')
        args[nom] = valeur
        with pytest.raises(client.ErreurClient):
            client.Session(**args)


def test_diagnostic_derniere_ligne(monkeypatch, capsys):
    original = subprocess.Popen
    code = "import sys; sys.stderr.write('bruit\\nrefus\\x1b[31m final\\n'); sys.stderr.flush()"

    def lancer(args, **kwargs):
        return original([sys.executable, '-c', code], **kwargs)

    monkeypatch.setattr(client.subprocess, 'Popen', lancer)
    s = client.Session('backend-admin', 'app', 'publique.pub', 'essai', ouverture_s=2, diagnostic=True)
    with pytest.raises(client.ErreurClient):
        s.ouvrir()
    assert s.derniere_ligne == filtrer('refus\x1b[31m final') and '\x1b' not in s.derniere_ligne
    assert capsys.readouterr() == ('', '')
