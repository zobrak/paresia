# Tests de Romulus ; dépendances : pytest, bibliothèque standard et server.
# Suivi des versions
#   0.1.15  2026-11-08  Les chemins du domaine kernel, servis par Romulus, sont exclus du test des 501.
#   0.1.8  2026-11-07  Déclarations de services injectées ; chemins lus sur le frontal ; sections nisaba et plugins.
#   0.1.1  2026-11-07  Démarrage en échec : codes sysexits (78, 71) et champs de startup_failed.
#   3.0.0-alpha.43  2026-11-07  Envoi tolérant au refus anticipé (envoyer), test déterministe.
#   3.0.0-alpha.41  2026-11-06  Option flux_max_simultanes dans l'exemple (D111).
#   3.0.0-alpha.41  2026-11-06  Origin par défaut, sections bunker et relay de l'exemple (T038).
#   3.0.0-alpha  2026-11-05  Configuration en couches (T015) : sections [composant.domaine], exemple paresia.conf.
#   3.0.0-alpha  2026-11-05  Pollux simulé et requêtes HTTP sur sockets Unix.
#   3.0.0-alpha  2026-11-05  Renforcement (cycle 1) : journal, umask, plafonds, concurrence, pairs.
#   3.0.0-alpha  2026-11-05  Cycle 3 : concurrence prouvée par select, témoin positif, échéances, fuite de place.
#   3.0.0-alpha  2026-11-05  Source avec identifiant de zone IPv6 refusée.
#   3.0.0-alpha  2026-11-05  Cycle 4 : envoi tolérant aux coupures, marge de délai en concurrence.
import errno
import hmac
from http.client import HTTPConnection
import io
import json
import os
from pathlib import Path
import re
import select
import secrets
import socket
import stat
import struct
import threading
import time
import tempfile

import pytest

from server.commun.client import Connexion
from server.commun.journal import Journal
from server.commun.jumeaux import encoder
from romulus_outils import CHARGEUR
from server.romulus import Romulus, configuration


def config_test(tmp_path, **http):
    return {'presence': {'socket': str(tmp_path / 'presence.sock'),
            'uid_pollux': os.getuid(), 'gid': os.getgid(), 'timeout_s': 5,
            'max_line': 1024, 'max_connexions': 16, 'max_sessions': 1024},
            'http': {'socket': str(tmp_path / 'http.sock'), 'uid_lighttpd': os.getuid(),
            'gid': os.getgid(), 'timeout_s': .5, 'max_body': 65536, 'max_connexions': 64,
            'read_deadline_s': 30, 'max_headers': 100, 'max_header_bytes': 16384,
            'client_ip_header': 'X-Client-IP', 'fallback_ip': '127.0.0.1', **http}}


@pytest.fixture
def dossier_socket():
    # Les worktrees dépassent parfois la limite des chemins AF_UNIX.
    with tempfile.TemporaryDirectory(prefix='romulus-') as dossier:
        yield Path(dossier)


@pytest.fixture
def service(dossier_socket):
    tmp_path = dossier_socket
    flux = io.StringIO()
    with Romulus(config_test(tmp_path), journal=Journal('romulus', flux=flux), chargeur=CHARGEUR) as demon:
        with Connexion(demon.presence.chemin) as pollux:
            yield demon, pollux, flux, tmp_path


def appel(pollux, action='open', session=0, params=None):
    if params is None:
        params = {'admin': 'alice@example', 'source': '192.0.2.1'} if action == 'open' else {}
    return pollux.appeler({'proto': 'jumeaux/1', 'id': secrets.token_hex(8),
                          'session': session, 'action': 'presence/session/' + action,
                          'params': params})


def ouvrir(service):
    return appel(service[1])['data']


def envoyer(connexion, methode, chemin, corps, headers):
    # Un refus est rendu avant la lecture du corps, puis la connexion est fermée : l'envoi
    # du corps peut échouer alors que la réponse est déjà reçue. Seul l'envoi est protégé ;
    # l'absence de réponse se manifeste à getresponse().
    try:
        connexion.request(methode, chemin, body=corps, headers=headers)
    except (BrokenPipeError, ConnectionResetError):
        pass


def http(service, token=None, *, methode='POST', chemin='/api/admin/relay/state/status',
         corps=b'', entetes=None, delai=2):
    headers = {'Origin': 'http://localhost', **(entetes or {})}
    if token is not None:
        headers['X-Admin-Token'] = token
    sock = socket.socket(socket.AF_UNIX)
    sock.settimeout(delai)
    sock.connect(service[0].http.server_address)
    connexion = HTTPConnection('localhost')
    connexion.sock = sock
    try:
        envoyer(connexion, methode, chemin, corps, headers)
        reponse = connexion.getresponse()
        brut = reponse.read()
        return reponse.status, json.loads(brut) if brut else None
    finally:
        connexion.close()


