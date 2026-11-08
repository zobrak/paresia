# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests du suivi HTTP ; dépendances : pytest, bibliothèque standard et server.
# Suivi des versions
#   0.1.8  2026-11-07  Déclarations de services injectées ; action de suivi nommée dans le test.
#   3.0.0-alpha.43  2026-11-07  Envoi tolérant au refus anticipé des requêtes.
#   3.0.0-alpha.41  2026-11-06  Flux, fermeture, battements et transport (D10, D85, D111).
from contextlib import contextmanager
from http.client import HTTPConnection
import json
import socket
import threading
import time

import pytest

from server.commun.client import Connexion
from server.commun.config import ErreurConfiguration
from server.commun.jumeaux import encoder, reponse
from romulus_outils import CHARGEUR
from server.romulus import configuration
from server.romulus.flux import BATTEMENT, evenement
from server.romulus.http import STATUTS
from test_romulus_aiguillage import banc, appeler, erreur  # noqa: F401
from test_romulus_presence_http import appel, dossier_socket, envoyer, evenements  # noqa: F401

ACTION_SUIVI = 'relay/state/follow'


@pytest.fixture
def suivi(banc):
    banc.config['relay'].update(heartbeat_s=.12, ping_delai_s=.03)
    return banc


def attendre(condition, delai=2):
    fin = time.monotonic() + delai
    while not condition():
        assert time.monotonic() < fin
        time.sleep(.005)


def tenir(requete, connexion):
    """Une première ligne, puis silence jusqu'à fermeture du transport."""
    try:
        connexion.sendall(encoder(reponse(requete['id'], {'ligne': 1}, stream='line')))
        assert connexion.recv(1) == b''
    except OSError:
        pass
    return b''


def emettre(*lignes):
    def comportement(requete, connexion):
        try:
            for ligne in lignes:
                connexion.sendall(encoder({'id': requete['id'], **ligne}))
        except OSError:
            pass
        return None
    return comportement


def socket_http(b):
    sock = socket.socket(socket.AF_UNIX)
    sock.settimeout(3)
    sock.connect(b.demon.http.server_address)
    return sock


@contextmanager
def client(b, **entetes):
    connexion = HTTPConnection('localhost')
    connexion.sock = socket_http(b)
    try:
        envoyer(connexion, 'POST', '/api/admin/' + ACTION_SUIVI, b'{}', {
            'Origin': 'http://localhost', 'X-Admin-Token': b.token, **entetes})
        resultat = connexion.getresponse()
        try:
            yield resultat
        finally:
            resultat.close()
    finally:
        connexion.close()


def bloc(resultat):
    lignes = []
    while ligne := resultat.fp.readline():
        lignes.append(ligne)
        if ligne == b'\n':
            break
    return b''.join(lignes)


def libere(b, objets=()):
    attendre(lambda: not b.demon.http._flux)
    assert not b.demon.sessions._abonnes
    for objet in objets:
        assert objet.termine.is_set()
        assert objet._connexion.rompue
        assert objet._fil is None or not objet._fil.is_alive()
    places = b.demon.aiguillage._places_flux
    assert places.acquire(blocking=False)
    places.release()


@pytest.mark.parametrize('code', ['relay_light_red', 'session_closed', 'peer_unavailable',
                                 'bad_request', 'not_available', 'command_busy', 'origin_refused'])
def test_flux_erreur_initiale(suivi, code):
    suivi.remus.comportement = lambda r, c: reponse(r['id'], code=code)
    attendu = code if code != 'origin_refused' else 'internal_error'
    with client(suivi) as r:
        assert r.status == STATUTS[attendu]
        assert r.getheader('Content-Type') == 'application/json'
        assert json.loads(r.read()) == erreur(r.status, attendu)[1]
    libere(suivi)


