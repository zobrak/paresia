# SPDX-License-Identifier: AGPL-3.0-or-later
# Durcissement de bunkerd 2.0.0 (cycle 1 de T005) ; dépendances : pytest et bibliothèque standard.
# Suivi des versions
#   0.1.1  2026-11-07  Démarrage sous le socle : code 78 et événement startup_failed.
#   3.0.0-alpha.32  2026-11-06  T007 : lecture du délai dans l'enveloppe au format 1.
#   3.0.0-alpha  2026-11-05  Première version : saut de ligne final, écriture atomique, relais de 255
#                            caractères, clé de relais protégée, verrou global, démarrage réel.
import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys
import threading
import time

import pytest

from bunkerd_outils import banc, ecrire_executable, faux_ncryptsec
from server.bunkerd import configuration
from server.bunkerd.ctl import commande
from server.commun.client import Connexion
from server.commun.config import ErreurConfiguration

RACINE = Path(__file__).resolve().parents[1]
EXEMPLE = str(RACINE / 'server/conf/paresia.conf')
HEX_A = 'ab' * 32
HEX_B = '12' * 32


def ok(reponse):
    assert reponse['ok'] is True, reponse
    return reponse.get('data')


def code(reponse):
    assert reponse['ok'] is False
    return reponse['error']['code']


def fichiers(b):
    return sorted(p.name for p in (b.home / '.config/nak/bunker').glob('*')) if (
        b.home / '.config/nak/bunker').exists() else []


def test_saut_de_ligne_final_refuse(tmp_path):
    with banc(tmp_path) as b:
        b.demarrer_admin()
        sec = faux_ncryptsec()
        b.profil('alpha')
        avant = fichiers(b)
        assert code(b.appeler('identity/add', {'identity': 'bob\n', 'ncryptsec': sec,
                                               'relays': ['wss://r.example']})) == 'invalid_identity'
        assert code(b.appeler('identity/add', {'identity': 'bob', 'ncryptsec': sec + '\n',
                                               'relays': ['wss://r.example']})) == 'invalid_ncryptsec'
        assert code(b.appeler('identity/add', {'identity': 'bob', 'ncryptsec': sec,
                                               'relays': ['wss://r.example\n']})) == 'invalid_relays'
        assert code(b.appeler('identity/relays', {'identity': 'alpha',
                                                  'relays': ['wss://r.example\n']})) == 'invalid_relays'
        assert code(b.appeler('identity/secret', {'identity': 'alpha',
                                                  'ncryptsec': sec + '\n'})) == 'invalid_ncryptsec'
        assert code(b.appeler('identity/clients', {'identity': 'alpha\n'})) == 'invalid_identity'
        assert fichiers(b) == avant == ['alpha']
        assert not (b.home / '.config/nak/bunker/bob').exists()
        with pytest.raises(ValueError):
            b.depot.profile_path('bob\n')
        # ctl.sock : même refus, message de 1.9.0 inchangé pour une entrée valide.
        with b.sup.lock:
            reponse = commande(b.ops, {'cmd': 'clients', 'id': 'alpha\n'}, bytearray())
        assert reponse == {'ok': False,
                           'error': "nom d'identité invalide (a-z, 0-9, - et _, 32 caractères au plus)"}
        with b.sup.lock:
            assert commande(b.ops, {'cmd': 'clients', 'id': 'alpha'}, bytearray()) == {
                'ok': True, 'clients': []}


def test_relay_identity_saut_de_ligne():
    with pytest.raises(ErreurConfiguration):
        configuration(['--config', EXEMPLE], {'PARESIA_BUNKERD_GENERAL_RELAY_IDENTITY': 'relais\n'})


def test_relais_255_caracteres(tmp_path):
    with banc(tmp_path) as b:
        b.demarrer_admin()
        b.profil('alpha')
        limite = 'wss://' + 'a' * (255 - len('wss://'))
        assert len(limite) == 255
        ok(b.appeler('identity/relays', {'identity': 'alpha', 'relays': [limite]}))
        assert code(b.appeler('identity/relays', {'identity': 'alpha', 'relays': [limite + 'a']})) \
            == 'invalid_relays'
        assert json.load(open(b.depot.profile_path('alpha')))['relays'] == [limite]


def test_relais_doublons_et_ncryptsec_non_texte(tmp_path):
    with banc(tmp_path) as b:
        b.demarrer_admin()
        a, c = 'wss://a.example', 'wss://c.example'
        ok(b.appeler('identity/add', {'identity': 'alpha', 'ncryptsec': faux_ncryptsec(),
                                      'relays': [a, a, c, a, c]}))
        assert json.load(open(b.depot.profile_path('alpha')))['relays'] == [a, c]
        for faux in (5, None, ['x'], {'a': 1}, True):
            assert code(b.appeler('identity/add', {'identity': 'beta', 'ncryptsec': faux,
                                                   'relays': [a]})) == 'invalid_ncryptsec'
        assert fichiers(b) == ['alpha']