def evenements(flux, nom=None):
    lignes = [json.loads(l) for l in flux.getvalue().splitlines()]
    return [l for l in lignes if nom is None or l['event'] == nom]


def brut(service, requete, lire=True):
    # Requête HTTP brute ; retourne (statut, octets) ou (None, b'') si fermée sans réponse.
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(3)
        sock.connect(service[0].http.server_address)
        donnees = b''
        try:
            sock.sendall(requete)
            while chunk := sock.recv(4096):
                donnees += chunk
        except (TimeoutError, ConnectionResetError, BrokenPipeError):
            pass
    return (int(donnees.split(b' ', 2)[1]) if donnees else None), donnees


def code(resultat, statut, erreur):
    assert resultat == (statut, {'ok': False, 'error': {'code': erreur}})


def test_open_jeton(service):
    a, b = ouvrir(service), ouvrir(service)
    assert a['session'] == 1 and b['session'] == 2
    assert re.fullmatch('[0-9a-f]{64}', a['token'])
    assert a['token'] != b['token']
    assert a['token'] not in repr(service[0].sessions)
    assert a['token'] not in repr(service[0].sessions._sessions)


def test_close_detruit_jeton(service):
    a = ouvrir(service)
    assert appel(service[1], 'close', a['session'])['ok']
    code(http(service, a['token']), 403, 'token_unknown')
    assert ouvrir(service)['session'] == 2


def test_close_inconnue(service):
    assert appel(service[1], 'close', 42)['error']['code'] == 'session_closed'


def attendre_refus(service, token):
    limite = time.monotonic() + 2
    while time.monotonic() < limite:
        resultat = http(service, token)
        if resultat[0] == 403:
            code(resultat, 403, 'token_unknown')
            return
        time.sleep(.01)
    pytest.fail('revocation_timeout')


def test_rupture_pollux(service):
    a, b = ouvrir(service), ouvrir(service)
    service[1].fermer()
    attendre_refus(service, a['token'])
    code(http(service, b['token']), 403, 'token_unknown')
    assert 'pollux_disconnected' in service[2].getvalue()


def test_jeton_cookie_entete(service):
    token = ouvrir(service)['token']
    code(http(service, token), 501, 'not_available')
    code(http(service, entetes={'Cookie': 'admin_token=' + token}), 501, 'not_available')
    code(http(service, token, entetes={'Cookie': 'admin_token=' + token}), 501, 'not_available')


def test_jeton_refuse(service):
    token = ouvrir(service)['token']
    code(http(service), 403, 'token_missing')
    code(http(service, secrets.token_hex(32)), 403, 'token_unknown')
    code(http(service, token, entetes={'Cookie': 'admin_token=' + secrets.token_hex(32),
                                     'X-Client-IP': '192.0.2.3'}), 400, 'token_conflict')
    refus = evenements(service[2], 'http_refused')
    assert {r['result'] for r in refus} == {'token_missing', 'token_unknown', 'token_conflict'}
    assert all(r['address'] for r in refus)
    dernier = [r for r in refus if r['result'] == 'token_conflict'][0]
    assert dernier['address'] == '192.0.2.3' and dernier['address_fallback'] is False
    manquant = [r for r in refus if r['result'] == 'token_missing'][0]
    assert manquant['address'] == '127.0.0.1' and manquant['address_fallback'] is True
    assert token not in service[2].getvalue()


def test_comparaison_temps_constant(service, monkeypatch):
    jetons = [ouvrir(service)['token'] for _ in range(3)]
    original, appels = hmac.compare_digest, []
    def comparer(a, b):
        appels.append(1)
        return original(a, b)
    monkeypatch.setattr(hmac, 'compare_digest', comparer)
    for token in [*jetons, secrets.token_hex(32), 'invalide']:
        appels.clear()
        http(service, token)
        assert len(appels) == 3


