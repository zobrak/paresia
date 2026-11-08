# Tests du journal d'activité de Romulus ; dépendances : pytest, bibliothèque standard et server.
# Suivi des versions
#   0.1.15  2026-11-08  Première version : niveaux, stockage borné, regroupement, défaillance, lecture.
import io
import json
import os
from pathlib import Path
import secrets
import stat
import tempfile

import pytest

from server.commun.journal import Journal
from server.romulus import activite as module
from server.romulus.activite import Activite, ActiviteInutilisable

EUID = os.geteuid()


class Horloge:
    def __init__(self):
        self.t = 1_700_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def racine():
    with tempfile.TemporaryDirectory(prefix='activite-') as dossier:
        yield Path(dossier)


def fabriquer(racine, **options):
    horloge = Horloge()
    flux = io.StringIO()
    options = {'detail': 1, 'taille_max': 65536, 'regroupement_max': 100000,
               'regroupements_simultanes': 64, **options}
    act = Activite(str(racine / 'activite'), options, Journal('romulus', flux=flux),
                   proprietaires={EUID}, racine_confiance=str(racine), horloge=horloge,
                   monotone=horloge)
    return act, horloge, flux


def lignes(racine, nom='activite.jsonl'):
    chemin = racine / 'activite' / nom
    return [json.loads(l) for l in chemin.read_text().splitlines()] if chemin.exists() else []


def action(act, resultat='ok', **champs):
    base = {'session': 3, 'admin': 'alice@example', 'source': '192.0.2.7', 'duree_ms': 12}
    act.requete('action', 'kernel/state/status', resultat, **{**base, **champs})


def test_niveau_1_champs_et_rien_d_autre(racine):
    act, _, _ = fabriquer(racine)
    action(act)
    act.requete('refusal', None, 'unknown_action', session=3, admin='alice@example')
    entrees = lignes(racine)
    assert set(entrees[0]) == {'ts', 'level', 'event', 'admin', 'session', 'domain', 'action',
                               'result'}
    assert entrees[0]['domain'] == 'kernel' and entrees[0]['action'] == 'kernel/state/status'
    assert entrees[0]['result'] == 'ok' and entrees[0]['level'] == 1
    assert entrees[1]['event'] == 'refusal'
    assert entrees[1]['domain'] is None and entrees[1]['action'] is None
    assert entrees[1]['result'] == 'unknown_action'


def test_dossier_et_fichiers_prives(racine):
    act, _, _ = fabriquer(racine)
    action(act)
    assert stat.S_IMODE(os.stat(racine / 'activite').st_mode) == 0o700
    assert stat.S_IMODE(os.stat(racine / 'activite' / 'activite.jsonl').st_mode) == 0o600


def test_niveau_2_duree_jumeau_source(racine):
    act, _, _ = fabriquer(racine, detail=2)
    act.jumeaux = {'kernel/state/status': 'romulus'}
    action(act, duree_ms=34)
    entree = lignes(racine)[0]
    assert entree['duration_ms'] == 34 and entree['twin'] == 'romulus'
    assert entree['source'] == '192.0.2.7'


def test_liste_enregistree_seulement_au_niveau_2(racine):
    act, _, _ = fabriquer(racine, detail=1)
    act.requete('action', 'kernel/activity/list', 'ok', session=3, admin='a')
    assert lignes(racine) == []
    act2, _, _ = fabriquer(racine / '..' / racine.name, detail=2)
    act2.requete('action', 'kernel/activity/list', 'ok', session=3, admin='a')
    assert lignes(racine)[0]['action'] == 'kernel/activity/list'


