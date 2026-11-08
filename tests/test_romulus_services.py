# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests des déclarations de services de Romulus : chargeur, aiguillage, introspection, configuration ; dépendances : pytest, bibliothèque standard et server.
# Suivi des versions
#   0.1.15  2026-11-08  Les cinq chemins du domaine kernel s'ajoutent à ceux des déclarations.
#   0.1.9  2026-11-08  Clés pages et journaliser, greffon sans action, déclaration de la web-ui.
#   0.1.8  2026-11-07  Première version : déclarations de services greffés, neutralité de Romulus (D148, D150, D154).
import ast
from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import re
import stat
from types import SimpleNamespace

import pytest

from romulus_outils import CHARGEUR, DOSSIER_SERVICES, RACINE, declarations_livrees, schema_romulus
from server.commun import services
from server.commun.catalogue import CIBLE_DEFAUT, action_catalogue
from server.commun.client import Connexion
from server.commun.config import ErreurConfiguration, Option
from server.commun.journal import Journal
from server.commun.jumeaux import CODES_ERREUR, reponse
from server.romulus import Romulus, configuration
import server.romulus.aiguillage as module_aiguillage
from test_romulus_aiguillage import FauxPair, ok
from test_romulus_presence_http import config_test, dossier_socket, http, ouvrir  # noqa: F401

PREFIXE = '/api/admin/'
EUID = os.geteuid()

# -- constantes d'avant, figées : les déclarations livrées doivent les reproduire -----------

TEXTE, ENTIER, LISTE = 'texte', 'entier', 'liste'
CHAMPS_BUNKER = {
    'identity/list': {},
    'identity/clients': {'identity': (TEXTE, True)},
    'identity/add': {'identity': (TEXTE, True), 'ncryptsec': (TEXTE, True),
                     'relays': (LISTE, True), 'timeout_min': (ENTIER, False)},
    'identity/secret': {'identity': (TEXTE, True), 'ncryptsec': (TEXTE, True)},
    'identity/relays': {'identity': (TEXTE, True), 'relays': (LISTE, True)},
    'identity/authorize': {'identity': (TEXTE, True), 'client': (TEXTE, True)},
    'identity/revoke': {'identity': (TEXTE, True), 'client': (TEXTE, True)},
    'identity/timeout': {'identity': (TEXTE, True), 'minutes': (ENTIER, True)},
    'identity/remove': {'identity': (TEXTE, True), 'confirmation': (TEXTE, True)},
    'relay-key/sign-mute-list': {'identity': (TEXTE, True), 'passphrase': (TEXTE, True),
                                 'pubkeys': (LISTE, True)},
}
CODES_BUNKERD = frozenset({
    'bad_request', 'internal_error', 'invalid_identity', 'unknown_identity',
    'identity_exists', 'identity_unlocked', 'invalid_relays', 'invalid_ncryptsec',
    'invalid_client', 'client_not_authorized', 'invalid_timeout', 'confirmation_mismatch',
    'relay_identity_protected', 'not_relay_key', 'bad_passphrase', 'invalid_pubkeys',
    'invalid_passphrase', 'pubkey_mismatch', 'log_n_too_high'})
CODES_REMUS = frozenset({
    'bad_request', 'not_available', 'relay_light_red', 'session_closed', 'peer_unavailable',
    'command_failed', 'command_timeout', 'command_busy', 'internal_error'})
ACTIONS_RELAY = frozenset('relay/' + a for a in (
    'state/status state/metrics state/nip11 state/log state/warnings state/connections '
    'state/follow events/count events/kinds events/list events/show events/delete-filter '
    'events/delete-age backup/export backup/import backup/list sync/download sync/compare '
    'sync/trees container/restart container/stop container/start container/config '
    'container/compact moderation/reports moderation/ban moderation/unban '
    'moderation/ban-import moderation/log moderation/mute-list '
    'moderation/publish-mute-list').split())
ACTIONS_LEGAL = frozenset('legal/journal/' + a for a in 'search export status verify'.split())
ACTIONS_NISABA = frozenset({'nisaba/state/status', 'nisaba/state/verify'})
CATALOGUES = frozenset(f'{d}/catalog/{o}' for d in ('bunker', 'nisaba', 'relay')
                       for o in ('list', 'describe'))
# Schéma d'avant des sections [romulus.bunker] et [romulus.relay].
SCHEMA_AVANT = {
    ('bunker', 'bunkerd_socket'): Option('chemin'),
    ('bunker', 'bunkerd_uid'): Option('uid'),
    ('bunker', 'delai_s'): Option('duree', 120),
    ('bunker', 'max_line'): Option('limite', 65536),
    ('relay', 'remus_socket'): Option('chemin'),
    ('relay', 'remus_uid'): Option('uid'),
    ('relay', 'pollux_socket'): Option('chemin'),
    ('relay', 'pollux_uid'): Option('uid'),
    ('relay', 'delai_s'): Option('duree', 600),
    ('relay', 'ping_delai_s'): Option('duree', 5),
    ('relay', 'heartbeat_s'): Option('duree', 30),
    ('relay', 'max_line'): Option('limite', 1048576),
    ('relay', 'flux_max_simultanes'): Option('limite', 8),
}


def par_domaine(declares=None):
    declares = declares or declarations_livrees()
    return {s.domaine: s for s in declares.services}


# -- outils ---------------------------------------------------------------------------------

BASE_OPTIONS = '''
[[options]]
nom = "socket"
type = "chemin"
role = "socket"

[[options]]
nom = "uid"
type = "uid"
role = "uid"

[[options]]
nom = "delai_s"
type = "duree"
defaut = 5
role = "delai"

[[options]]
nom = "max_line"
type = "limite"
defaut = 65536
role = "max_line"
'''
OPTIONS_PING = '''
[[options]]
nom = "ping_socket"
type = "chemin"
role = "ping_socket"

[[options]]
nom = "ping_uid"
type = "uid"
role = "ping_uid"
'''
OPTIONS_TEMPS = '''
[[options]]
nom = "ping_delai_s"
type = "duree"
defaut = 1
inferieure_a = "battement_s"
role = "ping_delai"

[[options]]
nom = "battement_s"
type = "duree"
defaut = 30
role = "battement"
'''
OPTIONS_SUIVI = '''
[[options]]
nom = "flux_max"
type = "limite"
defaut = 4
maximum = 16
role = "flux_max"
'''
ACTIONS_BASE = '''
[[actions]]
nom = "objet/lire"
erreurs = ["command_busy"]

[[actions.parametres]]
nom = "nom"
type = "texte"
bornes = { motif = '[a-z]+', longueur_max = 16 }

[[actions.parametres]]
nom = "n"
type = "entier"
bornes = { minimum = 0, maximum = 10 }
obligatoire = false

[[actions]]
nom = "objet/etat"
'''


def declaration(domaine='exemple', *, ping=False, suivi=False, haut='', section=None,
                actions=ACTIONS_BASE, options=None, greffon=None):
    """Déclaration valide d'un service fictif ; `haut` ajoute des clés avant les tables."""
    section = section or domaine
    options = options if options is not None else (
        BASE_OPTIONS + (OPTIONS_PING if ping else '')
        + (OPTIONS_TEMPS if ping or suivi else '') + (OPTIONS_SUIVI if suivi else ''))
    if suivi:
        actions = actions + '''
[[actions]]
nom = "objet/suivre"
suivi = true
'''
    return (f'format = 1\ngreffon = "{greffon or "paresia-yang-" + domaine}"\n'
            f'domaine = "{domaine}"\nsection = "{section}"\ncatalogue = "declaration"\n'
            f'codes = ["bad_request", "command_busy"]\n'
            + ('ping = true\n' if ping else '') + haut + options + actions)


def ecrire(dossier, nom, texte, mode=0o644):
    dossier.mkdir(parents=True, exist_ok=True, mode=0o755)
    dossier.chmod(0o755)
    chemin = dossier / nom
    chemin.write_text(texte, encoding='utf-8')
    chemin.chmod(mode)
    return chemin


def charger(racine, livrees=None, locales=None, rappel=None):
    """Écrit les fichiers {nom: texte} dans les dossiers l et e, puis charge."""
    for dossier, fichiers in (('l', livrees), ('e', locales)):
        if fichiers is not None:
            for nom, texte in fichiers.items():
                ecrire(racine / dossier, nom, texte)
    return services.charger(racine / 'l', racine / 'e', proprietaires=frozenset({EUID}),
                            racine_confiance=racine, rappel=rappel)


def chargeur_de(racine):
    return {'livrees': str(racine / 'l'), 'locales': str(racine / 'e'),
            'proprietaires': frozenset({EUID}), 'racine_confiance': str(racine)}


@contextmanager
def demarrer(dossier, sections=None, chargeur=CHARGEUR):
    flux = io.StringIO()
    config = config_test(dossier)
    config.update(sections or {})
    with Romulus(config, journal=Journal('romulus', flux=flux), chargeur=chargeur) as demon:
        with Connexion(demon.presence.chemin) as pollux:
            service = (demon, pollux, flux, dossier)
            ouverture = ouvrir(service)
            yield SimpleNamespace(service=service, demon=demon, flux=flux, config=config,
                                  token=ouverture['token'], session=ouverture['session'])


