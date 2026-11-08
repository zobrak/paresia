# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests de Pollux hors du verrou global (T010) ; dépendances : pytest et bibliothèque standard.
# Suivi des versions
#   0.1.1  2026-11-07  Lecture de l'exemple avec les sections journal et métriques du socle.
#   3.0.0-alpha.41  2026-11-06  Ouverture par défi signé (D20, D28).
#   3.0.0-alpha.32  2026-11-06  Pairs lents retenus par des événements : ordre, expirations, maximum, arrêt borné (T010).
import contextlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time
import types

import pytest

from server.commun.client import Connexion
from server.commun.config import lire
from server.commun.journal import Journal
from server.commun.jumeaux import ACTIONS, reponse
from server.commun.serveur import Serveur, ContexteConnexion
from aide_sshsig import ouverture, preparer_cles, proprietaire_root
from server.pollux import Pollux, SCHEMA, requete

ATTENTE = 5  # secondes, borne de toutes les attentes de test


def attendre(condition):
    fin = time.monotonic() + ATTENTE
    while not condition():
        assert time.monotonic() < fin, 'Échéance du test dépassée'
        time.sleep(0.005)


def fermetures(appels):
    return [q['session'] for q in appels if q['action'].endswith('/close')]


def code(resultat):
    return resultat['error']['code']


@contextlib.contextmanager
def monter(sessions=None, pair=1.5):
    """Pollux avec Romulus et Castor simulés ; hooks['r'] / hooks['c'](q, contexte) retiennent ou
    remplacent les réponses ; tenu_global liste les appels reçus alors que le verrou global était tenu."""
    with tempfile.TemporaryDirectory(prefix='pollux-') as dossier:
        flux = io.StringIO()
        journal = Journal('test', flux=flux)
        config = lire('pollux', SCHEMA, journal=True, metriques=True, argv=['--config', 'server/conf/paresia.conf'], environ={})
        for section in ('sessions', 'relay', 'romulus', 'castor'):
            config[section].update(socket=str(Path(dossier) / section), uid=os.getuid())
        for section in ('sessions', 'relay'):
            config[section]['gid'] = os.getgid()
        config['transport'].update(delai_s=8, pair_delai_s=pair, max_line=512)
        config['sessions'].update(heartbeat_s=0.2, timeout_s=3, verification_s=0.01)
        config['sessions'].update(sessions or {})
        appels_r, appels_c, tenu_global = [], [], []
        hooks, ref = {}, {}
        jeton = secrets.token_hex(32)
        compteur = [0]

        def verrou_libre():
            p = ref.get('p')
            if p is None:
                return True
            libre = p._verrou.acquire(timeout=0.5)
            if libre:
                p._verrou.release()
            return libre

        def traiter(nom, appels, q, contexte):
            appels.append(q)
            if not verrou_libre():
                tenu_global.append((nom, q['action']))
            hook = hooks.get(nom)
            return hook(q, contexte) if hook is not None else None

        def romulus(q, contexte):
            autre = traiter('r', appels_r, q, contexte)
            if autre is not None:
                return autre
            if q['action'] == 'presence/session/open':
                compteur[0] += 1
                return reponse(q['id'], {'session': compteur[0], 'token': jeton})
            return reponse(q['id'])

        def castor(q, contexte):
            autre = traiter('c', appels_c, q, contexte)
            return autre if autre is not None else reponse(q['id'])

        r = Serveur(config['romulus']['socket'], {os.getuid()}, ACTIONS, romulus,
                    gid=os.getgid(), delai=10, journal=journal).demarrer()
        c = Serveur(config['castor']['socket'], {os.getuid()}, ACTIONS, castor,
                    gid=os.getgid(), journal=journal).demarrer()
        signataire = preparer_cles(config, dossier, 'alice@site')
        droits = proprietaire_root()
        droits.start()
        try:
            p = Pollux(config, journal=journal).demarrer()
        except BaseException:
            droits.stop()      # le patch ne doit pas survivre à un démarrage refusé
            raise
        p.signataire = signataire
        ref['p'] = p
        clients = []

        def client(section='sessions'):
            connexion = Connexion(config[section]['socket'], 4)
            connexion.signataire = signataire
            clients.append(connexion)
            return connexion

        p.client = client
        p.r, p.c, p.appels_r, p.appels_c = r, c, appels_r, appels_c
        p.hooks, p.tenu_global, p.capture, p.jeton = hooks, tenu_global, flux, jeton
        try:
            yield p
        finally:
            for connexion in clients:
                connexion.fermer()
            for evenement in hooks.get('evenements', ()):
                evenement.set()
            p.arreter()
            r.arreter()
            c.arreter()
            droits.stop()