def test_liste_refus_enregistres_des_le_niveau_1(racine):
    act, _, _ = fabriquer(racine, detail=1)
    act.requete('action', 'kernel/activity/list', 'ok', session=3, admin='a')
    act.requete('refusal', 'kernel/activity/list', 'bad_request', session=3, admin='a')
    entrees = lignes(racine)
    assert [e['result'] for e in entrees] == ['bad_request']
    assert entrees[0]['event'] == 'refusal' and entrees[0]['action'] == 'kernel/activity/list'
    act.requete('refusal', 'kernel/activity/list', 'token_missing', source='192.0.2.7')
    act.fermer()
    assert any(e['result'] == 'token_missing' for e in lignes(racine))


def test_niveau_3_protocole_sans_donnees(racine):
    act, _, _ = fabriquer(racine, detail=3)
    act.protocole(request_id=secrets.token_hex(8), step='sent', session=3, bytes=120, peer_uid=5)
    act.protocole(request_id=secrets.token_hex(8), step='received', session=3, ok=False,
                  code='peer_unavailable', http_status=503, bytes=40, peer_uid=5)
    entrees = lignes(racine)
    assert [e['event'] for e in entrees] == ['protocol', 'protocol']
    assert all(e['level'] == 3 for e in entrees)
    assert not {'params', 'data', 'token'} & set(entrees[0])
    act1, _, _ = fabriquer(racine / '..' / racine.name, detail=1)
    act1.protocole(request_id=secrets.token_hex(8), step='sent')
    assert len(lignes(racine)) == 2


def test_parametres_non_marques_jamais_journalises(racine):
    act, _, _ = fabriquer(racine, detail=3)
    act.marques = {'kernel/state/metrics': frozenset({'daemon'})}
    faux = secrets.token_hex(32)
    params = {'daemon': 'romulus', 'token': faux, 'autre': faux, 'passphrase': faux}
    args = act.args_pour('kernel/state/metrics', params)
    assert args == {'daemon': 'romulus'}
    act.requete('action', 'kernel/state/metrics', 'ok', session=1, admin='a', args=args)
    act.requete('action', 'kernel/state/status', 'ok', session=1, admin='a',
                args=act.args_pour('kernel/state/status', params))
    contenu = (racine / 'activite' / 'activite.jsonl').read_text()
    assert faux not in contenu
    entrees = lignes(racine)
    assert entrees[0]['args'] == {'daemon': 'romulus'} and 'args' not in entrees[1]
    assert act.args_pour('kernel/state/metrics', {'daemon': 'x' * 500})['daemon'] == 'x' * 128
    assert act.args_pour('kernel/state/metrics', {'daemon': ['liste']}) == {}
    act1, _, _ = fabriquer(racine / '..' / racine.name, detail=1)
    act1.marques = act.marques
    act1.requete('action', 'kernel/state/metrics', 'ok', session=1, admin='a', args=args)
    assert 'args' not in lignes(racine)[-1]


def test_lien_symbolique_refuse(racine):
    (racine / 'cible').write_text('')
    os.mkdir(racine / 'activite', 0o700)
    os.symlink(racine / 'cible', racine / 'activite' / 'activite.jsonl')
    act, _, flux = fabriquer(racine)
    action(act)
    assert (racine / 'cible').read_text() == ''
    assert 'activity_unusable' in flux.getvalue()


def test_dossier_lien_symbolique_ou_ouvert_refuse(racine):
    os.mkdir(racine / 'reel', 0o700)
    os.symlink(racine / 'reel', racine / 'activite')
    act, _, flux = fabriquer(racine)
    action(act)
    assert 'activity_unusable' in flux.getvalue() and not list((racine / 'reel').iterdir())
    os.unlink(racine / 'activite')
    os.mkdir(racine / 'activite', 0o700)
    os.chmod(racine / 'activite', 0o770)
    act, _, flux = fabriquer(racine)
    action(act)
    assert 'activity_unusable' in flux.getvalue()