def test_depot_atomique(tmp_path):
    with banc(tmp_path) as b:
        b.demarrer_admin()
        ok(b.appeler('identity/add', {'identity': 'alpha', 'ncryptsec': faux_ncryptsec(),
                                      'relays': ['wss://r.example']}))
        ok(b.appeler('identity/secret', {'identity': 'alpha', 'ncryptsec': faux_ncryptsec()}))
        ok(b.appeler('identity/authorize', {'identity': 'alpha', 'client': HEX_A}))
        residus = [p for p in b.home.rglob('*.tmp')]
        assert residus == []
        assert oct(os.stat(b.depot.profile_path('alpha')).st_mode & 0o777) == '0o600'
        assert oct(os.stat(b.depot.state_file).st_mode & 0o777) == '0o600'
        # .tmp périmé : lien symbolique vers une cible tierce, jamais suivi ni modifié.
        cible = tmp_path / 'cible'
        cible.write_text('intact')
        os.symlink(cible, b.depot.state_file + '.tmp')
        os.symlink(cible, b.depot.profile_path('alpha') + '.tmp')
        ok(b.appeler('identity/timeout', {'identity': 'alpha', 'minutes': 3}))
        ok(b.appeler('identity/relays', {'identity': 'alpha', 'relays': ['wss://s.example']}))
        assert cible.read_text() == 'intact'
        assert [p for p in b.home.rglob('*.tmp')] == []
        # .tmp périmé ordinaire : remplacé.
        Path(b.depot.state_file + '.tmp').write_text('périmé')
        ok(b.appeler('identity/timeout', {'identity': 'alpha', 'minutes': 4}))
        assert json.load(open(b.depot.state_file))['identities']['alpha']['timeout'] == 240
        assert [p for p in b.home.rglob('*.tmp')] == []


def test_remove_relay_identity_protegee(tmp_path):
    with banc(tmp_path, GENERAL_RELAY_IDENTITY='relais') as b:
        b.demarrer_admin()
        b.profil('relais', timeout=600)
        b.profil('alpha')
        assert code(b.appeler('identity/remove', {'identity': 'relais', 'confirmation': 'relais'})) \
            == 'relay_identity_protected'
        assert b.depot.exists('relais') and 'relais' in b.depot.load_state()
        ok(b.appeler('identity/remove', {'identity': 'alpha', 'confirmation': 'alpha'}))
        # ctl.sock reste inchangé : root peut supprimer la clé du relais.
        with b.sup.lock:
            assert commande(b.ops, {'cmd': 'remove', 'id': 'relais'}, bytearray()) == {'ok': True}
        assert not b.depot.exists('relais')


def test_verrou_global_attend_deverrouillage_lent(tmp_path):
    with banc(tmp_path) as b:
        b.demarrer_admin()
        b.profil('alpha')
        b.sup.unlock_wait = 2
        # Faux nak muet : le déverrouillage dure tout le délai (le nak par défaut échoue aussitôt).
        lent = b.racine / 'nak_lent'
        ecrire_executable(lent, '#!/bin/sh\nsleep 5\n')
        b.sup.nak = str(lent)
        fin = {}

        def deverrouiller():
            with b.sup.lock:                      # comme ctl.sock : verrou tenu pendant l'attente
                b.sup.start_identity('alpha', bytearray(b'mauvaise'))
            fin['unlock'] = time.monotonic()

        fil = threading.Thread(target=deverrouiller)
        fil.start()
        time.sleep(0.4)                           # laisse le déverrouillage prendre le verrou
        debut = time.monotonic()
        ok(b.appeler('identity/relays', {'identity': 'alpha', 'relays': ['wss://z.example']}))
        fin['admin'] = time.monotonic()
        fil.join(10)
        assert fin['admin'] >= fin['unlock'] - 0.05
        assert fin['admin'] - debut >= 1.0
        assert json.load(open(b.depot.profile_path('alpha')))['relays'] == ['wss://z.example']


def test_concurrence_authorize_revoke(tmp_path):
    with banc(tmp_path) as b:
        b.demarrer_admin()
        b.profil('alpha')
        durables = [f'{i:02x}' * 32 for i in range(1, 17)]
        erreurs = []

        def stable(client):
            try:
                ok(b.appeler('identity/authorize', {'identity': 'alpha', 'client': client}))
            except Exception as erreur:  # noqa: BLE001
                erreurs.append(erreur)

        def bascule():
            try:
                for _ in range(15):
                    ok(b.appeler('identity/authorize', {'identity': 'alpha', 'client': HEX_A}))
                    reponse = b.appeler('identity/revoke', {'identity': 'alpha', 'client': HEX_A})
                    assert reponse['ok'] or code(reponse) == 'client_not_authorized'
            except Exception as erreur:  # noqa: BLE001
                erreurs.append(erreur)

        # Au plus 12 connexions simultanées (limite admin.max_connexions = 16, qui reste inchangée).
        vagues = [[threading.Thread(target=bascule) for _ in range(4)]
                  + [threading.Thread(target=stable, args=(c,)) for c in durables[:8]],
                  [threading.Thread(target=stable, args=(c,)) for c in durables[8:]]]
        for fils in vagues:
            for fil in fils:
                fil.start()
            for fil in fils:
                fil.join(60)
        assert not erreurs
        cles = [c['pubkey'] for c in json.load(open(b.depot.profile_path('alpha')))['clients']]
        assert len(cles) == len(set(cles))
        assert set(durables) <= set(cles) and set(cles) - set(durables) <= {HEX_A}