def test_flux_nominal(suivi):
    suivi.remus.comportement = emettre(
        {'ok': True, 'stream': 'line', 'data': {'n': 1}},
        {'ok': True, 'stream': 'line', 'data': {'n': 2}},
        {'ok': True, 'stream': 'end'})
    with client(suivi) as r:
        assert r.status == 200
        assert dict(r.getheaders()) == {
            'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store',
            'X-Content-Type-Options': 'nosniff', 'Connection': 'close'}
        assert r.read() == b'data: {"n":1}\n\ndata: {"n":2}\n\nevent: end\ndata: {}\n\n'
    assert suivi.remus.recus[0]['session'] == suivi.session
    assert set(suivi.remus.recus[0]) == {'proto', 'id', 'action', 'params', 'session'}
    assert suivi.token not in json.dumps(suivi.remus.recus)
    libere(suivi)


def test_flux_format(suivi):
    data = {'texte': 'é\n\r\x00\x1b\t\u2028event: error'}
    suivi.remus.comportement = emettre({'ok': True, 'stream': 'line', 'data': data},
                                      {'ok': True, 'stream': 'end'})
    with client(suivi) as r:
        sortie = r.read()
    assert sortie.isascii()
    assert sortie.count(b'\n\n') == 2
    assert json.loads(sortie.split(b'\n')[0][6:]) == data
    assert b'\r' not in sortie and b'\x00' not in sortie and b'\x1b' not in sortie
    assert b'id:' not in sortie and b'retry:' not in sortie
    assert evenement({}, 'error') == b'event: error\ndata: {}\n\n'


def test_flux_ping(suivi):
    dates = []
    suivi.remus.comportement = tenir

    def ping(r, c):
        dates.append(time.monotonic())
        return reponse(r['id'])

    suivi.pollux.comportement = ping
    with client(suivi) as r:
        assert bloc(r) == b'data: {"ligne":1}\n\n'
        actifs = tuple(suivi.demon.http._flux)
        attendre(lambda: len(dates) >= 3)
        # Une commande concurrente réutilise la réservation de la session.
        suivi.remus.comportement = lambda r, c: reponse(r['id'])
        assert appeler(suivi, 'relay/state/status') == (200, {'ok': True})
        assert suivi.ordre[:2] == [('remus', 'requete'), ('pollux', 'requete')]
        assert all(b - a >= .115 for a, b in zip(dates, dates[1:]))
    libere(suivi, actifs)
    nombre = len(dates)
    time.sleep(.2)
    assert len(dates) == nombre


@pytest.mark.parametrize('initial', [False, True])
@pytest.mark.parametrize('code', ['session_closed', 'peer_unavailable'])
def test_flux_ping_refuse(suivi, code, initial):
    suivi.remus.comportement = tenir

    def refuser(r, c):
        return reponse(r['id'], code=code) if code == 'session_closed' else b''

    if initial:
        suivi.pollux.comportement = refuser
    with client(suivi) as r:
        if initial:
            assert r.status == STATUTS[code]
            assert json.loads(r.read()) == erreur(r.status, code)[1]
        else:
            assert bloc(r) == b'data: {"ligne":1}\n\n'
            suivi.pollux.comportement = refuser
            assert evenement({'code': code}, 'error') in r.read()
    libere(suivi)


def test_flux_fermeture_session(suivi):
    suivi.remus.comportement = tenir
    with client(suivi) as r:
        assert bloc(r) == b'data: {"ligne":1}\n\n'
        actifs = tuple(suivi.demon.http._flux)
        assert appel(suivi.service[1], 'close', suivi.session)['ok']
        assert r.read() == evenement({'code': 'session_closed'}, 'error')
    libere(suivi, actifs)
    assert suivi.demon.sessions.verifier(suivi.token) is None