def test_fichier_mode_trop_ouvert_et_proprietaire_etranger(racine):
    os.mkdir(racine / 'activite', 0o700)
    fichier = racine / 'activite' / 'activite.jsonl'
    fichier.write_text('')
    os.chmod(fichier, 0o640)
    act, _, flux = fabriquer(racine)
    action(act)
    assert fichier.read_text() == '' and 'activity_unusable' in flux.getvalue()
    os.chmod(fichier, 0o600)
    etranger = Activite(str(racine / 'activite'), {'detail': 1}, Journal('romulus', flux=io.StringIO()),
                        proprietaires={EUID + 1}, racine_confiance=str(racine))
    with pytest.raises(ActiviteInutilisable):
        etranger.lire(10, 3, None)


def test_rotation_et_volume_borne(racine):
    act, horloge, _ = fabriquer(racine, taille_max=65536)
    for i in range(1500):
        action(act, session=i + 1)
    total = sum(os.path.getsize(racine / 'activite' / n)
                for n in ('activite.jsonl', 'activite.jsonl.1'))
    assert total <= 65536
    assert os.path.getsize(racine / 'activite' / 'activite.jsonl') <= 32768
    assert (racine / 'activite' / 'activite.jsonl.1').exists()
    entrees, tronque = act.lire(200, 3, None)
    assert entrees[0]['session'] == 1500 and tronque is True
    sessions = [e['session'] for e in entrees]
    assert sessions == sorted(sessions, reverse=True)


def test_un_seul_appel_d_ecriture_par_entree(racine, monkeypatch):
    act, _, _ = fabriquer(racine)
    appels = []
    reel = os.write
    monkeypatch.setattr(module.os, 'write', lambda fd, donnees: appels.append(donnees) or reel(fd, donnees))
    action(act)
    action(act)
    assert len(appels) == 2 and all(a.endswith(b'\n') and a.count(b'\n') == 1 for a in appels)


def test_lecture_ignore_lignes_hostiles(racine):
    act, _, _ = fabriquer(racine)
    action(act)
    fichier = racine / 'activite' / 'activite.jsonl'
    with open(fichier, 'ab') as sortie:
        sortie.write(b'{"ts":"x"}\n')
        sortie.write(b'pas du json\n')
        sortie.write(b'{"ts":"2024-01-01T00:00:00.000Z","level":1,"event":"action","admin":"a\\u0007b"}\n')
        sortie.write(b'{"ts":"2024-01-01T00:00:00.000Z","level":1,"event":"action","extra":1}\n')
        sortie.write(b'{"ts":"2024-01-01T00:00:00.000Z","level":1,"event":"action","result":"' + b'a' * 3000 + b'"}\n')
        sortie.write(b'{"ts":"2024-01-01T00:00:00.000Z","level":1')   # ligne tronquée
    entrees, tronque = act.lire(50, 3, None)
    assert len(entrees) == 1 and entrees[0]['result'] == 'ok' and tronque is False


def test_liste_filtres_exacts(racine):
    act, _, _ = fabriquer(racine, detail=3)
    act.requete('action', 'kernel/state/status', 'ok', session=1, admin='a')
    act.requete('action', 'bunker/identity/list', 'ok', session=1, admin='a')
    act.requete('action', 'relay/state/status', 'relay_light_red', session=1, admin='a')
    act.protocole(request_id='0123456789abcdef', step='sent')
    assert [e['domain'] for e in act.lire(50, 1, None)[0]] == ['relay', 'bunker', 'kernel']
    assert [e['domain'] for e in act.lire(50, 1, 'bunker')[0]] == ['bunker']
    assert act.lire(50, 1, 'bun')[0] == []
    assert len(act.lire(50, 3, None)[0]) == 4
    entrees, tronque = act.lire(2, 1, None)
    assert len(entrees) == 2 and tronque is True
    assert act.lire(3, 1, None)[1] is False


def test_liste_fichier_absent_et_non_conforme(racine):
    act, _, _ = fabriquer(racine)
    assert act.lire(10, 1, None) == ([], False)
    os.mkdir(racine / 'activite', 0o700)
    assert act.lire(10, 1, None) == ([], False)
    fichier = racine / 'activite' / 'activite.jsonl'
    fichier.write_text('')
    os.chmod(fichier, 0o666)
    with pytest.raises(ActiviteInutilisable):
        act.lire(10, 1, None)