def appeler(b, action, params=None, **options):
    return http(b.service, b.token, chemin=PREFIXE + action,
                corps=json.dumps(params if params is not None else {}).encode(), **options)


def erreur(statut, code):
    return (statut, {'ok': False, 'error': {'code': code}})


def pairs(dossier, **comportements):
    ordre = []
    return {nom: FauxPair(str(dossier / (nom + '.sock')), nom, comportement or ok, ordre)
            for nom, comportement in comportements.items()}, ordre


def section_bunker(pair):
    return {'bunker': {'bunkerd_socket': pair.chemin, 'bunkerd_uid': EUID, 'delai_s': 2,
                       'max_line': 65536}}


def section_relay(remus, pollux):
    return {'relay': {'remus_socket': remus.chemin, 'remus_uid': EUID,
                      'pollux_socket': pollux.chemin, 'pollux_uid': EUID, 'delai_s': 3,
                      'ping_delai_s': 1, 'heartbeat_s': 30, 'max_line': 65536}}


def section_nisaba(pair):
    return {'nisaba': {'socket': pair.chemin, 'uid': EUID, 'delai_s': 2, 'max_line': 65536}}


# -- les quatre déclarations livrées reproduisent l'existant -----------------------------------

def test_livrees_actions_codes_egaux_aux_constantes():
    par = par_domaine()
    assert set(par) == {'bunker', 'relay', 'nisaba', 'legal', 'webui'}
    assert {a.action for a in par['bunker'].actions} == {'bunker/' + a for a in CHAMPS_BUNKER}
    assert {a.action for a in par['relay'].actions} == ACTIONS_RELAY
    assert {a.action for a in par['legal'].actions} == ACTIONS_LEGAL
    assert {a.action for a in par['nisaba'].actions} == ACTIONS_NISABA
    assert par['bunker'].codes == CODES_BUNKERD and par['relay'].codes == CODES_REMUS
    assert par['bunker'].destination == 'bunkerd' and par['relay'].destination == 'remus'
    assert par['relay'].ping_oubli == frozenset({'relay_light_red'})
    declares = declarations_livrees()
    routables = declares.actions_routables()
    assert routables == (frozenset('bunker/' + a for a in CHAMPS_BUNKER) | ACTIONS_RELAY
                         | ACTIONS_LEGAL | ACTIONS_NISABA | CATALOGUES)
    assert declares.exports() == {'legal/journal/export'}
    assert declares.suivis() == {'relay/state/follow'}


def test_livrees_unicite_et_nommage():
    declares = declarations_livrees()
    assert declares.cible == CIBLE_DEFAUT and not declares.rejets
    for service in declares.services:
        assert re.fullmatch(r'paresia-yang-[a-z][a-z0-9-]*', service.greffon)
        assert (DOSSIER_SERVICES / (service.greffon + '.toml')).is_file()
        assert service.cible == CIBLE_DEFAUT
    assert sorted(p.name for p in DOSSIER_SERVICES.iterdir()) == [
        'paresia-yang-bunkerd.toml', 'paresia-yang-journal-legal.toml',
        'paresia-yang-nisaba.toml', 'paresia-yang-strfry.toml', 'paresia-yang-webui.toml']
    # La paire strfry n'a pas de fichier côté Remus dans cette livraison.
    assert not [p for d in ('server', 'deploy') for p in (RACINE / d).glob('**/paresia-yin-strfry*')]


def test_source_unique_parametres_de_bunkerd():
    type_json = {'texte': TEXTE, 'choix': TEXTE, 'hexadecimal': TEXTE, 'entier': ENTIER,
                 'liste_entiers': LISTE, 'liste_texte': LISTE}
    deduit = {a.action.split('/', 1)[1]: {p.nom: (type_json[p.type], p.obligatoire)
                                          for p in a.descripteur.parametres}
              for a in par_domaine()['bunker'].actions}
    assert deduit == CHAMPS_BUNKER


def test_source_unique_erreurs_de_bunkerd_et_nisaba():
    doc = (RACINE / 'docs/protocole.md').read_text(encoding='utf-8')

    def tableau(titre, prefixe):
        debut = doc.index(titre)
        lignes = doc[debut:].split('\n## ')[0].split('\n')
        attendues = {}
        for ligne in lignes:
            colonnes = [c.strip() for c in ligne.replace('\\|', '/').strip().strip('|').split('|')]
            if len(colonnes) == 4 and colonnes[0].startswith('`' + prefixe):
                codes = tuple(re.findall(r'`([a-z_]+)`', colonnes[3]))
                attendues[colonnes[0].strip('`')] = codes
        return attendues

    bunker = tableau('### 5.1 Domaine `bunker`', 'identity/') | tableau(
        '### 5.1 Domaine `bunker`', 'relay-key/')
    assert len(bunker) == 10
    par = par_domaine()
    for action in par['bunker'].actions:
        nom = action.action.split('/', 1)[1]
        assert set(action.descripteur.erreurs) == set(bunker[nom]), nom
        assert len(action.descripteur.erreurs) == len(set(bunker[nom]))
    nisaba = tableau('### 5.2 Domaine `nisaba`', 'nisaba/')
    for action in par['nisaba'].actions:
        assert set(action.descripteur.erreurs) == set(nisaba[action.action]), action.action


def test_champs_bunker_disparu_du_noyau():
    for chemin in (RACINE / 'server').rglob('*.py'):
        assert 'CHAMPS_BUNKER' not in chemin.read_text(encoding='utf-8'), chemin.name


def test_bornes_publiees_de_bunkerd():
    par = par_domaine()['bunker']
    decrit = {a.action: {p.nom: p for p in a.descripteur.parametres} for a in par.actions}
    identite = decrit['bunker/identity/add']['identity'].bornes
    assert identite['longueur_max'] == 32 and re.fullmatch(identite['motif'], 'a_b-9')
    assert not re.fullmatch(identite['motif'], 'A') and not re.fullmatch(identite['motif'], 'a' * 33)
    assert dict(decrit['bunker/identity/timeout']['minutes'].bornes) == {'minimum': 1, 'maximum': 1440}
    assert dict(decrit['bunker/identity/add']['timeout_min'].bornes) == {'minimum': 1, 'maximum': 1440}
    relays = decrit['bunker/identity/relays']['relays'].bornes
    assert (relays['nombre_min'], relays['nombre_max'], relays['longueur_max']) == (1, 10, 255)
    pubkeys = decrit['bunker/relay-key/sign-mute-list']['pubkeys'].bornes
    assert (pubkeys['nombre_min'], pubkeys['nombre_max'], pubkeys['longueur_max']) == (0, 500, 64)
    assert re.fullmatch(pubkeys['motif'], 'a' * 64) and not re.fullmatch(pubkeys['motif'], 'A' * 64)
    client = decrit['bunker/identity/authorize']['client'].bornes
    assert re.fullmatch(client['motif'], 'a' * 64) and re.fullmatch(client['motif'], 'npub1abc')


# -- format, forme, cible, nommage -------------------------------------------------------------

def test_declaration_valide_de_reference(tmp_path):
    declares = charger(tmp_path, {'paresia-yang-exemple.toml': declaration()})
    service = declares.services[0]
    assert service.domaine == 'exemple' and service.cible == CIBLE_DEFAUT
    assert repr(service) == '<Service>' and repr(declares) == '<Declarations>'
    assert declares.actions_routables() == {
        'exemple/objet/lire', 'exemple/objet/etat', 'exemple/catalog/list',
        'exemple/catalog/describe'}


def codes_de(racine, fichiers, local=False):
    """Code d'erreur d'une déclaration livrée, ou rejet de la même déclaration en local."""
    try:
        if local:
            return charger(racine, {}, fichiers).rejets
        charger(racine, fichiers)
    except services.ErreurService as erreur:
        return erreur.code, erreur.fichier
    return None


