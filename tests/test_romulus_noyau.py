# Tests du domaine kernel de Romulus ; dépendances : pytest, bibliothèque standard et server.
# Suivi des versions
#   0.1.15  2026-11-08  Première version : cinq actions, masquage, métriques, journal d'activité, configuration.
import io
import json
import os
from pathlib import Path
import re
import secrets
import socket
import tempfile
from http.client import HTTPConnection

import pytest

from romulus_outils import CHARGEUR, RACINE
from server.commun.client import Connexion
from server.commun.config import ErreurConfiguration
from server.commun.journal import Journal
from server.romulus import Romulus, configuration
from server.romulus.noyau import analyser_metriques, masquee
from test_romulus_presence_http import appel, config_test

EUID = os.geteuid()
PREFIXE = '/api/admin/kernel/'


@pytest.fixture
def racine():
    with tempfile.TemporaryDirectory(prefix='noyau-') as dossier:
        yield Path(dossier)


def demarrer(racine, detail=1, **activite):
    etat = racine / 'etat'
    os.makedirs(etat, mode=0o755, exist_ok=True)
    config = config_test(racine)
    config['activite'] = {'detail': detail, 'taille_max': 65536, 'regroupement_max': 100000,
                          'regroupements_simultanes': 64, 'dossier': None, **activite}
    config['noyau'] = {'dossier_etat': str(etat)}
    flux = io.StringIO()
    confiance = {'proprietaires': {EUID}, 'racine_confiance': str(racine),
                 'racine_systeme': racine / 'etc', 'version': lambda: '9.9.9'}
    demon = Romulus(config, journal=Journal('romulus', flux=flux), chargeur=CHARGEUR,
                    environ={'STATE_DIRECTORY': str(etat)}, confiance=confiance)
    return demon, flux, etat


def requete(demon, chemin, token=None, corps=None, origine='http://localhost'):
    sock = socket.socket(socket.AF_UNIX)
    sock.settimeout(3)
    sock.connect(demon.http.server_address)
    connexion = HTTPConnection('localhost')
    connexion.sock = sock
    entetes = {'Origin': origine}
    if token:
        entetes['X-Admin-Token'] = token
    try:
        try:
            connexion.request('POST', chemin, body=json.dumps(corps).encode() if corps is not None else b'',
                              headers=entetes)
        except (BrokenPipeError, ConnectionResetError):
            pass    # refus anticipé : le démon répond puis ferme sans lire le corps ; la réponse est déjà envoyée
        reponse = connexion.getresponse()
        brut = reponse.read()
        return reponse.status, json.loads(brut)
    finally:
        connexion.close()


def kernel(demon, token, action, corps=None):
    return requete(demon, PREFIXE + action, token, corps)


def session(demon, pollux):
    return appel(pollux)['data']['token']


@pytest.fixture
def banc(racine):
    demon, flux, etat = demarrer(racine)
    with demon:
        with Connexion(demon.presence.chemin) as pollux:
            yield demon, pollux, flux, etat, racine


def ecrire_prom(etat, demon, contenu, mode=0o644, dossier_mode=0o755):
    dossier = etat / f'paresia-{demon}'
    os.makedirs(dossier / 'metriques', exist_ok=True)
    os.chmod(dossier, dossier_mode)
    os.chmod(dossier / 'metriques', dossier_mode)
    chemin = dossier / 'metriques' / f'{demon}.prom'
    chemin.write_text(contenu)
    os.chmod(chemin, mode)
    return chemin


def test_cinq_actions_avec_jeton(banc):
    demon, pollux, *_ = banc
    token = session(demon, pollux)
    statut, corps = kernel(demon, token, 'state/status', {})
    assert statut == 200 and corps['data']['version'] == '9.9.9'
    assert corps['data']['sessions'] == 1 and corps['data']['activity_detail'] == 1
    assert [d['name'] for d in corps['data']['daemons']] == ['pollux', 'pollux-session', 'romulus']
    assert {d['metrics'] for d in corps['data']['daemons']} == {'disabled'}
    assert corps['data']['daemons'][1]['unit'] == ''
    statut, corps = kernel(demon, token, 'state/services', {})
    assert statut == 200
    assert {s['domain'] for s in corps['data']['services']} >= {'bunker', 'relay'}
    assert all(set(s) == {'domain', 'greffon', 'target', 'catalog', 'available'}
               for s in corps['data']['services'])
    assert kernel(demon, token, 'state/metrics', {'daemon': 'romulus'})[1]['data'] == {
        'daemon': 'romulus', 'available': False, 'samples': []}
    assert kernel(demon, token, 'state/config', {'daemon': 'romulus'})[0] == 200
    statut, corps = kernel(demon, token, 'activity/list', {})
    assert statut == 200 and corps['data']['detail'] == 1