def test_flux_fermeture_avant_premiere_ligne(suivi):
    recu = threading.Event()

    def silence(r, c):
        recu.set()
        assert c.recv(1) == b''
        return b''

    suivi.remus.comportement = silence
    with socket_http(suivi) as sock:
        sock.sendall(('POST /api/admin/' + ACTION_SUIVI + ' HTTP/1.1\r\nHost: localhost\r\n'
                      'Origin: http://localhost\r\nX-Admin-Token: ' + suivi.token + '\r\n\r\n').encode())
        assert recu.wait(1)
        sock.settimeout(.2)
        with pytest.raises(TimeoutError):
            sock.recv(1)
        assert appel(suivi.service[1], 'close', suivi.session)['ok']
        sock.settimeout(2)
        with sock.makefile('rb') as f:
            resultat = f.read()
        assert b'403' in resultat.split(b'\r\n')[0]
        assert b'text/event-stream' not in resultat
        assert json.loads(resultat.split(b'\r\n\r\n', 1)[1])['error']['code'] == 'session_closed'
    libere(suivi)


@pytest.mark.parametrize('fermeture', [False, True])
def test_sessions_abonnement(suivi, fermeture):
    sessions = suivi.demon.sessions
    session = sessions._sessions[suivi.session]
    rappels = []

    def verifier():
        # Un autre fil doit pouvoir prendre le verrou pendant le rappel.
        fini = threading.Event()
        fil = threading.Thread(target=lambda: (sessions.verifier(suivi.token), fini.set()), daemon=True)
        fil.start()
        acquis = fini.wait(1)
        fil.join(1)
        rappels.append((session.token == '', acquis))

    def echouer():
        raise RuntimeError('echec_simule')

    retire = lambda: rappels.append('retire')
    sessions.abonner(suivi.session, verifier)
    sessions.abonner(suivi.session, echouer)
    sessions.abonner(suivi.session, retire)
    sessions.desabonner(suivi.session, retire)
    if fermeture:
        suivi.service[1].fermer()
        attendre(lambda: bool(rappels))
    else:
        assert appel(suivi.service[1], 'close', suivi.session)['ok']
    assert rappels == [(True, True)]
    sessions.abonner(suivi.session, verifier)
    assert rappels == [(True, True), (True, True)]
    assert not sessions._abonnes


def test_flux_client_deconnecte(suivi):
    suivi.remus.comportement = tenir
    with client(suivi) as r:
        assert bloc(r)
        actifs = tuple(suivi.demon.http._flux)
    libere(suivi, actifs)
    assert evenements(suivi.flux, 'follow_stopped')[-1]['reason'] == 'client_disconnected'


@pytest.mark.parametrize('code', ['relay_light_red', 'command_failed', 'origin_refused'])
def test_flux_feu_rouge(suivi, code):
    suivi.remus.comportement = emettre({'ok': True, 'stream': 'line', 'data': {}},
                                      {'ok': False, 'error': {'code': code}})
    with client(suivi) as r:
        assert r.status == 200
        attendu = code if code != 'origin_refused' else 'internal_error'
        assert r.read() == evenement({}) + evenement({'code': attendu}, 'error')
    libere(suivi)
    attendu = 'light_red' if code == 'relay_light_red' else 'internal_error'
    assert evenements(suivi.flux, 'follow_stopped')[-1]['reason'] == attendu


def test_flux_plafond(suivi):
    suivi.demon.aiguillage._places_flux = threading.BoundedSemaphore(1)
    suivi.remus.comportement = tenir
    with client(suivi) as r:
        assert bloc(r)
        assert appeler(suivi, ACTION_SUIVI) == erreur(503, 'command_busy')
        assert len(suivi.remus.recus) == 1
    libere(suivi)
    suivi.remus.comportement = emettre({'ok': True, 'stream': 'end'})
    with client(suivi) as r:
        assert r.status == 200 and r.read() == evenement({}, 'end')
    libere(suivi)


def test_flux_battement(suivi):
    suite = threading.Event()

    def partiel(r, c):
        ligne = encoder(reponse(r['id'], {'suite': True}, stream='line'))
        c.sendall(encoder(reponse(r['id'], {}, stream='line')) + ligne[:12])
        assert suite.wait(2)
        c.sendall(ligne[12:] + encoder(reponse(r['id'], stream='end')))

    suivi.remus.comportement = partiel
    with client(suivi) as r:
        assert bloc(r) == evenement({})
        assert bloc(r) == BATTEMENT
        assert bloc(r) == BATTEMENT
        suite.set()
        assert r.read() == evenement({'suite': True}) + evenement({}, 'end')
    libere(suivi)


