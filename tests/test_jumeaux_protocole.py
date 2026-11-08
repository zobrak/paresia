# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests du protocole ; dépendances : pytest, bibliothèque standard, server.commun.
# Suivi des versions
#   0.1.18  2026-11-08  Intégration : le tableau de strfry.md admet une colonne d'état après le numéro.
#   3.0.0-alpha.41  2026-11-06  origin_refused et statuts HTTP de N4 (T038).
#   3.0.0-alpha  2026-11-06  Clés backup_* du catalogue admises (outil de sauvegarde, C36).
#   3.0.0-alpha.32  2026-11-06  T007 : admission des clés de démarrage dans les catalogues.
#   3.0.0-alpha.29  2026-11-06  Catalogues BCP 47 et compatibilité des codes (T027).
#   3.0.0-alpha  2026-11-05  Codes d'erreur de bunkerd (T005), dont relay_identity_protected.
#   3.0.0-alpha  2026-11-05  Enveloppes, encadrement et catalogues.
import ast
import io
import json
import re
import tomllib
from pathlib import Path

import pytest

from server.commun.catalogue import Catalogue, creer_descripteur, nom_varlink
from server.commun.jumeaux import (ACTIONS, CODES_ERREUR, ErreurProtocole,
                                  decoder, encoder, lire_ligne, reponse, valider)
from server.commun.noyau import CATALOGUE_NOYAU


CODES_ATTENDUS = {
    'challenge_required', 'challenge_expired', 'signature_invalid',
    'export_too_large', 'export_busy', 'origin_refused',
    'unknown_action', 'bad_request', 'internal_error', 'peer_unavailable',
    'token_missing', 'token_unknown', 'token_conflict', 'body_too_large',
    'not_available', 'session_limit', 'auth_info_unavailable', 'line_too_long',
    'protocol_version_mismatch', 'session_closed', 'relay_light_red',
    'invalid_identity', 'unknown_identity', 'identity_exists', 'identity_unlocked',
    'invalid_relays', 'invalid_ncryptsec', 'invalid_client', 'client_not_authorized',
    'invalid_timeout', 'confirmation_mismatch', 'relay_identity_protected',
    'not_relay_key', 'bad_passphrase', 'invalid_pubkeys', 'invalid_passphrase', 'pubkey_mismatch',
    'log_n_too_high',
}


RACINE = Path(__file__).resolve().parents[1]
ACTIONS_NOYAU = {
    'presence/session/challenge', 'presence/session/open', 'presence/session/ping',
    'presence/session/close', 'presence/relay/ping',
    'castor/light/ping', 'castor/light/state', 'castor/light/close',
}


def protocole():
    return (RACINE / 'docs/protocole.md').read_text(encoding='utf-8')


def section(document, debut, fin):
    return document.split(debut, 1)[1].split(fin, 1)[0]


def actions_du_tableau_noyau(document):
    tableau = section(document, '## 5. Actions', '### 5.1')
    attendues = set()
    for ligne in (l for l in tableau.splitlines() if l.startswith('| `')):
        noms = re.findall(r'`([^`]+)`', ligne)
        attendues.update(f'{noms[0]}/{action}' for action in noms[1:])
    return attendues


def lignes_tableau(texte):
    """Cellules des lignes `| `action` | … |` d'un tableau, par action."""
    resultat = {}
    for ligne in texte.splitlines():
        if ligne.startswith('| `'):
            cellules = [c.strip() for c in re.split(r'(?<!\\)\|', ligne.strip().strip('|'))]
            resultat[cellules[0].strip('`')] = cellules
    return resultat


def requete(**changements):
    return dict({'proto': 'jumeaux/1', 'id': 'a123456789abcdef', 'session': 0,
                 'action': 'presence/session/ping', 'params': {}}, **changements)


@pytest.mark.parametrize('champ', ['proto', 'id', 'session', 'action', 'params'])
def test_champ_manquant(champ):
    objet = requete()
    del objet[champ]
    with pytest.raises(ErreurProtocole) as erreur:
        valider(objet, ACTIONS)
    assert erreur.value.code == 'bad_request'
    assert erreur.value.identifiant == (None if champ == 'id' else requete()['id'])


@pytest.mark.parametrize('changement', [dict(inconnu=0), dict(params=None), dict(params=[]),
                                       dict(session=-1), dict(session=True), dict(session=1.5),
                                       dict(proto=None), dict(proto='autre/1')])
def test_enveloppe_non_conforme(changement):
    with pytest.raises(ErreurProtocole, match='bad_request'):
        valider(requete(**changement), ACTIONS)


