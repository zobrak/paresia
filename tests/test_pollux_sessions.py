# Tests d'intégration Pollux ; dépendances : pytest et bibliothèque standard.
# Suivi des versions
#   0.1.1  2026-11-07  Lecture de l'exemple avec les sections journal et métriques du socle.
#   3.0.0-alpha.42  2026-11-06  T067 : peercred, envoi interrompu par le serveur (BrokenPipe) = fermeture.
#   3.0.0-alpha.41  2026-11-06  Ouverture par défi signé (D20, D28).
#   3.0.0-alpha  2026-11-05  Configuration en couches (T015) : sections [composant.domaine], exemple paresia.conf.
#   3.0.0-alpha  2026-11-05  Cycle 2 : journal défaillant, modes des sockets, limites du jeton, fermeture pendant open.
#   3.0.0-alpha  2026-11-05  Cycle 1 : bancs paramétrables, une seule fermeture, isolation, expiration.
#   3.0.0-alpha  2026-11-05  Contrôle du jeton absent de l'état en session ouverte.
#   3.0.0-alpha  2026-11-05  Critères T002 sur sockets temporaires.
import contextlib
import io
import json
import os
from pathlib import Path
import secrets
import socket
import tempfile
import threading
import time
import types

import pytest

from server.commun.client import Connexion
from server.commun.config import ErreurConfiguration, lire
from server.commun.journal import Journal
from server.commun.jumeaux import ACTIONS, decoder, encoder, lire_ligne, reponse
from server.commun.serveur import Serveur, ContexteConnexion
from aide_sshsig import ouverture, preparer_cles, proprietaire_root
from server.pollux import Pollux, SCHEMA, requete


def attendre(condition):
    fin = time.monotonic() + 3
    while not condition():
        assert time.monotonic() < fin, 'Échéance du test dépassée'
        time.sleep(0.01)


PAUSE = 0.5  # supérieur à pair_delai_s (0,2) et à verification_s


def pause():
    time.sleep(PAUSE)


@contextlib.contextmanager
def monter(sessions=None, relay=None, **transport):
    with tempfile.TemporaryDirectory(prefix='pollux-') as dossier:
        flux = io.StringIO()
        journal = Journal('test', flux=flux)
        config = lire('pollux', SCHEMA, journal=True, metriques=True, argv=['--config', 'server/conf/paresia.conf'], environ={})
        for section in ('sessions', 'relay', 'romulus', 'castor'):
            config[section].update(socket=str(Path(dossier) / section), uid=os.getuid())
        for section in ('sessions', 'relay'):
            config[section]['gid'] = os.getgid()
        config['transport'].update({'delai_s': 5, 'pair_delai_s': 0.2, 'max_line': 512, **transport})
        config['sessions'].update(heartbeat_s=1, timeout_s=2, verification_s=0.01)
        config['sessions'].update(sessions or {})
        config['relay'].update(relay or {})
        appels_r, appels_c, contextes = [], [], []
        jeton = secrets.token_hex(32)
        etat_r = {'compteur': 0, 'open': None, 'rompre_open': False,
                  'rompre_close': False, 'delai_close': 0}

        def romulus(q, contexte):
            appels_r.append(q)
            if contexte not in contextes:
                contextes.append(contexte)
            if q['action'] == 'presence/session/open':
                if etat_r['rompre_open']:
                    contexte.fermer()
                    return reponse(q['id'], {'session': 99, 'token': jeton})
                if etat_r['open'] is not None:
                    # 'SANS_DATA' : réponse ok sans champ data.
                    return reponse(q['id'], None if etat_r['open'] == 'SANS_DATA' else etat_r['open'])
                etat_r['compteur'] += 1
                return reponse(q['id'], {'session': etat_r['compteur'], 'token': jeton})
            if q['action'] == 'presence/session/close':
                time.sleep(etat_r['delai_close'])
                if etat_r['rompre_close']:
                    contexte.fermer()
            return reponse(q['id'])

        def castor(q, _):
            appels_c.append(q)
            return reponse(q['id'])

        r = Serveur(config['romulus']['socket'], {os.getuid()}, ACTIONS, romulus,
                    gid=os.getgid(), delai=10, journal=journal).demarrer()
        c = Serveur(config['castor']['socket'], {os.getuid()}, ACTIONS, castor,
                    gid=os.getgid(), journal=journal).demarrer()
        signataire = preparer_cles(config, dossier, 'Alice@site')
        droits = proprietaire_root()
        droits.start()
        try:
            p = Pollux(config, journal=journal).demarrer()
        except BaseException:
            droits.stop()      # le patch ne doit pas survivre à un démarrage refusé
            raise
        p.signataire = signataire
        clients = []

        def client(section='sessions'):
            connexion = Connexion(config[section]['socket'], 3)
            connexion.signataire = signataire
            clients.append(connexion)
            return connexion

        p.client = client
        p.r, p.c, p.appels_r, p.appels_c, p.etat_r = r, c, appels_r, appels_c, etat_r
        p.capture, p.jeton, p.contextes = flux, jeton, contextes
        try:
            yield p
        finally:
            for connexion in clients:
                connexion.fermer()
            p.arreter()
            r.arreter()
            c.arreter()
            droits.stop()


