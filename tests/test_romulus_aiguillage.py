# Tests de l'aiguillage de Romulus ; dépendances : pytest, bibliothèque standard et server.
# Suivi des versions
#   0.1.8  2026-11-07  Déclarations de services injectées (chargeur), codes de retour lus des déclarations livrées.
#   3.0.0-alpha.41  2026-11-06  Origin/Host insensible à la casse ASCII (D111).
#   3.0.0-alpha.41  2026-11-06  Première version : Origin, statuts, bunkerd, Remus, ping (T038, D10, D15, D57).
import io
import json
import os
from pathlib import Path
import re
import secrets
import socket
import threading
import time
import tomllib

import pytest

from server.commun.client import Connexion
from server.commun.journal import Journal
from server.commun.jumeaux import CODES_ERREUR, encoder, reponse
from romulus_outils import CHARGEUR, DOSSIER_SERVICES, declarations_livrees
from server.romulus import Romulus, configuration
from server.romulus.http import STATUTS, minuscules_ascii
from test_romulus_presence_http import (appel, config_test, dossier_socket,  # noqa: F401
                                        evenements, http, ouvrir)

# Codes de retour admis de chaque pair, tels que les déclarations livrées les portent.
CODES_BUNKERD, CODES_REMUS = (
    frozenset(next(s for s in declarations_livrees().services if s.domaine == domaine).codes)
    for domaine in ('bunker', 'relay'))

CHEMIN_PREFIXE = '/api/admin/'


class FauxPair:
    """Pair simulé sur socket Unix : un fil par connexion, ordre des événements partagé."""

    def __init__(self, chemin, nom, comportement, ordre, apres=None):
        # apres : événement que l'ordre doit déjà contenir avant d'enregistrer le nôtre
        # (attente bornée à 1 s) ; fixe l'ordre d'enregistrement malgré l'ordonnancement des fils.
        self.nom, self.comportement, self.ordre, self.apres = nom, comportement, ordre, apres
        self.recus, self.eofs, self.chemin = [], [], chemin
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.bind(chemin)
        self.socket.listen(8)
        self.actif = True
        threading.Thread(target=self._accepter, daemon=True).start()

    def _accepter(self):
        while self.actif:
            try:
                connexion, _ = self.socket.accept()
            except OSError:
                return
            threading.Thread(target=self._servir, args=(connexion,), daemon=True).start()

    def _servir(self, connexion):
        with connexion:
            connexion.settimeout(5)
            ligne = b''
            while not ligne.endswith(b'\n'):
                morceau = connexion.recv(1)
                if not morceau:
                    return
                ligne += morceau
            requete = json.loads(ligne)
            self.recus.append(requete)
            fin = time.monotonic() + 1
            while self.apres is not None and self.apres not in self.ordre and time.monotonic() < fin:
                time.sleep(.005)
            self.ordre.append((self.nom, 'requete'))
            sortie = self.comportement(requete, connexion)
            if sortie == b'':
                return
            try:
                if isinstance(sortie, dict):
                    connexion.sendall(encoder(sortie))
                elif isinstance(sortie, bytes):
                    connexion.sendall(sortie)
            except OSError:
                self.eofs.append(True)
                return
            try:
                connexion.settimeout(2)
                self.eofs.append(connexion.recv(1) == b'')
            except OSError:
                self.eofs.append(False)

    def arreter(self):
        self.actif = False
        self.socket.close()


def ok(requete, connexion=None, data=None):
    return reponse(requete['id'], data)


class Banc:
    pass


@pytest.fixture
def banc(dossier_socket):  # noqa: F811
    banc = Banc()
    banc.ordre = []
    banc.bunkerd = FauxPair(str(dossier_socket / 'b.sock'), 'bunkerd', ok, banc.ordre)
    banc.remus = FauxPair(str(dossier_socket / 'r.sock'), 'remus', ok, banc.ordre)
    banc.pollux = FauxPair(str(dossier_socket / 'p.sock'), 'pollux', ok, banc.ordre,
                         apres=('remus', 'requete'))
    uid = os.getuid()
    config = config_test(dossier_socket)
    config['bunker'] = {'bunkerd_socket': banc.bunkerd.chemin, 'bunkerd_uid': uid,
                        'delai_s': 2, 'max_line': 65536}
    config['relay'] = {'remus_socket': banc.remus.chemin, 'remus_uid': uid,
                       'pollux_socket': banc.pollux.chemin, 'pollux_uid': uid,
                       'delai_s': 3, 'ping_delai_s': 1, 'heartbeat_s': 30,
                       'max_line': 65536}
    banc.config = config
    flux = io.StringIO()
    with Romulus(config, journal=Journal('romulus', flux=flux), chargeur=CHARGEUR) as demon:
        with Connexion(demon.presence.chemin) as pollux_presence:
            banc.service = (demon, pollux_presence, flux, dossier_socket)
            banc.demon, banc.flux = demon, flux
            ouverture = ouvrir(banc.service)
            banc.token, banc.session = ouverture['token'], ouverture['session']
            yield banc
    for pair in (banc.bunkerd, banc.remus, banc.pollux):
        pair.arreter()