def test_sans_jeton_ou_origine_fausse(banc):
    demon, pollux, *_ = banc
    token = session(demon, pollux)
    assert requete(demon, PREFIXE + 'state/status', None, {}) [1]['error']['code'] == 'token_missing'
    statut, corps = requete(demon, PREFIXE + 'state/status', token, {}, origine='http://autre')
    assert (statut, corps['error']['code']) == (403, 'origin_refused')
    assert requete(demon, PREFIXE + 'state/status', 'x' * 64, {})[1]['error']['code'] == 'token_unknown'
    assert requete(demon, PREFIXE + 'autre/chose/op', token, {})[0] == 404


@pytest.mark.parametrize('action,corps', [
    ('state/status', {'x': 1}), ('state/services', {'x': 1}),
    ('state/metrics', {}), ('state/metrics', {'daemon': 'strfry'}),
    ('state/metrics', {'daemon': 'romulus', 'x': 1}), ('state/metrics', {'daemon': 3}),
    ('state/config', {}), ('state/config', {'daemon': '../etc'}),
    ('activity/list', {'limit': 0}), ('activity/list', {'limit': 201}),
    ('activity/list', {'limit': -1}), ('activity/list', {'limit': True}),
    ('activity/list', {'limit': '5'}), ('activity/list', {'level': 0}),
    ('activity/list', {'level': 4}), ('activity/list', {'level': False}),
    ('activity/list', {'domain': 'Bunker'}), ('activity/list', {'domain': 'a/b'}),
    ('activity/list', {'domain': 5}), ('activity/list', {'inconnu': 1}),
])
def test_params_invalides(banc, action, corps, monkeypatch):
    demon, pollux, *_ = banc
    token = session(demon, pollux)
    ouvertures = []
    import server.romulus.noyau as noyau
    reel = noyau.ouvrir_dossier_confiance
    monkeypatch.setattr(noyau, 'ouvrir_dossier_confiance', lambda *a: ouvertures.append(a) or reel(*a))
    lectures = []
    monkeypatch.setattr(demon.activite, 'lire', lambda *a: lectures.append(a))
    statut, reponse = kernel(demon, token, action, corps)
    assert (statut, reponse['error']['code']) == (400, 'bad_request')
    assert not ouvertures and not lectures


def test_metriques_valides_et_hostiles(banc):
    demon, pollux, flux, etat, racine = banc
    token = session(demon, pollux)
    ecrire_prom(etat, 'romulus', '\n'.join([
        '# HELP paresia_up état', '# TYPE paresia_up gauge',
        'paresia_up{daemon="romulus"} 1', 'paresia_start_time_seconds{daemon="romulus"} 1.5e9',
        'ligne hostile sans forme', 'x{a="1} 3', 'nan_metrique NaN', 'inf_metrique +Inf',
        'bon{a="b\\"c",d="\x07e"} 2.5 1700000000000', '1mauvais 3', 'texte_libre 12abc',
        'long{l="' + 'z' * 500 + '"} 1']))
    statut, corps = kernel(demon, token, 'state/metrics', {'daemon': 'romulus'})
    assert statut == 200 and corps['data']['available'] is True
    noms = [s['name'] for s in corps['data']['samples']]
    assert noms == ['paresia_up', 'paresia_start_time_seconds', 'bon', 'long']
    bon = corps['data']['samples'][2]
    assert bon['labels']['a'] == 'b"c' and bon['labels']['d'] == '�e' and bon['value'] == 2.5
    assert len(corps['data']['samples'][3]['labels']['l']) == 128
    statut, corps = kernel(demon, token, 'state/status', {})
    entree = next(d for d in corps['data']['daemons'] if d['name'] == 'romulus')
    assert entree['metrics'] == 'enabled' and entree['sample_age_s'] >= 0


