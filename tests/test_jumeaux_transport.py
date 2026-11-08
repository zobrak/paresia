# Tests des sockets Unix ; dépendances : pytest, bibliothèque standard, server.commun.
# Suivi des versions
#   3.0.0-alpha  2026-11-05  Pairs, résilience, délais et corrélation.
#   3.0.0-alpha  2026-11-05  Socket jamais plus ouverte que le mode final (T005, audit de sécurité).
import io
import json
import os
import socket
import threading
import tempfile
from pathlib import Path

import pytest

from server.commun.client import Connexion, PairIndisponible, appeler
from server.commun.journal import Journal
from server.commun.jumeaux import ACTIONS, decoder, encoder, lire_ligne, reponse
from server.commun.serveur import Serveur


def requete(numero=1, **champs):
    return dict({'proto': 'jumeaux/1', 'id': f'{numero:016x}', 'session': 0,
                 'action': 'presence/session/ping', 'params': {}}, **champs)


@pytest.fixture
def dossier_socket():
    # Un chemin court reste compatible avec la limite AF_UNIX des worktrees.
    with tempfile.TemporaryDirectory(prefix="jumeaux-") as dossier:
        yield Path(dossier)


@pytest.fixture
def serveur(dossier_socket):
    journal = io.StringIO()
    with Serveur(str(dossier_socket / 's'), {os.getuid()}, ACTIONS,
                 lambda q, p: reponse(q['id'], {'uid': p.uid}), gid=os.getgid(),
                 max_line=512, journal=Journal('test', flux=journal)) as instance:
        instance.capture = journal
        yield instance


def connecter(serveur):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(2)
    sock.connect(serveur.chemin)
    return sock


def recevoir(sock):
    return decoder(lire_ligne(sock))


@pytest.mark.parametrize('ligne', [b'{\n', b'[]\n', b'12\n', b'\xff\n',
                                  encoder(requete(id='invalide')),
                                  encoder(requete(id=True))])
def test_ligne_malformee(serveur, ligne):
    with connecter(serveur) as sock:
        sock.sendall(ligne)
        resultat = recevoir(sock)
        assert resultat['id'] is None
        assert resultat['error']['code'] == 'bad_request'
        sock.sendall(encoder(requete()))
        assert recevoir(sock)['ok']


def test_ligne_trop_longue(serveur):
    with connecter(serveur) as sock:
        sock.sendall(b'x' * 513)
        assert recevoir(sock)['error']['code'] == 'line_too_long'
        assert sock.recv(1) == b''
    assert appeler(serveur.chemin, requete(), 2)['ok']


def test_proto_incompatible(serveur):
    with connecter(serveur) as sock:
        sock.sendall(encoder(requete(proto='jumeaux/2')))
        resultat = recevoir(sock)
        assert resultat['id'] == requete()['id']
        assert resultat['error']['code'] == 'protocol_version_mismatch'
        assert sock.recv(1) == b''
    assert appeler(serveur.chemin, requete(), 2)['ok']


def test_correlation_id(serveur):
    with connecter(serveur) as sock:
        sock.sendall(b''.join(encoder(requete(i)) for i in range(10)))
        for i in range(10):
            assert recevoir(sock)['id'] == requete(i)['id']


def test_peercred_admis(serveur):
    assert appeler(serveur.chemin, requete(), 2)['data']['uid'] == os.getuid()
    assert os.stat(serveur.chemin).st_mode & 0o777 == 0o660


def test_peercred_refuse(dossier_socket):
    journal = io.StringIO()
    with Serveur(str(dossier_socket / 's'), set(), ACTIONS,
                 lambda *_: pytest.fail('pair refusé traité'), gid=os.getgid(),
                 journal=Journal('test', flux=journal)) as serveur:
        with connecter(serveur) as sock:
            assert sock.recv(1) == b''
    assert json.loads(journal.getvalue())['event'] == 'peer_refused'


def test_client(serveur, tmp_path):
    assert appeler(serveur.chemin, requete(), 2)['ok']
    with pytest.raises(PairIndisponible, match='^peer_unavailable$'):
        appeler(str(tmp_path / 'absente'), requete(), 0.1)