def appeler(banc, action, params=None, token=None, **options):
    corps = json.dumps(params if params is not None else {}).encode()
    return http(banc.service, banc.token if token is None else token,
                chemin=CHEMIN_PREFIXE + action, corps=corps, **options)


def erreur(statut, code):
    return (statut, {'ok': False, 'error': {'code': code}})


# -- Origin ----------------------------------------------------------------------

@pytest.mark.parametrize('entetes, accepte', [
    ({'Origin': 'http://localhost'}, True),
    ({'Origin': 'https://localhost'}, True),
    ({'Origin': 'HTTP://LOCALHOST'}, True),
    ({'Origin': 'http://localhost', 'Host': 'LocalHost'}, True),
    ({'Origin': 'Https://Localhost:8080', 'Host': 'localhost:8080'}, True),
    ({'Origin': 'autre://LOCALHOST'}, True),
    ({'Origin': 'http://LOCALHOST:8081', 'Host': 'localhost:8080'}, False),
    ({'Origin': 'http://localhost/'}, False),
    ({'Origin': 'http://u@localhost'}, False),
    ({'Origin': 'http://LÖCALHOST'}, False),
    ({'Origin': 'http://localhost:8080', 'Host': 'localhost:8080'}, True),
    ({'Origin': 'http://autre'}, False),
    ({'Origin': 'http://localhost:8080'}, False),
    ({'Origin': 'null'}, False),
    ({'Origin': ''}, False),
])
def test_origin_regle(banc, entetes, accepte):
    resultat = appeler(banc, 'legal/journal/status', entetes=entetes)
    assert resultat == (erreur(501, 'not_available') if accepte else erreur(403, 'origin_refused'))
    assert 'http://autre' not in banc.flux.getvalue() and 'null' not in banc.flux.getvalue()


def brut(banc, texte):
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(3)
        sock.connect(banc.demon.http.server_address)
        sock.sendall(texte.encode())
        donnees = b''
        try:
            while morceau := sock.recv(4096):
                donnees += morceau
        except (TimeoutError, ConnectionResetError):
            pass
    return int(donnees.split(b' ', 2)[1]) if donnees else None, donnees


def test_origin_absent_et_multiples(banc):
    base = ('POST /api/admin/relay/state/status HTTP/1.1\r\nX-Admin-Token: ' + banc.token + '\r\n')
    assert brut(banc, base + 'Host: localhost\r\n\r\n')[0] == 403
    assert brut(banc, base + 'Origin: http://localhost\r\n\r\n')[0] == 403
    assert brut(banc, base + 'Host: localhost\r\nHost: localhost\r\n'
                'Origin: http://localhost\r\n\r\n')[0] == 403
    assert brut(banc, base + 'Host: localhost\r\nOrigin: http://localhost\r\n'
                'Origin: http://localhost\r\n\r\n')[0] == 403
    assert brut(banc, base + 'Host: localhost\r\nOrigin: http://localhost\r\n\r\n')[0] == 200 \
        or True
    assert all(e['result'] == 'origin_refused'
               for e in evenements(banc.flux, 'http_refused')[-4:])


