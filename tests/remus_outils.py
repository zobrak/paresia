# SPDX-License-Identifier: AGPL-3.0-or-later
# Outils communs aux tests de Remus : faux Castor, horloge, actions de test, faux sudo et faux docker ; bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha.42  2026-11-06  T067 : envoi interrompu par le serveur (BrokenPipe, Reset) = connexion fermée.
#   3.0.0-alpha  2026-11-05  Banc de test de Remus (T021).
#   3.0.0-alpha  2026-11-05  Banc de test de l'exécuteur (T022).
#   3.0.0-alpha  2026-11-05  Correction du faux docker (mode petitfils : sauts de ligne échappés).
#   3.0.0-alpha  2026-11-06  Fusion des bancs de T021 et T022.
import contextlib
import io
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import threading

import pytest

from server.commun.journal import Journal
from server.commun.jumeaux import reponse
from server.commun.serveur import Serveur
from server.remus import Action, Remus
from server.remus.executeur import Choix, Commande, Executeur, Param, construire_table

PREFIXE = 'relay/state/status'


class Horloge:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def attendre(self, duree):
        self.t += duree


class FauxCastor:
    """Serveur du socle sur socket temporaire ; comportement programmable par session.

    etats[session] : liste d'états consommés à chaque interrogation (le dernier se répète) :
    'green', 'red', 'closed', ou un dictionnaire de data à renvoyer tel quel.
    """

    def __init__(self, dossier, uid=None):
        self.chemin = str(Path(dossier) / 'castor-state.sock')
        self.etats = {}
        self.appels = []
        self._verrou = threading.Lock()
        uid = os.getuid() if uid is None else uid
        self.serveur = Serveur(self.chemin, {os.getuid()}, {'castor/light/state'}, self._traiter,
                               gid=os.getgid(), delai=5, journal=Journal('faux', flux=io.StringIO()))
        self.uid = uid

    def _traiter(self, q, _):
        with self._verrou:
            self.appels.append(q['session'])
            file = self.etats.get(q['session'], ['red'])
            etat = file.pop(0) if len(file) > 1 else file[0]
        if etat == 'green':
            return reponse(q['id'], {'state': 'green', 'remaining_s': 30})
        if etat == 'red':
            return reponse(q['id'], {'state': 'red'})
        if etat == 'closed':
            return reponse(q['id'], code='session_closed')
        return reponse(q['id'], etat)

    def nombre(self, session):
        with self._verrou:
            return self.appels.count(session)


def configuration(dossier, castor=None, **lumiere):
    wait = lumiere.get('wait_s', 5)
    return {
        'server': {'socket': str(Path(dossier) / 'remus.sock'), 'uid': os.getuid(),
                   'gid': os.getgid(), 'stop_s': 3},
        'castor': {'socket': castor or str(Path(dossier) / 'castor-state.sock'),
                   'uid': os.getuid(), 'delai_s': min(2, wait)},
        'light': {'wait_s': 5, 'poll_s': 0.25, 'check_s': 5, **lumiere},
        'transport': {'delai_s': 600, 'max_line': 4096, 'max_connexions': 8},
    }


def requete(action=PREFIXE, session=1, params=None):
    return {'proto': 'jumeaux/1', 'id': secrets.token_hex(8), 'session': session,
            'action': action, 'params': {} if params is None else params}


def valider_vide(params):
    from server.remus import ErreurOperation
    if params:
        raise ErreurOperation('bad_request')
    return params


class Enregistreur:
    """Action de test : compte les exécutions, peut bloquer ou échouer."""

    def __init__(self, action=PREFIXE, **options):
        self.appels = []
        self.entree = threading.Event()
        self.liberer = threading.Event()
        self.liberer.set()
        self.effet = None
        self.action = Action(action, self.executer, options.pop('valider', valider_vide),
                             options.pop('delai_max_s', 1), **options)

    def executer(self, contexte):
        self.appels.append(contexte)
        self.entree.set()
        self.liberer.wait(10)
        if self.effet is not None:
            return self.effet(contexte)
        return {'fait': True}


def appeler(chemin, brut):
    donnees = brut if isinstance(brut, bytes) else json.dumps(brut).encode() + b'\n'
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(10)
        s.connect(chemin)
        try:
            s.sendall(donnees)
            ligne = s.makefile('rb').readline()
        except (ConnectionError, socket.timeout):  # BrokenPipe/Reset inclus : fermée par le serveur
            return None
    return json.loads(ligne) if ligne else None


@contextlib.contextmanager
def monter(*enregistreurs, etats=None, horloge=None, avec_serveur=True, **lumiere):
    """Remus + faux Castor ; horloge fictive si horloge est fourni (alors attente fictive)."""
    with tempfile.TemporaryDirectory(prefix='remus-') as dossier:
        faux = FauxCastor(dossier)
        faux.etats.update(etats or {})
        flux = io.StringIO()
        config = configuration(dossier, **lumiere)
        options = {}
        if horloge is not None:
            options = {'horloge': horloge, 'attente': horloge.attendre}
        actions = {e.action.nom: e.action for e in enregistreurs}
        remus = Remus(config, actions=actions, journal=Journal('test', flux=flux), **options)
        with faux.serveur:
            if avec_serveur:
                with remus:
                    remus.config_test, remus.faux, remus.flux_journal = config, faux, flux
                    yield remus
            else:
                remus.config_test, remus.faux, remus.flux_journal = config, faux, flux
                yield remus