def test_session_dans_params():
    with pytest.raises(ErreurProtocole, match='bad_request'):
        valider(requete(params={'session': 0}), ACTIONS)


@pytest.mark.parametrize('action,admises', [('inconnue', ACTIONS), ('presence/session/ping', set()),
                                          ([], ACTIONS)])
def test_action_inconnue(action, admises):
    with pytest.raises(ErreurProtocole, match='unknown_action'):
        valider(requete(action=action), admises)


def test_proto_incompatible():
    with pytest.raises(ErreurProtocole) as erreur:
        valider(requete(proto='jumeaux/2'), ACTIONS)
    assert erreur.value.code == 'protocol_version_mismatch'
    assert erreur.value.fermer


@pytest.mark.parametrize('ligne', ['{}\n'.encode('utf-16'), b'[]\n', b'1\n', b'{\n', b'\xff\n', b'{"x":NaN}\n',
                                  b'{"x":1,"x":2}\n', b'[' * 2000 + b']' * 2000])
def test_decodage_invalide(ligne):
    with pytest.raises(ErreurProtocole, match='bad_request'):
        decoder(ligne)


def test_lecture_bornee():
    class Source:
        def __init__(self):
            self.lu = 0
        def readinto(self, destination):
            assert len(destination) == 1
            self.lu += 1
            destination[0] = ord('x')
            return 1
    source = Source()
    with pytest.raises(ErreurProtocole, match='line_too_long'):
        lire_ligne(source, 64)
    assert source.lu == 65
    assert lire_ligne(io.BytesIO(b'123\n'), 4) == b'123\n'
    assert lire_ligne(io.BytesIO(b''), 4) is None
    with pytest.raises(ErreurProtocole, match='bad_request'):
        lire_ligne(io.BytesIO(b'123'), 4)


def test_reponses():
    identifiant = requete()['id']
    assert reponse(identifiant) == {'id': identifiant, 'ok': True}
    for stream in ('line', 'end'):
        assert reponse(identifiant, stream=stream)['stream'] == stream
    for code in CODES_ERREUR:
        resultat = reponse(identifiant, code=code)
        assert resultat['error']['code'] == code
        assert decoder(encoder(resultat)) == resultat


def test_catalogues_i18n():
    racine = Path(__file__).resolve().parents[1]
    fr = json.loads((racine / 'i18n/fr-FR.json').read_text())
    en = json.loads((racine / 'i18n/en-US.json').read_text())
    # Les trois codes T027 seront reportés au protocole par le documentaliste.
    attendus = CODES_ATTENDUS | {'command_failed', 'command_timeout', 'command_busy'}
    assert fr.keys() == en.keys()
    assert attendus <= fr.keys()
    assert CODES_ERREUR == attendus
    assert all(isinstance(v, str) and v for v in [*fr.values(), *en.values()])


def test_codes_documentes():
    document = (Path(__file__).resolve().parents[1] / 'docs/protocole.md').read_text()
    section = document.split('## 9.')[1].split('## Suivi')[0]
    assert all(f'`{code}`' in section for code in CODES_ATTENDUS)
    assert ACTIONS == actions_du_tableau_noyau(document)


def test_statuts_http_documentes():
    document = (Path(__file__).resolve().parents[1] / 'docs/protocole.md').read_text()
    section = document.split('## 9.')[1].split('## Suivi')[0]
    lignes = {ligne.split('|')[1].strip().strip('`'): ligne.split('|')[3].strip()
              for ligne in section.splitlines() if ligne.startswith('| `')}
    attendus = {'challenge_required': '—', 'challenge_expired': '—', 'signature_invalid': '—',
                'export_too_large': '422', 'export_busy': '503',
                'bad_request': '400 ; 405 pour une méthode autre que POST',
                'unknown_action': '404', 'internal_error': '500', 'peer_unavailable': '503',
                'token_missing': '403', 'token_unknown': '403', 'token_conflict': '400',
                'origin_refused': '403', 'body_too_large': '413', 'not_available': '501',
                'session_limit': '—', 'auth_info_unavailable': '—', 'line_too_long': '—',
                'protocol_version_mismatch': '—', 'session_closed': '403',
                'relay_light_red': '503', 'command_failed': '502', 'command_timeout': '504',
                'command_busy': '503',
                'invalid_identity': '422', 'unknown_identity': '404', 'identity_exists': '409',
                'identity_unlocked': '409', 'invalid_relays': '422', 'invalid_ncryptsec': '422',
                'invalid_client': '422', 'client_not_authorized': '404', 'invalid_timeout': '422',
                'confirmation_mismatch': '422', 'relay_identity_protected': '409',
                'not_relay_key': '422', 'bad_passphrase': '422', 'invalid_pubkeys': '422',
                'invalid_passphrase': '422', 'pubkey_mismatch': '409', 'log_n_too_high': '422'}
    assert lignes == attendus