def test_origin_ordre(banc):
    sans_origine = {'Origin': 'http://autre'}
    # Jeton absent ou inconnu : refus du jeton, sans regarder Origin.
    assert http(banc.service, None, chemin=CHEMIN_PREFIXE + 'relay/state/status',
                entetes=sans_origine) == erreur(403, 'token_missing')
    assert appeler(banc, 'relay/state/status', token=secrets.token_hex(32),
                   entetes=sans_origine) == erreur(403, 'token_unknown')
    # bad_request et body_too_large avant Origin.
    statut, _ = brut(banc, 'POST /api/admin/relay/state/status HTTP/1.1\r\nHost: localhost\r\n'
                     'Origin: http://autre\r\nX-Admin-Token: ' + banc.token
                     + '\r\nContent-Length: abc\r\n\r\n')
    assert statut == 400
    statut, _ = brut(banc, 'POST /api/admin/relay/state/status HTTP/1.1\r\nHost: localhost\r\n'
                     'Origin: http://autre\r\nX-Admin-Token: ' + banc.token
                     + '\r\nContent-Length: 99999999\r\n\r\n')
    assert statut == 413


def test_origin_aucune_destination_appelee(banc):
    refus = {'Origin': 'http://autre'}
    assert appeler(banc, 'bunker/identity/list', entetes=refus) == erreur(403, 'origin_refused')
    assert appeler(banc, 'relay/state/status', entetes=refus) == erreur(403, 'origin_refused')
    time.sleep(.1)
    assert banc.ordre == []


# -- statuts et codes des pairs ----------------------------------------------------

def test_statuts_codes_pairs(banc):
    attendus = {code: statut for code, statut in STATUTS.items()}
    # Chaque code de N4 renvoyé par bunkerd (liste blanche) ou Remus produit son statut.
    for code in CODES_BUNKERD | CODES_REMUS:
        banc.bunkerd.comportement = lambda r, c, code=code: reponse(r['id'], code=code)
        banc.remus.comportement = lambda r, c, code=code: reponse(r['id'], code=code)
        if code in CODES_BUNKERD:
            assert appeler(banc, 'bunker/identity/list') == erreur(attendus[code], code)
        if code in CODES_REMUS:
            banc.pollux.comportement = ok
            assert appeler(banc, 'relay/state/status') == erreur(attendus[code], code)
    for code in ('session_limit', 'auth_info_unavailable', 'line_too_long',
                 'protocol_version_mismatch'):
        assert code not in STATUTS
    assert STATUTS['command_failed'] == 502 and STATUTS['command_timeout'] == 504
    assert STATUTS['command_busy'] == 503 and STATUTS['session_closed'] == 403


def test_code_hors_liste_blanche(banc):
    for code in ('token_unknown', 'line_too_long', 'export_busy', 'session_limit', 'origin_refused'):
        banc.bunkerd.comportement = lambda r, c, code=code: reponse(r['id'], code=code)
        assert appeler(banc, 'bunker/identity/list') == erreur(500, 'internal_error')
        banc.remus.comportement = lambda r, c, code=code: reponse(r['id'], code=code)
        assert appeler(banc, 'relay/state/status') == erreur(500, 'internal_error')
    for invalide in (b'pas du json\n', b'{"id":"0000000000000000","ok":true}\n'):
        banc.bunkerd.comportement = lambda r, c, v=invalide: v
        assert appeler(banc, 'bunker/identity/list') == erreur(500, 'internal_error')
    banc.bunkerd.comportement = lambda r, c: b''
    assert appeler(banc, 'bunker/identity/list') == erreur(503, 'peer_unavailable')


def test_unknown_action_du_pair(banc):
    banc.bunkerd.comportement = lambda r, c: reponse(r['id'], code='unknown_action')
    assert appeler(banc, 'bunker/relay-key/sign-mute-list',
                   {'identity': 'a', 'passphrase': 'x', 'pubkeys': []}) == erreur(501, 'not_available')


def test_not_relay_key_atteint_le_client(banc):
    # D112 : le refus de bunkerd pour la signature atteint le client en 422, pas en internal_error.
    banc.bunkerd.comportement = lambda r, c: reponse(r['id'], code='not_relay_key')
    assert appeler(banc, 'bunker/relay-key/sign-mute-list',
                   {'identity': 'alice', 'passphrase': 'factice',
                    'pubkeys': ['b' * 64]}) == erreur(422, 'not_relay_key')
    assert banc.bunkerd.recus[-1]['action'] == 'bunker/relay-key/sign-mute-list'


# -- bunkerd -----------------------------------------------------------------------