def test_client_delai(dossier_socket):
    liberation = threading.Event()
    def traiter(q, _):
        liberation.wait(2)
        return reponse(q['id'])
    with Serveur(str(dossier_socket / 's'), {os.getuid()}, ACTIONS, traiter,
                 gid=os.getgid(), journal=Journal('test', flux=io.StringIO())) as serveur:
        try:
            with pytest.raises(PairIndisponible, match='^peer_unavailable$'):
                appeler(serveur.chemin, requete(), 0.05)
        finally:
            liberation.set()


def test_client_persistant(serveur):
    with Connexion(serveur.chemin, 2) as client:
        assert client.appeler(requete())['ok']
        socket_initiale = client._socket
        assert client.appeler(requete(2))['id'] == requete(2)['id']
        assert client._socket is socket_initiale
        serveur.arreter()
        with pytest.raises(PairIndisponible, match='^peer_unavailable$'):
            client.appeler(requete(3))
        serveur.demarrer()
        with pytest.raises(PairIndisponible, match='^peer_unavailable$'):
            client.appeler(requete(4))


def test_exception_traitement(serveur):
    def traiter(*_):
        raise RuntimeError('texte qui ne doit pas sortir')
    serveur.traiter = traiter
    assert appeler(serveur.chemin, requete(), 2)['error']['code'] == 'internal_error'
    assert 'texte qui' not in serveur.capture.getvalue()


def test_socket_existante_preservee(tmp_path):
    chemin = tmp_path / 's'
    chemin.write_text('fichier existant')
    serveur = Serveur(str(chemin), {os.getuid()}, ACTIONS, lambda *_: None, gid=os.getgid())
    with pytest.raises(OSError):
        serveur.demarrer()
    assert chemin.read_text() == 'fichier existant'


class SocketMemoire:
    """Transport déterministe pour vérifier les chemins sans appel système."""
    def __init__(self, entree):
        self.entree = io.BytesIO(entree)
        self.sortie = bytearray()
        self.fermee = False

    def recv_into(self, destination):
        return self.entree.readinto(destination)

    def sendall(self, contenu):
        self.sortie.extend(contenu)

    def close(self):
        self.fermee = True

    def settimeout(self, delai):
        assert delai > 0

    def connect(self, chemin):
        pass


@pytest.mark.parametrize('entree,code,fermeture', [
    (b'[]\n', 'bad_request', False),
    (encoder(requete(proto='jumeaux/2')), 'protocol_version_mismatch', True),
    (b'x' * 513, 'line_too_long', True),
])
def test_traitement_en_memoire(entree, code, fermeture, tmp_path):
    from server.commun.serveur import ContexteConnexion
    sock = SocketMemoire(entree + encoder(requete(2)))
    fermetures = []
    contexte = ContexteConnexion(os.getpid(), os.getuid(), os.getgid())
    serveur = Serveur(str(tmp_path / 's'), {os.getuid()}, ACTIONS,
                      lambda q, c: reponse(q['id']), gid=os.getgid(), max_line=512,
                      fermeture=fermetures.append, journal=Journal('test', flux=io.StringIO()))
    serveur._servir(sock, contexte)
    resultats = [json.loads(ligne) for ligne in sock.sortie.splitlines()]
    assert resultats[0]['error']['code'] == code
    assert len(resultats) == (1 if fermeture else 2)
    if not fermeture:
        assert resultats[1]['id'] == requete(2)['id']
    assert sock.fermee and fermetures == [contexte]


def test_client_en_memoire(monkeypatch):
    sock = SocketMemoire(encoder(reponse(requete()['id'])) + encoder(reponse(requete(2)['id'])))
    creations = []
    def creer(*_):
        creations.append(sock)
        return sock
    monkeypatch.setattr(socket, 'socket', creer)
    with Connexion('transport-memoire', 1) as client:
        assert client.appeler(requete())['ok']
        assert client.appeler(requete(2))['ok']
        with pytest.raises(PairIndisponible, match='^peer_unavailable$'):
            client.appeler(requete(3))
        with pytest.raises(PairIndisponible, match='^peer_unavailable$'):
            client.appeler(requete(4))
    assert len(creations) == 1
    assert sock.fermee


