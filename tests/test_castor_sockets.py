# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests des sockets et de la journalisation de Castor ; dépendances : pytest et bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha  2026-11-05  Critères B et D de T020.
import io
import os
from pathlib import Path
import re
import stat
import tempfile

import pytest

import server.castor
from castor_outils import appeler, configuration, evenements, monter, requete, Horloge
from server.castor import Castor
from server.commun.journal import Journal

PING, ETAT, FERME = 'castor/light/ping', 'castor/light/state', 'castor/light/close'


def test_castor_entrees_malformees():
    with monter() as (c, _, _):
        for chemin in (c.config['tunnel']['socket'], c.config['state']['socket']):
            action = PING if 'state' not in chemin else ETAT
            assert appeler(chemin, requete(action, 0))['error']['code'] == 'bad_request'
            assert appeler(chemin, requete(action, 1, {'x': 1}))['error']['code'] == 'bad_request'
            assert appeler(chemin, requete(action, 1, {'session': 1}))['error']['code'] == 'bad_request'
            assert appeler(chemin, requete('presence/relay/ping'))['error']['code'] == 'unknown_action'
            mauvaise = requete(action)
            mauvaise['proto'] = 'jumeaux/2'
            assert appeler(chemin, mauvaise)['error']['code'] == 'protocol_version_mismatch'
            appeler(chemin, b'x' * 2000 + b'\n')  # ligne trop longue : réponse ou fermeture
            assert appeler(chemin, b'{pas du json\n')['error']['code'] == 'bad_request'
        assert appeler(c.config['tunnel']['socket'], requete(PING))['ok'] is True  # toujours vivant


def test_castor_actions_par_socket():
    with monter() as (c, _, _):
        for action in (PING, FERME):
            r = appeler(c.config['state']['socket'], requete(action))
            assert r['error']['code'] == 'unknown_action'
        r = appeler(c.config['tunnel']['socket'], requete(ETAT))
        assert r['error']['code'] == 'unknown_action'


def _verifier_peercred(section):
    with tempfile.TemporaryDirectory(prefix='castor-') as dossier:
        config = configuration(dossier)
        config[section]['uid'] = os.getuid() + 1
        with Castor(config, horloge=Horloge(), journal=Journal('test', flux=io.StringIO())):
            action = ETAT if section == 'state' else PING
            assert appeler(config[section]['socket'], requete(action)) is None


def test_castor_peercred_tunnel():
    _verifier_peercred('tunnel')


def test_castor_peercred_etat():
    _verifier_peercred('state')


def test_castor_ligne_max_line_plus_un():
    with tempfile.TemporaryDirectory(prefix='castor-') as dossier:
        config = configuration(dossier)
        config['transport']['max_line'] = 160
        with Castor(config, horloge=Horloge(), journal=Journal('test', flux=io.StringIO())):
            t = config['tunnel']['socket']
            r = appeler(t, b'x' * 160 + b'\n')  # max_line + 1 octets, LF compris
            assert r is None or r['error']['code'] == 'line_too_long'
            assert appeler(t, requete(PING))['ok'] is True  # nouvelle connexion


def test_castor_sessions_independantes():
    with monter() as (c, _, _):
        t, s = c.config['tunnel']['socket'], c.config['state']['socket']
        assert appeler(t, requete(PING, 1))['ok'] is True
        assert appeler(t, requete(PING, 2))['ok'] is True
        assert appeler(t, requete(FERME, 2))['ok'] is True
        assert appeler(s, requete(ETAT, 1))['data']['state'] == 'green'
        assert appeler(s, requete(ETAT, 2))['error']['code'] == 'session_closed'


def test_castor_fermee_purgee_sous_maximum():
    with monter(maximum=1) as (c, h, _):
        t = c.config['tunnel']['socket']
        assert appeler(t, requete(PING, 1))['ok'] is True
        assert appeler(t, requete(FERME, 1))['ok'] is True
        h.t += c.config['lights']['closed_s'] + 1
        assert appeler(t, requete(PING, 2))['ok'] is True


def test_castor_sockets_modes():
    with monter() as (c, _, _):
        for s in ('tunnel', 'state'):
            st = os.stat(c.config[s]['socket'])
            assert stat.S_IMODE(st.st_mode) == 0o660 and st.st_gid == os.getgid()


def test_castor_arret_nettoie():
    with monter() as (c, _, _):
        chemins = [c.config[s]['socket'] for s in ('tunnel', 'state')]
    assert not any(os.path.exists(p) for p in chemins)


def test_castor_demarrage_echec():
    with tempfile.TemporaryDirectory(prefix='castor-') as dossier:
        config = configuration(dossier)
        Path(config['state']['socket']).write_text('existant')
        castor = Castor(config, horloge=Horloge(), journal=Journal('test', flux=io.StringIO()))
        with pytest.raises(OSError):
            castor.demarrer()
        assert not os.path.exists(config['tunnel']['socket'])
        assert Path(config['state']['socket']).read_text() == 'existant'


def test_castor_aucun_reseau_ni_horloge_murale():
    for fichier in Path(server.castor.__file__).parent.glob('*.py'):
        source = fichier.read_text()
        for interdit in ('AF_INET', 'AF_INET6', 'time.time'):
            assert interdit not in source, (fichier.name, interdit)


def test_castor_journal_audit():
    with monter(maximum=1) as (c, h, flux):
        t, s = c.config['tunnel']['socket'], c.config['state']['socket']
        appeler(t, requete(PING, 1))
        appeler(t, requete(PING, 2))               # session_limit
        appeler(t, requete(PING, 0))               # bad_request
        appeler(t, requete(FERME, 1))
        appeler(t, requete(PING, 1))               # session_closed
        appeler(t, requete(PING, 3))
        h.t += 40
        c.verifier()
        appeler(s, requete(ETAT, 3, {'jeton': 'secret-ne-doit-pas-sortir'}))
    brut = flux.getvalue()
    assert 'secret-ne-doit-pas-sortir' not in brut and 'params' not in brut
    lignes = evenements(flux)
    assert len(lignes) == len(brut.splitlines())
    noms = {e['event'] for e in lignes}
    assert {'light_green', 'light_closed', 'light_expired', 'request_refused',
            'startup', 'request_completed', 'shutdown'} <= noms
    raisons = {e['reason'] for e in lignes if e['event'] == 'request_refused'}
    assert raisons == {'session_limit', 'bad_request', 'session_closed'}
    assert all(e['component'] == 'test' for e in lignes)
    assert not re.search(r'[\x00-\x1f\x7f]', brut.replace('\n', ''))