def test_jeton_non_journalise(service, capfd):
    token = ouvrir(service)['token']
    inconnu = secrets.token_hex(32)
    toutes = []
    for chemin in [*service[0].http.chemins, '/api/admin/' + token]:
        toutes.append(http(service, token, chemin=chemin, corps=json.dumps({'secret': token})))
        toutes.append(http(service, chemin=chemin, entetes={'Cookie': 'admin_token=' + token}))
        toutes.append(http(service, inconnu, chemin=chemin))
        toutes.append(http(service, token, chemin=chemin,
                           entetes={'Cookie': 'admin_token=' + inconnu}))
    assert token not in json.dumps(toutes) and inconnu not in json.dumps(toutes)
    journal = service[2].getvalue()
    sortie = capfd.readouterr()
    for secret in (token, inconnu):
        assert secret not in journal and secret not in sortie.out and secret not in sortie.err
    # En-têtes de réponse : ni jeton ni Set-Cookie.
    statut, donnees = brut(service, ('POST /api/admin/relay/state/status HTTP/1.1\r\n'
                                     'Host: localhost\r\nOrigin: http://localhost\r\n'
                                     'Cookie: admin_token=' + token + '\r\n\r\n').encode())
    assert statut == 501
    assert token.encode() not in donnees and b'set-cookie' not in donnees.lower()


def test_journal_requete(service):
    ouverture = ouvrir(service)
    token = ouverture['token']
    code(http(service, token, entetes={'X-Client-IP': '192.0.2.9'}), 501, 'not_available')
    code(http(service, entetes={'X-Client-IP': '192.0.2.9'}), 403, 'token_missing')
    code(http(service, secrets.token_hex(32)), 403, 'token_unknown')
    appel(service[1], 'close', ouverture['session'])
    ouvert = evenements(service[2], 'session_opened')[0]
    assert (ouvert['session'], ouvert['admin'], ouvert['source']) == (1, 'alice@example', '192.0.2.1')
    ferme = evenements(service[2], 'session_closed')[0]
    assert (ferme['session'], ferme['admin'], ferme['source']) == (1, 'alice@example', '192.0.2.1')
    requete = evenements(service[2], 'http_request')[0]
    assert requete['session'] == 1 and requete['address'] == '192.0.2.9'
    assert requete['action'] == 'relay/state/status' and requete['result'] == 'not_available'
    assert not {'token', 'cookie', 'body', 'corps'} & {k.lower() for k in requete}
    refus = {r['result']: r for r in evenements(service[2], 'http_refused')}
    assert refus['token_missing']['address'] == '192.0.2.9'
    assert refus['token_unknown']['address_fallback'] is True
    assert token not in service[2].getvalue()


@pytest.mark.parametrize('adresse', ['192.0.2.1\nFAUX', 'a\x1b[31mb', '::1%eth0'])
def test_controles_client(service, adresse):
    brutal = ('POST /api/admin/relay/state/status HTTP/1.1\r\nX-Client-IP: '
              + adresse.replace('\n', '').replace('\r', '') + '\r\n\r\n').encode('latin-1')
    brut(service, brutal)
    valeur = service[2].getvalue()
    assert '\x1b' not in valeur
    lignes = valeur.splitlines()
    assert all(json.loads(l) for l in lignes)
    refus = evenements(service[2], 'http_refused')[-1]
    assert refus['address_fallback'] is True and refus['address'] == '127.0.0.1'


def test_controles_chemin_et_admin(service):
    brut(service, b'POST /api/admin/\x1b[2Jx\x07 HTTP/1.1\r\n\r\n')
    valeur = service[2].getvalue()
    assert '\x1b' not in valeur and '\x07' not in valeur
    assert appel(service[1], params={'admin': 'a\x1b[2J', 'source': '::1'})['error']['code'] == 'bad_request'
    assert all(ord(c) >= 32 for c in service[2].getvalue().replace('\n', ''))
    assert len(service[2].getvalue().splitlines()) == len(evenements(service[2]))


def test_corps_et_longueurs(service):
    token = ouvrir(service)['token']
    code(http(service, token, corps=b''), 501, 'not_available')
    for entete in ['-1', 'abc', '1.5', '', '1 2']:
        statut, donnees = brut(service, ('POST /api/admin/relay/state/status HTTP/1.1\r\n'
                                        'X-Admin-Token: ' + token + '\r\nContent-Length: '
                                        + entete + '\r\n\r\n').encode())
        assert statut == 400 and b'bad_request' in donnees, entete
    # Content-Length absent : corps vide.
    statut, _ = brut(service, ('POST /api/admin/relay/state/status HTTP/1.1\r\n'
                               'Host: localhost\r\nOrigin: http://localhost\r\n'
                               'X-Admin-Token: ' + token + '\r\n\r\n').encode())
    assert statut == 501


def test_tous_les_chemins_501(service):
    token = ouvrir(service)['token']
    for chemin in sorted(c for c in service[0].http.chemins if '/kernel/' not in c):
        code(http(service, token, chemin=chemin), 501, 'not_available')


def test_domaine_inconnu_avec_jeton(service):
    token = ouvrir(service)['token']
    code(http(service, token, chemin='/api/admin/autre/objet/op'), 404, 'unknown_action')