@pytest.fixture
def banc():
    with monter() as p:
        yield p


def journal_de(banc):
    return [json.loads(l) for l in banc.capture.getvalue().splitlines()]


def brut(banc, section, q):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(2)
        sock.connect(banc.config[section]['socket'])
        sock.sendall(encoder(q))
        return decoder(lire_ligne(sock))


def ouvrir(client, **params):
    return ouverture(client, 'Alice@site', params)


def numero(client):
    return ouvrir(client)['data']['session']


def code(resultat):
    return resultat['error']['code']


def fermetures(appels):
    return [q['session'] for q in appels if q['action'].endswith('/close')]


def test_open_session(banc):
    a, b = banc.client(), banc.client()
    data = ouvrir(a)['data']
    assert data == {'session': 1, 'token': banc.jeton, 'heartbeat_s': 1, 'timeout_s': 2}
    assert banc.appels_r[0]['params'] == {'admin': 'Alice@site', 'source': '2001:db8::1'}
    assert numero(b) == 2
    assert len(banc.contextes) == 1
    assert code(ouvrir(a)) == 'bad_request'


@pytest.mark.parametrize('params', [
    {'admin': '', 'source': '127.0.0.1'}, {'admin': 'a'*65, 'source': '127.0.0.1'},
    {'admin': 'a\n', 'source': '127.0.0.1'}, {'admin': 1, 'source': '127.0.0.1'},
    {'admin': 'a', 'source': 'invalide'}, {'admin': 'a', 'source': 1},
    {'admin': 'a'}, {'admin': 'a', 'source': '127.0.0.1', 'extra': 1},
    {'admin': 'a', 'source': 'fe80::1%eth0'}, {'admin': 'a', 'source': 'fe80::1%\n'},
    {'admin': 'a', 'source': '127.0.0.1\n'}, {'admin': 'a', 'source': ' 127.0.0.1'},
    {'admin': 'a', 'source': ''},
])
def test_open_params_invalides(banc, params):
    assert code(ouvrir(banc.client(), **params)) == 'bad_request'
    assert not banc.appels_r


def test_jeton_non_journalise(banc):
    a = banc.client()
    n = numero(a)
    assert banc.jeton not in banc.capture.getvalue()
    assert all(banc.jeton not in repr(vars(s)) for s in banc.sessions.values())
    a.appeler(requete('presence/session/close', n))
    assert banc.jeton not in banc.capture.getvalue()
    evenements = [json.loads(l) for l in banc.capture.getvalue().splitlines()]
    assert any(e['event'] == 'session_closed' and e['reason'] == 'close' for e in evenements)


def test_ping_session(banc):
    a = banc.client()
    assert code(a.appeler(requete('presence/session/ping', 100))) == 'session_closed'
    n = numero(a)
    assert a.appeler(requete('presence/session/ping', n))['ok']
    for action in ('ping', 'close'):
        assert code(a.appeler(requete('presence/session/' + action, n+1))) == 'bad_request'
    assert code(a.appeler(requete('presence/session/ping', n, {'x': 1}))) == 'bad_request'