def ouvrir(client, **params):
    return ouverture(client, 'alice@site', params)


def numero(client):
    return ouvrir(client)['data']['session']


def en_fil(fonction, *args):
    sortie = []
    fil = threading.Thread(target=lambda: sortie.append(fonction(*args)), daemon=True)
    fil.start()
    return fil, sortie


def retenir(action, session=None, nom='c'):
    """Hook retenant l'action (et la session) jusqu'à `liberer` ; `entre` signale l'arrivée."""
    entre, liberer = threading.Event(), threading.Event()

    def hook(q, _):
        if q['action'] == action and (session is None or q['session'] == session):
            entre.set()
            liberer.wait(ATTENTE)
        return None

    return hook, entre, liberer


def test_castor_lent_ne_bloque_pas():
    with monter({'timeout_s': 1.0}) as banc:
        a, b, c = banc.client(), banc.client(), banc.client()
        na, nb, nc = numero(a), numero(b), numero(c)
        hook, entre, liberer = retenir('castor/light/ping', na)
        banc.hooks['c'] = hook
        banc.hooks['evenements'] = [liberer]
        fil, sortie = en_fil(banc.client('relay').appeler, requete('presence/relay/ping', na))
        assert entre.wait(ATTENTE)
        debut = time.monotonic()
        assert banc.client('relay').appeler(requete('presence/relay/ping', nb))['ok']
        d = banc.client()
        nd = numero(d)
        # a, b, d pinguent ; c n'a jamais pingué et expire pendant que le ping de a est retenu.
        while nc not in fermetures(banc.appels_c):
            assert time.monotonic() - debut < 1.4, 'expiration retardée par le pair lent'
            for client, n in ((a, na), (b, nb), (d, nd)):
                assert client.appeler(requete('presence/session/ping', n))['ok']
            time.sleep(0.05)
        assert time.monotonic() - debut < 1.4
        assert fil.is_alive()  # le ping retenu n'est pas terminé
        liberer.set()
        fil.join(ATTENTE)
        assert sortie[0]['ok']
        assert not banc.tenu_global


def test_romulus_lent_ne_bloque_pas():
    with monter() as banc:
        a, b = banc.client(), banc.client()
        n, m = numero(a), numero(b)
        hook, entre, liberer = retenir('presence/session/close', n, nom='r')
        banc.hooks['r'] = hook
        banc.hooks['evenements'] = [liberer]
        fil, sortie = en_fil(a.appeler, requete('presence/session/close', n))
        assert entre.wait(ATTENTE)
        debut = time.monotonic()
        attendre(lambda: fermetures(banc.appels_c) == [n])  # light/close non retardé
        assert b.appeler(requete('presence/session/ping', m))['ok']
        assert banc.client('relay').appeler(requete('presence/relay/ping', m))['ok']
        assert time.monotonic() - debut < 1.0
        assert fil.is_alive()
        liberer.set()
        fil.join(ATTENTE)
        assert sortie[0]['ok']