def test_jeton_formes(service):
    token = ouvrir(service)['token']
    code(http(service, entetes={'Cookie': 'a=1; admin_token=' + token + '; b=2'}), 501, 'not_available')
    code(http(service, entetes={'Cookie': 'admin_token='}), 403, 'token_unknown')
    code(http(service, entetes={'Cookie': ''}), 403, 'token_missing')
    code(http(service, entetes={'X-Admin-Token': ''}), 403, 'token_unknown')
    code(http(service, entetes={'Cookie': 'admin_token=' + token + '; admin_token=' + token}), 400, 'bad_request')


@pytest.mark.parametrize('methode', ['GET', 'HEAD', 'PUT', 'DELETE', 'OPTIONS', 'PATCH', 'AUTRE'])
def test_methodes(service, methode):
    resultat = http(service, methode=methode)
    assert resultat[0] == 405
    if methode != 'HEAD':
        code(resultat, 405, 'bad_request')


@pytest.mark.parametrize('corps', [b'[]', b'null', b'1', b'"x"', b'{', b'{"session":1}',
                                    b'{"a":1,"a":2}', b'{"a":NaN}'])
def test_requetes_invalides(service, corps):
    code(http(service, ouvrir(service)['token'], corps=corps), 400, 'bad_request')


@pytest.mark.parametrize('chemin', ['/api/admin/relay/state/inconnu', '/api/admin/presence/session/open',
                                     '/api/admin/relay/state/status?x=1', '/autre'])
def test_chemins_inconnus_avant_jeton(service, chemin):
    code(http(service, chemin=chemin), 404, 'unknown_action')


def test_corps_trop_grand(service):
    code(http(service, ouvrir(service)['token'], corps=b' ' * 65537), 413, 'body_too_large')


@pytest.mark.parametrize('adresse,repli', [('2001:db8::1', False), ('192.0.2.1', False),
                                         ('invalide', True), (None, True)])
def test_adresse_client(service, adresse, repli):
    http(service, entetes={} if adresse is None else {'X-Client-IP': adresse})
    ligne = evenements(service[2], 'http_refused')[-1]
    assert ligne['address_fallback'] is repli
    assert ligne['address'] == ('127.0.0.1' if repli else adresse)


def test_sessions_multiples(service):
    a = ouvrir(service)
    with Connexion(service[0].presence.chemin) as autre:
        b = appel(autre)['data']
        # close d'une session d'une autre connexion : comme inconnue, rien détruit.
        assert appel(autre, 'close', a['session'])['error']['code'] == 'session_closed'
        code(http(service, a['token']), 501, 'not_available')
        service[1].fermer()
        attendre_refus(service, a['token'])
        code(http(service, b['token']), 501, 'not_available')


def test_sessions_meme_connexion(service):
    a, b = ouvrir(service), ouvrir(service)
    assert a['token'] != b['token']
    code(http(service, a['token']), 501, 'not_available')
    code(http(service, b['token']), 501, 'not_available')
    assert appel(service[1], 'close', a['session'])['ok']
    code(http(service, a['token']), 403, 'token_unknown')
    code(http(service, b['token']), 501, 'not_available')
    assert appel(service[1], 'close', a['session'])['error']['code'] == 'session_closed'
    c = ouvrir(service)
    assert c['session'] == 3
    service[1].fermer()
    attendre_refus(service, c['token'])
    with Connexion(service[0].presence.chemin) as nouvelle:
        assert appel(nouvelle)['data']['session'] == 4


def test_limite_sessions(dossier_socket):
    config = config_test(dossier_socket)
    config['presence']['max_sessions'] = 2
    with Romulus(config, journal=Journal('romulus', flux=io.StringIO()), chargeur=CHARGEUR) as demon:
        with Connexion(demon.presence.chemin) as p1, Connexion(demon.presence.chemin) as p2:
            assert appel(p1)['ok'] and appel(p1)['ok']
            assert appel(p1)['error']['code'] == 'session_limit'
            assert appel(p2)['ok']


@pytest.mark.parametrize('source', ['fe80::1%eth0', 'fe80::1%\n', 'fe80::1%\x1b[31m'])
def test_source_zone_refusee(service, source):
    r = appel(service[1], params={'admin': 'alice@example', 'source': source})
    assert r['ok'] is False and r['error']['code'] == 'bad_request' and 'data' not in r
    assert service[0].sessions._sessions == {}
    assert ouvrir(service)['session'] == 1


