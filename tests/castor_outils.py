# SPDX-License-Identifier: AGPL-3.0-or-later
# Outils communs aux tests de Castor ; dépendances : bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha.42  2026-11-06  T067 : envoi interrompu par le serveur (BrokenPipe, Reset) = connexion fermée.
#   3.0.0-alpha  2026-11-05  Banc de test de Castor (T020).
import contextlib
import io
import json
import os
from pathlib import Path
import secrets
import socket
import tempfile
import time

from server.castor import Castor
from server.commun.journal import Journal


class Horloge:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def configuration(dossier, **lumieres):
    return {
        'tunnel': {'socket': str(Path(dossier) / 'castor.sock'), 'uid': os.getuid(), 'gid': os.getgid()},
        'state': {'socket': str(Path(dossier) / 'castor-state.sock'), 'uid': os.getuid(), 'gid': os.getgid()},
        'lights': {'heartbeat_s': 30, 'margin_s': 5, 'maximum': 64, 'closed_s': 10,
                   'verification_s': 1, **lumieres},
        'transport': {'delai_s': 5, 'max_line': 512, 'max_connexions': 8},
    }


def requete(action, session=1, params=None):
    return {'proto': 'jumeaux/1', 'id': secrets.token_hex(8), 'session': session,
            'action': action, 'params': {} if params is None else params}


def appeler(chemin, brut):
    """Envoie une ligne (dict ou octets) ; retourne la réponse décodée ou None si fermée."""
    donnees = brut if isinstance(brut, bytes) else json.dumps(brut).encode() + b'\n'
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(3)
        s.connect(chemin)
        try:
            s.sendall(donnees)
            ligne = s.makefile('rb').readline()
        except (ConnectionError, socket.timeout):  # BrokenPipe/Reset inclus : fermée par le serveur
            return None
    return json.loads(ligne) if ligne else None


@contextlib.contextmanager
def monter(**lumieres):
    with tempfile.TemporaryDirectory(prefix='castor-') as dossier:
        flux = io.StringIO()
        horloge = Horloge()
        config = configuration(dossier, **lumieres)
        castor = Castor(config, horloge=horloge, journal=Journal('test', flux=flux))
        with castor:
            castor.config = config
            yield castor, horloge, flux


def evenements(flux):
    return [json.loads(l) for l in flux.getvalue().splitlines()]
