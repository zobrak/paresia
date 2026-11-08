# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests des feux de Castor ; dépendances : pytest et bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha  2026-11-05  Critères A de T020.
import time

from castor_outils import appeler, evenements, monter, requete

PING, ETAT, FERME = 'castor/light/ping', 'castor/light/state', 'castor/light/close'


def tunnel(c, action, session=1):
    return appeler(c.config['tunnel']['socket'], requete(action, session))


def etat(c, session=1):
    return appeler(c.config['state']['socket'], requete(ETAT, session))


def code(r):
    return r['error']['code']


def test_castor_feu_vert_puis_rouge():
    with monter() as (c, h, _):
        assert tunnel(c, PING)['ok'] is True and 'data' not in tunnel(c, PING)
        assert etat(c)['data'] == {'state': 'green', 'remaining_s': 35}
        h.t += 34.9
        assert etat(c)['data'] == {'state': 'green', 'remaining_s': 1}
        h.t += 0.1
        r = etat(c)
        assert r['ok'] is True and r['data'] == {'state': 'red'}


def test_castor_green_s_reglable():
    with monter(heartbeat_s=2, margin_s=1) as (c, h, _):
        tunnel(c, PING)
        h.t += 2.9
        assert etat(c)['data']['state'] == 'green'
        h.t += 0.1
        assert etat(c)['data'] == {'state': 'red'}


def test_castor_ping_renouvelle():
    with monter() as (c, h, _):
        tunnel(c, PING)
        h.t += 30
        tunnel(c, PING)
        h.t += 34.9
        assert etat(c)['data']['state'] == 'green'
        h.t += 0.1
        assert etat(c)['data'] == {'state': 'red'}


def test_castor_close_immediat():
    with monter() as (c, h, _):
        tunnel(c, PING)
        assert tunnel(c, FERME)['ok'] is True
        assert code(etat(c)) == 'session_closed'


def test_castor_ping_apres_close():
    with monter() as (c, h, _):
        tunnel(c, PING)
        tunnel(c, FERME)
        assert code(tunnel(c, PING)) == 'session_closed'
        assert code(etat(c)) == 'session_closed'
        h.t += 10
        assert etat(c)['data'] == {'state': 'red'}
        assert tunnel(c, PING)['ok'] is True
        assert etat(c)['data']['state'] == 'green'


def test_castor_close_idempotent():
    with monter() as (c, _, _):
        assert tunnel(c, FERME, 7)['ok'] is True
        assert tunnel(c, FERME, 7)['ok'] is True


def test_castor_session_inconnue_rouge():
    with monter() as (c, _, _):
        r = etat(c, 42)
        assert r['ok'] is True and r['data'] == {'state': 'red'}


def test_castor_sessions_independantes():
    with monter() as (c, h, _):
        tunnel(c, PING, 1)
        h.t += 20
        tunnel(c, PING, 2)
        tunnel(c, PING, 3)
        tunnel(c, FERME, 3)
        assert etat(c, 1)['data']['state'] == 'green'
        assert etat(c, 2)['data']['state'] == 'green'
        h.t += 15  # session 1 expirée, 2 encore verte
        assert etat(c, 1)['data'] == {'state': 'red'}
        assert etat(c, 2)['data']['state'] == 'green'


def test_castor_limite_sessions():
    with monter(maximum=2) as (c, h, _):
        tunnel(c, PING, 1)
        tunnel(c, PING, 2)
        assert code(tunnel(c, PING, 3)) == 'session_limit'
        assert etat(c, 3)['data'] == {'state': 'red'}
        assert etat(c, 1)['data']['state'] == 'green'
        assert tunnel(c, PING, 1)['ok'] is True  # renouvellement permis


def test_castor_purge_expires():
    with monter(maximum=2) as (c, h, _):
        tunnel(c, PING, 1)
        tunnel(c, PING, 2)
        h.t += 35
        assert tunnel(c, PING, 3)['ok'] is True
        assert etat(c, 3)['data']['state'] == 'green'


def test_castor_fermees_bornees():
    with monter(maximum=2) as (c, h, _):
        for n in (1, 2, 3):
            tunnel(c, FERME, n)
        assert len(c._fermees) == 2
        assert etat(c, 1)['data'] == {'state': 'red'}  # la plus ancienne est oubliée
        assert code(etat(c, 3)) == 'session_closed'


def test_castor_surveillance_expiration():
    with monter(verification_s=0.05) as (c, h, flux):
        tunnel(c, PING, 5)
        h.t += 36
        assert etat(c, 5)['data'] == {'state': 'red'}  # exact sans passe
        fin = time.monotonic() + 3
        while not any(e['event'] == 'light_expired' for e in evenements(flux)):
            assert time.monotonic() < fin
            time.sleep(0.01)
    with monter(verification_s=3600) as (c, h, flux):
        tunnel(c, PING, 6)
        h.t += 36
        c.verifier()
        assert [e for e in evenements(flux) if e['event'] == 'light_expired'][0]['session'] == 6