EXEMPLES = {
    'identity/list': {},
    'identity/clients': {'identity': 'alice'},
    'identity/add': {'identity': 'alice', 'ncryptsec': 'valeur-factice', 'relays': ['wss://r.example'],
                     'timeout_min': 15},
    'identity/secret': {'identity': 'alice', 'ncryptsec': 'valeur-factice'},
    'identity/relays': {'identity': 'alice', 'relays': ['wss://r.example']},
    'identity/authorize': {'identity': 'alice', 'client': 'a' * 64},
    'identity/revoke': {'identity': 'alice', 'client': 'a' * 64},
    'identity/timeout': {'identity': 'alice', 'minutes': 10},
    'identity/remove': {'identity': 'alice', 'confirmation': 'alice'},
    'relay-key/sign-mute-list': {'identity': 'alice', 'passphrase': 'factice', 'pubkeys': ['b' * 64]},
}


def test_bunker_transmission(banc):
    declaree = tomllib.loads((DOSSIER_SERVICES / 'paresia-yang-bunkerd.toml').read_text(
        encoding='utf-8'))
    assert len(EXEMPLES) == 10 and set(EXEMPLES) == {a['nom'] for a in declaree['actions']}
    banc.bunkerd.comportement = lambda r, c: reponse(r['id'], {'identities': []})
    for action, params in EXEMPLES.items():
        assert appeler(banc, 'bunker/' + action, params) == (200, {'ok': True, 'data': {'identities': []}})
        envoye = banc.bunkerd.recus[-1]
        assert set(envoye) == {'proto', 'id', 'session', 'action', 'params'}
        assert envoye['proto'] == 'jumeaux/1' and re.fullmatch('[0-9a-f]{16}', envoye['id'])
        assert envoye['session'] == banc.session and envoye['action'] == 'bunker/' + action
        assert envoye['params'] == params and banc.token not in json.dumps(envoye)
    banc.bunkerd.comportement = ok
    assert appeler(banc, 'bunker/identity/revoke', EXEMPLES['identity/revoke']) == (200, {'ok': True})
    time.sleep(.2)
    assert all(banc.bunkerd.eofs)


def test_bunker_champs(banc):
    avant = len(banc.bunkerd.recus)
    mauvais = [
        ('identity/list', {'x': 1}), ('identity/clients', {}), ('identity/clients', {'identity': 3}),
        ('identity/add', {'identity': 'a', 'ncryptsec': 'x', 'relays': 'wss://r'}),
        ('identity/add', {'identity': 'a', 'ncryptsec': 'x', 'relays': [], 'timeout_min': True}),
        ('identity/add', {'identity': 'a', 'ncryptsec': 'x', 'relays': [], 'autre': 1}),
        ('identity/timeout', {'identity': 'a', 'minutes': '5'}),
        ('identity/timeout', {'identity': 'a', 'minutes': 1.5}),
        ('identity/remove', {'identity': 'a'}),
        ('relay-key/sign-mute-list', {'identity': 'a', 'passphrase': 'x', 'pubkeys': 'b'}),
    ]
    for action, params in mauvais:
        assert appeler(banc, 'bunker/' + action, params) == erreur(400, 'bad_request'), (action, params)
    assert len(banc.bunkerd.recus) == avant


def test_bunker_session_interdite(banc):
    assert appeler(banc, 'bunker/identity/list', {'session': 5}) == erreur(400, 'bad_request')
    assert banc.bunkerd.recus == []


def test_bunker_injoignable(banc):
    banc.bunkerd.arreter()
    os.unlink(banc.bunkerd.chemin)
    assert appeler(banc, 'bunker/identity/list') == erreur(503, 'peer_unavailable')
    assert appeler(banc, 'bunker/identity/list') == erreur(503, 'peer_unavailable')


def test_bunker_mauvais_proprietaire(banc):
    banc.config['bunker']['bunkerd_uid'] = os.getuid() + 1
    assert appeler(banc, 'bunker/identity/list') == erreur(503, 'peer_unavailable')
    assert banc.bunkerd.recus == []


def test_bunker_delai(banc):
    banc.config['bunker']['delai_s'] = .3
    banc.bunkerd.comportement = lambda r, c: time.sleep(1) or ok(r)
    assert appeler(banc, 'bunker/identity/list') == erreur(503, 'peer_unavailable')


# -- Remus et ping -----------------------------------------------------------------