def test_fermeture_sure(service):
    # Même si la fermeture échoue (journal défaillant), les jetons sont détruits.
    token = ouvrir(service)['token']
    sessions = service[0].sessions
    def echec(*_):
        raise OSError('x')
    sessions._journaliser = echec
    service[1].fermer()
    limite = time.monotonic() + 2
    while sessions._sessions and time.monotonic() < limite:
        time.sleep(.01)
    assert not sessions._sessions
    del sessions._journaliser
    code(http(service, token), 403, 'token_unknown')
    assert evenements(service[2], 'connection_cleanup_failed')


def test_concurrence(dossier_socket):
    flux = io.StringIO()
    config = config_test(dossier_socket, timeout_s=5)
    with Romulus(config, journal=Journal('romulus', flux=flux), chargeur=CHARGEUR) as demon:
        with Connexion(demon.presence.chemin) as pollux:
            service = (demon, pollux, flux, dossier_socket)
            token = ouvrir(service)['token']
            with socket.socket(socket.AF_UNIX) as lente:
                lente.connect(demon.http.server_address)
                lente.sendall(('POST /api/admin/relay/state/status HTTP/1.1\r\n'
                               'Host: localhost\r\nOrigin: http://localhost\r\n'
                               'X-Admin-Token: ' + token + '\r\nContent-Length: 20\r\n\r\n{').encode())
                resultats = []
                def client():
                    resultats.append(http(service, token, delai=8))
                fils = [threading.Thread(target=client) for _ in range(8)]
                for fil in fils:
                    fil.start()
                for fil in fils:
                    fil.join(10)
                assert resultats == [(501, {'ok': False, 'error': {'code': 'not_available'}})] * 8
                # Pendant ce temps la connexion lente est restée ouverte et incomplète :
                # ni donnée ni fermeture à lire (select non bloquant).
                if select.select([lente], [], [], 0)[0]:
                    pytest.fail('connexion lente fermée ou répondue trop tôt')
                # Puis le délai de lecture la coupe.
                echeance = time.monotonic() + 10
                fin = None
                while time.monotonic() < echeance:
                    if select.select([lente], [], [], .1)[0]:
                        fin = b''
                        try:
                            while chunk := lente.recv(4096):
                                fin += chunk
                        except OSError:
                            pass
                        break
                assert fin is not None, 'connexion lente non coupée'
                assert b'400' in fin or fin == b''


def test_echeance_globale(dossier_socket):
    config = config_test(dossier_socket, timeout_s=1, read_deadline_s=.5)
    with Romulus(config, journal=Journal('romulus', flux=io.StringIO()), chargeur=CHARGEUR) as demon:
        service = (demon,)
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(4)
            sock.connect(demon.http.server_address)
            debut = time.monotonic()
            try:
                for _ in range(20):  # goutte à goutte : chaque lecture reste sous 1 s
                    sock.sendall(b'X')
                    time.sleep(.2)
            except OSError:
                pass
            assert time.monotonic() - debut < 3


def test_plafond_connexions_http(dossier_socket):
    flux = io.StringIO()
    config = config_test(dossier_socket, max_connexions=2, timeout_s=3)
    with Romulus(config, journal=Journal('romulus', flux=flux), chargeur=CHARGEUR) as demon:
        ouvertes = []
        try:
            for _ in range(2):
                s1 = socket.socket(socket.AF_UNIX)
                s1.connect(demon.http.server_address)
                s1.sendall(b'POST /api')
                ouvertes.append(s1)
            # Les deux places sont prises quand un excédent est refusé (échéance, pas de pause fixe).
            echeance = time.monotonic() + 10
            refuse = False
            while time.monotonic() < echeance and not refuse:
                exces = socket.socket(socket.AF_UNIX)
                ouvertes.append(exces)
                exces.settimeout(2)
                exces.connect(demon.http.server_address)
                try:
                    refuse = exces.recv(10) == b''
                except OSError:
                    refuse = True
                if not refuse:
                    time.sleep(.02)
            assert refuse
            assert evenements(flux, 'http_connection_limit')
            # Une place libérée est réutilisable.
            ouvertes[0].close()
            echeance = time.monotonic() + 10
            debut = b''
            while time.monotonic() < echeance and not debut.startswith(b'HTTP/1.1 405'):
                with socket.socket(socket.AF_UNIX) as nouveau:
                    nouveau.settimeout(2)
                    nouveau.connect(demon.http.server_address)
                    try:
                        nouveau.sendall(b'GET / HTTP/1.1\r\n\r\n')
                        debut = nouveau.recv(12)
                    except OSError:
                        debut = b''
                if not debut:
                    time.sleep(.02)
            assert debut.startswith(b'HTTP/1.1 405')
        finally:
            for sock in ouvertes:
                sock.close()