def verifier_fermeture(banc, motif):
    a = banc.client()
    n = numero(a)
    if motif == 'timeout':
        attendre(lambda: fermetures(banc.appels_c) == [n])
        assert a._socket.recv(1) == b''
    elif motif == 'disconnect':
        a.fermer()
    else:
        assert a.appeler(requete('presence/session/close', n))['ok']
        assert code(a.appeler(requete('presence/session/ping', n))) == 'session_closed'
        assert code(a.appeler(requete('presence/session/close', n))) == 'session_closed'
        a.fermer()
    attendre(lambda: fermetures(banc.appels_c) == [n])
    pause()
    assert fermetures(banc.appels_c) == [n]
    assert fermetures(banc.appels_r) == [n]
    assert not banc.sessions
    fermees = [e for e in journal_de(banc) if e['event'] == 'session_closed' and e['session'] == n]
    assert len(fermees) == 1
    assert (fermees[0]['admin'], fermees[0]['source'], fermees[0]['reason']) == (
        'Alice@site', '2001:db8::1', motif)
    ouvertes = [e for e in journal_de(banc) if e['event'] == 'session_opened']
    assert [(e['session'], e['admin'], e['source']) for e in ouvertes] == [(n, 'Alice@site', '2001:db8::1')]


def test_expiration_sans_ping():
    with monter({'timeout_s': 0.3, 'heartbeat_s': 0.1}) as banc:
        verifier_fermeture(banc, 'timeout')


def test_fermeture_connexion(banc):
    verifier_fermeture(banc, 'disconnect')


def test_close_application(banc):
    verifier_fermeture(banc, 'close')


def test_expiration_pings_reguliers():
    with monter({'timeout_s': 0.4, 'heartbeat_s': 0.1}) as banc:
        a = banc.client()
        n = numero(a)
        debut = time.monotonic()
        while time.monotonic() - debut < 1.0:  # plus de 2 x timeout_s
            assert a.appeler(requete('presence/session/ping', n))['ok']
            time.sleep(0.1)
        assert n in banc.sessions and not banc.appels_c
        attendre(lambda: not banc.sessions)
        assert a._socket.recv(1) == b''
        pause()
        assert fermetures(banc.appels_c) == [n] and fermetures(banc.appels_r) == [n]


def test_expiration_deux_sessions():
    with monter({'timeout_s': 0.4, 'heartbeat_s': 0.1}) as banc:
        a, b = banc.client(), banc.client()
        n, m = numero(a), numero(b)
        debut = time.monotonic()
        while time.monotonic() - debut < 0.9:
            assert b.appeler(requete('presence/session/ping', m))['ok']
            time.sleep(0.1)
        assert list(banc.sessions) == [m]
        assert b.appeler(requete('presence/session/ping', m))['ok']
        assert fermetures(banc.appels_c) == [n] and fermetures(banc.appels_r) == [n]
        assert a._socket.recv(1) == b''


def test_session_expiree_refusee():
    with monter({'timeout_s': 0.2, 'heartbeat_s': 0.1}) as banc:
        a = banc.client()
        n = numero(a)
        attendre(lambda: fermetures(banc.appels_c) == [n])
        pause()
        relais = banc.client('relay')
        assert code(relais.appeler(requete('presence/relay/ping', n))) == 'session_closed'
        assert code(banc.client().appeler(requete('presence/session/ping', n))) == 'session_closed'
        assert [q['action'] for q in banc.appels_c] == ['castor/light/close']


def test_ping_pendant_attente_du_verrou():
    with monter({'timeout_s': 1, 'heartbeat_s': 0.5}) as banc:
        a = banc.client()
        n = numero(a)
        resultat = []
        time.sleep(0.7)
        with banc._verrou:
            fil = threading.Thread(target=lambda: resultat.append(
                a.appeler(requete('presence/session/ping', n))))
            fil.start()
            time.sleep(0.6)  # ping reçu à 0,7 s, verrou libéré à 1,3 s > timeout_s depuis l'ouverture
        fil.join(3)
        assert resultat and resultat[0]['ok']
        assert n in banc.sessions and not banc.appels_c


def test_rupture_romulus(banc):
    a, b = banc.client(), banc.client()
    assert [numero(a), numero(b)] == [1, 2]
    banc.r.arreter()
    attendre(lambda: len(fermetures(banc.appels_c)) == 2)
    pause()
    assert sorted(fermetures(banc.appels_c)) == [1, 2]
    assert not banc.sessions
    assert a._socket.recv(1) == b''
    assert b._socket.recv(1) == b''
    assert not fermetures(banc.appels_r)
    motifs = sorted(e['reason'] for e in journal_de(banc) if e['event'] == 'session_closed')
    assert motifs == ['romulus_lost', 'romulus_lost']
    assert banc.jeton not in banc.capture.getvalue()