def test_metriques_refus(banc):
    demon, pollux, flux, etat, racine = banc
    token = session(demon, pollux)
    chemin = ecrire_prom(etat, 'romulus', 'a 1\n', mode=0o666)
    assert kernel(demon, token, 'state/metrics', {'daemon': 'romulus'})[1]['error']['code'] == 'not_available'
    assert next(d for d in kernel(demon, token, 'state/status', {})[1]['data']['daemons']
                if d['name'] == 'romulus')['metrics'] == 'unreadable'
    os.chmod(chemin, 0o644)
    chemin.write_text('a 1\n' * 100000)    # plus de 256 Kio
    assert kernel(demon, token, 'state/metrics', {'daemon': 'romulus'})[1]['error']['code'] == 'not_available'
    chemin.unlink()
    cible = racine / 'cible.prom'
    cible.write_text('a 1\n')
    os.symlink(cible, chemin)
    assert kernel(demon, token, 'state/metrics', {'daemon': 'romulus'})[1]['error']['code'] == 'not_available'
    chemin.unlink()
    assert kernel(demon, token, 'state/metrics', {'daemon': 'romulus'})[1]['data']['available'] is False
    os.chmod(etat / 'paresia-romulus', 0o777)
    assert kernel(demon, token, 'state/metrics', {'daemon': 'romulus'})[1]['error']['code'] == 'not_available'


def test_metriques_proprietaire_etranger(racine):
    demon, flux, etat = demarrer(racine)
    ecrire_prom(etat, 'romulus', 'a 1\n')
    demon.noyau.proprietaires = frozenset({EUID + 1})
    with demon:
        with Connexion(demon.presence.chemin) as pollux:
            token = session(demon, pollux)
            assert kernel(demon, token, 'state/metrics', {'daemon': 'romulus'})[1]['error']['code'] == 'not_available'


def test_analyse_limite_echantillons():
    texte = '\n'.join(f'm{i} {i}' for i in range(900)).encode()
    assert len(analyser_metriques(texte)) == 500


def test_masquage_regles():
    assert masquee('socket', 'chemin') and masquee('compte_acl', 'compte') and masquee('nom', 'texte')
    assert not masquee('timeout_s', 'duree') and not masquee('max_line', 'limite')
    assert not masquee('uid_pollux', 'uid') and not masquee('niveau', 'niveau')
    assert not masquee('actif', 'booleen') and not masquee('namespace', 'texte')
    for cle in ('secret_x', 'ma_passphrase', 'password', 'api_token', 'jeton', 'authorized_keys', 'cle_x', 'key'):
        assert masquee(cle, 'uid') and masquee(cle, 'limite')


def test_configuration_romulus_masquee(banc):
    demon, pollux, *_ = banc
    token = session(demon, pollux)
    statut, corps = kernel(demon, token, 'state/config', {'daemon': 'romulus'})
    options = {(o['section'], o['key']): o for o in corps['data']['options']}
    assert options[('http', 'timeout_s')]['value'] == .5 and options[('http', 'timeout_s')]['masked'] is False
    assert options[('http', 'socket')] == {'section': 'http', 'key': 'socket', 'type': 'chemin',
                                           'value': None, 'masked': True}
    assert options[('http', 'client_ip_header')]['value'] == 'X-Client-IP'
    assert options[('presence', 'uid_pollux')]['masked'] is False
    assert str(banc[4]) not in json.dumps(corps)


def test_configuration_pollux_et_session_depuis_les_couches(racine):
    demon, flux, etat = demarrer(racine)
    etc = racine / 'etc'
    os.mkdir(etc, 0o755)
    exemple = (RACINE / 'server/conf/paresia.conf').read_text(encoding='utf-8')
    (etc / 'paresia.conf').write_text(exemple)
    os.chmod(etc / 'paresia.conf', 0o644)
    with demon:
        with Connexion(demon.presence.chemin) as pollux:
            token = session(demon, pollux)
            for nom in ('pollux', 'pollux-session'):
                statut, corps = kernel(demon, token, 'state/config', {'daemon': nom})
                assert statut == 200 and corps['data']['options'], nom
                for option in corps['data']['options']:
                    if option['masked']:
                        assert option['value'] is None
                    if re.search('secret|passphrase|token|key|cle', option['key']):
                        assert option['masked'] is True
                texte = json.dumps(corps)
                assert '/run/' not in texte and '/etc/' not in texte
            (etc / 'paresia.conf').write_text('[pollux.inconnue]\nx = 1\n')
            assert kernel(demon, token, 'state/config', {'daemon': 'pollux'})[1]['error']['code'] == 'not_available'