def test_entetes_bornes(dossier_socket):
    config = config_test(dossier_socket, max_headers=5, max_header_bytes=300)
    with Romulus(config, journal=Journal('romulus', flux=io.StringIO()), chargeur=CHARGEUR) as demon:
        service = (demon,)
        trop = b''.join(b'H%d: x\r\n' % i for i in range(8))
        statut, donnees = brut(service, b'POST /api/admin/relay/state/status HTTP/1.1\r\n' + trop + b'\r\n')
        assert statut == 400 and b'bad_request' in donnees
        gros = b'X-A: ' + b'a' * 400 + b'\r\n'
        statut, donnees = brut(service, b'POST /api/admin/relay/state/status HTTP/1.1\r\n' + gros + b'\r\n')
        assert statut == 400 and b'bad_request' in donnees
        statut, _ = brut(service, b'GET / HTTP/1.1\r\nA: b\r\n\r\n')
        assert statut == 405


def test_peercred_romulus(dossier_socket):
    # Pollux et lighttpd ont des uid distincts, tous deux différents du nôtre
    # pour le refus ; les refus croisés se testent avec des uid factices.
    uid = os.getuid()
    flux = io.StringIO()
    # Cas 1 : seule la socket de présence est refusée.
    config = config_test(dossier_socket)
    config['presence']['uid_pollux'] = uid + 1
    with Romulus(config, journal=Journal('romulus', flux=flux), chargeur=CHARGEUR) as demon:
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(2)
            sock.connect(config['presence']['socket'])
            assert sock.recv(1) == b''
        # La socket HTTP (uid_lighttpd = nous) répond encore.
        assert brut((demon,), b'GET / HTTP/1.1\r\n\r\n')[0] == 405
    # Cas 2 : seule la socket HTTP est refusée ; la présence reste servie.
    config = config_test(dossier_socket, uid_lighttpd=uid + 1)
    with Romulus(config, journal=Journal('romulus', flux=flux), chargeur=CHARGEUR) as demon:
        assert brut((demon,), b'GET / HTTP/1.1\r\n\r\n') == (None, b'')
        with Connexion(config['presence']['socket']) as pollux:
            assert appel(pollux)['ok']
        assert brut((demon,), b'GET / HTTP/1.1\r\n\r\n') == (None, b'')
    # Cas 3 : les deux refusées, démon vivant ensuite.
    config = config_test(dossier_socket, uid_lighttpd=uid + 1)
    config['presence']['uid_pollux'] = uid + 2
    with Romulus(config, journal=Journal('romulus', flux=flux), chargeur=CHARGEUR) as demon:
        for chemin in [config['presence']['socket'], config['http']['socket']]:
            for _ in range(2):
                with socket.socket(socket.AF_UNIX) as sock:
                    sock.settimeout(2)
                    sock.connect(chemin)
                    assert sock.recv(1) == b''
        assert demon.http._fil.is_alive() and demon.presence._fil.is_alive()
    assert evenements(flux, 'peer_refused') and evenements(flux, 'http_peer_refused')
    assert 'token' not in flux.getvalue()


def test_robustesse_romulus(service):
    base = {'proto': 'jumeaux/1', 'id': secrets.token_hex(8), 'session': 0,
            'action': 'presence/session/open', 'params': {'admin': 'a', 'source': '::1'}}
    cas = [(b'invalide\n', 'bad_request'),
           (encoder({**base, 'action': 'presence/relay/ping'}), 'unknown_action'),
           (encoder({**base, 'inconnu': 1}), 'bad_request'),
           (encoder({**base, 'proto': 'jumeaux/2'}), 'protocol_version_mismatch'),
           (b'x' * 1025 + b'\n', 'line_too_long')]
    for contenu, erreur in cas:
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(2)
            sock.connect(service[0].presence.chemin)
            sock.sendall(contenu)
            with sock.makefile('rb') as flux:
                assert json.loads(flux.readline())['error']['code'] == erreur
        assert ouvrir(service)['session'] > 0


@pytest.mark.parametrize('params', [{'admin': '', 'source': '::1'}, {'admin': 'a' * 65, 'source': '::1'},
                                  {'admin': 'a\n', 'source': '::1'}, {'admin': 'a', 'source': 'non'},
                                  {'admin': 'a', 'source': 1}, {'admin': 'a'},
                                  {'admin': 'a', 'source': '::1', 'autre': 1}])
def test_open_invalide(service, params):
    assert appel(service[1], params=params)['error']['code'] == 'bad_request'