def test_flux_ecriture_bornee(suivi):
    suivi.config['relay']['max_line'] = 1048576
    suivi.demon.http.delai = .05
    termine = threading.Event()

    def abondant(r, c):
        ligne = encoder(reponse(r['id'], {'texte': 'a' * 300000}, stream='line'))
        try:
            for _ in range(40):
                c.sendall(ligne)
        except OSError:
            pass
        finally:
            termine.set()
        return b''

    suivi.remus.comportement = abondant
    with socket_http(suivi) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        sock.sendall(('POST /api/admin/' + ACTION_SUIVI + ' HTTP/1.1\r\nHost: localhost\r\n'
                      'Origin: http://localhost\r\nX-Admin-Token: ' + suivi.token + '\r\n\r\n').encode())
        attendre(lambda: bool(suivi.remus.recus))
        attendre(lambda: bool(evenements(suivi.flux, 'follow_stopped')), delai=5)
        assert termine.wait(1)
    libere(suivi)
    assert evenements(suivi.flux, 'follow_stopped')[-1]['reason'] == 'client_disconnected'


def test_flux_journal(suivi):
    suivi.remus.comportement = emettre({'ok': True, 'stream': 'line', 'data': {'texte': 'contenu_prive'}},
                                      {'ok': True, 'stream': 'end'})
    with client(suivi) as r:
        assert b'contenu_prive' in r.read()
    libere(suivi)
    texte = suivi.flux.getvalue()
    assert 'contenu_prive' not in texte and suivi.token not in texte
    debut = evenements(suivi.flux, 'follow_started')
    fin = evenements(suivi.flux, 'follow_stopped')
    assert len(debut) == len(fin) == 1
    assert debut[0]['session'] == fin[0]['session'] == suivi.session
    assert fin[0]['reason'] == 'end' and fin[0]['duration_ms'] >= 0


def test_flux_arret(suivi):
    suivi.remus.comportement = tenir
    with client(suivi) as r:
        assert bloc(r)
        actifs = tuple(suivi.demon.http._flux)
        suivi.demon.arreter()
        assert evenement({'code': 'session_closed'}, 'error') in r.read()
    libere(suivi, actifs)


@pytest.mark.parametrize('valeur', ['1', '1024', '0', '1025', '-1'])
def test_flux_config(valeur):
    options = {'argv': ['--config', 'server/conf/paresia.conf'], 'environ': {
        'PARESIA_ROMULUS_RELAY_FLUX_MAX_SIMULTANES': valeur}, 'chargeur': CHARGEUR}
    if 1 <= int(valeur) <= 1024:
        assert configuration(**options)['relay']['flux_max_simultanes'] == int(valeur)
    else:
        with pytest.raises(ErreurConfiguration):
            configuration(**options)
    assert configuration(argv=['--config', 'server/conf/paresia.conf'], environ={},
                         chargeur=CHARGEUR)['relay']['flux_max_simultanes'] == 8


def test_flux_resultat_reserve(suivi):
    action = suivi.demon.http.actions[ACTION_SUIVI]
    suivi.demon.http.actions['relay/state/status'] = action
    assert appeler(suivi, 'relay/state/status') == erreur(404, 'unknown_action')
    assert not suivi.remus.recus
    libere(suivi)


@pytest.mark.parametrize('leve', [False, True])
def test_flux_apres_envoi(suivi, leve):
    suivi.remus.comportement = emettre({'ok': True, 'stream': 'end'})
    appels = []
    echec = OSError('rappel_simule')

    def rappel():
        attendre(lambda: bool(suivi.remus.recus))
        appels.append('envoye')
        if leve:
            raise echec

    with Connexion(suivi.remus.chemin, 1) as connexion:
        requete = suivi.demon.aiguillage._enveloppe(ACTION_SUIVI, {}, suivi.session)
        if leve:
            with pytest.raises(OSError) as info:
                connexion.appeler_flux(requete, apres_envoi=rappel)
            assert info.value is echec and connexion.rompue
        else:
            lecteur = connexion.appeler_flux(requete, apres_envoi=rappel)
            assert next(lecteur)['stream'] == 'end'
            lecteur.close()
        assert appels == ['envoye']