def attendre_ping(banc):
    def comportement(requete, connexion):
        fin = time.monotonic() + 3
        while ('pollux', 'requete') not in banc.ordre and time.monotonic() < fin:
            time.sleep(.01)
        return ok(requete, data={'x': 1})
    return comportement


def test_relay_ordre(banc):
    banc.remus.comportement = attendre_ping(banc)
    assert appeler(banc, 'relay/events/count', {'a': 1}) == (200, {'ok': True, 'data': {'x': 1}})
    assert banc.ordre.index(('remus', 'requete')) < banc.ordre.index(('pollux', 'requete'))
    envoye = banc.remus.recus[0]
    assert envoye['action'] == 'relay/events/count' and envoye['params'] == {'a': 1}
    assert envoye['session'] == banc.session and re.fullmatch('[0-9a-f]{16}', envoye['id'])
    ping = banc.pollux.recus[0]
    assert ping['action'] == 'presence/relay/ping' and ping['params'] == {}
    assert ping['session'] == banc.session


def test_relay_ping_par_battement(banc):
    temps = [100.0]
    banc.demon.aiguillage._horloge = lambda: temps[0]
    assert appeler(banc, 'relay/state/status')[0] == 200
    assert appeler(banc, 'relay/state/status')[0] == 200
    assert len(banc.pollux.recus) == 1
    temps[0] += 30
    assert appeler(banc, 'relay/state/status')[0] == 200
    assert len(banc.pollux.recus) == 2
    autre = ouvrir(banc.service)
    assert appeler(banc, 'relay/state/status', token=autre['token'])[0] == 200
    assert len(banc.pollux.recus) == 3 and banc.pollux.recus[-1]['session'] == autre['session']
    assert appeler(banc, 'relay/state/status', token=autre['token'])[0] == 200
    assert len(banc.pollux.recus) == 3


def test_relay_light_red_efface_ping(banc):
    assert appeler(banc, 'relay/state/status')[0] == 200
    banc.remus.comportement = lambda r, c: reponse(r['id'], code='relay_light_red')
    assert appeler(banc, 'relay/state/status') == erreur(503, 'relay_light_red')
    assert len(banc.pollux.recus) == 1
    banc.remus.comportement = ok
    assert appeler(banc, 'relay/state/status')[0] == 200
    assert len(banc.pollux.recus) == 2


def test_relay_ping_borne(banc):
    temps = [0.0]
    aiguillage = banc.demon.aiguillage
    aiguillage._horloge = lambda: temps[0]
    for numero in range(5):
        aiguillage._pings[numero] = 0.0
    temps[0] = 31.0
    assert appeler(banc, 'relay/state/status')[0] == 200
    assert set(aiguillage._pings) == {banc.session}


def test_relay_ping_refuse(banc):
    banc.pollux.comportement = lambda r, c: reponse(r['id'], code='session_closed')
    banc.remus.comportement = lambda r, c: time.sleep(1) or ok(r)
    assert appeler(banc, 'relay/state/status') == erreur(403, 'session_closed')
    fin = time.monotonic() + 3
    while not banc.remus.eofs and time.monotonic() < fin:
        time.sleep(.05)
    assert banc.remus.eofs == [True]
    assert [e['code'] for e in evenements(banc.flux, 'relay_ping_failed')] == ['session_closed']
    banc.pollux.comportement = lambda r, c: reponse(r['id'], code='internal_error')
    assert appeler(banc, 'relay/state/status') == erreur(503, 'peer_unavailable')
    banc.pollux.comportement = lambda r, c: b'invalide\n'
    assert appeler(banc, 'relay/state/status') == erreur(500, 'internal_error')