def test_jeton_pas_sur_disque(service, monkeypatch, tmp_path):
    monkeypatch.setenv('TMPDIR', str(tmp_path))
    jetons = []
    trouves = []
    def balayer():
        racines = {service[3], tmp_path, Path.cwd(), Path(tempfile.gettempdir())}
        for racine in racines:
            for fichier in racine.rglob('*'):
                try:
                    if fichier.is_file() and not fichier.is_symlink() and fichier.stat().st_size < 10**7:
                        contenu = fichier.read_bytes()
                        for t in jetons:
                            if t.encode() in contenu:
                                trouves.append(fichier)
                except OSError:
                    pass
        resultat = list(trouves)
        trouves.clear()
        return resultat
    a = ouvrir(service)
    jetons.append(a['token'])
    # Témoin positif : un fichier contenant le jeton doit être détecté.
    temoin = tmp_path / 'temoin.txt'
    temoin.write_text(a['token'])
    assert temoin in balayer()
    temoin.unlink()
    assert not balayer()
    http(service, a['token'])
    assert not balayer()
    appel(service[1], 'close', a['session'])
    assert not balayer()
    b = ouvrir(service)
    jetons.append(b['token'])
    service[1].fermer()
    attendre_refus(service, b['token'])
    assert not balayer()


def test_modes_sockets(service):
    for chemin in [service[0].presence.chemin, service[0].http.server_address]:
        assert stat.S_IMODE(os.stat(chemin).st_mode) == 0o660
        assert os.stat(chemin).st_gid == os.getgid()


@pytest.mark.parametrize('masque', [0o000, 0o077])
def test_modes_sockets_umask(dossier_socket, masque):
    ancien = os.umask(masque)
    try:
        with Romulus(config_test(dossier_socket), journal=Journal('romulus', flux=io.StringIO()), chargeur=CHARGEUR) as demon:
            courant = os.umask(masque)
            assert courant == masque  # umask restauré après le bind
            for chemin in [demon.presence.chemin, demon.http.server_address]:
                assert stat.S_IMODE(os.stat(chemin).st_mode) == 0o660
    finally:
        os.umask(ancien)


def test_socket_residuelle(dossier_socket):
    config = config_test(dossier_socket)
    residu = Path(config['http']['socket'])
    residu.touch()
    with pytest.raises(OSError):
        Romulus(config, journal=Journal('romulus', flux=io.StringIO()), chargeur=CHARGEUR).demarrer()
    assert residu.exists()  # jamais supprimée
    residu.unlink()
    with Romulus(config, journal=Journal('romulus', flux=io.StringIO()), chargeur=CHARGEUR):
        pass
    assert not Path(config['presence']['socket']).exists()


def test_conf_exemple_romulus():
    config = configuration(argv=['--config', 'server/conf/paresia.conf'], environ={}, chargeur=CHARGEUR)
    attendu = {'presence': {'socket', 'uid_pollux', 'gid', 'timeout_s', 'max_line',
                            'max_connexions', 'max_sessions'},
               'http': {'socket', 'uid_lighttpd', 'gid', 'timeout_s', 'max_body',
                        'max_connexions', 'read_deadline_s', 'max_headers',
                        'max_header_bytes', 'client_ip_header', 'fallback_ip',
                        'export_max_octets', 'export_max_simultanes'},
               'bunker': {'bunkerd_socket', 'bunkerd_uid', 'delai_s', 'max_line'},
               'relay': {'remus_socket', 'remus_uid', 'pollux_socket', 'pollux_uid', 'delai_s',
                         'ping_delai_s', 'heartbeat_s', 'max_line', 'flux_max_simultanes'},
               # Sections ajoutées par les déclarations livrées et par les dossiers de déclarations.
               'nisaba': {'socket', 'uid', 'delai_s', 'max_line'},
               'plugins': {'livrees', 'locales'},
               'activite': {'detail', 'taille_max', 'dossier', 'regroupement_max',
                            'regroupements_simultanes'},
               'noyau': {'dossier_etat'}}
    # Sections du socle commun (journal, métriques) ajoutées à celles du démon.
    attendu = {**attendu, 'journal': {'niveau'}, 'metriques': {'actif', 'dossier', 'periode_s'}}
    assert {k: set(v) for k, v in config.items()} == attendu
    texte = Path('server/conf/paresia.conf').read_text(encoding='utf-8')
    for cle in attendu['http'] | attendu['presence'] | attendu['bunker'] | attendu['relay']:
        assert re.search(r'^' + cle + r' = ', texte, re.M)
    assert config['http']['max_body'] == 65536
    config = configuration(argv=['--config', 'server/conf/paresia.conf'],
                           environ={'PARESIA_ROMULUS_HTTP_MAX_BODY': '128'}, chargeur=CHARGEUR)
    assert config['http']['max_body'] == 128