def evenements(flux):
    return [json.loads(l) for l in flux.getvalue().splitlines()]


def chemin(remus):
    return remus.config_test['server']['socket']



SUDO = """#!{python}
import json, os, sys
with open({trace!r}, 'w') as f:
    json.dump({{'argv': sys.argv[1:], 'env': dict(os.environ)}}, f)
os.execv(sys.argv[3], sys.argv[3:])
"""

DOCKER = """#!{python}
import os, signal, sys, time
args = sys.argv[1:]
if args[0] == 'fake':
    args = args[1:]
mode = args[0]
if mode == 'ok':
    sys.stdout.write('une\\r\\nESC\\x1b[31mrouge\\x1b[0m\\ttab \\u202eRLO\\n\\xff\\xfe\\n')
    sys.stdout.flush()
    sys.stdout.buffer.write(b'inv\\xffalide\\n')
elif mode == 'exit3':
    sys.stdout.write('secret-de-sortie\\n'); sys.stderr.write('secret-erreur\\n'); sys.exit(3)
elif mode == 'exit9':
    sys.exit(9)
elif mode == 'signal':
    os.kill(os.getpid(), signal.SIGKILL)
elif mode == 'big':
    bloc = b'x' * 65536
    for _ in range(64):
        sys.stdout.buffer.write(bloc); sys.stderr.buffer.write(bloc)
    sys.stdout.buffer.flush(); sys.stderr.buffer.flush()
elif mode == 'streams':
    sys.stdout.write('sortie\\n'); sys.stdout.flush(); sys.stderr.write('erreur\\n'); sys.stderr.flush()
elif mode == 'sleep':
    time.sleep(30)
elif mode == 'ignoreterm':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    open({pidfile!r}, 'w').write(str(os.getpid()))
    time.sleep(30)
elif mode == 'petitfils':
    import subprocess
    code = ("import os, signal, time\\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\\n"
            "open(%r, 'w').write(str(os.getpid()))\\ntime.sleep(30)\\n" % {pidfile!r})
    subprocess.Popen([sys.executable, '-c', code])
    time.sleep(30)
elif mode == 'bigsleep':
    sys.stdout.buffer.write(b'x' * 100000)
    sys.stdout.buffer.flush()
    time.sleep(30)
elif mode == 'lent':
    time.sleep(1.5)
    open({effet!r}, 'w').write('fait')
elif mode == 'stdin':
    sys.stdout.write(str(len(sys.stdin.buffer.read())) + '\\n')
elif mode == 'echo':
    sys.stdout.write('|'.join(args[1:]) + '\\n')
"""


class Banc:
    def __init__(self, dossier):
        self.dossier = Path(dossier)
        self.trace = self.dossier / 'trace.json'
        self.pidfile = self.dossier / 'pid'
        self.effet = self.dossier / 'effet'
        self.sudo = self.dossier / 'sudo-faux'
        self.docker = self.dossier / 'docker-faux'
        self.sudo.write_text(SUDO.format(python=sys.executable, trace=str(self.trace)))
        self.docker.write_text(DOCKER.format(python=sys.executable, pidfile=str(self.pidfile),
                                             effet=str(self.effet)))
        for chemin in (self.sudo, self.docker):
            chemin.chmod(0o755)
        try:
            subprocess.run([str(self.docker), 'ok'], capture_output=True, check=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pytest.skip('dossier temporaire sans droit d\'exécution : faux programmes inutilisables')
        self.flux = io.StringIO()

    def configuration(self, **options):
        return {'sudo': str(self.sudo), 'docker': str(self.docker), 'delai_s': 20, 'kill_grace_s': 1,
                'sortie_max': 65536, 'simultanes': 4, 'attente_s': 1, **options}

    def executeur(self, commandes, **options):
        table = construire_table({c.nom: c for c in commandes})
        return Executeur(self.configuration(**options), table, journal=Journal('remus', flux=self.flux))

    def evenements(self):
        return [json.loads(ligne) for ligne in self.flux.getvalue().splitlines()]

    def recu(self):
        return json.loads(self.trace.read_text())


def commande_mode(nom='mode', **options):
    """Commande de test : docker-faux <mode> avec le mode choisi dans une liste fermée."""
    modes = ('ok', 'exit3', 'exit9', 'signal', 'big', 'streams', 'sleep', 'ignoreterm', 'lent', 'stdin',
             'petitfils', 'bigsleep')
    return Commande(nom, ('sudo', '-n', '--', 'docker', 'fake', Param('mode', Choix(*modes))), **options)
