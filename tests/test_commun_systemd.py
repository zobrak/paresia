# SPDX-License-Identifier: AGPL-3.0-or-later
# Suivi des versions
#   0.1.1  2026-11-07  Adresses refusées et contrôles dans STATUS.
#   0.1.1  2026-11-07  Vérification du socle commun.
import os
import socket
import tempfile
import pytest
from server.commun import systemd

@pytest.mark.parametrize('adresse', [None, '', 'relatif', '/absent/socket', '@absent'])
def test_adresse_invalide(adresse):
    assert not systemd.notifier('READY=1', environ={} if adresse is None else {'NOTIFY_SOCKET': adresse})

@pytest.mark.parametrize('abstrait', [False, True])
def test_notifications(tmp_path, abstrait):
    dossier_court = tempfile.TemporaryDirectory(prefix='paresia-')
    adresse = dossier_court.name + '/notify'
    if abstrait:
        adresse = '@paresia-test-' + str(os.getpid())
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as flux:
        flux.bind('\0' + adresse[1:] if abstrait else adresse)
        flux.settimeout(1)
        env = {'NOTIFY_SOCKET': adresse}
        assert systemd.pret('bon\njour', environ=env)
        assert flux.recv(8192).decode() == 'READY=1\nSTATUS=bon�jour'
        assert systemd.arret(environ=env)
        assert flux.recv(8192) == b'STOPPING=1'
        assert systemd.statut('x' * 2000, environ=env)
        assert len(flux.recv(8192)) == 1031
        assert systemd.statut('a\x1bb\x00c', environ=env)
        assert flux.recv(8192).decode('utf-8') == 'STATUS=a�b�c'

def test_flux(tmp_path):
    with (tmp_path / 'flux').open('w') as flux:
        st = os.fstat(flux.fileno())
        env = {'JOURNAL_STREAM': f'{st.st_dev}:{st.st_ino}'}
        assert systemd.flux_journal(flux.fileno(), env)
        assert not systemd.flux_journal(-1, env)
        assert not systemd.flux_journal(flux.fileno(), {})


@pytest.mark.parametrize('adresse', ['vsock:1:2', '/' + 'a' * 108, '/' + 'é' * 54])
def test_adresse_refusee_avant_ouverture(adresse, monkeypatch):
    def ouverture_interdite(*args, **kw):
        pytest.fail('socket ouvert pour une adresse non admise')

    monkeypatch.setattr(socket, 'socket', ouverture_interdite)
    assert systemd.notifier('READY=1', environ={'NOTIFY_SOCKET': adresse}) is False
