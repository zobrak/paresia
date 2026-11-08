# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests de la file d'attente d'écoute du frontal HTTP ; dépendances : pytest, bibliothèque standard et server.
# Suivi des versions
#   3.0.0-alpha.40  2026-11-06  File d'attente d'écoute au moins égale à la limite de connexions.
import io
import os
from pathlib import Path
import socket
import tempfile

import pytest

from server.commun.journal import Journal
import server.romulus.http as module
from server.romulus.http import FrontalHTTP
from server.romulus.sessions import Sessions


def config(dossier, maximum):
    return {'socket': str(dossier / 'http.sock'), 'uid_lighttpd': os.getuid(),
            'gid': os.getgid(), 'timeout_s': .5, 'max_body': 65536,
            'max_connexions': maximum, 'read_deadline_s': 30, 'max_headers': 100,
            'max_header_bytes': 16384, 'client_ip_header': 'X-Client-IP',
            'fallback_ip': '127.0.0.1'}


@pytest.fixture
def dossier_socket():
    # Les worktrees dépassent parfois la limite des chemins AF_UNIX.
    with tempfile.TemporaryDirectory(prefix='romulus-') as dossier:
        yield Path(dossier)


def construire(dossier, maximum):
    journal = Journal('romulus', flux=io.StringIO())
    return FrontalHTTP(config(dossier, maximum), Sessions(journal), journal)


@pytest.mark.parametrize('maximum', [1, 2, 16, 64, 1024])
def test_attribut_file(monkeypatch, dossier_socket, maximum):
    monkeypatch.setattr(module.ThreadingHTTPServer, '__init__', lambda *a, **k: None)
    frontal = construire(dossier_socket, maximum)
    assert frontal.request_queue_size >= maximum
    if maximum <= 5:
        assert frontal.request_queue_size == 5


@pytest.mark.parametrize('maximum', [64, 16])
def test_rafale_sans_acceptation(dossier_socket, maximum):
    frontal = construire(dossier_socket, maximum)
    clients = []
    try:
        frontal.server_bind()
        frontal.server_activate()
        for _ in range(maximum):
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            clients.append(client)
            client.settimeout(0)
            client.connect(frontal.server_address)
    finally:
        for client in clients:
            client.close()
        frontal.server_close()
    assert len(clients) == maximum