def test_ordre_ping_close():
    with monter() as banc:
        a = banc.client()
        n = numero(a)
        hook, entre, liberer = retenir('castor/light/ping', n)
        banc.hooks['c'] = hook
        banc.hooks['evenements'] = [liberer]
        ping, _ = en_fil(banc.client('relay').appeler, requete('presence/relay/ping', n))
        assert entre.wait(ATTENTE)
        # Fermeture pendant le ping en cours.
        fermeture, _ = en_fil(a.appeler, requete('presence/session/close', n))
        attendre(lambda: n not in banc.sessions)
        time.sleep(0.2)
        assert fermetures(banc.appels_c) == []  # light/close attend la fin du ping
        # Ping arrivé après la décision : refusé, jamais envoyé.
        assert code(banc.client('relay').appeler(requete('presence/relay/ping', n))) == 'session_closed'
        liberer.set()
        fermeture.join(ATTENTE)
        ping.join(ATTENTE)
        assert [q['action'] for q in banc.appels_c] == ['castor/light/ping', 'castor/light/close']


def test_session_fermee_immediate():
    with monter({'timeout_s': 0.5}) as banc:
        a = banc.client()
        n = numero(a)
        hook, entre, liberer = retenir('castor/light/close', n)
        banc.hooks['c'] = hook
        banc.hooks['evenements'] = [liberer]
        assert entre.wait(ATTENTE)  # expiration décidée, notification retenue
        debut = time.monotonic()
        assert code(banc.client().appeler(requete('presence/session/ping', n))) == 'session_closed'
        assert code(banc.client('relay').appeler(requete('presence/relay/ping', n))) == 'session_closed'
        assert code(banc.client().appeler(requete('presence/session/close', n))) == 'session_closed'
        assert time.monotonic() - debut < 0.5
        liberer.set()


def test_fermeture_une_fois():
    with monter({'timeout_s': 0.4}) as banc:
        a = banc.client()
        n = numero(a)
        hook, entre, liberer = retenir('castor/light/close', n)
        banc.hooks['c'] = hook
        banc.hooks['evenements'] = [liberer]
        assert entre.wait(ATTENTE)
        a.fermer()  # déconnexion pendant la notification d'expiration
        time.sleep(0.3)
        liberer.set()
        time.sleep(0.3)
        assert fermetures(banc.appels_c) == [n] and fermetures(banc.appels_r) == [n]
        # Deux fermetures directes simultanées d'une même session.
        b = banc.client()
        m = numero(b)
        banc.hooks.pop('c')
        fils = [threading.Thread(target=banc._fermer, args=(m, 'close')) for _ in range(2)]
        for fil in fils:
            fil.start()
        for fil in fils:
            fil.join(ATTENTE)
        assert fermetures(banc.appels_c) == [n, m] and fermetures(banc.appels_r) == [n, m]


def test_maximum_sous_concurrence():
    with monter({'maximum': 2}) as banc:
        hook, entre, liberer = retenir('presence/session/open', nom='r')
        arrivees = []

        def retient(q, contexte):
            if q['action'] == 'presence/session/open':
                arrivees.append(1)
            return hook(q, contexte)

        banc.hooks['r'] = retient
        banc.hooks['evenements'] = [liberer]
        clients = [banc.client() for _ in range(5)]
        fils = [en_fil(ouvrir, cl) for cl in clients]
        attendre(lambda: len(arrivees) == 1)  # le client Romulus sérialise ses appels (exigence 10)
        # Les trois autres sont refusées pendant que les deux premières places sont réservées.
        attendre(lambda: sum(len(s) for _, s in fils) == 3)
        assert all(code(s[0]) == 'session_limit' for _, s in fils if s)
        liberer.set()
        for fil, _ in fils:
            fil.join(ATTENTE)
        resultats = [s[0] for _, s in fils]
        assert sorted(r['ok'] for r in resultats) == [False, False, False, True, True]
        assert len(banc.sessions) == 2 and banc._reservations == 0
        # Échec côté Romulus : la place réservée est libérée.
        banc.hooks['r'] = lambda q, _: (reponse(q['id'], code='bad_request')
                                        if q['action'] == 'presence/session/open' else None)
        extra = banc.client()
        assert code(ouvrir(extra)) == 'session_limit'
        assert banc._reservations == 0 and len(banc.sessions) == 2