def test_configuration_sans_fichier_not_available(banc):
    demon, pollux, *_ = banc
    token = session(demon, pollux)
    statut, corps = kernel(demon, token, 'state/config', {'daemon': 'pollux'})
    assert (statut, corps['error']['code']) == (501, 'not_available') or statut == 200


def test_activite_de_bout_en_bout(racine):
    demon, flux, etat = demarrer(racine, detail=3)
    with demon:
        with Connexion(demon.presence.chemin) as pollux:
            token = session(demon, pollux)
            faux = secrets.token_hex(32)
            kernel(demon, token, 'state/metrics', {'daemon': 'romulus'})
            requete(demon, PREFIXE + 'state/status', None, {})
            requete(demon, '/api/admin/ne/pas/recopier-ce-chemin', token, {})
            requete(demon, PREFIXE + 'activity/list', token, {'limit': 7, 'domain': 'x' + faux[:10]})
            statut, corps = kernel(demon, token, 'activity/list', {'level': 3})
    entrees = corps['data']['entries']
    assert statut == 200
    evenements = [(e['event'], e.get('action'), e.get('result')) for e in entrees]
    assert ('session_open', None, 'ok') in evenements
    assert ('action', 'kernel/state/metrics', 'ok') in evenements
    assert ('action', 'kernel/activity/list', 'ok') in evenements
    metrique = next(e for e in entrees if e.get('action') == 'kernel/state/metrics')
    assert metrique['admin'] == 'alice@example' and metrique['session'] == 1
    assert metrique['twin'] == 'romulus' and metrique['args'] == {'daemon': 'romulus'}
    assert metrique['source'] == '192.0.2.1' and metrique['duration_ms'] >= 0
    assert any(e['event'] == 'protocol' and e['step'] == 'received' and e['http_status'] == 200
               and e['peer_uid'] == EUID for e in entrees)
    fichier = (etat / 'activite' / 'activite.jsonl').read_text()
    assert token not in fichier and faux not in fichier and 'recopier' not in fichier
    assert 'domain' in fichier and '"alice@example"' in fichier
    # le refus sans jeton est regroupé et visible à la lecture
    demon.activite.fermer()
    tout = [json.loads(l) for l in (etat / 'activite' / 'activite.jsonl').read_text().splitlines()]
    assert any(e.get('count') == 1 and e['result'] == 'token_missing' for e in tout)
    inconnu = [e for e in tout if e.get('result') == 'unknown_action']
    assert len(inconnu) == 1 and inconnu[0]['domain'] is None and inconnu[0]['action'] is None


def test_activite_niveau_1_sans_liste_ni_duree(racine):
    demon, flux, etat = demarrer(racine, detail=1)
    with demon:
        with Connexion(demon.presence.chemin) as pollux:
            token = session(demon, pollux)
            kernel(demon, token, 'state/status', {})
            statut, corps = kernel(demon, token, 'activity/list', {})
    entrees = corps['data']['entries']
    action = next(e for e in entrees if e.get('action') == 'kernel/state/status')
    assert set(action) == {'ts', 'level', 'event', 'admin', 'session', 'domain', 'action', 'result'}
    assert not any(e.get('action') == 'kernel/activity/list' for e in entrees)


def test_activite_inutilisable_not_available(racine):
    demon, flux, etat = demarrer(racine)
    os.makedirs(etat / 'activite', mode=0o700)
    (etat / 'activite' / 'activite.jsonl').write_text('')
    os.chmod(etat / 'activite' / 'activite.jsonl', 0o666)
    with demon:
        with Connexion(demon.presence.chemin) as pollux:
            token = session(demon, pollux)
            statut, corps = kernel(demon, token, 'activity/list', {})
            assert (statut, corps['error']['code']) == (501, 'not_available')
            assert kernel(demon, token, 'state/status', {})[0] == 200   # l'action n'est pas refusée


