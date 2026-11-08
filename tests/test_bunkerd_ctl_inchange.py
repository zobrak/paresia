# Réponses de ctl.sock figées sur bunkerd 1.9.0 ; dépendances : pytest et bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha  2026-11-05  Première version (T005) : réponses de 1.9.0 inchangées.
import os
import socket

import pytest

from bunkerd_outils import banc, faux_ncryptsec
from server.bunkerd.ctl import commande, traiter_connexion

HEX_A = 'ab' * 32
URI = 'bunker://' + 'ab' * 32 + '?relay=wss%3A%2F%2Fr.example&secret=abc'


def cmd(b, requete, mot_de_passe=b''):
    with b.sup.lock:
        return commande(b.ops, dict(requete), bytearray(mot_de_passe))


def test_ctl_listes_et_formes(tmp_path):
    with banc(tmp_path) as b:
        assert cmd(b, {'cmd': 'list'}) == {'ok': True, 'identities': []}
        b.profil('alpha', clients=[{'pubkey': HEX_A}], timeout=1200)
        reponse = cmd(b, {'cmd': 'list'})
        assert reponse == {'ok': True, 'identities': [
            {'id': 'alpha', 'unlocked': False, 'pubkey': None, 'clients': 1,
             'relays': ['wss://relais.example'], 'timeout': 1200}]}
        assert list(reponse['identities'][0]) == ['id', 'unlocked', 'pubkey', 'clients', 'relays', 'timeout']
        assert cmd(b, {'cmd': 'unlock', 'id': 'alpha'}, b.phrase.encode()) == {'ok': True}
        item = cmd(b, {'cmd': 'list'})['identities'][0]
        assert list(item) == ['id', 'unlocked', 'pubkey', 'clients', 'relays', 'timeout', 'remaining']
        assert item['pubkey'] == 'cd' * 32 and item['unlocked'] is True
        assert cmd(b, {'cmd': 'uri', 'id': 'alpha'}) == {'ok': True, 'uri': URI}
        assert cmd(b, {'cmd': 'unlock', 'id': 'alpha'}, b'x') == {'ok': False, 'error': 'identité déjà déverrouillée'}
        assert cmd(b, {'cmd': 'lock', 'id': 'alpha'}) == {'ok': True}
        assert cmd(b, {'cmd': 'lock', 'id': 'alpha'}) == {'ok': False, 'error': 'identité déjà verrouillée'}
        assert cmd(b, {'cmd': 'uri', 'id': 'alpha'}) == {
            'ok': False, 'error': 'identité verrouillée : déverrouille-la pour obtenir son adresse'}
        assert cmd(b, {'cmd': 'clients', 'id': 'alpha'}) == {
            'ok': True, 'clients': [{'pubkey': HEX_A, 'name': '', 'url': ''}]}


def test_ctl_deverrouillage_refuse(tmp_path):
    with banc(tmp_path) as b:
        b.profil('alpha')
        assert cmd(b, {'cmd': 'unlock', 'id': 'alpha'}) == {'ok': False, 'error': 'mot de passe vide'}
        assert cmd(b, {'cmd': 'unlock', 'id': 'zzz'}, b'x') == {'ok': False, 'error': 'identité inconnue'}
        assert cmd(b, {'cmd': 'unlock', 'id': 'alpha'}, b'mauvais') == {
            'ok': False, 'error': 'déverrouillage impossible (mot de passe incorrect, ou relais injoignable)'}
        assert not b.sup.running