def test_echec_romulus_libere_reservation():
    with monter({'maximum': 1}) as banc:
        banc.hooks['r'] = lambda q, _: (reponse(q['id'], code='bad_request')
                                        if q['action'] == 'presence/session/open' else None)
        for _ in range(3):
            assert code(ouvrir(banc.client())) == 'bad_request'
        assert banc._reservations == 0
        banc.hooks.pop('r')
        assert ouvrir(banc.client())['ok']


def test_open_deconnexion_pendant():
    with monter() as banc:
        contexte = ContexteConnexion(0, os.getuid(), os.getgid())
        contexte.ferme = []
        contexte.fermer = lambda: contexte.ferme.append(1)

        def hook(q, _):
            if q['action'] == 'presence/session/open':
                banc._deconnexion(contexte)  # rupture signalée pendant l'appel à Romulus
            return None

        banc.hooks['r'] = hook
        identite = {'admin': 'alice@site', 'source': '2001:db8::1'}
        defi = banc._application(requete('presence/session/challenge', params=identite), contexte)['data']
        resultat = banc._application(requete('presence/session/open', params=dict(
            identite, signature=banc.signataire.presence(defi))), contexte)
        assert not resultat['ok'] and code(resultat) == 'session_closed'
        assert banc.jeton not in json.dumps(resultat)
        attendre(lambda: fermetures(banc.appels_r) == [1] and fermetures(banc.appels_c) == [1])
        assert not banc.sessions and banc._reservations == 0 and contexte.ferme
        assert 'reservation' not in contexte.etat and 'deconnecte' not in contexte.etat


def test_open_perte_romulus_pendant():
    with monter() as banc:
        banc.hooks['r'] = lambda q, contexte: (
            (contexte.fermer(), reponse(q['id'], {'session': 7, 'token': 'a' * 32}))[1]
            if q['action'] == 'presence/session/open' else None)
        assert code(ouvrir(banc.client())) == 'peer_unavailable'
        time.sleep(0.3)
        assert not banc.sessions and banc._romulus is None and banc._reservations == 0
        assert not banc.appels_c and fermetures(banc.appels_r) == []


def test_perte_romulus_hors_verrou():
    with monter() as banc:
        clients = [banc.client() for _ in range(3)]
        numeros = [numero(cl) for cl in clients]
        compte = []
        liberer = threading.Event()

        def hook(q, _):
            if q['action'] == 'castor/light/close':
                compte.append(q['session'])
                liberer.wait(ATTENTE)

        banc.hooks['c'] = hook
        banc.hooks['evenements'] = [liberer]
        banc.r.arreter()
        attendre(lambda: len(compte) == 3)  # les trois notifications partent en parallèle
        assert not banc.sessions  # décision terminée avant les notifications
        for cl in clients:
            assert cl._socket.recv(1) == b''
        liberer.set()
        time.sleep(0.3)
        assert sorted(compte) == sorted(numeros) and not fermetures(banc.appels_r)
        assert not banc.tenu_global


def test_pas_de_fausse_expiration():
    with monter({'timeout_s': 0.6, 'heartbeat_s': 0.2}) as banc:
        a, b = banc.client(), banc.client()
        na, nb = numero(a), numero(b)
        hook, entre, liberer = retenir('castor/light/close', nb)
        banc.hooks['c'] = hook
        banc.hooks['evenements'] = [liberer]
        while not entre.is_set():  # a pingue pendant que b expire
            assert a.appeler(requete('presence/session/ping', na))['ok']
            time.sleep(0.05)
        debut = time.monotonic()
        while time.monotonic() - debut < 1.4:  # plus de deux fois timeout_s
            assert a.appeler(requete('presence/session/ping', na))['ok']
            time.sleep(0.1)
        assert na in banc.sessions and fermetures(banc.appels_c) == [nb]
        liberer.set()