CAS_INVALIDES = [
    ('action_forme', ('nom = "objet/lire"', 'nom = "Objet/Lire"')),
    ('action_catalogue', ('nom = "objet/etat"', 'nom = "catalog/list"')),
    ('action_describe', ('nom = "objet/etat"', 'nom = "catalog/describe"')),
    ('domaine_reserve_castor', ('domaine = "exemple"', 'domaine = "castor"')),
    ('domaine_reserve_presence', ('domaine = "exemple"', 'domaine = "presence"')),
    ('domaine_forme', ('domaine = "exemple"', 'domaine = "Exemple"')),
    ('socket_absent', ('role = "socket"\n', '')),
    ('uid_absent', ('role = "uid"\n', '')),
    ('role_en_double', ('role = "delai"', 'role = "socket"')),
    ('role_inconnu', ('role = "delai"', 'role = "lent"')),
    ('role_type_incoherent', ('role = "max_line"', 'role = "delai"')),
    ('erreur_hors_codes', ('erreurs = ["command_busy"]', 'erreurs = ["command_failed"]')),
    ('erreur_inconnue_du_protocole', ('codes = ["bad_request", "command_busy"]',
                                      'codes = ["bad_request", "code_inventé"]')),
    ('borne_manquante', ("bornes = { motif = '[a-z]+', longueur_max = 16 }",
                         "bornes = { motif = '[a-z]+' }")),
    ('motif_invalide', ("motif = '[a-z]+'", "motif = '['")),
    ('type_inconnu', ('type = "entier"\nbornes', 'type = "flottant"\nbornes')),
    ('cle_inconnue', ('catalogue = "declaration"', 'catalogue = "declaration"\nscript = "x"')),
    ('cle_privilege', ('catalogue = "declaration"', 'catalogue = "declaration"\nprivilege = "x"')),
    ('greffon_yin', ('greffon = "paresia-yang-exemple"', 'greffon = "paresia-yin-exemple"')),
    ('greffon_autre_nom', ('greffon = "paresia-yang-exemple"', 'greffon = "paresia-yang-autre"')),
    ('greffon_absent', ('greffon = "paresia-yang-exemple"\n', '')),
    ('format_absent', ('format = 1\n', '')),
    ('format_texte', ('format = 1', 'format = "1"')),
    ('catalogue_inconnu', ('catalogue = "declaration"', 'catalogue = "autre"')),
    ('params_transmis_hors_pair', ('nom = "objet/etat"', 'nom = "objet/etat"\nparams_transmis = true')),
    ('section_reservee', ('section = "exemple"', 'section = "http"')),
    ('inferieure_a_inconnue', ('defaut = 5\nrole = "delai"', 'defaut = 5\ninferieure_a = "x"\nrole = "delai"')),
    ('defaut_hors_plafond', ('defaut = 5\nrole = "delai"', 'defaut = 99999\nrole = "delai"')),
    ('toml_invalide', ('format = 1', 'format = = 1')),
]


@pytest.mark.parametrize('cas, remplacement', CAS_INVALIDES, ids=[c for c, _ in CAS_INVALIDES])
def test_declaration_invalide_livree_fatale_locale_ignoree(tmp_path, cas, remplacement):
    texte = declaration()
    assert remplacement[0] in texte, cas
    mauvais = texte.replace(*remplacement, 1)
    assert codes_de(tmp_path / 'a', {'paresia-yang-exemple.toml': mauvais}) == (
        'service_declaration_invalid', 'paresia-yang-exemple.toml')
    rejets = codes_de(tmp_path / 'b', {'paresia-yang-exemple.toml': mauvais}, local=True)
    assert rejets == (services.Rejet('service_declaration_invalid', 'local',
                                     'paresia-yang-exemple.toml'),)


def test_collision_de_noms_varlink(tmp_path):
    actions = ACTIONS_BASE + '\n[[actions]]\nnom = "objet/lire-un"\n\n[[actions]]\nnom = "objet/lire_un"\n'
    texte = declaration(actions=actions)
    assert codes_de(tmp_path, {'paresia-yang-exemple.toml': texte}) == (
        'service_declaration_invalid', 'paresia-yang-exemple.toml')


def test_format_et_forme(tmp_path):
    texte = declaration()
    for racine, mauvais, code in (
            ('a', texte.replace('format = 1', 'format = 2'), 'service_format_unsupported'),
            ('b', texte.replace('format = 1', 'format = 1\nforme = "continu"'),
             'service_form_unsupported'),
            ('c', texte.replace('format = 1', 'format = 1\nforme = 3'), 'service_declaration_invalid')):
        assert codes_de(tmp_path / racine, {'paresia-yang-exemple.toml': mauvais}) == (
            code, 'paresia-yang-exemple.toml')
        rejets = codes_de(tmp_path / (racine + 'l'), {'paresia-yang-exemple.toml': mauvais},
                          local=True)
        assert [r.code for r in rejets] == [code]
        assert 'continu' not in repr(rejets)
    declares = charger(tmp_path / 'd', {'paresia-yang-exemple.toml': texte.replace(
        'format = 1', 'format = 1\nforme = "ponctuel"')})
    assert len(declares.services) == 1


def test_fichiers_non_conformes(tmp_path):
    texte = declaration()
    nom = 'paresia-yang-exemple.toml'
    # Droits d'écriture pour les autres, nom hors motif, entrée non ordinaire, trop gros.
    racine = tmp_path / 'a'
    ecrire(racine / 'l', nom, texte, mode=0o666)
    with pytest.raises(services.ErreurService) as info:
        services.charger(racine / 'l', racine / 'e', proprietaires=frozenset({EUID}),
                         racine_confiance=racine)
    assert (info.value.code, info.value.fichier) == ('plugin_unsafe_permissions', nom)
    assert codes_de(tmp_path / 'b', {'autre.toml': texte}) == ('plugin_unexpected_entry', 'autre.toml')
    racine = tmp_path / 'c'
    ecrire(racine / 'l', 'paresia-yang-cible.toml', declaration('cible'))
    (racine / 'l' / 'paresia-yang-lien.toml').symlink_to('paresia-yang-cible.toml')
    with pytest.raises(services.ErreurService) as info:
        services.charger(racine / 'l', racine / 'e', proprietaires=frozenset({EUID}),
                         racine_confiance=racine)
    assert (info.value.code, info.value.fichier) == (
        'plugin_unsafe_permissions', 'paresia-yang-lien.toml')
    (racine / 'l' / 'paresia-yang-lien.toml').unlink()
    (racine / 'l' / 'paresia-yang-cible.toml').unlink()
    (racine / 'l' / 'paresia-yang-repertoire.toml').mkdir()
    with pytest.raises(services.ErreurService) as info:
        services.charger(racine / 'l', racine / 'e', proprietaires=frozenset({EUID}),
                         racine_confiance=racine)
    assert info.value.code == 'plugin_unexpected_entry'
    gros = declaration(haut='# ' + 'x' * 70000 + '\n')
    assert codes_de(tmp_path / 'd', {nom: gros}) == ('service_declaration_invalid', nom)
    # Mauvais propriétaire : l'utilisateur du test n'est pas root.
    if EUID != 0:
        racine = tmp_path / 'e'
        ecrire(racine / 'l', nom, texte)
        with pytest.raises(services.ErreurService) as info:
            services.charger(racine / 'l', racine / 'e', proprietaires=frozenset({0}),
                             racine_confiance=racine)
        assert info.value.code == 'plugin_unsafe_permissions'


def test_dossier_absent_et_vide(tmp_path):
    declares = services.charger(tmp_path / 'absent', tmp_path / 'absent2',
                                proprietaires=frozenset({EUID}), racine_confiance=tmp_path)
    assert declares.services == () and declares.rejets == () and declares.cible == CIBLE_DEFAUT


def test_nom_de_fichier_filtre_dans_les_erreurs():
    erreur = services.ErreurService('service_declaration_invalid', 'a\x1b[31mb')
    assert erreur.fichier == 'invalid_name'


# -- livrées / locales ----------------------------------------------------------------------

def test_locale_ne_remplace_pas_un_domaine_livre(tmp_path):
    rappel = []
    declares = charger(
        tmp_path, {'paresia-yang-exemple.toml': declaration()},
        {'paresia-yang-autre.toml': declaration(greffon='paresia-yang-autre'),
         'paresia-yang-neuf.toml': declaration('neuf')},
        rappel=lambda *a, **k: rappel.append((a, k)))
    assert sorted(s.domaine for s in declares.services) == ['exemple', 'neuf']
    assert [r.file for r in declares.rejets] == ['paresia-yang-autre.toml']
    assert rappel == [(('service_declaration_rejected', 'error'),
                       {'code': 'service_declaration_invalid', 'scope': 'local',
                        'file': 'paresia-yang-autre.toml'})]
    # Une locale ne reprend pas non plus la section d'un service livré.
    declares = charger(tmp_path / 'b', {'paresia-yang-exemple.toml': declaration()},
                       {'paresia-yang-voisin.toml': declaration('voisin', section='exemple')})
    assert [s.domaine for s in declares.services] == ['exemple']
    assert [r.code for r in declares.rejets] == ['service_declaration_invalid']


def test_dossier_local_defectueux_ignore_en_entier(tmp_path):
    rappel = []
    racine = tmp_path
    ecrire(racine / 'l', 'paresia-yang-exemple.toml', declaration())
    ecrire(racine / 'e', 'paresia-yang-neuf.toml', declaration('neuf'))
    (racine / 'e').chmod(0o777)
    declares = services.charger(racine / 'l', racine / 'e', proprietaires=frozenset({EUID}),
                                racine_confiance=racine,
                                rappel=lambda *a, **k: rappel.append((a, k)))
    assert [s.domaine for s in declares.services] == ['exemple']
    assert declares.rejets == (services.Rejet('plugin_unsafe_permissions', 'local', 'e'),)
    assert rappel == [(('service_declaration_rejected', 'error'),
                       {'code': 'plugin_unsafe_permissions', 'scope': 'local', 'file': 'e'})]
    # Ancêtre inscriptible : ignoré de même.
    profond = tmp_path / 'p'
    ecrire(profond / 'l', 'paresia-yang-exemple.toml', declaration())
    ecrire(profond / 'x' / 'e', 'paresia-yang-neuf.toml', declaration('neuf'))
    (profond / 'x').chmod(0o777)
    declares = services.charger(profond / 'l', profond / 'x' / 'e',
                                proprietaires=frozenset({EUID}), racine_confiance=profond)
    assert [s.domaine for s in declares.services] == ['exemple']
    assert [r.code for r in declares.rejets] == ['plugin_unsafe_permissions']