def test_client_correlation_invalide(monkeypatch):
    from server.commun.jumeaux import ErreurProtocole
    sock = SocketMemoire(encoder(reponse(requete(2)['id'])))
    monkeypatch.setattr(socket, 'socket', lambda *_: sock)
    with Connexion('transport-memoire', 1) as client:
        with pytest.raises(ErreurProtocole):
            client.appeler(requete())
        assert sock.fermee


@pytest.mark.parametrize('champs,code', [({'inconnu': 0}, 'bad_request'),
    ({'params': {'session': 1}}, 'bad_request'), ({'action': 'inconnue'}, 'unknown_action')])
def test_refus_vraie_socket(serveur, champs, code):
    with connecter(serveur) as sock:
        sock.sendall(encoder(requete(**champs)))
        resultat = recevoir(sock)
        assert resultat['id'] == requete()['id']
        assert resultat['error']['code'] == code
        sock.sendall(encoder(requete(2)))
        assert recevoir(sock)['ok']


def test_requete_invalide_absente_journal(serveur):
    import secrets
    marqueur = secrets.token_hex(24)
    with connecter(serveur) as sock:
        sock.sendall(encoder(requete(inconnu=marqueur, params={'contenu': marqueur})))
        assert recevoir(sock)['error']['code'] == 'bad_request'
        sock.sendall(encoder(requete(2)))
        assert recevoir(sock)['ok']
    assert marqueur not in serveur.capture.getvalue()
    assert 'contenu' not in serveur.capture.getvalue()


def test_uid_serveur_vraie_socket(serveur):
    assert appeler(serveur.chemin, requete(), uid_serveur=os.getuid())['ok']
    with pytest.raises(PairIndisponible, match='^peer_unavailable$'):
        appeler(serveur.chemin, requete(), uid_serveur=os.getuid() + 1)


def test_plafond_connexions_vraie_socket(dossier_socket):
    journal = io.StringIO()
    with Serveur(str(dossier_socket / 's'), {os.getuid()}, ACTIONS,
                 lambda q, c: reponse(q['id']), gid=os.getgid(), max_connexions=1,
                 journal=Journal('test', flux=journal)) as serveur:
        with connecter(serveur) as premiere:
            premiere.sendall(encoder(requete()))
            assert recevoir(premiere)['ok']
            with connecter(serveur) as seconde:
                assert seconde.recv(1) == b''
            premiere.sendall(encoder(requete(2)))
            assert recevoir(premiere)['ok']
    assert 'connection_limit' in journal.getvalue()


@pytest.mark.parametrize('mode', [0o660, 0o600])
def test_socket_jamais_plus_ouverte_que_le_mode_final(dossier_socket, monkeypatch, mode):
    chemin = str(dossier_socket / 's')
    vus, umask_avant = [], os.umask(0o022)
    os.umask(umask_avant)
    for nom in ('chown', 'chmod'):
        reel = getattr(os, nom)

        def espion(cible, *args, _reel=reel, _nom=nom):
            vus.append((_nom, os.stat(cible).st_mode & 0o777))
            return _reel(cible, *args)
        monkeypatch.setattr(os, nom, espion)
    with Serveur(chemin, {os.getuid()}, ACTIONS, lambda q, p: reponse(q['id']), gid=os.getgid(),
                 mode=mode):
        assert os.stat(chemin).st_mode & 0o777 == mode
    # Avant chown et chmod, la socket n'a aucun droit ; l'umask du processus est restauré.
    assert vus and all(droits == 0 for _, droits in vus[:2])
    assert vus[0][0] == 'chown' and os.umask(umask_avant) == umask_avant


@pytest.mark.parametrize('mode', [0o666, 0o640 | 0o010, 0o060, True, '0600'])
def test_mode_invalide_refuse(dossier_socket, mode):
    with pytest.raises(ValueError):
        Serveur(str(dossier_socket / 's'), {os.getuid()}, ACTIONS, lambda *_: None,
                gid=os.getgid(), mode=mode)


