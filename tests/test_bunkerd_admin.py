# Tests de la socket d'administration de bunkerd 2.0.0 ; dépendances : pytest et bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha  2026-11-05  Première version (T005) : les neuf actions, formats, conditions, concurrence.
#   3.0.0-alpha  2026-11-05  Cycle 1 : socket 0600 dès la création, compte d'uid 0, relais filtrés, max_line par défaut.
import json
import os
import secrets
import socket
import stat
import threading
import time

import pytest

from bunkerd_outils import autre_compte, banc, compte_courant, faux_ncryptsec, setfacl_simule
from server.commun.jumeaux import decoder, lire_ligne

HEX_A = 'ab' * 32
HEX_B = '12' * 32
RELAIS = ['wss://relais.example']


def ok(reponse):
    assert reponse['ok'] is True, reponse
    return reponse.get('data')


def code(reponse):
    assert reponse['ok'] is False
    return reponse['error']['code']


def echange(chemin, octets, lignes=1):
    """Envoie des octets bruts ; renvoie les réponses décodées (liste vide si fermeture)."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(5)
    resultats = []
    try:
        sock.connect(chemin)
        try:
            sock.sendall(octets)
        except OSError:
            return resultats
        for _ in range(lignes):
            try:
                ligne = lire_ligne(sock)
            except OSError:
                break
            if ligne is None:
                break
            resultats.append(decoder(ligne))
    finally:
        sock.close()
    return resultats


def ligne(**champs):
    base = {'proto': 'jumeaux/1', 'id': secrets.token_hex(8), 'session': 0,
            'action': 'bunker/identity/list', 'params': {}}
    base.update(champs)
    return (json.dumps(base) + '\n').encode()


def test_admin_peercred(tmp_path):
    with banc(tmp_path, ADMIN_ROMULUS_USER=autre_compte()) as b:
        assert b.demarrer_admin() is not None
        assert echange(b.config['admin']['socket'], ligne()) == []
        for _ in range(50):
            if any(e['event'] == 'peer_refused' for e in b.lignes_journal()):
                break
            time.sleep(0.05)
        refus = [e for e in b.lignes_journal() if e['event'] == 'peer_refused']
        assert refus and refus[0]['uid'] == os.getuid()
    (tmp_path / 'admis').mkdir()
    with banc(tmp_path / 'admis') as b:
        assert b.demarrer_admin() is not None
        assert ok(b.appeler('identity/list')) == {'identities': []}
        chemin = b.config['admin']['socket']
        assert stat.S_IMODE(os.stat(chemin).st_mode) == 0o600
        appels = open(f'{b.setfacl}.appels').read().splitlines()
        compte = compte_courant()
        assert appels == [f'-m u:{compte}:x {os.path.dirname(chemin)}', f'-m u:{compte}:rw {chemin}']


def test_admin_acl_et_compte(tmp_path):
    (tmp_path / 'a').mkdir()
    with banc(tmp_path / 'a', ADMIN_ROMULUS_USER='compte-inexistant') as b:
        assert b.demarrer_admin() is None
        assert not os.path.exists(b.config['admin']['socket'])
        assert [e for e in b.lignes_journal() if e['event'] == 'admin_disabled'][0]['reason'] == 'unknown_account'
    (tmp_path / 'b').mkdir()
    with banc(tmp_path / 'b') as b:
        setfacl_simule(b.setfacl, reussite=False)
        assert b.demarrer_admin() is None
        assert not os.path.exists(b.config['admin']['socket'])
        assert [e for e in b.lignes_journal() if e['event'] == 'admin_disabled'][0]['reason'] == 'acl_failed'
    (tmp_path / 'c').mkdir()
    with banc(tmp_path / 'c') as b:                    # socket périmée d'un arrêt brutal : remplacée
        perimee = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        perimee.bind(b.config['admin']['socket'])
        perimee.close()
        assert b.demarrer_admin() is not None
        ok(b.appeler('identity/list'))


def test_admin_enveloppe(tmp_path):
    with banc(tmp_path, ADMIN_MAX_LINE='512') as b:
        b.demarrer_admin()
        chemin = b.config['admin']['socket']
        b.profil('alpha')
        # Une même connexion survit aux lignes malformées (hors fermeture voulue).
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(chemin)
        for envoi in (b'pas du json\n', b'[1]\n', ligne(extra=1),
                      ligne(session=-1), ligne(session=True), ligne(params=[]),
                      ligne(id='zz'), ligne(action='bunker/identity/unlock'),
                      ligne(action='bunker/identity/lock'), ligne(action='bunker/identity/uri'),
                      ligne(action='bunker/relay-key/sign-mute-list'),
                      ligne(action='bunker/relay-key/sign-mute-list', params={'identity': 'alpha', 'inconnu': 1}),
                      ligne(action='presence/session/open'),
                      ligne(params={'identity': 'alpha', 'inconnu': 1}),
                      ligne(action='bunker/identity/clients'),
                      ligne(action='bunker/identity/add', params={'identity': 'x'})):
            sock.sendall(envoi)
            reponse = decoder(lire_ligne(sock))
            assert reponse['ok'] is False
            attendu = {'bad_request', 'unknown_action'}
            assert reponse['error']['code'] in attendu, (envoi, reponse)
        for envoi, attendu in ((ligne(action='bunker/identity/unlock'), 'unknown_action'),
                               (ligne(action='bunker/relay-key/sign-event'), 'unknown_action'),
                               (ligne(params={'identity': 'alpha', 'inconnu': 1}), 'bad_request')):
            sock.sendall(envoi)
            assert code(decoder(lire_ligne(sock))) == attendu
        sock.sendall(ligne(action='bunker/identity/clients', params={'identity': 'alpha'}))
        assert ok(decoder(lire_ligne(sock))) == {'clients': []}
        sock.close()
        # proto incompatible et ligne trop longue : réponse puis fermeture de cette connexion.
        reponses = echange(chemin, ligne(proto='jumeaux/2'))
        assert code(reponses[0]) == 'protocol_version_mismatch'
        reponses = echange(chemin, b'x' * 600 + b'\n')
        assert code(reponses[0]) == 'line_too_long'
        # Le démon continue.
        assert ok(b.appeler('identity/list'))['identities'][0]['identity'] == 'alpha'


def test_admin_list(tmp_path):
    with banc(tmp_path, GENERAL_RELAY_IDENTITY='beta') as b:
        b.demarrer_admin()
        b.profil('alpha', clients=[{'pubkey': HEX_A}], relais=('wss://r1.example', 'wss://r2.example'),
                 timeout=1200)
        b.profil('beta')
        liste = ok(b.appeler('identity/list'))['identities']
        assert [i['identity'] for i in liste] == ['alpha', 'beta']
        alpha, beta = liste
        assert alpha == {'identity': 'alpha', 'unlocked': False, 'pubkey': None,
                         'relays': ['wss://r1.example', 'wss://r2.example'], 'clients': 1,
                         'timeout': 1200, 'relay_key': False}
        assert beta['relay_key'] is True and beta['timeout'] == 900
        assert code(b.appeler('identity/list', {'x': 1})) == 'bad_request'
        # Déverrouillée (nak simulé) : délai restant en secondes et clé publique.
        assert b.sup.start_identity('alpha', bytearray(b.phrase.encode()))['ok']
        alpha = ok(b.appeler('identity/list'))['identities'][0]
        assert alpha['unlocked'] is True and alpha['pubkey'] == 'cd' * 32
        assert 0 < alpha['remaining'] <= 1200


def test_admin_clients(tmp_path):
    with banc(tmp_path) as b:
        b.demarrer_admin()
        b.profil('alpha', clients=[{'pubkey': HEX_A, 'name': 'app\x1b[31m', 'url': 'https://c.example/\x07'},
                                   {'pubkey': HEX_B}])
        data = ok(b.appeler('identity/clients', {'identity': 'alpha'}))
        assert data == {'clients': [
            {'pubkey': HEX_A, 'name': 'app�[31m', 'url': 'https://c.example/�'},
            {'pubkey': HEX_B, 'name': '', 'url': ''}]}
        assert code(b.appeler('identity/clients', {'identity': 'zzz'})) == 'unknown_identity'
        assert code(b.appeler('identity/clients', {'identity': 'A/../b'})) == 'invalid_identity'
        # Lecture permise sur une identité déverrouillée.
        assert b.sup.start_identity('alpha', bytearray(b.phrase.encode()))['ok']
        assert len(ok(b.appeler('identity/clients', {'identity': 'alpha'}))['clients']) == 2


def test_admin_add(tmp_path):
    with banc(tmp_path) as b:
        b.demarrer_admin()
        sec = faux_ncryptsec()
        params = {'identity': 'alpha', 'ncryptsec': sec,
                  'relays': ['wss://r1.example', 'wss://r2.example', 'wss://r1.example']}
        assert ok(b.appeler('identity/add', params)) is None
        chemin = b.depot.profile_path('alpha')
        assert json.load(open(chemin)) == {'clients': [], 'sec': sec,
                                           'relays': ['wss://r1.example', 'wss://r2.example']}
        assert stat.S_IMODE(os.stat(chemin).st_mode) == 0o600
        assert b.depot.load_state()['alpha'] == {'timeout': 900}
        assert stat.S_IMODE(os.stat(b.depot.state_file).st_mode) == 0o600
        assert code(b.appeler('identity/add', params)) == 'identity_exists'
        params = {'identity': 'beta', 'ncryptsec': sec, 'relays': RELAIS, 'timeout_min': 30}
        ok(b.appeler('identity/add', params))
        assert b.depot.load_state()['beta'] == {'timeout': 1800}
        for valeur in (0, 1441, True, '5', 1.5):
            assert code(b.appeler('identity/add', dict(params, identity='gamma', timeout_min=valeur))) \
                == 'invalid_timeout'
        assert not b.depot.exists('gamma')
        # Ordre : identité, existence, ncryptsec, relais.
        assert code(b.appeler('identity/add', {'identity': 'delta', 'ncryptsec': 'x', 'relays': []})) \
            == 'invalid_ncryptsec'
        assert code(b.appeler('identity/add', {'identity': 'Delta', 'ncryptsec': 'x', 'relays': []})) \
            == 'invalid_identity'


def test_admin_secret(tmp_path):
    with banc(tmp_path) as b:
        b.demarrer_admin()
        ancien = b.profil('alpha', clients=[{'pubkey': HEX_A}])
        etat = b.depot.load_state()
        etat['alpha'] = {'timeout': 600, 'pubkey': HEX_B}
        b.depot.save_state(etat)
        nouveau = faux_ncryptsec()
        ok(b.appeler('identity/secret', {'identity': 'alpha', 'ncryptsec': nouveau}))
        profil = json.load(open(b.depot.profile_path('alpha')))
        assert profil['sec'] == nouveau != ancien and profil['clients'] == [{'pubkey': HEX_A}]
        assert b.depot.load_state()['alpha'] == {'timeout': 600}      # pubkey retirée
        assert code(b.appeler('identity/secret', {'identity': 'alpha', 'ncryptsec': 'ncryptsec1abc'})) \
            == 'invalid_ncryptsec'
        assert code(b.appeler('identity/secret', {'identity': 'zzz', 'ncryptsec': nouveau})) \
            == 'unknown_identity'


def test_admin_relays(tmp_path):
    with banc(tmp_path) as b:
        b.demarrer_admin()
        b.profil('alpha', clients=[{'pubkey': HEX_A}])
        ok(b.appeler('identity/relays', {'identity': 'alpha',
                                         'relays': ['wss://r2.example', 'ws://x.onion', 'wss://r2.example']}))
        profil = json.load(open(b.depot.profile_path('alpha')))
        assert profil['relays'] == ['wss://r2.example', 'ws://x.onion']
        assert profil['clients'] == [{'pubkey': HEX_A}]
        assert code(b.appeler('identity/relays', {'identity': 'zzz', 'relays': RELAIS})) == 'unknown_identity'


def test_admin_authorize(tmp_path):
    with banc(tmp_path) as b:
        b.demarrer_admin()
        b.profil('alpha')
        for _ in range(2):                              # idempotent
            ok(b.appeler('identity/authorize', {'identity': 'alpha', 'client': HEX_A}))
        ok(b.appeler('identity/authorize', {'identity': 'alpha', 'client': HEX_B}))
        profil = json.load(open(b.depot.profile_path('alpha')))
        assert profil['clients'] == [{'pubkey': HEX_A}, {'pubkey': HEX_B}]
        assert code(b.appeler('identity/authorize', {'identity': 'zzz', 'client': HEX_A})) \
            == 'unknown_identity'


def test_admin_revoke(tmp_path):
    with banc(tmp_path) as b:
        b.demarrer_admin()
        b.profil('alpha', clients=[{'pubkey': HEX_A}, {'pubkey': HEX_B}])
        ok(b.appeler('identity/revoke', {'identity': 'alpha', 'client': HEX_A}))
        assert json.load(open(b.depot.profile_path('alpha')))['clients'] == [{'pubkey': HEX_B}]
        assert code(b.appeler('identity/revoke', {'identity': 'alpha', 'client': HEX_A})) \
            == 'client_not_authorized'


def test_admin_timeout(tmp_path):
    with banc(tmp_path) as b:
        b.demarrer_admin()
        b.profil('alpha')
        ok(b.appeler('identity/timeout', {'identity': 'alpha', 'minutes': 5}))
        assert b.depot.load_state()['alpha']['timeout'] == 300
        # Permis déverrouillée, et immédiat.
        assert b.sup.start_identity('alpha', bytearray(b.phrase.encode()))['ok']
        ok(b.appeler('identity/timeout', {'identity': 'alpha', 'minutes': 1440}))
        alpha = ok(b.appeler('identity/list'))['identities'][0]
        assert alpha['timeout'] == 86400 and alpha['remaining'] > 86000


def test_admin_remove(tmp_path):
    with banc(tmp_path) as b:
        b.demarrer_admin()
        b.profil('alpha', timeout=600)
        b.profil('beta', timeout=600)
        for mauvaise in ('beta', '', 'ALPHA', 1):
            assert code(b.appeler('identity/remove', {'identity': 'alpha', 'confirmation': mauvaise})) \
                == 'confirmation_mismatch'
        assert b.depot.exists('alpha')
        ok(b.appeler('identity/remove', {'identity': 'alpha', 'confirmation': 'alpha'}))
        assert not b.depot.exists('alpha') and 'alpha' not in b.depot.load_state()
        assert b.depot.exists('beta') and 'beta' in b.depot.load_state()
        assert code(b.appeler('identity/remove', {'identity': 'alpha', 'confirmation': 'alpha'})) \
            == 'unknown_identity'
        assert code(b.appeler('identity/remove', {'identity': 'beta'})) == 'bad_request'


@pytest.mark.parametrize('action,params,attendu', [
    ('identity/clients', {'identity': 'Ab'}, 'invalid_identity'),
    ('identity/clients', {'identity': 'a' * 33}, 'invalid_identity'),
    ('identity/clients', {'identity': ''}, 'invalid_identity'),
    ('identity/clients', {'identity': 5}, 'invalid_identity'),
    ('identity/relays', {'identity': 'alpha', 'relays': []}, 'invalid_relays'),
    ('identity/relays', {'identity': 'alpha', 'relays': [f'wss://r{i}.example' for i in range(11)]},
     'invalid_relays'),
    ('identity/relays', {'identity': 'alpha', 'relays': 'wss://r.example'}, 'invalid_relays'),
    ('identity/relays', {'identity': 'alpha', 'relays': [5]}, 'invalid_relays'),
    ('identity/relays', {'identity': 'alpha', 'relays': ['ws://relais.example']}, 'invalid_relays'),
    ('identity/relays', {'identity': 'alpha', 'relays': ['ws://.onion']}, 'invalid_relays'),
    ('identity/relays', {'identity': 'alpha', 'relays': ['http://r.example']}, 'invalid_relays'),
    ('identity/relays', {'identity': 'alpha', 'relays': ['wss://r.example/a b']}, 'invalid_relays'),
    ('identity/secret', {'identity': 'alpha', 'ncryptsec': 'nsec1abc'}, 'invalid_ncryptsec'),
    ('identity/secret', {'identity': 'alpha', 'ncryptsec': 5}, 'invalid_ncryptsec'),
    ('identity/authorize', {'identity': 'alpha', 'client': 'zz'}, 'invalid_client'),
    ('identity/authorize', {'identity': 'alpha', 'client': 'AB' * 31}, 'invalid_client'),
    ('identity/authorize', {'identity': 'alpha', 'client': 7}, 'invalid_client'),
    ('identity/timeout', {'identity': 'alpha', 'minutes': 0}, 'invalid_timeout'),
    ('identity/timeout', {'identity': 'alpha', 'minutes': 1441}, 'invalid_timeout'),
    ('identity/timeout', {'identity': 'alpha', 'minutes': True}, 'invalid_timeout'),
    ('identity/timeout', {'identity': 'alpha', 'minutes': '5'}, 'invalid_timeout'),
    ('identity/remove', {'identity': 'alpha', 'confirmation': 'autre'}, 'confirmation_mismatch'),
])
def test_admin_formats(tmp_path, action, params, attendu):
    with banc(tmp_path) as b:
        b.demarrer_admin()
        b.profil('alpha')
        avant = json.load(open(b.depot.profile_path('alpha')))
        assert code(b.appeler(action, params)) == attendu
        assert json.load(open(b.depot.profile_path('alpha'))) == avant


def test_admin_formats_acceptes(tmp_path):
    with banc(tmp_path) as b:
        b.demarrer_admin()
        b.profil('alpha')
        for relais in (['ws://x.onion'], ['ws://y.relais.onion:8080/chemin'], ['wss://r.example:443'],
                       [f'wss://r{i}.example' for i in range(10)]):
            ok(b.appeler('identity/relays', {'identity': 'alpha', 'relays': relais}))
        for minutes in (1, 1440):
            ok(b.appeler('identity/timeout', {'identity': 'alpha', 'minutes': minutes}))
        ok(b.appeler('identity/add', {'identity': 'a_b-9', 'ncryptsec': faux_ncryptsec(), 'relays': RELAIS}))
        ok(b.appeler('identity/add', {'identity': 'n' * 32, 'ncryptsec': faux_ncryptsec(), 'relays': RELAIS}))


def test_admin_conditions(tmp_path):
    with banc(tmp_path) as b:
        b.demarrer_admin()
        sec = b.profil('alpha', clients=[{'pubkey': HEX_A}])
        assert b.sup.start_identity('alpha', bytearray(b.phrase.encode()))['ok']
        # Déverrouillée : refus avant toute vérification de format (ordre de command()).
        for action, params in (
                ('identity/secret', {'ncryptsec': 'invalide'}),
                ('identity/relays', {'relays': []}),
                ('identity/authorize', {'client': 'invalide'}),
                ('identity/revoke', {'client': HEX_B}),
                ('identity/remove', {'confirmation': 'autre'}),
                ('identity/add', {'ncryptsec': 'invalide', 'relays': []})):
            assert code(b.appeler(action, dict(params, identity='alpha'))) == 'identity_unlocked', action
        assert json.load(open(b.depot.profile_path('alpha')))['sec'] == sec
        # Lecture et délai restent permis.
        ok(b.appeler('identity/clients', {'identity': 'alpha'}))
        ok(b.appeler('identity/timeout', {'identity': 'alpha', 'minutes': 2}))
        # Ordre : forme de l'identité, puis existence (clients, timeout), puis minutes.
        assert code(b.appeler('identity/timeout', {'identity': 'zzz', 'minutes': 0})) == 'unknown_identity'
        assert code(b.appeler('identity/timeout', {'identity': 'ZZZ', 'minutes': 0})) == 'invalid_identity'
        # Non déverrouillée, identité inconnue : existence avant formats.
        assert code(b.appeler('identity/secret', {'identity': 'zzz', 'ncryptsec': 'invalide'})) \
            == 'unknown_identity'
        assert code(b.appeler('identity/remove', {'identity': 'zzz', 'confirmation': 'autre'})) \
            == 'unknown_identity'
        assert b.sup.stop_identity('alpha', 'admin_request')
        # Verrouillée : les écritures passent.
        ok(b.appeler('identity/revoke', {'identity': 'alpha', 'client': HEX_A}))


def bech32_npub(octets):
    """Encodeur BIP-173 indépendant du code testé."""
    alphabet = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l'
    donnees, acc, bits = [], 0, 0
    for octet in octets:
        acc, bits = (acc << 8) | octet, bits + 8
        while bits >= 5:
            bits -= 5
            donnees.append((acc >> bits) & 31)
    if bits:
        donnees.append((acc << (5 - bits)) & 31)

    def polymod(valeurs):
        generateur = (0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3)
        somme = 1
        for v in valeurs:
            haut, somme = somme >> 25, ((somme & 0x1ffffff) << 5) ^ v
            for i in range(5):
                somme ^= generateur[i] if (haut >> i) & 1 else 0
        return somme

    hrp = [ord(c) >> 5 for c in 'npub'] + [0] + [ord(c) & 31 for c in 'npub']
    controle = polymod(hrp + donnees + [0] * 6) ^ 1
    donnees += [(controle >> 5 * (5 - i)) & 31 for i in range(6)]
    return 'npub1' + ''.join(alphabet[d] for d in donnees)


def test_admin_npub(tmp_path):
    with banc(tmp_path) as b:
        b.demarrer_admin()
        b.profil('alpha')
        cle = secrets.token_bytes(32)
        npub = bech32_npub(cle)
        ok(b.appeler('identity/authorize', {'identity': 'alpha', 'client': npub}))
        ok(b.appeler('identity/authorize', {'identity': 'alpha', 'client': cle.hex()}))   # même client
        assert json.load(open(b.depot.profile_path('alpha')))['clients'] == [{'pubkey': cle.hex()}]
        ok(b.appeler('identity/revoke', {'identity': 'alpha', 'client': npub.upper()}))
        assert json.load(open(b.depot.profile_path('alpha')))['clients'] == []
        faux = npub[:-1] + ('q' if npub[-1] != 'q' else 'p')            # somme erronée
        assert code(b.appeler('identity/authorize', {'identity': 'alpha', 'client': faux})) == 'invalid_client'
        court = bech32_npub(cle[:31])
        assert code(b.appeler('identity/authorize', {'identity': 'alpha', 'client': court})) == 'invalid_client'
        autre = 'nsec1' + npub[5:]
        assert code(b.appeler('identity/authorize', {'identity': 'alpha', 'client': autre})) == 'invalid_client'
        assert code(b.appeler('identity/authorize', {'identity': 'alpha', 'client': 'npub1' + 'b' * 50})) \
            == 'invalid_client'
        assert json.load(open(b.depot.profile_path('alpha')))['clients'] == []


def test_admin_sans_secret(tmp_path):
    with banc(tmp_path) as b:
        b.demarrer_admin()
        sec = faux_ncryptsec()
        sortie = []
        sortie.append(b.appeler('identity/add', {'identity': 'alpha', 'ncryptsec': sec, 'relays': RELAIS}))
        sortie.append(b.appeler('identity/add', {'identity': 'alpha', 'ncryptsec': sec, 'relays': RELAIS}))
        sortie.append(b.appeler('identity/add', {'identity': 'beta', 'ncryptsec': sec, 'relays': []}))
        sortie.append(b.appeler('identity/secret', {'identity': 'alpha', 'ncryptsec': sec}))
        sortie.append(b.appeler('identity/secret', {'identity': 'alpha', 'ncryptsec': sec + '!'}))
        sortie.append(b.appeler('identity/secret', {'identity': 'zzz', 'ncryptsec': sec}))
        sortie.append(b.appeler('identity/secret', {'identity': 'alpha', 'ncryptsec': sec, 'x': 1}))
        sortie.append(b.appeler('identity/list'))
        sortie.append(b.appeler('identity/clients', {'identity': 'alpha'}))
        assert b.sup.start_identity('alpha', bytearray(b.phrase.encode()))['ok']
        sortie.append(b.appeler('identity/secret', {'identity': 'alpha', 'ncryptsec': sec}))
        # Octets bruts : ligne contenant le secret mais malformée.
        bruts = echange(b.config['admin']['socket'], b'{"x":"' + sec.encode() + b'"\n')
        texte = json.dumps(sortie) + json.dumps(bruts) + b.flux.getvalue()
        assert sec not in texte and b.phrase not in texte
        assert 'ncryptsec1' not in texte
        for evenement in b.lignes_journal():
            assert 'params' not in evenement and 'ncryptsec' not in evenement


def test_admin_concurrence(tmp_path):
    with banc(tmp_path) as b:
        b.demarrer_admin()
        b.profil('alpha')
        clients = [secrets.token_hex(32) for _ in range(48)]
        erreurs = []

        def tache(morceau):
            try:
                for client in morceau:
                    reponse = b.appeler('identity/authorize', {'identity': 'alpha', 'client': client})
                    assert reponse['ok'], reponse
                    ok(b.appeler('identity/list'))
            except Exception as erreur:  # noqa: BLE001
                erreurs.append(erreur)

        fils = [threading.Thread(target=tache, args=(clients[i::8],)) for i in range(8)]
        for fil in fils:
            fil.start()
        for fil in fils:
            fil.join(30)
        assert not erreurs
        profil = json.load(open(b.depot.profile_path('alpha')))
        assert sorted(c['pubkey'] for c in profil['clients']) == sorted(clients)
        if os.path.exists(b.depot.state_file):
            json.load(open(b.depot.state_file))        # fichier d'état jamais corrompu


def test_admin_compte_uid_zero_refuse(tmp_path):
    with banc(tmp_path, ADMIN_ROMULUS_USER='root') as b:
        assert b.demarrer_admin() is None
        evenements = [e for e in b.lignes_journal() if e['event'] == 'admin_disabled']
        assert [e['reason'] for e in evenements] == ['invalid_account']
        assert not os.path.exists(b.config['admin']['socket'])


def test_admin_socket_0600_sans_fenetre(tmp_path, monkeypatch):
    modes = []
    reel = os.chown

    def espion(cible, *args):
        modes.append(os.stat(cible).st_mode & 0o777)
        return reel(cible, *args)
    with banc(tmp_path) as b:
        monkeypatch.setattr(os, 'chown', espion)
        assert b.demarrer_admin() is not None
        assert modes == [0]
        assert stat.S_IMODE(os.stat(b.config['admin']['socket']).st_mode) == 0o600


def test_admin_list_filtre_les_controles_des_relais(tmp_path):
    with banc(tmp_path) as b:
        b.demarrer_admin()
        b.profil('alpha', relais=['wss://a\x1b[31m.example', 'wss://b\x07.example', 'wss://ok.example'])
        relais = ok(b.appeler('identity/list'))['identities'][0]['relays']
        assert relais == ['wss://a\ufffd[31m.example', 'wss://b\ufffd.example', 'wss://ok.example']
        assert all(c.isprintable() for r in relais for c in r)
        b.profil('beta', relais=RELAIS)
        valides = {e['identity']: e['relays'] for e in ok(b.appeler('identity/list'))['identities']}
        assert valides['beta'] == RELAIS


def test_admin_max_line_defaut_65536(tmp_path):
    with banc(tmp_path) as b:
        assert b.config['admin']['max_line'] == 65536