def test_locale_sans_defaut_est_ajoutee(tmp_path):
    declares = charger(tmp_path, {'paresia-yang-exemple.toml': declaration()},
                       {'paresia-yang-neuf.toml': declaration('neuf')})
    assert [s.domaine for s in declares.services] == ['exemple', 'neuf']
    assert declares.rejets == ()


def test_domaine_en_double_dans_les_livrees(tmp_path):
    fichiers = {'paresia-yang-exemple.toml': declaration(),
                'paresia-yang-copie.toml': declaration('exemple', section='copie',
                                                       greffon='paresia-yang-copie')}
    assert codes_de(tmp_path, fichiers)[0] == 'service_declaration_invalid'


def test_au_plus_un_service_suivi_ou_ping(tmp_path):
    for racine, premier, second in (
            ('a', dict(ping=True), dict(ping=True)),
            ('b', dict(suivi=True), dict(suivi=True)),
            ('c', dict(ping=True), dict(suivi=True))):
        fichiers = {'paresia-yang-un.toml': declaration('un', **premier),
                    'paresia-yang-deux.toml': declaration('deux', **second)}
        assert codes_de(tmp_path / racine, fichiers)[0] == 'service_declaration_invalid'
    # Un seul service avec suivi et ping : admis.
    declares = charger(tmp_path / 'ok', {'paresia-yang-un.toml': declaration('un', ping=True, suivi=True),
                                        'paresia-yang-deux.toml': declaration('deux')})
    assert len(declares.services) == 2
    # La seconde déclaration locale est rejetée.
    declares = charger(tmp_path / 'loc', {'paresia-yang-un.toml': declaration('un', ping=True)},
                       {'paresia-yang-deux.toml': declaration('deux', suivi=True)})
    assert [s.domaine for s in declares.services] == ['un']
    assert [r.code for r in declares.rejets] == ['service_declaration_invalid']
    # Deux actions de suivi dans un même service : refusé.
    deux = declaration(suivi=True) + '\n[[actions]]\nnom = "objet/autre"\nsuivi = true\n'
    assert codes_de(tmp_path / 'ds', {'paresia-yang-exemple.toml': deux})[0] == 'service_declaration_invalid'


def test_cible_unique(tmp_path):
    fichiers = {'paresia-yang-un.toml': declaration('un'),
                'paresia-yang-deux.toml': declaration('deux', haut='cible = "autre"\n')}
    assert codes_de(tmp_path / 'a', fichiers)[0] == 'service_declaration_invalid'
    declares = charger(tmp_path / 'b', {'paresia-yang-un.toml': declaration('un')},
                       {'paresia-yang-deux.toml': declaration('deux', haut='cible = "autre"\n')})
    assert [s.domaine for s in declares.services] == ['un']
    assert [r.code for r in declares.rejets] == ['service_declaration_invalid']
    seule = charger(tmp_path / 'c', {'paresia-yang-un.toml': declaration('un', haut='cible = "autre"\n')})
    assert seule.cible == 'autre' and seule.services[0].cible == 'autre'
    assert codes_de(tmp_path / 'd', {'paresia-yang-un.toml': declaration('un', haut='cible = "Mal"\n')})[0] \
        == 'service_declaration_invalid'


def test_demarrage_refuse_sans_nom_de_fichier(tmp_path, capfd, monkeypatch):
    ecrire(tmp_path / 'l', 'paresia-yang-exemple.toml', declaration().replace('role = "uid"\n', ''))
    chargeur = chargeur_de(tmp_path)
    with pytest.raises(ErreurConfiguration) as info:
        Romulus(config_test(tmp_path), journal=Journal('romulus', flux=io.StringIO()),
                chargeur=chargeur)
    assert (info.value.code, info.value.section, info.value.cle, info.value.fichier) == (
        'service_declaration_invalid', 'plugins', 'livrees', None)
    assert 'exemple' not in str(info.value)
    # Le démon complet : code de sortie 78 et startup_failed sans nom de fichier.
    import server.romulus.__main__ as m
    original = services.charger
    monkeypatch.setattr(services, 'charger', lambda livrees, locales, **options: original(
        livrees, locales, **{**options, 'proprietaires': chargeur['proprietaires'],
                             'racine_confiance': chargeur['racine_confiance']}))
    config = config_test(tmp_path)
    config['plugins'] = {'livrees': chargeur['livrees'], 'locales': chargeur['locales']}
    monkeypatch.setattr(m, 'configuration', lambda **_: config)
    assert m.main([]) == 78
    ligne = json.loads(capfd.readouterr().out.splitlines()[-1])
    assert ligne['event'] == 'startup_failed' and ligne['cause'] == 'service_declaration_invalid'
    assert (ligne['section'], ligne['option']) == ('plugins', 'livrees')
    assert 'exemple' not in json.dumps(ligne)


def test_demarrage_avec_locale_defectueuse(dossier_socket):  # noqa: F811
    racine = dossier_socket
    ecrire(racine / 'l', 'paresia-yang-exemple.toml', declaration())
    ecrire(racine / 'e', 'paresia-yang-neuf.toml', declaration('neuf').replace('role = "uid"\n', ''))
    with demarrer(racine, chargeur=chargeur_de(racine)) as b:
        rejets = [json.loads(l) for l in b.flux.getvalue().splitlines()
                  if json.loads(l)['event'] == 'service_declaration_rejected']
        assert [(r['code'], r['scope'], r['file'], r['level']) for r in rejets] == [
            ('service_declaration_invalid', 'local', 'paresia-yang-neuf.toml', 'error')]
        assert 'paresia-yang-exemple' not in json.dumps(rejets)
        assert appeler(b, 'exemple/objet/etat') == erreur(501, 'not_available')
        assert appeler(b, 'neuf/objet/etat') == erreur(404, 'unknown_action')


# -- configuration assemblée à partir des déclarations --------------------------------------

def test_schema_bunker_et_relay_egal_a_l_ancien():
    schema = schema_romulus()
    assert {cle: option for cle, option in schema.items() if cle[0] in ('bunker', 'relay')} \
        == SCHEMA_AVANT
    # Nisaba : section facultative, jamais d'exigence.
    nisaba = {cle[1]: option for cle, option in schema.items() if cle[0] == 'nisaba'}
    assert nisaba['socket'] == Option('chemin', facultatif=True)
    assert nisaba['uid'] == Option('uid', facultatif=True)
    assert nisaba['delai_s'].defaut == 120 and nisaba['max_line'].defaut == 1048576
    assert not any(cle[0] in ('legal',) for cle in schema)


def fichier_conf(tmp_path, retirer=None):
    texte = Path('server/conf/paresia.conf').read_text(encoding='utf-8')
    if retirer:
        texte = re.sub(r'^' + retirer + r' = .*\n', '', texte, flags=re.M)
    fichier = tmp_path / 'r.conf'
    fichier.write_text(texte, encoding='utf-8')
    fichier.chmod(0o600)
    return str(fichier)


def test_configuration_controles_croises():
    def lire(**environ):
        return configuration(argv=['--config', 'server/conf/paresia.conf'], environ=environ,
                             chargeur=CHARGEUR)

    assert lire()['relay']['flux_max_simultanes'] == 8
    for cle, valeur in (('PING_DELAI_S', '30'), ('PING_DELAI_S', '31'),
                        ('FLUX_MAX_SIMULTANES', '1025')):
        with pytest.raises(ErreurConfiguration) as info:
            lire(**{'PARESIA_ROMULUS_RELAY_' + cle: valeur})
        assert (info.value.code, info.value.section) == ('config_invalid', 'relay'), cle
        assert info.value.cle == cle.lower()
    with pytest.raises(ErreurConfiguration) as info:
        lire(PARESIA_ROMULUS_RELAY_FLUX_MAX_SIMULTANES='0')
    assert info.value.code == 'config_invalid'
    assert lire(PARESIA_ROMULUS_RELAY_FLUX_MAX_SIMULTANES='1024')['relay']['flux_max_simultanes'] == 1024


def test_configuration_option_manquante(tmp_path):
    for cle, section in (('bunkerd_socket', 'bunker'), ('bunkerd_uid', 'bunker'),
                         ('remus_socket', 'relay'), ('remus_uid', 'relay'),
                         ('pollux_socket', 'relay'), ('pollux_uid', 'relay')):
        with pytest.raises(ErreurConfiguration) as info:
            configuration(argv=['--config', fichier_conf(tmp_path, cle)], environ={},
                          chargeur=CHARGEUR)
        assert (info.value.code, info.value.section, info.value.cle) == ('config_missing', section, cle)