def test_journal_filtre_les_controles(tmp_path):
    with banc(tmp_path) as b:
        b.demarrer_admin()
        b.journal.ecrire('info', 'test_filtrage', identity='a\x1b[31mb\r\n\x07c', reason='\x9b2J‮')
        b.appeler('identity/clients', {'identity': 'x\x1b[2Jy\x00'})
        brut = b.flux.getvalue()
        assert '\x1b' not in brut and '\x07' not in brut and '\x00' not in brut
        assert '‮' not in brut and '\x9b' not in brut
        for ligne in brut.splitlines():
            json.loads(ligne)                   # une ligne = un objet JSON
        operations = [e for e in b.lignes_journal() if e['event'] == 'admin_operation']
        assert operations and all('identity' not in e for e in operations)


def _lancer(b, relay_identity):
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'PYTHONPATH': str(RACINE),
           'PARESIA_BUNKERD_CONFIG': EXEMPLE,
           'PARESIA_BUNKERD_GENERAL_RELAY_IDENTITY': relay_identity,
           'PARESIA_BUNKERD_ETAT_HOME': str(b.home),
           'PARESIA_BUNKERD_OUTILS_NAK': str(b.nak),
           'PARESIA_BUNKERD_OUTILS_SETFACL': str(b.setfacl),
           'PARESIA_BUNKERD_CONTROLE_SOCKET': str(b.socks / 'ctl-reel.sock'),
           'PARESIA_BUNKERD_WEB_SOCKET': '(none)',
           'PARESIA_BUNKERD_WEB_USER': b.config['web']['user'],
           'PARESIA_BUNKERD_ADMIN_SOCKET': str(b.socks / 'adm-reel.sock'),
           'PARESIA_BUNKERD_ADMIN_ROMULUS_USER': b.config['admin']['romulus_user']}
    return subprocess.Popen([sys.executable, '-m', 'server.bunkerd'], cwd=RACINE, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)


def _evenements(processus, attendus, delai=10):
    """Lit le journal du démon jusqu'à voir tous les événements attendus."""
    vus, fin = [], time.monotonic() + delai
    while time.monotonic() < fin and not attendus <= {e['event'] for e in vus}:
        if select.select([processus.stdout], [], [], 0.2)[0]:
            ligne = processus.stdout.readline()
            if not ligne:
                break
            vus.append(json.loads(ligne))
    return vus


def test_demarrage_reel_relay_identity_invalide(tmp_path):
    with banc(tmp_path) as b:
        for invalide in ('Relais', 'relais\n', 'a' * 33):
            processus = _lancer(b, invalide)
            try:
                sortie, _ = processus.communicate(timeout=15)
            finally:
                processus.kill()
            assert processus.returncode == 78
            evenements = [json.loads(ligne) for ligne in sortie.splitlines()]
            echec = [e for e in evenements if e['event'] == 'startup_failed']
            assert echec and echec[0]['cause'] == 'config_invalid'
            assert not any(e['event'] == 'bunkerd_ready' for e in evenements)


def test_demarrage_reel_relay_identity_inconnue_et_client_coupe(tmp_path):
    with banc(tmp_path) as b:
        processus = _lancer(b, 'absente')
        try:
            vus = _evenements(processus, {'relay_identity_unknown', 'admin_started', 'bunkerd_ready'})
            noms = [e['event'] for e in vus]
            assert 'relay_identity_unknown' in noms and 'bunkerd_ready' in noms and 'admin_started' in noms
            avert = [e for e in vus if e['event'] == 'relay_identity_unknown'][0]
            assert avert['level'] == 'warning'
            chemin = str(b.socks / 'adm-reel.sock')
            # Client coupé au milieu d'une ligne : le démon continue.
            for morceau in (b'{"proto": "jumeaux/1", "id": "x', b'{"proto"', b'\x00\xff'):
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.connect(chemin)
                sock.sendall(morceau)
                sock.close()
            time.sleep(0.3)
            assert processus.poll() is None
            requete = {'proto': 'jumeaux/1', 'id': 'abcd1234abcd1234', 'session': 1,
                       'action': 'bunker/identity/list', 'params': {}}
            with Connexion(chemin, 5) as connexion:
                assert connexion.appeler(requete)['data'] == {'identities': []}
            assert processus.poll() is None
        finally:
            if processus.poll() is None:
                processus.send_signal(signal.SIGTERM)
            try:
                processus.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                processus.kill()
        assert processus.returncode == 0