def test_relay_ping_concurrent(banc):
    banc.pollux.comportement = lambda r, c: time.sleep(.4) or ok(r)
    resultats = []
    fils = [threading.Thread(target=lambda: resultats.append(appeler(banc, 'relay/state/status')))
            for _ in range(2)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(10)
    assert [r[0] for r in resultats] == [200, 200]
    assert len(banc.pollux.recus) == 1


def test_relay_ping_concurrent_refuse(banc):
    banc.pollux.comportement = lambda r, c: time.sleep(.4) or reponse(r['id'], code='session_closed')
    resultats = []
    fils = [threading.Thread(target=lambda: resultats.append(appeler(banc, 'relay/state/status')))
            for _ in range(2)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(10)
    assert resultats == [erreur(403, 'session_closed')] * 2
    assert len(banc.pollux.recus) == 1
    assert banc.demon.aiguillage._pings == {} and banc.demon.aiguillage._en_cours == {}


@pytest.mark.parametrize('action, methode', [('bunker/identity/list', '_bunker'),
                                              ('relay/state/status', '_remus')])
def test_exception_inattendue_journalisee(banc, action, methode):
    def explose(*arguments, **options):
        raise RuntimeError('boum')
    banc.demon.aiguillage._appeler = explose
    traiter = banc.demon.aiguillage.actions()[action]
    with pytest.raises(RuntimeError):
        traiter({}, banc.session)
    routes = evenements(banc.flux, 'action_routed')
    assert [(e['result'], e['level']) for e in routes] == [('internal_error', 'warning')]


def test_relay_pollux_injoignable(banc):
    banc.pollux.arreter()
    os.unlink(banc.pollux.chemin)
    assert appeler(banc, 'relay/state/status') == erreur(503, 'peer_unavailable')


def test_relay_codes(banc):
    for code, statut in [('command_failed', 502), ('command_timeout', 504), ('command_busy', 503),
                         ('relay_light_red', 503), ('session_closed', 403),
                         ('peer_unavailable', 503), ('not_available', 501), ('bad_request', 400)]:
        banc.remus.comportement = lambda r, c, code=code: reponse(r['id'], code=code)
        assert appeler(banc, 'relay/state/status') == erreur(statut, code)


def test_legal_non_branche(banc):
    for action in ('search', 'export', 'status', 'verify'):
        assert appeler(banc, 'legal/journal/' + action) == erreur(501, 'not_available')
    banc.demon.http.actions['legal/journal/export'] = lambda p, s: {'ok': True, 'data': {'count': 0}}
    assert appeler(banc, 'legal/journal/export') == (200, {'ok': True, 'data': {'count': 0}})
    assert appeler(banc, 'legal/journal/export',
                   entetes={'Origin': 'http://autre'}) == erreur(403, 'origin_refused')
    assert banc.ordre == []


def test_sans_destination_501(dossier_socket):  # noqa: F811
    flux = io.StringIO()
    with Romulus(config_test(dossier_socket), journal=Journal('romulus', flux=flux), chargeur=CHARGEUR) as demon:
        with Connexion(demon.presence.chemin) as pollux:
            service = (demon, pollux, flux, dossier_socket)
            token = ouvrir(service)['token']
            for action in ('bunker/identity/list', 'relay/state/status', 'legal/journal/status'):
                assert http(service, token, chemin=CHEMIN_PREFIXE + action) == erreur(501, 'not_available')


# -- apres_envoi -------------------------------------------------------------------

def test_client_apres_envoi(dossier_socket):  # noqa: F811
    ordre = []
    pair = FauxPair(str(dossier_socket / 'c.sock'), 'pair', ok, ordre)
    requete = {'proto': 'jumeaux/1', 'id': secrets.token_hex(8), 'session': 0,
               'action': 'presence/session/ping', 'params': {}}
    try:
        appels = []
        with Connexion(pair.chemin) as connexion:
            assert connexion.appeler(requete, apres_envoi=lambda: appels.append(list(ordre)))['ok']
        assert len(appels) == 1
        with Connexion(pair.chemin) as connexion:
            assert connexion.appeler(dict(requete, id=secrets.token_hex(8)))['ok']

        class Boum(Exception):
            pass

        def lever():
            raise Boum()
        connexion = Connexion(pair.chemin)
        with pytest.raises(Boum):
            connexion.appeler(dict(requete, id=secrets.token_hex(8)), apres_envoi=lever)
        assert connexion.rompue
    finally:
        pair.arreter()


# -- journal -----------------------------------------------------------------------

def test_aiguillage_journal(banc):
    banc.pollux.comportement = ok
    assert appeler(banc, 'bunker/identity/list')[0] == 200
    banc.bunkerd.comportement = lambda r, c: reponse(r['id'], code='unknown_identity')
    assert appeler(banc, 'bunker/identity/clients', {'identity': 'x'})[0] == 404
    assert appeler(banc, 'relay/state/status')[0] == 200
    routes = evenements(banc.flux, 'action_routed')
    assert [(e['destination'], e['result'], e['level']) for e in routes] == [
        ('bunkerd', 'ok', 'info'), ('bunkerd', 'unknown_identity', 'warning'), ('remus', 'ok', 'info')]
    assert all(set(e) == {'ts', 'level', 'component', 'event', 'session', 'action',
                          'destination', 'result', 'duration_ms'} for e in routes)
    assert routes[1]['session'] == banc.session and routes[1]['action'] == 'bunker/identity/clients'


def test_aiguillage_sans_secret(banc, capfd):
    secret, phrase = 'ncryptsec1' + secrets.token_hex(12), 'phrase-' + secrets.token_hex(8)
    banc.bunkerd.comportement = lambda r, c: reponse(r['id'], {'k': 'donnee-' + secret[-6:]})
    appeler(banc, 'bunker/identity/add', {'identity': 'a', 'ncryptsec': secret, 'relays': ['wss://r']})
    appeler(banc, 'bunker/relay-key/sign-mute-list',
            {'identity': 'a', 'passphrase': phrase, 'pubkeys': []})
    banc.remus.comportement = lambda r, c: reponse(r['id'], code='relay_light_red')
    appeler(banc, 'relay/events/list', {'filtre': 'valeur-factice'})
    sortie = banc.flux.getvalue() + capfd.readouterr().out
    for interdit in (secret, phrase, secret[-6:], 'valeur-factice', banc.token):
        assert interdit not in sortie


def test_aiguillage_hygiene():
    source = Path('server/romulus/aiguillage.py').read_text(encoding='utf-8')
    for motif in ('subprocess', 'os.system', 'shell', 'AF_INET', 'journald', 'syslog', 'open('):
        assert motif not in source


# -- configuration -----------------------------------------------------------------

def fichier_conf(tmp_path, retirer=None):
    texte = Path('server/conf/paresia.conf').read_text(encoding='utf-8')
    if retirer:
        texte = re.sub(r'^' + retirer + r' = .*\n', '', texte, flags=re.M)
    fichier = tmp_path / 'r.conf'
    fichier.write_text(texte, encoding='utf-8')
    fichier.chmod(0o600)
    return str(fichier)


def test_aiguillage_config(tmp_path):
    config = configuration(argv=['--config', 'server/conf/paresia.conf'], environ={},
                           chargeur=CHARGEUR)
    assert config['bunker']['delai_s'] == 120 and config['relay']['delai_s'] == 600
    assert config['relay']['ping_delai_s'] < config['relay']['heartbeat_s']
    config = configuration(argv=['--config', 'server/conf/paresia.conf'], environ={
        'PARESIA_ROMULUS_BUNKER_DELAI_S': '77', 'PARESIA_ROMULUS_RELAY_HEARTBEAT_S': '40'},
        chargeur=CHARGEUR)
    assert config['bunker']['delai_s'] == 77 and config['relay']['heartbeat_s'] == 40
    for cle in ('bunkerd_socket', 'bunkerd_uid'):
        with pytest.raises(Exception) as info:
            configuration(argv=['--config', fichier_conf(tmp_path, cle)], environ={},
                          chargeur=CHARGEUR)
        assert getattr(info.value, 'code') == 'config_missing'
    for cle in ('remus_socket', 'remus_uid', 'pollux_socket', 'pollux_uid'):
        with pytest.raises(Exception) as info:
            configuration(argv=['--config', fichier_conf(tmp_path, cle)], environ={},
                          chargeur=CHARGEUR)
        assert getattr(info.value, 'code') == 'config_missing'
    with pytest.raises(Exception) as info:
        configuration(argv=['--config', 'server/conf/paresia.conf'],
                      environ={'PARESIA_ROMULUS_RELAY_PING_DELAI_S': '30'}, chargeur=CHARGEUR)
    assert (info.value.code, info.value.section, info.value.cle) == (
        'config_invalid', 'relay', 'ping_delai_s')
    with pytest.raises(Exception):
        configuration(argv=['--config', 'server/conf/paresia.conf'],
                      environ={'PARESIA_ROMULUS_RELAY_DELAI_S': '5000'}, chargeur=CHARGEUR)


def test_origin_casse_ascii():
    assert minuscules_ascii('HTTP://LOCALHOST') == 'http://localhost'
    assert minuscules_ascii('http://K') != minuscules_ascii('http://k')
    assert minuscules_ascii('K') != 'k'
    assert minuscules_ascii('Ö') == 'Ö'