def test_reconnexion_romulus(banc):
    a, b = banc.client(), banc.client()
    assert [numero(a), numero(b)] == [1, 2]
    banc.r.arreter()
    attendre(lambda: len(fermetures(banc.appels_c)) == 2)
    pause()
    assert sorted(fermetures(banc.appels_c)) == [1, 2]
    assert not banc.sessions
    assert a._socket.recv(1) == b''
    assert not fermetures(banc.appels_r)
    banc.r.demarrer()
    assert numero(banc.client()) == 3
    assert len(banc.contextes) == 2
    pause()
    assert sorted(fermetures(banc.appels_c)) == [1, 2]


def test_rupture_romulus_castor_echec_journalise(banc):
    a, b = banc.client(), banc.client()
    numero(a), numero(b)
    banc.c.arreter()
    banc.r.arreter()
    attendre(lambda: not banc.sessions)
    pause()
    evenements = journal_de(banc)
    assert sum(e['event'] == 'peer_unavailable' and e.get('peer') == 'castor'
               for e in evenements) == 2
    assert sorted(e['session'] for e in evenements if e.get('reason') == 'romulus_lost') == [1, 2]
    assert not banc.appels_c


def test_rupture_romulus_sans_session_puis_open(banc):
    a = banc.client()
    n = numero(a)
    assert a.appeler(requete('presence/session/close', n))['ok']
    banc.r.arreter()
    pause()
    assert not banc.sessions
    banc.r.demarrer()
    assert numero(banc.client()) == 2
    pause()
    assert fermetures(banc.appels_c) == [1]


def test_rupture_romulus_castor_absent(banc):
    a = banc.client()
    numero(a)
    banc.c.arreter()
    banc.r.arreter()
    attendre(lambda: not banc.sessions)
    attendre(lambda: any(e['event'] == 'peer_unavailable' for e in journal_de(banc)))
    pause()
    assert a._socket.recv(1) == b''
    assert not banc.appels_c and code(ouvrir(banc.client())) == 'peer_unavailable'


def test_rupture_romulus_pendant_open(banc):
    banc.etat_r['rompre_open'] = True
    assert code(ouvrir(banc.client())) == 'peer_unavailable'
    pause()
    assert not banc.sessions and not banc.appels_c
    banc.etat_r['rompre_open'] = False
    assert numero(banc.client()) == 1


def test_rupture_romulus_pendant_close(banc):
    a, b = banc.client(), banc.client()
    n, m = numero(a), numero(b)
    banc.etat_r['rompre_close'] = True
    assert a.appeler(requete('presence/session/close', n))['ok']
    attendre(lambda: len(fermetures(banc.appels_c)) == 2)
    pause()
    assert sorted(fermetures(banc.appels_c)) == [n, m]
    assert fermetures(banc.appels_r) == [n]
    assert not banc.sessions
    assert b._socket.recv(1) == b''


def test_expiration_pendant_fermeture():
    with monter({'timeout_s': 0.1, 'heartbeat_s': 0.05}) as banc:
        banc.etat_r['delai_close'] = 0.15
        a = banc.client()
        n = numero(a)
        assert a.appeler(requete('presence/session/close', n))['ok']
        a.fermer()
        pause()
        assert fermetures(banc.appels_c) == [n] and fermetures(banc.appels_r) == [n]


def test_exception_pendant_expiration():
    with monter({'timeout_s': 0.2, 'heartbeat_s': 0.1}) as banc:
        a, b, c = banc.client(), banc.client(), banc.client()
        n, m = numero(a), numero(b)
        origine = banc._castor

        def castor_defaillant(action, session):
            if session == n:
                raise RuntimeError()
            return origine(action, session)

        banc._castor = castor_defaillant
        attendre(lambda: not banc.sessions)
        pause()
        assert fermetures(banc.appels_r) == [n, m]
        assert fermetures(banc.appels_c) == [m]
        assert any(e['event'] == 'expiry_failed' for e in journal_de(banc))
        banc._castor = origine
        assert numero(c) == 3  # la surveillance et Pollux vivent encore
        attendre(lambda: fermetures(banc.appels_c) == [m, 3])