def test_lecture_bornee_a_1_mio(racine):
    act, _, _ = fabriquer(racine, taille_max=16777216)
    action(act)
    fichier = racine / 'activite' / 'activite.jsonl'
    ligne = fichier.read_bytes()
    with open(fichier, 'ab') as sortie:
        for _ in range(8000):
            sortie.write(ligne)
    assert os.path.getsize(fichier) > 1024 * 1024
    entrees, tronque = act.lire(200, 1, None)
    assert len(entrees) == 200 and tronque is True


def test_mille_refus_identiques_une_entree(racine):
    act, horloge, _ = fabriquer(racine)
    action(act)
    for _ in range(1000):
        act.requete('refusal', None, 'token_missing', source='192.0.2.9')
    assert len(lignes(racine)) == 1   # regroupement encore ouvert
    horloge.t += 61
    action(act)
    entrees = lignes(racine)
    groupe = [e for e in entrees if e.get('count')]
    assert len(groupe) == 1 and groupe[0]['count'] == 1000
    assert groupe[0]['result'] == 'token_missing' and groupe[0]['source'] == '192.0.2.9'
    assert len(entrees) == 3
    assert [e['count'] for e in act.lire(10, 1, None)[0] if 'count' in e] == [1000]


def test_regroupements_simultanes_plafonnes(racine):
    act, horloge, _ = fabriquer(racine, regroupements_simultanes=64)
    for i in range(100):
        act.requete('refusal', None, 'token_unknown', source=f'192.0.2.{i + 1}')
    assert len(act._groupes) <= 65
    act.fermer()
    assert sum(e['count'] for e in lignes(racine)) == 100
    assert len(lignes(racine)) <= 65


def test_regroupement_max_ouvre_nouvelle_entree(racine):
    act, _, _ = fabriquer(racine, regroupement_max=10)
    for _ in range(25):
        act.requete('refusal', None, 'origin_refused', source='192.0.2.1')
    act.fermer()
    assert sorted(e['count'] for e in lignes(racine)) == [5, 10, 10]


def test_defaillance_d_ecriture_signalee_une_fois_par_minute(racine, monkeypatch):
    act, horloge, flux = fabriquer(racine)
    action(act)

    def echec(*_):
        raise OSError(28, 'plein')
    monkeypatch.setattr(module.os, 'write', echec)
    for _ in range(5):
        action(act)
        horloge.t += 6
    signaux = [json.loads(l) for l in flux.getvalue().splitlines()
               if 'activity_write_failed' in l]
    assert len(signaux) == 1 and signaux[0]['code'] == 'activity_io_error'
    assert 'plein' not in flux.getvalue()
    horloge.t += 61
    action(act)
    assert len([l for l in flux.getvalue().splitlines() if 'activity_write_failed' in l]) == 2


def test_session_et_options_invalides(racine):
    act, _, _ = fabriquer(racine, detail=2)
    act.session('session_open', 4, 'alice@example', '192.0.2.5')
    entree = lignes(racine)[0]
    assert entree['event'] == 'session_open' and entree['admin'] == 'alice@example'
    assert entree['source'] == '192.0.2.5'
    with pytest.raises(ValueError):
        Activite(str(racine / 'x'), {'detail': 4}, None)
    with pytest.raises(ValueError):
        Activite(str(racine / 'x'), {'taille_max': 100}, None)


def test_serialiser_tronque_les_champs():
    entree = {'ts': '2024-01-01T00:00:00.000Z', 'level': 3, 'event': 'action',
              'args': {f'k{i}': 'x' * 128 for i in range(8)}}
    assert module.serialiser(entree) is not None
    assert len(module.serialiser(entree)) <= module.LIGNE_MAX
    assert module.serialiser({'ts': 'x', 'level': 1, 'event': 'action'}) is None