def test_proto_prioritaire_sur_enveloppe():
    with pytest.raises(ErreurProtocole) as erreur:
        valider({'proto': 'jumeaux/2', 'id': requete()['id'], 'nouveau_champ': 1}, ACTIONS)
    assert erreur.value.code == 'protocol_version_mismatch'
    assert erreur.value.fermer


@pytest.mark.parametrize('proto', ['jumeaux/1.0', 'jumeaux/-1', 'jumeaux/+1',
                                   'jumeaux/１', 'jumeaux/1\n', 'jumeaux/', 'jumeaux/1beta'])
def test_forme_proto_stricte(proto):
    with pytest.raises(ErreurProtocole, match='bad_request'):
        valider(requete(proto=proto), ACTIONS)


def test_valider_ensemble_hors_actions():
    admises = {'exemple/objet/lire'}
    assert valider(requete(action='exemple/objet/lire'), admises)
    with pytest.raises(ErreurProtocole, match='unknown_action'):
        valider(requete(action='exemple/objet/ecrire'), admises)


@pytest.mark.parametrize('action', ['exemple/1objet/lire', 'Exemple/objet', 'a', 'a/b/c/d/e',
                                    'a/_b', 'a/b/', 'a//b', 'a/b\n', 'a/' + 'b' * 130])
def test_valider_forme_invalide_refusee(action):
    with pytest.raises(ErreurProtocole, match='unknown_action'):
        valider(requete(action=action), {action})


def test_valider_exige_un_ensemble():
    for mauvais in (None, ['exemple/objet/lire'], 'exemple/objet/lire', {'a': 1}, ()):
        with pytest.raises(ValueError, match='invalid_actions'):
            valider(requete(action='exemple/objet/lire'), mauvais)


def test_valider_ensemble_hors_actions_et_forme():
    admis = frozenset({'exemple/objet/lire', 'exemple/1/lire'})
    assert valider(requete(action='exemple/objet/lire'), admis)
    assert valider(requete(action='exemple/objet/lire'), {'exemple/objet/lire'})
    with pytest.raises(ErreurProtocole, match='unknown_action'):
        valider(requete(action='exemple/objet/autre'), admis)
    with pytest.raises(ErreurProtocole, match='unknown_action'):
        valider(requete(action='exemple/1/lire'), admis)


def test_charger_json_strict():
    from server.commun.jumeaux import charger_json_strict
    assert charger_json_strict(b' {"a": 1}\n') == {'a': 1}
    for mauvais in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'\xff', b'', b'{'):
        with pytest.raises(ValueError):
            charger_json_strict(mauvais)


def test_actions_calculees_du_catalogue_du_noyau():
    assert ACTIONS == ACTIONS_NOYAU
    assert ACTIONS == frozenset(CATALOGUE_NOYAU.actions)
    assert set(CATALOGUE_NOYAU.descripteurs) == ACTIONS
    assert not any(a.split('/')[1] == 'catalog' for a in ACTIONS)
    with pytest.raises(AttributeError):
        CATALOGUE_NOYAU.autre = 1
    # Aucun littéral d'action du noyau dans jumeaux.py : seul noyau.py les porte.
    arbre = ast.parse((RACINE / 'server/commun/jumeaux.py').read_text(encoding='utf-8'))
    chaines = [n.value for n in ast.walk(arbre) if isinstance(n, ast.Constant)
               and isinstance(n.value, str)]
    assert not [c for c in chaines if c.startswith(('presence/', 'castor/'))]


def test_tableau_du_noyau_sans_domaine_de_greffon():
    tableau = section(protocole(), '## 5. Actions', '### 5.1')
    lignes = [l for l in tableau.splitlines() if l.startswith('| `')]
    assert {re.findall(r'`([^`]+)`', l)[0] for l in lignes} == {'presence', 'castor'}
    assert actions_du_tableau_noyau(protocole()) == ACTIONS


def test_section_5_3_egale_le_catalogue_du_noyau():
    texte = section(protocole(), '### 5.3', '### 5.4')
    lignes = lignes_tableau(texte)
    assert set(lignes) == ACTIONS
    for action, cellules in lignes.items():
        descripteur = CATALOGUE_NOYAU.descripteurs[action]
        assert set(re.findall(r'`([a-z_]+)`', cellules[3])) == set(descripteur.erreurs), action
        for parametre in descripteur.parametres:
            assert f'`{parametre.nom}`' in cellules[1], action
        if not descripteur.parametres:
            assert cellules[1].startswith('`{}`'), action