def test_session_limit():
    with monter({'maximum': 1}) as banc:
        a = banc.client()
        n = numero(a)
        b = banc.client()
        assert code(ouvrir(b)) == 'session_limit'
        assert len(banc.appels_r) == 1
        a.appeler(requete('presence/session/close', n))
        assert code(ouvrir(b)) == 'challenge_required'     # le défi est à usage unique
        assert numero(banc.client()) == 2


def test_open_simultanes_maximum_un():
    with monter({'maximum': 1}) as banc:
        clients = [banc.client(), banc.client()]
        resultats = []
        depart = threading.Barrier(2)

        def tache(client):
            depart.wait()
            resultats.append(ouvrir(client))

        fils = [threading.Thread(target=tache, args=(c,)) for c in clients]
        for fil in fils:
            fil.start()
        for fil in fils:
            fil.join(5)
        assert sorted(r['ok'] for r in resultats) == [False, True]
        assert [code(r) for r in resultats if not r['ok']] == ['session_limit']
        assert len(banc.sessions) == 1
        assert [q['action'] for q in banc.appels_r] == ['presence/session/open']


def test_relay_ping(banc):
    n = numero(banc.client())
    relais = banc.client('relay')
    assert relais.appeler(requete('presence/relay/ping', n))['ok']
    assert banc.appels_c[-1]['session'] == n
    assert banc.appels_c[-1]['action'] == 'castor/light/ping'
    assert code(relais.appeler(requete('presence/relay/ping', n+1))) == 'session_closed'
    assert len(banc.appels_c) == 1
    banc.c.arreter()
    assert code(relais.appeler(requete('presence/relay/ping', n))) == 'peer_unavailable'


@pytest.mark.parametrize('motif', ['close', 'disconnect', 'timeout', 'romulus_lost'])
def test_castor_close_sans_reessai(motif):
    with monter({'timeout_s': 0.3, 'heartbeat_s': 0.1}) as banc:
        a = banc.client()
        n = numero(a)
        banc.c.arreter()
        if motif == 'close':
            assert a.appeler(requete('presence/session/close', n))['ok']
        elif motif == 'disconnect':
            a.fermer()
        elif motif == 'romulus_lost':
            banc.r.arreter()
        attendre(lambda: any(e['event'] == 'peer_unavailable' and e.get('peer') == 'castor'
                             for e in journal_de(banc)))
        banc.c.demarrer()
        time.sleep(0.6)  # supérieur à pair_delai_s : aucun nouvel essai
        assert not banc.appels_c
        assert sum(e['event'] == 'peer_unavailable' and e.get('peer') == 'castor'
                   for e in journal_de(banc)) == 1
        assert any(e.get('reason') == motif for e in journal_de(banc))


def test_open_romulus_injoignable(banc):
    banc.r.arreter()
    assert code(ouvrir(banc.client())) == 'peer_unavailable'
    assert not banc.sessions


@pytest.mark.parametrize('data', [
    'SANS_DATA', [], {'session': 1}, {'session': 1, 'token': 'a'*64, 'extra': 1},
    {'session': 1, 'token': 'court'}, {'session': 1, 'token': 'a'*257},
    {'session': 1, 'token': 'a'*15 + '\n'}, {'session': 1, 'token': 'é'*20},
    {'session': 1, 'token': 5}, {'session': True, 'token': 'a'*64},
    {'session': 0, 'token': 'a'*64}, {'session': -3, 'token': 'a'*64},
    {'session': '1', 'token': 'a'*64}, {'session': 1.0, 'token': 'a'*64},
])
def test_open_reponse_romulus_malformee(banc, data):
    banc.etat_r['open'] = data
    assert code(ouvrir(banc.client())) == 'peer_unavailable'
    assert not banc.sessions
    pause()
    assert not banc.appels_c
    valide = (isinstance(data, dict) and type(data.get('session')) is int
              and data['session'] >= 1)
    assert fermetures(banc.appels_r) == ([1] if valide else [])
    banc.etat_r['open'] = None
    assert numero(banc.client()) == 1


def test_open_reponse_romulus_doublon(banc):
    a = banc.client()
    n = numero(a)
    banc.etat_r['open'] = {'session': n, 'token': 'a'*64}
    assert code(ouvrir(banc.client())) == 'peer_unavailable'
    assert fermetures(banc.appels_r) == []  # pas de close pour le numéro déjà en usage
    assert not banc.sessions  # perte de Romulus : toutes les sessions fermées
    assert a._socket.recv(1) == b''


