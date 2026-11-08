# Journal JSON de bunkerd 2.0.0 ; dépendances : pytest et bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha  2026-11-05  Première version (T005) : lignes D5 sans secret.
import json

from bunkerd_outils import banc, faux_ncryptsec
from server.bunkerd.ctl import commande
from server.commun.jumeaux import PROTO

HEX_A = 'ab' * 32


def test_bunkerd_journal(tmp_path):
    with banc(tmp_path) as b:
        b.demarrer_admin()
        sec = faux_ncryptsec()
        b.appeler('identity/add', {'identity': 'alpha', 'ncryptsec': sec, 'relays': ['wss://r.example']}, session=7)
        b.appeler('identity/authorize', {'identity': 'alpha', 'client': HEX_A}, session=7)
        b.appeler('identity/timeout', {'identity': 'alpha', 'minutes': 5}, session=7)
        b.appeler('identity/revoke', {'identity': 'alpha', 'client': HEX_A}, session=7)
        b.appeler('identity/remove', {'identity': 'alpha', 'confirmation': 'non'}, session=7)
        with b.sup.lock:
            commande(b.ops, {'cmd': 'unlock', 'id': 'alpha'}, bytearray(b.phrase.encode()))
            commande(b.ops, {'cmd': 'lock', 'id': 'alpha'}, bytearray())
        b.appeler('identity/secret', {'identity': 'alpha', 'ncryptsec': sec}, session=8)
        b.appeler('identity/relays', {'identity': 'alpha', 'relays': ['wss://r2.example']}, session=8)
        b.appeler('identity/remove', {'identity': 'alpha', 'confirmation': 'alpha'}, session=8)
        brut = b.flux.getvalue()
        evenements = [json.loads(ligne) for ligne in brut.splitlines()]
        assert all({'ts', 'level', 'component', 'event'} <= e.keys() and e['component'] == 'bunkerd'
                   for e in evenements)
        assert all(e['ts'].endswith('Z') for e in evenements)
        noms = [e['event'] for e in evenements]
        for attendu in ('admin_started', 'identity_added', 'client_authorized', 'identity_timeout_changed',
                        'client_revoked', 'identity_unlocked', 'identity_locked', 'identity_secret_replaced',
                        'identity_relays_changed', 'identity_removed', 'admin_operation'):
            assert attendu in noms, attendu
        operations = [e for e in evenements if e['event'] == 'admin_operation']
        assert len(operations) == 8
        assert operations[0] == {**operations[0], 'session': 7, 'action': 'bunker/identity/add',
                                 'identity': 'alpha', 'result': 'ok'}
        refus = operations[4]
        assert refus['result'] == 'error' and refus['code'] == 'confirmation_mismatch'
        verrouillage = [e for e in evenements if e['event'] == 'identity_locked'][0]
        assert verrouillage['identity'] == 'alpha' and verrouillage['reason'] == 'admin_request'
        assert [e for e in evenements if e['event'] == 'identity_unlocked'][0]['source'] == 'ctl'
        # Aucun secret : ncryptsec, passphrase, secret de l'adresse bunker://.
        for interdit in (sec, b.phrase, 'secret=abc', 'bunker://', PROTO):
            assert interdit not in brut