def test_configuration_section_sans_declaration_refusee():
    # Sans déclaration chargée, une section de service est inconnue (lecture stricte au second temps).
    with pytest.raises(ErreurConfiguration) as info:
        configuration(argv=['--config', 'server/conf/paresia.conf'], environ={},
                      chargeur={**CHARGEUR, 'livrees': str(RACINE / 'absent-livrees')})
    assert info.value.code == 'config_unknown_section' and info.value.section == 'bunker'


def test_configuration_nisaba_facultative(tmp_path):
    config = configuration(argv=['--config', 'server/conf/paresia.conf'], environ={},
                           chargeur=CHARGEUR)
    assert config['nisaba'] == {'socket': None, 'uid': None, 'delai_s': 120, 'max_line': 1048576}
    config = configuration(argv=['--config', 'server/conf/paresia.conf'], chargeur=CHARGEUR, environ={
        'PARESIA_ROMULUS_NISABA_SOCKET': '/run/exemple/n.sock', 'PARESIA_ROMULUS_NISABA_UID': '7'})
    assert config['nisaba']['socket'] == '/run/exemple/n.sock' and config['nisaba']['uid'] == 7


def test_configuration_dossiers_par_variables_et_par_section(tmp_path):
    ecrire(tmp_path / 'v', 'paresia-yang-exemple.toml', declaration())
    base = Path('server/conf/paresia.conf').read_text(encoding='utf-8')
    texte = re.sub(r'(?ms)^\[romulus\.bunker\].*?^\[romulus\.journal\]', '[romulus.journal]', base)
    fichier = tmp_path / 'sans.conf'
    fichier.write_text(texte + f'\n[romulus.exemple]\nsocket = /run/e.sock\nuid = 5\n', encoding='utf-8')
    fichier.chmod(0o600)
    chargeur = {'proprietaires': frozenset({EUID}), 'racine_confiance': str(tmp_path)}
    config = configuration(argv=['--config', str(fichier)], chargeur=chargeur, environ={
        'PARESIA_ROMULUS_PLUGINS_LIVREES': str(tmp_path / 'v'),
        'PARESIA_ROMULUS_PLUGINS_LOCALES': str(tmp_path / 'absent')})
    assert config['exemple']['socket'] == '/run/e.sock' and config['exemple']['delai_s'] == 5
    assert config['plugins'] == {'livrees': str(tmp_path / 'v'), 'locales': str(tmp_path / 'absent')}
    # La couche de fichier désigne aussi les dossiers.
    fichier.write_text(texte + f'\n[romulus.plugins]\nlivrees = {tmp_path / "v"}\n'
                       f'locales = {tmp_path / "absent"}\n[romulus.exemple]\nsocket = /run/e.sock\nuid = 5\n',
                       encoding='utf-8')
    assert configuration(argv=['--config', str(fichier)], chargeur=chargeur,
                         environ={})['exemple']['uid'] == 5


def test_configuration_declaration_livree_defectueuse(tmp_path):
    ecrire(tmp_path / 'l', 'paresia-yang-exemple.toml', 'format = 2\n')
    with pytest.raises(ErreurConfiguration) as info:
        configuration(argv=['--config', 'server/conf/paresia.conf'], environ={},
                      chargeur=chargeur_de(tmp_path))
    assert (info.value.code, info.value.section, info.value.cle) == (
        'service_format_unsupported', 'plugins', 'livrees')


# -- Nisaba ---------------------------------------------------------------------------------

def test_nisaba_aiguille_et_verifie_l_uid(dossier_socket):  # noqa: F811
    faux, ordre = pairs(dossier_socket, nisaba=lambda r, c: reponse(r['id'], {'taches': {}}))
    try:
        with demarrer(dossier_socket, section_nisaba(faux['nisaba'])) as b:
            assert appeler(b, 'nisaba/state/status') == (200, {'ok': True, 'data': {'taches': {}}})
            envoye = faux['nisaba'].recus[-1]
            assert envoye['action'] == 'nisaba/state/status' and envoye['params'] == {}
            assert envoye['session'] == b.session
            assert appeler(b, 'nisaba/state/verify')[0] == 200
            assert appeler(b, 'nisaba/state/status', {'x': 1}) == erreur(400, 'bad_request')
            assert len(faux['nisaba'].recus) == 2
            faux['nisaba'].comportement = lambda r, c: reponse(r['id'], code='command_busy')
            assert appeler(b, 'nisaba/state/status') == erreur(503, 'command_busy')
            faux['nisaba'].comportement = lambda r, c: reponse(r['id'], code='invalid_identity')
            assert appeler(b, 'nisaba/state/status') == erreur(500, 'internal_error')
            routes = [json.loads(l) for l in b.flux.getvalue().splitlines()
                      if json.loads(l)['event'] == 'action_routed']
            assert {r['destination'] for r in routes} == {'nisaba'}
            # Autre uid de pair : refus avant tout envoi.
            avant = len(faux['nisaba'].recus)
            b.config['nisaba']['uid'] = EUID + 1
            assert appeler(b, 'nisaba/state/status') == erreur(503, 'peer_unavailable')
            assert len(faux['nisaba'].recus) == avant
            # Les actions réservées à la socket de contrôle n'ont pas de route.
            assert appeler(b, 'nisaba/job/run') == erreur(404, 'unknown_action')
    finally:
        for pair in faux.values():
            pair.arreter()


def test_nisaba_sans_section_ou_sans_declaration(dossier_socket):  # noqa: F811
    with demarrer(dossier_socket) as b:
        for action in ('nisaba/state/status', 'nisaba/state/verify', 'nisaba/catalog/list',
                       'nisaba/catalog/describe'):
            assert appeler(b, action, {'action': 'nisaba/state/status'}
                           if action.endswith('describe') else None) == erreur(501, 'not_available')
    # Section présente mais sans socket : même refus.
    with demarrer(dossier_socket, {'nisaba': {'socket': None, 'uid': None, 'delai_s': 5,
                                              'max_line': 65536}}) as b:
        assert appeler(b, 'nisaba/state/status') == erreur(501, 'not_available')
    # Sans la déclaration de Nisaba : aucune route.
    ecrire(dossier_socket / 'l', 'paresia-yang-bunkerd.toml',
           (DOSSIER_SERVICES / 'paresia-yang-bunkerd.toml').read_text(encoding='utf-8'))
    with demarrer(dossier_socket, chargeur=chargeur_de(dossier_socket)) as b:
        assert appeler(b, 'nisaba/state/status') == erreur(404, 'unknown_action')
        assert appeler(b, 'bunker/identity/list') == erreur(501, 'not_available')


# -- introspection ------------------------------------------------------------------------

def test_introspection_par_declaration_sans_appeler_le_service(dossier_socket):  # noqa: F811
    faux, _ = pairs(dossier_socket, bunkerd=None, nisaba=None)
    try:
        sections = {**section_bunker(faux['bunkerd']), **section_nisaba(faux['nisaba'])}
        with demarrer(dossier_socket, sections) as b:
            par = par_domaine()
            vus = ''
            for domaine, pair in (('bunker', faux['bunkerd']), ('nisaba', faux['nisaba'])):
                service = par[domaine]
                statut, corps = appeler(b, f'{domaine}/catalog/list')
                vus += json.dumps(corps)
                assert statut == 200 and corps['ok']
                data = corps['data']
                assert data['proto'] == 'jumeaux/1' and data['target'] == CIBLE_DEFAUT
                assert data['domain'] == domaine and data['format'] == 1
                attendues = {a.action for a in service.actions} | {
                    f'{domaine}/catalog/list', f'{domaine}/catalog/describe'}
                assert {a['action'] for a in data['actions']} == attendues
                assert {a['plugin'] for a in data['actions']} == {service.greffon, None}
                assert len(data['actions']) == len(service.actions) + 2
                for declaree in service.actions:
                    statut, corps = appeler(b, f'{domaine}/catalog/describe',
                                            {'action': declaree.action})
                    assert (statut, corps) == (200, {'ok': True, 'data': declaree.descripteur.publier()})
                    vus += json.dumps(corps)
                assert pair.recus == []
                assert appeler(b, f'{domaine}/catalog/list', {'x': 1}) == erreur(400, 'bad_request')
                assert appeler(b, f'{domaine}/catalog/describe') == erreur(400, 'bad_request')
                assert appeler(b, f'{domaine}/catalog/describe',
                               {'action': f'{domaine}/catalog/list', 'x': 1}) == erreur(400, 'bad_request')
                assert appeler(b, f'{domaine}/catalog/describe',
                               {'action': f'{domaine}/objet/absent'}) == erreur(404, 'unknown_action')
            # Paramètres typés et bornés, erreurs : publiés tels quels.
            _, corps = appeler(b, 'bunker/catalog/describe', {'action': 'bunker/identity/add'})
            noms = {p['name']: p for p in corps['data']['parameters']}
            assert noms['timeout_min']['required'] is False and noms['relays']['type'] == 'liste_texte'
            assert noms['relays']['bounds']['nombre_max'] == 10
            assert 'invalid_relays' in corps['data']['errors']
            assert faux['bunkerd'].recus == [] and faux['nisaba'].recus == []
            for secret in (faux['bunkerd'].chemin, faux['nisaba'].chemin, str(dossier_socket), '.sock'):
                assert secret not in vus
    finally:
        for pair in faux.values():
            pair.arreter()