def test_isolation_connexion_perimee(banc):
    a = banc.client()
    n = numero(a)
    assert a.appeler(requete('presence/session/close', n))['ok']
    banc.etat_r['compteur'] = 0  # redémarrage simulé de Romulus
    b = banc.client()
    assert numero(b) == n  # le numéro est réattribué à B
    assert code(a.appeler(requete('presence/session/ping', n))) == 'session_closed'
    assert code(a.appeler(requete('presence/session/close', n))) == 'session_closed'
    perimee = ContexteConnexion(0, os.getuid(), os.getgid(), etat={'session': n})
    assert code(banc._application(requete('presence/session/close', n), perimee)) == 'session_closed'
    banc._deconnexion(perimee)
    a.fermer()
    pause()
    assert b.appeler(requete('presence/session/ping', n))['ok']
    assert n in banc.sessions
    assert fermetures(banc.appels_c) == [n] and fermetures(banc.appels_r) == [n]  # celle de A seulement


def test_sessions_independantes(banc):
    a, b = banc.client(), banc.client()
    n, m = numero(a), numero(b)
    a.appeler(requete('presence/session/close', n))
    assert b.appeler(requete('presence/session/ping', m))['ok']
    assert banc.client('relay').appeler(requete('presence/relay/ping', m))['ok']
    assert code(banc.client('relay').appeler(requete('presence/relay/ping', n))) == 'session_closed'
    assert fermetures(banc.appels_c) == [n]


def test_jeton_absent_partout():
    with monter({'timeout_s': 0.3, 'heartbeat_s': 0.1, 'maximum': 2}) as banc:
        reponses = []
        a, b, c = banc.client(), banc.client(), banc.client()
        reponses.append(ouvrir(a))
        reponses.append(ouvrir(b))
        reponses.append(ouvrir(c))  # session_limit
        reponses.append(ouvrir(banc.client(), admin='x', source='fe80::1%eth0'))  # bad_request
        attendre(lambda: not banc.sessions)  # expiration
        pause()
        banc.etat_r['open'] = {'session': 7, 'token': 'a'*10}
        reponses.append(ouvrir(banc.client()))
        banc.etat_r['open'] = None
        numero(banc.client())
        banc.r.arreter()  # rupture
        attendre(lambda: not banc.sessions)
        pause()
        for r in reponses:
            if not r['ok']:
                assert banc.jeton not in json.dumps(r)
        assert [r['ok'] for r in reponses] == [True, True, False, False, False]
        assert {code(r) for r in reponses if not r['ok']} == {
            'session_limit', 'bad_request', 'peer_unavailable'}
        assert banc.jeton not in banc.capture.getvalue()


def brut_section(banc, section, action):
    q = requete('presence/session/ping')
    q['action'] = action
    return brut(banc, section, q)


@pytest.mark.parametrize('section,action', [
    ('sessions', 'presence/relay/ping'), ('sessions', 'castor/light/ping'),
    ('sessions', 'inconnue'),
    ('relay', 'presence/session/challenge'), ('relay', 'presence/session/open'), ('relay', 'presence/session/ping'),
    ('relay', 'presence/session/close'), ('relay', 'inconnue'),
])
def test_actions_par_socket(banc, section, action):
    assert code(brut_section(banc, section, action)) == 'unknown_action'
    assert not banc.appels_r and not banc.appels_c


@pytest.mark.parametrize('action', ['presence/session/ping', 'presence/session/close'])
def test_actions_session_admises(banc, action):
    assert code(brut(banc, 'sessions', requete(action, 4))) == 'session_closed'
    assert code(brut(banc, 'relay', requete('presence/relay/ping', 5))) == 'session_closed'
    assert not banc.appels_r and not banc.appels_c


@pytest.mark.parametrize('refuse', ['sessions', 'relay'])
def test_peercred_pollux(refuse):
    autre = 'relay' if refuse == 'sessions' else 'sessions'
    uids = {refuse: {'uid': os.getuid() + 1}, autre: {'uid': os.getuid()}}
    with monter(sessions=uids['sessions'], relay=uids['relay']) as banc:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(2)
            sock.connect(banc.config[refuse]['socket'])
            try:
                sock.sendall(encoder(requete('presence/relay/ping' if refuse == 'relay'
                                             else 'presence/session/ping')))
                assert sock.recv(1) == b''  # fermeture sans réponse
            except (BrokenPipeError, ConnectionResetError):  # fermée par le serveur
                pass
        attendre(lambda: any(e['event'] == 'peer_refused' and e['uid'] == os.getuid()
                             for e in journal_de(banc)))
        assert not banc.appels_r and not banc.appels_c
        # L'autre écoute admet cet uid.
        if autre == 'relay':
            assert code(banc.client('relay').appeler(requete('presence/relay/ping', 4))) == 'session_closed'
        else:
            assert code(banc.client().appeler(requete('presence/session/ping', 4))) == 'session_closed'