@pytest.mark.parametrize('requete,erreur', [
    ({'cmd': 'clients'}, "nom d'identité invalide (a-z, 0-9, - et _, 32 caractères au plus)"),
    ({'cmd': 'frobnicate', 'id': 'A'}, "nom d'identité invalide (a-z, 0-9, - et _, 32 caractères au plus)"),
    ({'cmd': 'clients', 'id': 'zzz'}, 'identité inconnue'),
    ({'cmd': 'frobnicate', 'id': 'zzz'}, 'identité inconnue'),
    ({'cmd': 'frobnicate', 'id': 'alpha'}, 'commande inconnue'),
    ({'cmd': 'timeout', 'id': 'zzz', 'minutes': 0}, 'identité inconnue'),
    ({'cmd': 'timeout', 'id': 'alpha', 'minutes': 0}, 'délai invalide (1 à 1440 minutes)'),
    ({'cmd': 'timeout', 'id': 'alpha', 'minutes': True}, 'délai invalide (1 à 1440 minutes)'),
    ({'cmd': 'add', 'id': 'alpha', 'ncryptsec': 'x', 'relays': []}, 'cette identité existe déjà'),
    ({'cmd': 'add', 'id': 'beta', 'ncryptsec': 'x', 'relays': []}, 'ncryptsec invalide'),
    ({'cmd': 'relays', 'id': 'alpha', 'relays': []}, 'indique de 1 à 10 relais'),
    ({'cmd': 'relays', 'id': 'alpha', 'relays': 'wss://r.example'}, 'indique de 1 à 10 relais'),
    ({'cmd': 'relays', 'id': 'alpha', 'relays': ['ftp://r.example']}, 'adresse de relais invalide'),
    ({'cmd': 'relays', 'id': 'alpha', 'relays': ['ws://r.example']}, 'adresse de relais invalide'),
    ({'cmd': 'secret', 'id': 'alpha', 'ncryptsec': 'x'}, 'ncryptsec invalide'),
    ({'cmd': 'authorize', 'id': 'alpha', 'client': 'npub1' + 'q' * 58},
     'clé de client invalide (64 caractères hex)'),
    ({'cmd': 'authorize', 'id': 'alpha'}, 'clé de client invalide (64 caractères hex)'),
    ({'cmd': 'revoke', 'id': 'alpha', 'client': HEX_A}, "ce client n'est pas autorisé"),
])
def test_ctl_refus(tmp_path, requete, erreur):
    with banc(tmp_path) as b:
        b.profil('alpha')
        assert cmd(b, requete) == {'ok': False, 'error': erreur}


def test_ctl_verrouillee_et_effets(tmp_path):
    with banc(tmp_path) as b:
        b.profil('alpha')
        assert cmd(b, {'cmd': 'unlock', 'id': 'alpha'}, b.phrase.encode()) == {'ok': True}
        for requete in ({'cmd': 'add', 'id': 'alpha'}, {'cmd': 'remove', 'id': 'alpha'},
                        {'cmd': 'relays', 'id': 'alpha', 'relays': ['wss://r.example']},
                        {'cmd': 'secret', 'id': 'alpha', 'ncryptsec': 'x'},
                        {'cmd': 'authorize', 'id': 'alpha', 'client': HEX_A},
                        {'cmd': 'frobnicate', 'id': 'alpha'}):
            assert cmd(b, requete) == {'ok': False, 'error': "verrouille d'abord cette identité"}
        assert cmd(b, {'cmd': 'timeout', 'id': 'alpha', 'minutes': 3}) == {'ok': True}
        b.sup.stop_identity('alpha', 'admin_request')
        assert cmd(b, {'cmd': 'authorize', 'id': 'alpha', 'client': HEX_A}) == {'ok': True}
        assert cmd(b, {'cmd': 'relays', 'id': 'alpha', 'relays': ['wss://r.example', 'ws://x.onion']}) == {'ok': True}
        assert cmd(b, {'cmd': 'add', 'id': 'beta', 'ncryptsec': faux_ncryptsec(), 'relays': ['wss://r.example'],
                       'timeout_min': 99}) == {'ok': True}
        assert b.depot.load_state()['beta'] == {'timeout': 900}          # timeout_min ignoré sur ctl.sock
        assert cmd(b, {'cmd': 'remove', 'id': 'beta', 'confirmation': 'autre'}) == {'ok': True}  # sans confirmation
        assert not b.depot.exists('beta')


@pytest.mark.skipif(os.getuid() == 0, reason='le compte de test est root')
def test_ctl_reserve_a_root(tmp_path):
    with banc(tmp_path) as b:
        serveur, client = socket.socketpair()
        client.settimeout(5)
        traiter_connexion(b.ops, serveur)
        assert client.recv(1024) == b'{"ok": false, "error": "reserve a root"}\n'
        assert any(e['event'] == 'ctl_peer_refused' for e in b.lignes_journal())