def requete_brute(b, methode='POST', entetes=None):
    connexion = HTTPConnection('localhost')
    connexion.sock = socket_http(b)
    try:
        envoyer(connexion, methode, '/api/admin/' + ACTION_SUIVI, b'{}' if methode == 'POST' else None,
                {'Origin': 'http://localhost', **(entetes or {})})
        resultat = connexion.getresponse()
        return resultat.status, resultat.getheader('Content-Type'), resultat.read()
    finally:
        connexion.close()


@pytest.mark.parametrize('methode, entetes, statut, code', [
    ('POST', {}, 403, 'token_missing'),
    ('POST', {'X-Admin-Token': 'jeton-invalide'}, 403, 'token_unknown'),
    ('GET', 'valide', 405, 'bad_request'),
    ('POST', 'valide-origine', 403, 'origin_refused'),
])
def test_flux_refus_avant_ouverture(suivi, methode, entetes, statut, code):
    """Contrôles avant le flux : réponse JSON habituelle, jamais d'événements, Remus non appelé."""
    if entetes == 'valide':
        entetes = {'X-Admin-Token': suivi.token}
    elif entetes == 'valide-origine':
        entetes = {'X-Admin-Token': suivi.token, 'Origin': 'http://autre.example.org'}
    suivi.remus.comportement = tenir
    etat, type_contenu, corps = requete_brute(suivi, methode, entetes)
    assert etat == statut
    assert type_contenu == 'application/json'
    assert 'text/event-stream' not in (type_contenu or '')
    assert json.loads(corps) == erreur(statut, code)[1]
    assert suivi.remus.recus == []
    libere(suivi)
    assert suivi.remus.recus == []


def test_flux_rien_apres_deconnexion(suivi, monkeypatch):
    """Après la déconnexion du client, une ligne de Remus n'est pas écrite et la connexion est rompue."""
    ecritures = []
    reprise = threading.Event()
    eofs = []
    envoyee = threading.Event()

    class Enregistreur:
        def __init__(self, flux):
            self._flux = flux

        def write(self, donnees):
            ecritures.append(bytes(donnees))
            return self._flux.write(donnees)

        def __getattr__(self, nom):
            return getattr(self._flux, nom)

    classe = suivi.demon.http.RequestHandlerClass
    setup = classe.setup

    def setup_enregistre(self):
        setup(self)
        self.wfile = Enregistreur(self.wfile)

    monkeypatch.setattr(classe, 'setup', setup_enregistre)

    def attend_puis_emet(r, c):
        try:
            c.sendall(encoder(reponse(r['id'], {'ligne': 1}, stream='line')))
            reprise.wait(3)
            try:
                c.sendall(encoder(reponse(r['id'], {'ligne': 'apres_deconnexion'}, stream='line')))
            except OSError:
                pass
            envoyee.set()
            try:
                c.settimeout(2)
                eofs.append(c.recv(1) == b'')
            except OSError:
                eofs.append(True)
        except OSError:
            eofs.append(True)
        return b''

    suivi.remus.comportement = attend_puis_emet
    with client(suivi) as r:
        assert bloc(r)
        actifs = tuple(suivi.demon.http._flux)
    libere(suivi, actifs)
    assert evenements(suivi.flux, 'follow_stopped')[-1]['reason'] == 'client_disconnected'
    reprise.set()
    assert envoyee.wait(3)
    attendre(lambda: bool(eofs))
    assert eofs == [True]
    assert all(objet._connexion.rompue for objet in actifs)
    assert not any(b'apres_deconnexion' in morceau for morceau in ecritures)
    assert any(b'"ligne":1' in morceau for morceau in ecritures)