def test_introspection_sans_section_501(dossier_socket):  # noqa: F811
    with demarrer(dossier_socket) as b:
        assert appeler(b, 'bunker/catalog/list') == erreur(501, 'not_available')
        assert appeler(b, 'bunker/catalog/describe',
                       {'action': 'bunker/identity/list'}) == erreur(501, 'not_available')


def test_introspection_pair_transmise_au_service(dossier_socket):  # noqa: F811
    faux, ordre = pairs(dossier_socket, remus=lambda r, c: reponse(r['id'], {'actions': []}),
                        pollux=None)
    try:
        with demarrer(dossier_socket, section_relay(faux['remus'], faux['pollux'])) as b:
            assert appeler(b, 'relay/catalog/list') == (200, {'ok': True, 'data': {'actions': []}})
            envoye = faux['remus'].recus[-1]
            assert (envoye['action'], envoye['params'], envoye['session']) == (
                'relay/catalog/list', {}, b.session)
            assert appeler(b, 'relay/catalog/describe',
                           {'action': 'relay/state/status'})[0] == 200
            assert faux['remus'].recus[-1]['params'] == {'action': 'relay/state/status'}
            avant = len(faux['remus'].recus)
            assert appeler(b, 'relay/catalog/list', {'x': 1}) == erreur(400, 'bad_request')
            assert appeler(b, 'relay/catalog/describe') == erreur(400, 'bad_request')
            assert appeler(b, 'relay/catalog/describe', {'action': 3}) == erreur(400, 'bad_request')
            assert len(faux['remus'].recus) == avant
            # Le Répertoire de Romulus ne contient pas ce domaine.
            assert b.demon.aiguillage.repertoire.obtenir(CIBLE_DEFAUT, 'relay') is None
            faux['remus'].comportement = lambda r, c: reponse(r['id'], code='unknown_action')
            assert appeler(b, 'relay/catalog/list') == erreur(501, 'not_available')
            faux['remus'].arreter()
            os.unlink(faux['remus'].chemin)
            assert appeler(b, 'relay/catalog/list') == erreur(503, 'peer_unavailable')
    finally:
        for pair in faux.values():
            pair.arreter()


def test_relay_params_transmis_sans_prevalidation(dossier_socket):  # noqa: F811
    faux, _ = pairs(dossier_socket, remus=None, pollux=None)
    try:
        with demarrer(dossier_socket, section_relay(faux['remus'], faux['pollux'])) as b:
            params = {'filtre': {'imbrique': [1, 2]}, 'n': 3}
            assert appeler(b, 'relay/events/list', params)[0] == 200
            assert faux['remus'].recus[-1]['params'] == params
    finally:
        for pair in faux.values():
            pair.arreter()


def test_params_transmis_regles(tmp_path):
    transmis = '\n[[actions]]\nnom = "objet/libre"\nparams_transmis = true\n'
    pair = declaration(haut='', actions=transmis).replace('catalogue = "declaration"', 'catalogue = "pair"')
    assert charger(tmp_path / 'a', {'paresia-yang-exemple.toml': pair}).services[0].actions[0].params_transmis
    avec_param = pair.replace('params_transmis = true\n', '''params_transmis = true

[[actions.parametres]]
nom = "n"
type = "entier"
bornes = { minimum = 0, maximum = 1 }
''')
    assert codes_de(tmp_path / 'b', {'paresia-yang-exemple.toml': avec_param})[0] == 'service_declaration_invalid'
    hors_pair = pair.replace('catalogue = "pair"', 'catalogue = "declaration"')
    assert codes_de(tmp_path / 'c', {'paresia-yang-exemple.toml': hors_pair})[0] == 'service_declaration_invalid'


# -- domaine fictif : neutralité de Romulus -------------------------------------------------

def test_domaine_fictif_route_prevalide_et_introspectable(dossier_socket):  # noqa: F811
    racine = dossier_socket
    ecrire(racine / 'l', 'paresia-yang-exemple.toml', declaration())
    faux, _ = pairs(racine, exemple=lambda r, c: reponse(r['id'], {'vu': r['params']}))
    try:
        sections = {'exemple': {'socket': faux['exemple'].chemin, 'uid': EUID, 'delai_s': 2,
                                'max_line': 65536}}
        with demarrer(racine, sections, chargeur_de(racine)) as b:
            assert appeler(b, 'exemple/objet/lire', {'nom': 'abc'}) == (
                200, {'ok': True, 'data': {'vu': {'nom': 'abc'}}})
            assert appeler(b, 'exemple/objet/lire', {'nom': 'abc', 'n': 2})[0] == 200
            avant = len(faux['exemple'].recus)
            for mauvais in ({}, {'nom': 3}, {'nom': 'a', 'n': True}, {'nom': 'a', 'n': 1.5},
                            {'nom': 'a', 'autre': 1}, {'nom': ['a']}):
                assert appeler(b, 'exemple/objet/lire', mauvais) == erreur(400, 'bad_request')
            assert len(faux['exemple'].recus) == avant
            assert appeler(b, 'exemple/objet/etat')[0] == 200
            # Bornes publiées, non appliquées : le service reste l'autorité.
            assert appeler(b, 'exemple/objet/lire', {'nom': 'A' * 99, 'n': 5000})[0] == 200
            statut, corps = appeler(b, 'exemple/catalog/describe', {'action': 'exemple/objet/lire'})
            assert statut == 200
            assert corps['data']['parameters'][0]['bounds'] == {'motif': '[a-z]+', 'longueur_max': 16}
            assert corps['data']['errors'] == ['command_busy']
            liste = appeler(b, 'exemple/catalog/list')[1]['data']['actions']
            assert {a['action']: a['plugin'] for a in liste}['exemple/objet/lire'] == (
                'paresia-yang-exemple')
            # Les autres domaines livrés ne sont pas déclarés dans ce dossier.
            assert appeler(b, 'bunker/identity/list') == erreur(404, 'unknown_action')
            assert b.demon.aiguillage.destination(CIBLE_DEFAUT, 'exemple') is not None
            assert b.demon.aiguillage.destination('autre', 'exemple') is None
            assert b.demon.aiguillage.repertoire.obtenir(CIBLE_DEFAUT, 'exemple') is not None
    finally:
        faux['exemple'].arreter()


def test_bornes_non_appliquees_par_romulus(dossier_socket):  # noqa: F811
    faux, _ = pairs(dossier_socket, bunkerd=lambda r, c: reponse(r['id'], code='invalid_timeout'))
    try:
        with demarrer(dossier_socket, section_bunker(faux['bunkerd'])) as b:
            parametres = {'identity': 'a', 'ncryptsec': 'x', 'relays': ['wss://r.example']}
            assert appeler(b, 'bunker/identity/add', {**parametres, 'timeout_min': 5000}) == erreur(
                422, 'invalid_timeout')
            assert faux['bunkerd'].recus[-1]['params']['timeout_min'] == 5000
            assert appeler(b, 'bunker/identity/add', {**parametres, 'timeout_min': True}) == erreur(
                400, 'bad_request')
            assert appeler(b, 'bunker/identity/clients', {'identity': 5}) == erreur(400, 'bad_request')
            assert len(faux['bunkerd'].recus) == 1
    finally:
        faux['bunkerd'].arreter()


# -- comportements génériques ---------------------------------------------------------------

def test_roles_et_options_generiques(dossier_socket):  # noqa: F811
    par = par_domaine()
    assert par['relay'].roles() == {
        'socket': 'remus_socket', 'uid': 'remus_uid', 'ping_socket': 'pollux_socket',
        'ping_uid': 'pollux_uid', 'delai': 'delai_s', 'ping_delai': 'ping_delai_s',
        'battement': 'heartbeat_s', 'max_line': 'max_line', 'flux_max': 'flux_max_simultanes'}
    assert par['relay'].option('ping_delai_s').inferieure_a == 'heartbeat_s'
    assert par['relay'].option('flux_max_simultanes').maximum == 1024
    assert par['legal'].section is None and par['legal'].sans_destination
    assert par['nisaba'].obligatoire is False and par['bunker'].obligatoire is True
    assert [a.action for a in par['relay'].actions if a.suivi] == ['relay/state/follow']
    assert all(a.params_transmis for a in par['relay'].actions)
    assert [a.action for a in par['legal'].actions if a.export] == ['legal/journal/export']
    with demarrer(dossier_socket) as b:
        assert b.demon.http.exports == {'legal/journal/export'}
        assert b.demon.http.suivis == {'relay/state/follow'}
        assert b.demon.http.chemins == {PREFIXE + a for a in declarations_livrees().actions_routables()} | {
            c for c in b.demon.http.chemins if c.startswith(PREFIXE + 'kernel/')}
        assert len([c for c in b.demon.http.chemins if c.startswith(PREFIXE + 'kernel/')]) == 5
        assert b.demon.aiguillage._places_flux is not None


