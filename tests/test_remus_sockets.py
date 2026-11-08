# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests des sockets et du transport de Remus ; dépendances : pytest et bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha  2026-11-05  Critère B de T021.
import ast
import os
from pathlib import Path
import re
import stat

from remus_outils import Enregistreur, appeler, chemin, monter, requete
from server import remus as paquet


def test_remus_peercred():
    a = Enregistreur()
    with monter(a, etats={1: ['green']}, avec_serveur=False) as r:
        r.config['server']['uid'] = os.getuid() + 1
        from server.remus import Remus
        autre = Remus(r.config, actions={a.action.nom: a.action}, journal=r.journal)
        with autre:
            assert appeler(chemin(r), requete()) is None
        assert not a.appels


def test_remus_socket_mode():
    with monter(Enregistreur()) as r:
        st = os.stat(chemin(r))
        assert stat.S_IMODE(st.st_mode) == 0o660 and stat.S_ISSOCK(st.st_mode)


def test_remus_entrees_malformees():
    a = Enregistreur()
    with monter(a, etats={1: ['green']}) as r:
        c = chemin(r)
        assert appeler(c, b'{pas du json\n')['error']['code'] == 'bad_request'
        mauvaise = requete()
        mauvaise['proto'] = 'jumeaux/2'
        assert appeler(c, mauvaise)['error']['code'] == 'protocol_version_mismatch'
        assert appeler(c, requete(params={'session': 1}))['error']['code'] == 'bad_request'
        supplementaire = requete()
        supplementaire['x'] = 1
        assert appeler(c, supplementaire)['error']['code'] == 'bad_request'
        appeler(c, b'x' * 10000 + b'\n')  # ligne trop longue : réponse ou fermeture
        assert appeler(c, requete())['ok'] is True  # démon vivant
        assert len(a.appels) == 1


def test_remus_aucun_processus():
    racine = Path(paquet.__file__).parent
    for nom in ('__init__.py', 'actions.py', '__main__.py'):
        source = (racine / nom).read_text()
        assert not re.search(r'subprocess|os\.system|shell\s*=\s*True|os\.popen|os\.exec|os\.spawn', source), nom
        modules = {n.names[0].name.split('.')[0] for n in ast.walk(ast.parse(source))
                   if isinstance(n, ast.Import)}
        modules |= {n.module.split('.')[0] for n in ast.walk(ast.parse(source))
                    if isinstance(n, ast.ImportFrom) and n.module}
        assert not modules & {'subprocess', 'pty', 'shlex'}, nom