def test_configuration_durees_refusees():
    for sessions in ({'heartbeat_s': 2, 'timeout_s': 2}, {'heartbeat_s': 30, 'timeout_s': 2},
                     {'verification_s': 3, 'timeout_s': 2}):
        with pytest.raises(ErreurConfiguration):
            with monter(sessions):
                pass
    with monter({'verification_s': 2, 'timeout_s': 2}):
        pass


@pytest.mark.parametrize('section', ['sessions', 'relay'])
@pytest.mark.parametrize('genre,attendu,ferme', [
    ('json', 'bad_request', False), ('objet', 'bad_request', False),
    ('champ', 'bad_request', False), ('action', 'unknown_action', False),
    ('proto', 'protocol_version_mismatch', True), ('longue', 'line_too_long', True),
])
def test_robustesse_pollux(banc, section, genre, attendu, ferme):
    q = requete('presence/session/ping' if section == 'sessions' else 'presence/relay/ping')
    if genre == 'champ':
        q['extra'] = 1
    if genre == 'action':
        q['action'] = 'inconnue'
    if genre == 'proto':
        q['proto'] = 'jumeaux/2'
    ligne = {'json': b'{\n', 'objet': b'[]\n', 'longue': b'x'*513}.get(genre, encoder(q))
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(2)
        sock.connect(banc.config[section]['socket'])
        sock.sendall(ligne)
        assert code(decoder(lire_ligne(sock))) == attendu
        if ferme:
            assert sock.recv(1) == b''
    assert numero(banc.client()) > 0


def test_conf_exemple_pollux():
    config = lire('pollux', SCHEMA, journal=True, metriques=True, argv=['--config', 'server/conf/paresia.conf'], environ={})
    assert config['sessions']['heartbeat_s'] == 30
    assert config['sessions']['timeout_s'] == 90
    assert config['sessions']['maximum'] == 16


def test_journal_defaillant_a_la_fermeture(banc):
    a = banc.client()
    n = numero(a)
    ecrire = banc.journal.ecrire

    def defaillant(niveau, evenement, **champs):
        if evenement == 'session_closed':
            raise OSError()
        return ecrire(niveau, evenement, **champs)

    banc.journal.ecrire = defaillant
    try:
        with banc._verrou:
            banc._fermer(n, 'close')
    finally:
        banc.journal.ecrire = ecrire
    assert fermetures(banc.appels_r) == [n]
    assert fermetures(banc.appels_c) == [n]
    assert not banc.sessions


@pytest.mark.parametrize('masque', [0o000, 0o077])
def test_mode_final_des_sockets(masque):
    ancien = os.umask(masque)
    try:
        with monter() as banc:
            for section in ('sessions', 'relay'):
                mode = os.stat(banc.config[section]['socket']).st_mode & 0o777
                assert mode == 0o660
    finally:
        os.umask(ancien)


@pytest.mark.parametrize('longueur,accepte', [(16, True), (256, True), (15, False), (257, False)])
def test_limites_du_jeton(banc, longueur, accepte):
    banc.etat_r['open'] = {'session': 1, 'token': 'a' * longueur}
    resultat = ouvrir(banc.client())
    assert resultat['ok'] is accepte
    if not accepte:
        assert code(resultat) == 'peer_unavailable'


def test_fermeture_romulus_pendant_open(banc):
    banc.etat_r['rompre_open'] = True
    erreurs = []
    ancien = threading.excepthook
    threading.excepthook = lambda args: erreurs.append(args)
    try:
        assert code(ouvrir(banc.client())) == 'peer_unavailable'
        pause()
    finally:
        threading.excepthook = ancien
    assert not erreurs
    assert not banc.sessions and banc._romulus is None
    assert not banc.appels_c
    assert fermetures(banc.appels_r) == []
