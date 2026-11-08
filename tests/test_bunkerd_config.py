# SPDX-License-Identifier: AGPL-3.0-or-later
# Configuration, clé de relais et codes de bunkerd 2.0.0 ; dépendances : pytest et bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha.29  2026-11-06  Catalogues BCP 47 et compatibilité des codes (T027).
#   3.0.0-alpha  2026-11-05  Première version (T005) : lecture par lire, exemple, relay_identity, codes.
#   3.0.0-alpha  2026-11-05  Exemple : sections [bunkerd…] de paresia.conf ; max_line par défaut 65536.
import json
from pathlib import Path
import re

import pytest

from bunkerd_outils import banc
from server.bunkerd import SCHEMA, configuration
from server.commun.config import ErreurConfiguration, lire
from server.commun.jumeaux import CODES_ERREUR, DETAILS

RACINE = Path(__file__).resolve().parents[1]
EXEMPLE = str(RACINE / 'server/conf/paresia.conf')
CODES_BUNKERD = {'invalid_identity', 'unknown_identity', 'identity_exists', 'identity_unlocked',
                 'invalid_relays', 'invalid_ncryptsec', 'invalid_client', 'client_not_authorized',
                 'invalid_timeout', 'confirmation_mismatch', 'relay_identity_protected',
                 'not_relay_key', 'bad_passphrase', 'invalid_pubkeys', 'invalid_passphrase',
                 'pubkey_mismatch', 'log_n_too_high'}


def test_bunkerd_config_source_sans_lecture_directe():
    for fichier in (RACINE / 'server/bunkerd').glob('*.py'):
        texte = fichier.read_text()
        for interdit in ('configparser', 'os.environ', 'getenv', 'NOSTR_BUNKER'):
            assert interdit not in texte, (fichier.name, interdit)
    assert 'lire(' in (RACINE / 'server/bunkerd/__init__.py').read_text()


def test_bunkerd_config_surcharge_et_obligatoires(tmp_path):
    base = configuration(['--config', EXEMPLE], {})
    assert base['admin']['socket'] == '/run/nostr-bunker/admin.sock'
    sur = configuration(['--config', EXEMPLE], {'PARESIA_BUNKERD_ADMIN_SOCKET': '/run/x/a.sock',
                                                'PARESIA_BUNKERD_ADMIN_DELAI_S': '12',
                                                'PARESIA_BUNKERD_GENERAL_RELAY_IDENTITY': 'beta'})
    assert sur['admin']['socket'] == '/run/x/a.sock' and sur['admin']['delai_s'] == 12
    assert sur['general']['relay_identity'] == 'beta'
    # Option obligatoire manquante : refus.
    sans = tmp_path / 'sans.conf'
    sans.write_text(re.sub(r'(?m)^romulus_user = .*\n', '', Path(EXEMPLE).read_text()))
    with pytest.raises(ErreurConfiguration) as erreur:
        configuration(['--config', str(sans)], {})
    assert (erreur.value.code, erreur.value.section, erreur.value.cle) == ('config_missing', 'admin', 'romulus_user')
    # Les anciennes variables ne sont plus lues.
    ancien = configuration(['--config', EXEMPLE], {'NOSTR_BUNKER_HOME': '/autre', 'NOSTR_BUNKER_SOCKET': '/autre/s'})
    assert ancien['etat']['home'] == '/var/lib/nostr-bunker'
    assert ancien['controle']['socket'] == '/run/nostr-bunker/ctl.sock'
    with pytest.raises(ErreurConfiguration):
        configuration([], {})                                    # aucun fichier ni chemin par défaut


def test_bunkerd_config_valeurs_facultatives():
    sans_web = configuration(['--config', EXEMPLE], {'PARESIA_BUNKERD_WEB_SOCKET': '(none)'})
    assert sans_web['web']['socket'] == ''
    assert configuration(['--config', EXEMPLE], {})['general']['relay_identity'] is None
    for variable, valeur in (('GENERAL_RELAY_IDENTITY', 'A/B'), ('GENERAL_RELAY_IDENTITY', 'x' * 33),
                             ('WEB_SOCKET', 'relatif.sock'), ('ADMIN_SOCKET', 'relatif.sock'),
                             ('ADMIN_ROMULUS_USER', 'a b'), ('ADMIN_DELAI_S', '0')):
        with pytest.raises(ErreurConfiguration) as erreur:
            configuration(['--config', EXEMPLE], {f'PARESIA_BUNKERD_{variable}': valeur})
        assert valeur not in str(erreur.value)