def test_section_5_2_egale_la_declaration_de_nisaba():
    chemin = (RACINE / 'deploy/backend-admin/usr/local/lib/paresia/romulus/services'
              / 'paresia-yang-nisaba.toml')
    declaration = tomllib.loads(chemin.read_text(encoding='utf-8'))
    lignes = lignes_tableau(section(protocole(), '### 5.2', '### 5.3'))
    declarees = {'nisaba/' + a['nom']: set(a.get('erreurs', ())) for a in declaration['actions']}
    assert set(declarees) == {'nisaba/state/status', 'nisaba/state/verify'}
    for action, erreurs in declarees.items():
        assert set(re.findall(r'`([a-z_]+)`', lignes[action][3])) == erreurs


def test_actions_de_strfry_egales_a_la_declaration():
    document = (RACINE / 'docs/plugins/strfry.md').read_text(encoding='utf-8')
    assert 'paresia-yin-strfry' in document and 'paresia-yang-strfry' in document
    documentees = {}
    for ligne in document.splitlines():
        m = re.fullmatch(r'\| `([a-z0-9-]+/[a-z0-9-]+)` \| \((\d+)\) \|(?: [^|]+ \|)?', ligne)
        if m:
            documentees['relay/' + m.group(1)] = int(m.group(2))
    chemin = (RACINE / 'deploy/backend-admin/usr/local/lib/paresia/romulus/services'
              / 'paresia-yang-strfry.toml')
    declaration = tomllib.loads(chemin.read_text(encoding='utf-8'))
    assert set(documentees) == {'relay/' + a['nom'] for a in declaration['actions']}
    assert len(documentees) == 31
    attendus = {'state/status': 1, 'state/metrics': 2, 'state/nip11': 3, 'state/log': 4,
                'state/warnings': 5, 'state/connections': 6, 'state/follow': 7,
                'events/count': 10, 'events/kinds': 11, 'events/list': 12, 'events/show': 13,
                'events/delete-filter': 14, 'events/delete-age': 15, 'backup/export': 20,
                'backup/import': 21, 'backup/list': 22, 'sync/download': 30,
                'sync/compare': 31, 'sync/trees': 32, 'container/restart': 40,
                'container/stop': 41, 'container/start': 42, 'container/config': 43,
                'container/compact': 44, 'moderation/reports': 60, 'moderation/ban': 61,
                'moderation/unban': 61, 'moderation/ban-import': 61, 'moderation/log': 62,
                'moderation/mute-list': 63, 'moderation/publish-mute-list': 63}
    assert documentees == {'relay/' + a: n for a, n in attendus.items()}


def test_champs_d_introspection_documentes():
    catalogue = Catalogue('principale', 'essai', [creer_descripteur('essai/objet/action')])
    lignes = lignes_tableau(section(protocole(), '### 5.5', '**Contrat de sortie'))
    liste = catalogue.reponse('essai/catalog/list', {})
    decrire = catalogue.reponse('essai/catalog/describe', {'action': 'essai/objet/action'})
    produits_liste = set(liste) | set(liste['actions'][0])
    produits_description = set(decrire)
    champs = lambda cellule: set(re.findall(r'"([a-z_]+)"', cellule))
    assert champs(lignes['<domaine>/catalog/list'][2]) == produits_liste
    assert champs(lignes['<domaine>/catalog/describe'][2]) == produits_description
    assert champs(lignes['<domaine>/catalog/describe'][1]) == {'action'}


def test_enonces_de_neutralite_et_de_non_fermeture():
    document = protocole()
    noyau = section(document, '## 5. Actions', '### 5.1')
    assert '(cible, domaine, action)' in noyau
    assert 'indexés par (cible, domaine)' in noyau
    assert '`target`' in noyau
    assert 'paresia-yin-<nom>' in noyau and 'paresia-yang-<nom>' in noyau
    assert '1:1' not in noyau
    for langage in ('python', 'bash', 'perl', 'lua'):
        assert langage not in noyau.lower()


def test_correspondance_varlink_documentee():
    noyau = section(protocole(), '## 5. Actions', '### 5.1')
    for action, nom in (('identity/add', 'IdentityAdd'),
                        ('relay-key/sign-mute-list', 'RelayKeySignMuteList')):
        assert f'`{action}` devient `{nom}`' in noyau
        assert nom_varlink('bunker/' + action) == nom
    assert '<interface>.<CodeEnCamelCase>' in noyau