def test_ping_et_oubli_par_declaration(dossier_socket):  # noqa: F811
    faux, ordre = pairs(dossier_socket, remus=None, pollux=None)
    try:
        with demarrer(dossier_socket, section_relay(faux['remus'], faux['pollux'])) as b:
            assert appeler(b, 'relay/state/status')[0] == 200
            assert appeler(b, 'relay/state/status')[0] == 200
            assert len(faux['pollux'].recus) == 1
            assert faux['pollux'].recus[0]['action'] == 'presence/relay/ping'
            faux['remus'].comportement = lambda r, c: reponse(r['id'], code='relay_light_red')
            assert appeler(b, 'relay/state/status') == erreur(503, 'relay_light_red')
            faux['remus'].comportement = ok
            assert appeler(b, 'relay/state/status')[0] == 200
            assert len(faux['pollux'].recus) == 2
    finally:
        for pair in faux.values():
            pair.arreter()


def test_ping_sans_service_declare_ne_fait_rien(dossier_socket):  # noqa: F811
    racine = dossier_socket
    ecrire(racine / 'l', 'paresia-yang-exemple.toml', declaration())
    faux, _ = pairs(racine, exemple=None)
    try:
        sections = {'exemple': {'socket': faux['exemple'].chemin, 'uid': EUID}}
        with demarrer(racine, sections, chargeur_de(racine)) as b:
            assert b.demon.aiguillage._comportement is None
            b.demon.aiguillage._pinguer(b.session)
            assert appeler(b, 'exemple/objet/etat')[0] == 200
    finally:
        faux['exemple'].arreter()


def test_export_par_declaration_et_route_sans_destination(dossier_socket):  # noqa: F811
    with demarrer(dossier_socket) as b:
        assert appeler(b, 'legal/journal/export') == erreur(501, 'not_available')
        b.demon.http.actions['legal/journal/export'] = lambda p, s: {'ok': True, 'data': {'count': 0}}
        assert appeler(b, 'legal/journal/export') == (200, {'ok': True, 'data': {'count': 0}})
        assert appeler(b, 'legal/journal/inconnue') == erreur(404, 'unknown_action')


def test_connexions_avec_ensemble_d_actions(dossier_socket, monkeypatch):  # noqa: F811
    appels = []
    origine = module_aiguillage.Connexion

    def espion(*arguments, **options):
        appels.append(options)
        return origine(*arguments, **options)

    monkeypatch.setattr(module_aiguillage, 'Connexion', espion)
    faux, _ = pairs(dossier_socket, bunkerd=None, remus=None, pollux=None)
    try:
        sections = {**section_bunker(faux['bunkerd']), **section_relay(faux['remus'], faux['pollux'])}
        with demarrer(dossier_socket, sections) as b:
            assert appeler(b, 'bunker/identity/list')[0] == 200
            assert appeler(b, 'relay/state/status')[0] == 200
        assert len(appels) == 3
        assert all(type(o['actions']) is frozenset for o in appels)
        assert frozenset({'presence/relay/ping'}) in [o['actions'] for o in appels]
        assert any('bunker/catalog/describe' in o['actions'] and 'bunker/identity/list' in o['actions']
                   for o in appels)
        assert any('relay/catalog/list' in o['actions'] and 'relay/state/follow' in o['actions']
                   for o in appels)
        # Une action hors de l'ensemble n'est jamais envoyée par la connexion.
        connexion = origine(faux['bunkerd'].chemin, 1, actions=appels[0]['actions'])
        faux['bunkerd'].recus.clear()
        with pytest.raises(Exception):
            connexion.appeler({'proto': 'jumeaux/1', 'id': '0' * 16, 'session': 0,
                               'action': 'bunker/identity/inconnue', 'params': {}})
        assert faux['bunkerd'].recus == []
    finally:
        for pair in faux.values():
            pair.arreter()


def appels_connexion(chemin):
    arbre = ast.parse(Path(chemin).read_text(encoding='utf-8'))
    return [n for n in ast.walk(arbre) if isinstance(n, ast.Call)
            and getattr(n.func, 'id', None) == 'Connexion']


def test_chaque_site_connexion_porte_actions():
    sites = appels_connexion('server/romulus/aiguillage.py') + appels_connexion('server/romulus/flux.py')
    assert len(sites) == 2     # le service, le ping ; le flux passe par la méthode du premier
    for site in sites:
        assert 'actions' in {k.arg for k in site.keywords}


# -- non-fermeture ---------------------------------------------------------------------------

MOTS_LANGAGE = ('interpreteur', 'module', 'classe', 'import', 'script', 'privilege',
                'commandes_privilegiees', 'yin', 'python', 'sudo', 'entry', 'exec')


def test_cles_exactes_sans_notion_de_langage_ni_de_contrepartie():
    assert services.CLES_DECLARATION == frozenset({
        'format', 'forme', 'greffon', 'cible', 'domaine', 'section', 'options', 'obligatoire',
        'sans_destination', 'destination', 'ping', 'ping_oubli', 'actions', 'codes', 'catalogue', 'pages'})
    assert set(services.ROLES_OPTION) == {
        'socket', 'uid', 'delai', 'max_line', 'flux_max', 'battement', 'ping_delai',
        'ping_socket', 'ping_uid'}
    for cle in (*services.CLES_DECLARATION, *services.ROLES_OPTION, *services.CLES_ACTION,
                *services.CLES_OPTION, *services.CLES_PARAMETRE):
        assert not any(mot in cle for mot in MOTS_LANGAGE), cle


def test_reponses_d_introspection_sans_contrepartie():
    for service in declarations_livrees().services:
        for declaree in service.actions:
            publie = declaree.descripteur.publier()
            assert set(publie) == {'action', 'plugin', 'privilege', 'delay_s', 'parameters', 'errors'}
            assert publie['plugin'] == service.greffon and publie['privilege'] is None
            assert 'yin' not in json.dumps(publie)
        reponse_liste = service.catalogue.reponse(action_catalogue(service.domaine, 'list'), {})
        assert 'yin' not in json.dumps(reponse_liste)
        assert set(reponse_liste) == {'proto', 'target', 'domain', 'format', 'actions'}


def test_aucune_resolution_de_greffon_yin():
    for chemin in (*Path('server/romulus').glob('*.py'), Path('server/commun/services.py')):
        assert 'paresia-yin' not in chemin.read_text(encoding='utf-8'), chemin.name


def test_forme_absente_ou_ponctuelle_pour_les_livrees():
    for chemin in DOSSIER_SERVICES.glob('*.toml'):
        texte = chemin.read_text(encoding='utf-8')
        assert re.search(r'^forme = "ponctuel"$', texte, re.M) and re.search(r'^format = 1$', texte, re.M)


def test_tables_indexees_par_cible_et_domaine(dossier_socket):  # noqa: F811
    faux, _ = pairs(dossier_socket, bunkerd=None)
    try:
        with demarrer(dossier_socket, section_bunker(faux['bunkerd'])) as b:
            aiguillage = b.demon.aiguillage
            assert list(aiguillage.destinations) == [(CIBLE_DEFAUT, 'bunker')]
            assert aiguillage.destination(CIBLE_DEFAUT, 'bunker') is not None
            assert aiguillage.destination('autre', 'bunker') is None
            assert aiguillage.repertoire.cles() == [(CIBLE_DEFAUT, 'bunker'), (CIBLE_DEFAUT, 'nisaba')]
            assert repr(aiguillage.destination(CIBLE_DEFAUT, 'bunker')) == '<Liaison>'
    finally:
        faux['bunkerd'].arreter()


# -- neutralité et hygiène du code ------------------------------------------------------------

def noms_et_litteraux(chemin):
    """Identifiants et chaînes du code (ni commentaires ni docstrings), par arbre syntaxique."""
    arbre = ast.parse(Path(chemin).read_text(encoding='utf-8'))
    docstrings = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            premier = noeud.body[0] if noeud.body else None
            if (isinstance(premier, ast.Expr) and isinstance(premier.value, ast.Constant)
                    and isinstance(premier.value.value, str)):
                docstrings.add(id(premier.value))
    trouves = []
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str) \
                and id(noeud) not in docstrings:
            trouves.append(noeud.value)
        elif isinstance(noeud, ast.Name):
            trouves.append(noeud.id)
        elif isinstance(noeud, ast.Attribute):
            trouves.append(noeud.attr)
        elif isinstance(noeud, (ast.FunctionDef, ast.ClassDef)):
            trouves.append(noeud.name)
        elif isinstance(noeud, ast.arg):
            trouves.append(noeud.arg)
        elif isinstance(noeud, ast.keyword) and noeud.arg:
            trouves.append(noeud.arg)
    return trouves


def test_neutralite_du_noyau_de_romulus():
    motif = re.compile(r'bunker|nisaba|legal|strfry|\brelay\b|remus_socket|pollux_socket'
                       r'|bunkerd_socket|bunkerd_uid|remus_uid|pollux_uid', re.I)
    fichiers = [*Path('server/romulus').glob('*.py'), Path('server/commun/services.py')]
    trouves = {}
    for chemin in fichiers:
        for texte in noms_et_litteraux(chemin):
            if motif.search(texte):
                trouves.setdefault(chemin.name, []).append(texte)
    # Seule l'action du noyau « ping de session » nomme un greffon, par son identifiant de protocole.
    assert trouves == {'aiguillage.py': ['presence/relay/ping']}
    # Aucune socket de service ni nom de cible écrits en dur dans le point de contact.
    for chemin in Path('server/romulus').glob('*.py'):
        for texte in noms_et_litteraux(chemin):
            assert not texte.endswith('.sock') and not texte.startswith('/run'), chemin.name
            assert texte != 'principale', chemin.name