def test_bunkerd_conf_exemple():
    config = lire('bunkerd', SCHEMA, argv=['--config', EXEMPLE], environ={})
    assert config['admin']['romulus_user'] == 'paresia-romulus'
    assert config['controle']['socket'] == '/run/nostr-bunker/ctl.sock'
    assert config['web'] == {'socket': '/run/nostr-bunker/web.sock', 'user': 'www-data'}
    assert config['outils']['nak'] == '/usr/local/bin/nak'
    assert config['etat']['home'] == '/var/lib/nostr-bunker'
    assert config['signature']['log_n'] == 20
    assert set(config) == {key[0] for key in SCHEMA}
    assert configuration(['--config', EXEMPLE], {})['general']['relay_identity'] is None


def test_relay_identity(tmp_path):
    (tmp_path / 'a').mkdir()
    with banc(tmp_path / 'a', GENERAL_RELAY_IDENTITY='relais') as b:
        b.profil('alpha')
        b.profil('relais')
        b.demarrer_admin()
        assert b.ops.verifier_relay_identity() is True
        marques = {i['identity']: i['relay_key'] for i in b.appeler('identity/list')['data']['identities']}
        assert marques == {'alpha': False, 'relais': True}
        # Aucune action ne la modifie.
        b.appeler('identity/remove', {'identity': 'relais', 'confirmation': 'relais'})
        b.appeler('identity/add', {'identity': 'relais', 'ncryptsec': b.profil('tmp'), 'relays': ['wss://r.example']})
        assert b.config['general']['relay_identity'] == 'relais'
    (tmp_path / 'b').mkdir()
    with banc(tmp_path / 'b', GENERAL_RELAY_IDENTITY='absente') as b:
        b.profil('alpha')
        b.demarrer_admin()
        assert b.ops.verifier_relay_identity() is False
        assert [e for e in b.lignes_journal() if e['event'] == 'relay_identity_unknown'][0]['level'] == 'warning'
        assert not any(i['relay_key'] for i in b.appeler('identity/list')['data']['identities'])
    with pytest.raises(ErreurConfiguration):
        configuration(['--config', EXEMPLE], {'PARESIA_BUNKERD_GENERAL_RELAY_IDENTITY': 'Relais'})


def test_codes_bunkerd():
    fr = json.loads((RACINE / 'i18n/fr-FR.json').read_text())
    en = json.loads((RACINE / 'i18n/en-US.json').read_text())
    assert fr.keys() == en.keys()
    assert CODES_BUNKERD <= fr.keys() and CODES_BUNKERD <= CODES_ERREUR == DETAILS.keys()
    protocole = (RACINE / 'docs/protocole.md').read_text()
    section = protocole.split('## 9.')[1].split('## Suivi')[0]
    for code in CODES_BUNKERD:
        assert f'`{code}`' in section
        assert fr[code] and en[code] and re.fullmatch(r'[A-Za-z ]+', DETAILS[code])
    # Tous les champs des dix actions sont décrits au § 5.
    tableau = protocole.split('### 5.1')[1].split('## 6.')[0]
    for champ in ('identity', 'ncryptsec', 'relays', 'timeout_min', 'client', 'minutes', 'confirmation',
                  'relay_key', 'remaining', 'passphrase', 'pubkeys'):
        assert champ in tableau


def test_bunkerd_conf_max_line_defaut_documente(tmp_path):
    # Défaut abaissé à 65536 : valeur du schéma, de l'exemple et de la configuration lue.
    assert configuration(['--config', EXEMPLE], {})['admin']['max_line'] == 65536
    texte = Path(EXEMPLE).read_text()
    assert re.search(r'(?m)^max_line = 65536$', texte) and 'défaut 65536' in texte
    sans = tmp_path / 'sans.conf'
    sans.write_text(re.sub(r'(?m)^max_line = .*\n', '', texte))
    assert configuration(['--config', str(sans)], {})['admin']['max_line'] == 65536