def test_conf_plafond_http_refuse(tmp_path):
    ini = Path('server/conf/paresia.conf').read_text(encoding='utf-8')
    fichier = tmp_path / 'r.ini'
    fichier.write_text(ini, encoding='utf-8')
    fichier.chmod(0o600)
    with pytest.raises(Exception):
        configuration(argv=['--config', str(fichier)],
                      environ={'PARESIA_ROMULUS_HTTP_MAX_CONNEXIONS': '2000'}, chargeur=CHARGEUR)


def test_startup_failed_cause(tmp_path, capfd):
    from server.romulus.__main__ import main
    import server.romulus.__main__ as m
    ini = tmp_path / 'r.ini'
    ini.write_text(Path('server/conf/paresia.conf').read_text(encoding='utf-8'), encoding='utf-8')
    ini.chmod(0o600)
    env = dict(os.environ)
    os.environ['PARESIA_ROMULUS_HTTP_FALLBACK_IP'] = 'valeur-secrete-xyz'
    os.environ['PARESIA_ROMULUS_CONFIG'] = str(ini)
    try:
        m.configuration = lambda **_: configuration(argv=['--config', str(ini)], chargeur=CHARGEUR)
        assert main() == 78
    finally:
        os.environ.clear(); os.environ.update(env)
        from server.romulus import configuration as origine
        m.configuration = origine
    sortie = capfd.readouterr().out
    ligne = json.loads(sortie.splitlines()[-1])
    assert ligne['event'] == 'startup_failed' and ligne['cause'] == 'config_invalid'
    assert ligne['section'] == 'http' and ligne['option'] == 'fallback_ip'
    assert 'valeur-secrete-xyz' not in sortie


def test_startup_failed_oserror(dossier_socket, capfd, monkeypatch):
    import server.romulus.__main__ as m
    config = config_test(dossier_socket)
    Path(config['presence']['socket']).touch()
    monkeypatch.setattr(m, 'configuration', lambda **_: config)
    assert m.main() == 71
    ligne = json.loads(capfd.readouterr().out.splitlines()[-1])
    assert ligne['event'] == 'startup_failed'
    assert ligne['cause'] == 'os_error' and ligne['errno'] == errno.EADDRINUSE
    assert set(ligne) <= {'ts', 'level', 'component', 'event', 'cause', 'section', 'option', 'errno'}


def test_verify_request_settimeout_ne_perd_pas_de_place(dossier_socket):
    config = config_test(dossier_socket, max_connexions=1)
    with Romulus(config, journal=Journal('romulus', flux=io.StringIO()), chargeur=CHARGEUR) as demon:
        class Casse:
            def getsockopt(self, *args):
                return struct.pack('3i', 1, os.getuid(), os.getgid())
            def settimeout(self, delai):
                raise OSError('échec simulé')
        for _ in range(3):
            assert demon.http.verify_request(Casse(), None) is False
        assert demon.http._places.acquire(blocking=False)  # la seule place est toujours libre
        demon.http._places.release()


class ConnexionTardive(HTTPConnection):
    # Envoie les en-têtes, puis retient le corps jusqu'à ce que le serveur ait fermé.
    def __init__(self, ferme):
        super().__init__('localhost')
        self.ferme = ferme
        self.envois = 0

    def send(self, donnees):
        self.envois += 1
        if self.envois > 1:
            assert self.ferme.wait(3)
        super().send(donnees)


def test_refus_avant_corps_puis_fermeture(service, monkeypatch):
    """Refus rendu avant lecture du corps : l'envoi tardif du corps échoue, la réponse reste lisible."""
    demon = service[0]
    ferme = threading.Event()
    origine = demon.http.shutdown_request

    def fermer(requete):
        origine(requete)
        ferme.set()

    monkeypatch.setattr(demon.http, 'shutdown_request', fermer)
    entetes = {'Origin': 'http://localhost', 'X-Admin-Token': 'jeton-invalide'}

    def ouvrir_connexion():
        ferme.clear()
        sock = socket.socket(socket.AF_UNIX)
        sock.settimeout(3)
        sock.connect(demon.http.server_address)
        connexion = ConnexionTardive(ferme)
        connexion.sock = sock
        return connexion

    brute = ouvrir_connexion()
    try:
        with pytest.raises((BrokenPipeError, ConnectionResetError)):
            brute.request('POST', '/api/admin/relay/state/status', body=b'{}', headers=entetes)
    finally:
        brute.close()
    tolerante = ouvrir_connexion()
    try:
        envoyer(tolerante, 'POST', '/api/admin/relay/state/status', b'{}', entetes)
        assert tolerante.getresponse().status == 403
    finally:
        tolerante.close()