def test_services_sans_chargement_de_code():
    interdits_imports = {'ctypes', 'multiprocessing', 'socket', 'pty', 'shlex', 'subprocess',
                         'importlib', 'runpy', 'pkgutil'}
    arbre = ast.parse(Path('server/commun/services.py').read_text(encoding='utf-8'))
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            assert not {a.name.split('.')[0] for a in noeud.names} & interdits_imports
        elif isinstance(noeud, ast.ImportFrom):
            assert (noeud.module or '').split('.')[0] not in interdits_imports
            if (noeud.module or '').endswith('plugins'):
                assert 'charger' not in {a.name for a in noeud.names}
        elif isinstance(noeud, ast.Name):
            assert noeud.id not in {'exec', 'eval', '__import__', 'entry_points', 'getattr'}
        elif isinstance(noeud, ast.Attribute):
            assert not noeud.attr.startswith(('fork', 'exec', 'posix_spawn'))
            assert noeud.attr not in {'system', 'popen', 'import_module', 'entry_points', 'charger'}
    source = Path('server/commun/services.py').read_text(encoding='utf-8')
    assert 'shell=True' not in source and 'AGPL-3.0-or-later' in source.split('\n')[0]


def test_declarations_livrees_sans_renvoi_a_une_tache_et_sans_chemin_du_poste():
    for chemin in DOSSIER_SERVICES.glob('*.toml'):
        texte = chemin.read_text(encoding='utf-8')
        assert texte.startswith('# SPDX-License-Identifier: AGPL-3.0-or-later')
        assert not re.search(r'\bT\d{3}\b|fiche|coordinateur|/home/|\.worktrees', texte), chemin.name
        assert stat.S_ISREG(chemin.stat().st_mode)


def test_erreurs_de_service_sans_valeur_fautive(tmp_path):
    mauvais = declaration().replace('format = 1', 'format = 1\nforme = "valeur-secrete-xyz"')
    with pytest.raises(services.ErreurService) as info:
        charger(tmp_path, {'paresia-yang-exemple.toml': mauvais})
    assert 'valeur-secrete-xyz' not in repr(info.value) and 'valeur-secrete-xyz' not in str(info.value)
    assert str(tmp_path) not in str(info.value) and '/' not in (info.value.fichier or '')


# -- socket et uid : l'un ne va pas sans l'autre ----------------------------------------------

@pytest.mark.parametrize('section', [
    {'socket': '/x/s'}, {'uid': 5},
    {'socket': '/x/s', 'uid': 5, 'ping_socket': '/x/p'},
    {'socket': '/x/s', 'uid': 5, 'ping_uid': 5}])
def test_socket_et_uid_vont_ensemble(tmp_path, section):
    declares = charger(tmp_path, {'paresia-yang-exemple.toml': declaration(ping=True)})
    with pytest.raises(ErreurConfiguration) as exc:
        services.verifier_options(declares, {'exemple': section})
    assert exc.value.code == 'config_invalid'


def test_socket_et_uid_complets_ou_absents(tmp_path):
    declares = charger(tmp_path, {'paresia-yang-exemple.toml': declaration(ping=True)})
    services.verifier_options(declares, {'exemple': {}})
    services.verifier_options(declares, {'exemple': {
        'socket': '/x/s', 'uid': 5, 'ping_socket': '/x/p', 'ping_uid': 5}})


def test_aucune_connexion_sans_uid_serveur(monkeypatch):
    construites = []
    monkeypatch.setattr(module_aiguillage, 'Connexion',
                        lambda *a, **k: construites.append(k))
    aiguillage = module_aiguillage.Aiguillage.__new__(module_aiguillage.Aiguillage)
    option = lambda nom, role: SimpleNamespace(nom=nom, role=role, defaut=None)  # noqa: E731
    service = SimpleNamespace(options=(option('s', 'socket'), option('u', 'uid'),
                                       option('ps', 'ping_socket'), option('pu', 'ping_uid')))
    liaison = module_aiguillage.Liaison(service, {'s': '/x/s', 'ps': '/x/p'}, frozenset())
    with pytest.raises(module_aiguillage.UidServeurAbsent):
        aiguillage._connexion(liaison)
    with pytest.raises(module_aiguillage.UidServeurAbsent):
        aiguillage._ping_pair(liaison, 'session')
    assert construites == []


# -- pages d'un greffon, journaliser, greffon sans action ----------------------------------------

PAGE = '[[pages]]\nid = "etat"\ntitre_cle = "ui_exemple_etat"\nscript = "etat.js"\n'


def avec_pages(*pages):
    return declaration() + ''.join(pages)


def refusee(tmp_path, texte):
    with pytest.raises(services.ErreurService) as e:
        charger(tmp_path, {'paresia-yang-exemple.toml': texte})
    assert e.value.code == 'service_declaration_invalid'
    locales = charger(tmp_path / 'loc', {}, {'paresia-yang-exemple.toml': texte})
    assert [r.code for r in locales.rejets] == ['service_declaration_invalid']
    assert not locales.services


def test_pages_valides(tmp_path):
    declares = charger(tmp_path, {'paresia-yang-exemple.toml': avec_pages(
        PAGE, PAGE.replace('"etat"', '"autre"').replace('etat.js', 'a.b-c_d.js'))})
    pages = declares.services[0].pages
    assert [(p.id, p.titre_cle, p.script) for p in pages] == [
        ('etat', 'ui_exemple_etat', 'etat.js'), ('autre', 'ui_exemple_etat', 'a.b-c_d.js')]


def test_pages_sans_cle_inchange(tmp_path):
    assert charger(tmp_path, {'paresia-yang-exemple.toml': declaration()}).services[0].pages == ()


def test_titre_cle_prefixe_avec_tirets_remplaces(tmp_path):
    texte = declaration('mon_greffon', greffon='paresia-yang-mon-greffon') + PAGE.replace(
        'ui_exemple_etat', 'ui_mon_greffon_etat')
    charger(tmp_path, {'paresia-yang-mon-greffon.toml': texte})


@pytest.mark.parametrize('page', [
    PAGE + 'extra = 1\n',
    PAGE.replace('script = "etat.js"\n', ''),
    PAGE.replace('etat.js', 'dir/etat.js'),
    PAGE.replace('etat.js', '../etat.js'),
    PAGE.replace('etat.js', 'etat.txt'),
    PAGE.replace('ui_exemple_etat', 'ui_autre_etat'),
    PAGE.replace('ui_exemple_etat', 'ui_exemple_'),
    PAGE.replace('ui_exemple_etat', 'exemple_etat'),
    PAGE.replace('"etat"', '"Etat"'),
])
def test_pages_invalides(tmp_path, page):
    refusee(tmp_path, avec_pages(page))


def test_pages_doublon_et_plafond(tmp_path):
    refusee(tmp_path / 'a', avec_pages(PAGE, PAGE.replace('etat.js', 'b.js')))
    seize = ''.join(PAGE.replace('"etat"', f'"p{i}"') for i in range(16))
    assert len(charger(tmp_path / 'b', {'paresia-yang-exemple.toml': avec_pages(seize)}
                       ).services[0].pages) == 16
    refusee(tmp_path / 'c', avec_pages(seize + PAGE))


ACTION_JOURNALISEE = '''
[[actions]]
nom = "objet/agir"
journaliser = ["cible"]

[[actions.parametres]]
nom = "cible"
type = "texte"
bornes = { motif = '[a-z]+', longueur_max = 16 }
'''


def test_journaliser_par_action(tmp_path):
    texte = declaration(actions=ACTION_JOURNALISEE)
    action = charger(tmp_path, {'paresia-yang-exemple.toml': texte}).services[0].actions[0]
    assert action.journaliser == ('cible',)
    for i, variante in enumerate(('journaliser = ["inconnu"]', 'journaliser = ["cible", "cible"]',
                                  'journaliser = "cible"')):
        refusee(tmp_path / str(i), texte.replace('journaliser = ["cible"]', variante))


def test_greffon_sans_action_ni_section(tmp_path):
    texte = ('format = 1\ngreffon = "paresia-yang-exemple"\ndomaine = "exemple"\n'
             'sans_destination = true\ncatalogue = "aucun"\n' + PAGE)
    service = charger(tmp_path, {'paresia-yang-exemple.toml': texte}).services[0]
    assert service.actions == () and service.section is None and len(service.pages) == 1
    refusee(tmp_path / 'x', texte.replace('sans_destination = true', 'sans_destination = false'))


def test_declaration_webui_livree():
    service = [s for s in declarations_livrees().services if s.greffon == 'paresia-yang-webui'][0]
    assert (service.domaine, service.sans_destination, service.actions, service.pages,
            service.catalogue_mode) == ('webui', True, (), (), 'aucun')