def test_defaillance_ecriture_n_empeche_pas_l_action(racine, monkeypatch):
    demon, flux, etat = demarrer(racine)
    import server.romulus.activite as module

    def echec(*_):
        raise OSError(28, 'plein')
    monkeypatch.setattr(module.os, 'write', echec)
    with demon:
        with Connexion(demon.presence.chemin) as pollux:
            token = session(demon, pollux)
            for _ in range(3):
                assert kernel(demon, token, 'state/status', {})[0] == 200
    assert flux.getvalue().count('activity_write_failed') == 1


def test_sans_activite_configuree(racine):
    config = config_test(racine)
    with Romulus(config, journal=Journal('romulus', flux=io.StringIO()), chargeur=CHARGEUR,
                 environ={}) as demon:
        with Connexion(demon.presence.chemin) as pollux:
            token = session(demon, pollux)
            assert requete(demon, PREFIXE + 'state/status', token, {})[0] == 200
            assert requete(demon, PREFIXE + 'activity/list', token, {})[1]['error']['code'] == 'not_available'


# -- configuration ---------------------------------------------------------------------------

@pytest.mark.parametrize('cle,valeur', [
    ('detail', '0'), ('detail', '4'), ('taille_max', '65535'), ('taille_max', '16777217'),
    ('regroupement_max', '1000001'), ('regroupements_simultanes', '1025')])
def test_configuration_bornes(cle, valeur):
    with pytest.raises(ErreurConfiguration) as erreur:
        configuration(argv=['--config', str(RACINE / 'server/conf/paresia.conf')],
                      environ={f'PARESIA_ROMULUS_ACTIVITE_{cle.upper()}': valeur}, chargeur=CHARGEUR)
    assert erreur.value.code in ('config_invalid',) and erreur.value.section in (None, 'activite')


def test_configuration_defauts_et_exemple():
    config = configuration(argv=['--config', str(RACINE / 'server/conf/paresia.conf')], environ={},
                           chargeur=CHARGEUR)
    assert config['activite']['detail'] == 1 and config['activite']['taille_max'] == 1048576
    assert config['activite']['regroupement_max'] == 100000
    assert config['activite']['regroupements_simultanes'] == 64
    assert config['noyau']['dossier_etat'] == '/var/lib'
    assert config['http']['client_ip_header'] == 'X-Paresia-Client-IP'
    texte = (RACINE / 'server/conf/paresia.conf').read_text(encoding='utf-8')
    assert re.search(r'^client_ip_header = X-Paresia-Client-IP$', texte, re.M)
    assert not re.search(r'^client_ip_header\s*=\s*X-Forwarded-For', texte, re.M)
    assert config['metriques']['actif'] is False


def test_metriques_desactivees_sauf_demonstration():
    for chemin in (RACINE / 'server/conf/paresia.conf',
                   RACINE / 'deploy/backend-admin/etc/paresia/conf.d/10-backend-admin.conf'):
        texte = chemin.read_text(encoding='utf-8')
        assert not re.search(r'^actif\s*=\s*true', texte, re.M), chemin
    demo = (RACINE / 'deploy/backend-admin/etc/paresia/exemples/demonstration.conf').read_text(encoding='utf-8')
    assert re.search(r'\[romulus\.metriques\]\s*actif = true', demo)
    assert re.search(r'\[pollux\.metriques\]\s*actif = true', demo)
    assert 'démonstration' in demo
    for script in (RACINE / 'deploy/backend-admin').glob('*.sh'):
        assert 'demonstration' not in script.read_text(encoding='utf-8')


def test_aucune_trace_sudo_ni_journalctl():
    fichiers = [RACINE / 'server/romulus/noyau.py', RACINE / 'server/romulus/activite.py',
                RACINE / 'deploy/backend-admin/etc/paresia/exemples/demonstration.conf']
    for fichier in fichiers:
        assert not re.search(r'sudo|journalctl|shell=True|subprocess', fichier.read_text(encoding='utf-8')), fichier
    unite = (RACINE / 'deploy/backend-admin/etc/systemd/system/romulus.service').read_text(encoding='utf-8')
    assert 'sudo' not in unite and 'NoNewPrivileges=yes' in unite