@pytest.mark.parametrize('mode', [0o400, 0o200, 0o700, 0o000, 0o666])
def test_mode_refuse(dossier_socket, mode):
    with pytest.raises(ValueError):
        Serveur(str(dossier_socket / 's'), {os.getuid()}, ACTIONS,
                lambda *a: None, gid=os.getgid(), mode=mode)


@pytest.mark.parametrize('mode', [0o600, 0o620, 0o640, 0o660])
def test_mode_admis(dossier_socket, mode):
    Serveur(str(dossier_socket / 's'), {os.getuid()}, ACTIONS,
            lambda *a: None, gid=os.getgid(), mode=mode)


def test_serveur_ensemble_hors_actions_et_forme(dossier_socket):
    appels = []

    def traiter(q, p):
        appels.append(q['action'])
        return reponse(q['id'], {})

    with pytest.raises(ValueError, match='invalid_server_config'):
        Serveur(str(dossier_socket / 'f'), {os.getuid()}, {'exemple/1/lire'}, traiter,
                gid=os.getgid())
    with Serveur(str(dossier_socket / 's'), {os.getuid()}, {'exemple/objet/lire'}, traiter,
                 gid=os.getgid()) as instance:
        for action, attendu in (('exemple/objet/lire', True), ('exemple/objet/ecrire', False)):
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect(instance.chemin)
            sock.sendall(encoder({'proto': 'jumeaux/1', 'id': 'a123456789abcdef', 'session': 0,
                                  'action': action, 'params': {}}))
            donnees = decoder(sock.makefile('rb').readline())
            sock.close()
            assert donnees['ok'] is attendu
            if not attendu:
                assert donnees['error']['code'] == 'unknown_action'
    assert appels == ['exemple/objet/lire']


def test_connexion_actions_facultatives(dossier_socket):
    from server.commun.client import Connexion
    from server.commun.jumeaux import ErreurProtocole
    requete = {'proto': 'jumeaux/1', 'id': 'a123456789abcdef', 'session': 0,
               'action': 'exemple/objet/lire', 'params': {}}
    with Serveur(str(dossier_socket / 's'), {os.getuid()}, {'exemple/objet/lire'},
                 lambda q, p: reponse(q['id'], {}), gid=os.getgid()) as instance:
        with Connexion(instance.chemin, 2) as connexion:
            assert connexion.appeler(requete)['ok'] is True
        with Connexion(instance.chemin, 2, actions={'autre/objet/lire'}) as connexion:
            with pytest.raises(ErreurProtocole, match='unknown_action'):
                connexion.appeler(requete)
        with Connexion(instance.chemin, 2) as connexion:
            with pytest.raises(ErreurProtocole, match='unknown_action'):
                connexion.appeler(dict(requete, action='exemple/1/lire'))


def test_client_sans_ensemble_ne_passe_jamais_none(dossier_socket, monkeypatch):
    from server.commun import client
    from server.commun.jumeaux import ErreurProtocole
    vus = []
    reel = client.valider
    monkeypatch.setattr(client, 'valider',
                        lambda requete, actions: vus.append(actions) or reel(requete, actions))
    requete = {'proto': 'jumeaux/1', 'id': 'a123456789abcdef', 'session': 0,
               'action': 'exemple/objet/lire', 'params': {}}
    with Serveur(str(dossier_socket / 's'), {os.getuid()}, {'exemple/objet/lire'},
                 lambda q, p: reponse(q['id'], {}), gid=os.getgid()) as instance:
        assert appeler(instance.chemin, requete, 2)['ok'] is True
        with pytest.raises(ErreurProtocole, match='unknown_action'):
            appeler(instance.chemin, dict(requete, action='exemple/1/lire'), 2)
        with pytest.raises(ErreurProtocole, match='unknown_action'):
            appeler(instance.chemin, dict(requete, action=7), 2)
    assert vus and all(type(v) is frozenset for v in vus)
    assert vus[0] == frozenset({'exemple/objet/lire'}) and vus[1] == frozenset()