def test_arret_borne():
    pair = 0.4
    with monter({'timeout_s': 30, 'heartbeat_s': 1}, pair=pair) as banc:
        n = 4
        for _ in range(n):
            numero(banc.client())
        lib_r, lib_c = threading.Event(), threading.Event()
        banc.hooks['evenements'] = [lib_r, lib_c]
        banc.hooks['r'] = lambda q, _: lib_r.wait(ATTENTE) and None if q['action'].endswith('/close') else None
        banc.hooks['c'] = lambda q, _: lib_c.wait(ATTENTE) and None if q['action'].endswith('/close') else None
        debut = time.monotonic()
        banc.arreter()
        duree = time.monotonic() - debut
        pire_sequentiel = n * (pair + pair)
        # Borne explicite : pair_delai_s (plus la marge d'ordonnancement), loin du pire cas séquentiel.
        assert duree < pair + 0.5 and duree < pire_sequentiel
        assert banc._romulus is None
        print('arret_mesure_s=%.2f borne_s=%.2f pire_sequentiel_s=%.2f' % (duree, pair, pire_sequentiel))
        lib_r.set()
        lib_c.set()
        attendre(lambda: len(fermetures(banc.appels_c)) == n)  # une tentative par session


def test_jeton_non_journalise_hors_verrou():
    with monter() as banc:
        a = banc.client()
        numero(a)
        assert banc.jeton not in repr([vars(s) for s in banc.sessions.values()])
        banc.hooks['r'] = lambda q, _: (
            reponse(q['id'], {'session': 9, 'token': banc.jeton, 'extra': 1})
            if q['action'] == 'presence/session/open' else None)
        resultat = ouvrir(banc.client())
        assert code(resultat) == 'peer_unavailable' and banc.jeton not in json.dumps(resultat)
        attendre(lambda: not banc.sessions)
        time.sleep(0.3)
        assert banc.jeton not in banc.capture.getvalue()


def test_verrou_non_tenu_pendant_appels():
    with monter({'timeout_s': 0.6, 'heartbeat_s': 0.2}) as banc:
        a, b, c = banc.client(), banc.client(), banc.client()
        na, nb, nc = numero(a), numero(b), numero(c)
        assert banc.client('relay').appeler(requete('presence/relay/ping', na))['ok']
        a.appeler(requete('presence/session/close', na))
        attendre(lambda: nb not in banc.sessions and nc not in banc.sessions)  # expirations
        d, e = banc.client(), banc.client()
        numero(d), numero(e)
        banc.r.arreter()  # perte de Romulus
        attendre(lambda: not banc.sessions)
        time.sleep(0.3)
        assert banc.appels_r and banc.appels_c
        assert banc.tenu_global == []


def test_validation_ouverture_isolee():
    with monter() as banc:
        contexte = types.SimpleNamespace(etat={})
        valide = requete('presence/session/open', params={'admin': 'alice@site', 'source': '192.0.2.1', 'signature': 'YQ=='})
        assert banc._valider_ouverture(valide, contexte) is None
        invalide = requete('presence/session/open', params={'admin': 'a\n', 'source': '192.0.2.1'})
        assert code(banc._valider_ouverture(invalide, contexte)) == 'bad_request'
        contexte.etat['session'] = 3
        assert code(banc._valider_ouverture(valide, contexte)) == 'bad_request'
        assert not banc.appels_r and not banc.sessions


def test_commentaire_conf_hors_verrou():
    texte = Path('server/conf/paresia.conf').read_text(encoding='utf-8')
    debut = texte.index('[pollux.transport]')
    section = texte[debut:texte.index('delai_s = 120', debut)]
    assert 'maximum x pair_delai_s' in section and 'verrou global' in section
    assert 'Limite connue' not in section
    assert 'sous le verrou global' not in section or 'plus' in section
    assert not [ip for ip in re.findall(r'\b\d{1,3}(?:\.\d{1,3}){3}\b', section) if ip != '127.0.0.1']
    config = lire('pollux', SCHEMA, journal=True, metriques=True, argv=['--config', 'server/conf/paresia.conf'], environ={})
    assert config['transport']['pair_delai_s'] == 5
