# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests du socle de Nisaba : configuration, planificateur, purge, sockets, échecs, hygiène ;
# dépendances : pytest et bibliothèque standard.
# Suivi des versions
#   0.1.1  2026-11-07  Options journal et métriques du socle dans la configuration lue.
#   3.0.0-alpha.40  2026-11-06  Création (T031, D87).
#   3.0.0-alpha.41  2026-11-06  Validation du compte ACL unique et du refus avant initialisation (D111).
#   3.0.0-alpha.41  2026-11-06  Comparaison exacte des comptes ACL (casse) et construction sans section droits (D111).
import datetime
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import threading
import time

import pytest

sys.path.insert(0, str(Path(__file__).parent / 'outils' / 'nisaba'))
from nisaba_outils import BASE, Horloge, appeler, journal_capture, monter, requete  # noqa: E402
from server.commun.client import PairIndisponible, appeler as appeler_client  # noqa: E402
from server.commun.config import ErreurConfiguration, lire  # noqa: E402
from server.nisaba import SCHEMA, Nisaba, Occupe, Planificateur, TACHES, configuration  # noqa: E402
from server.nisaba.purge import purger  # noqa: E402

RACINE = Path(__file__).resolve().parents[1]
EXEMPLE = RACINE / 'server' / 'conf' / 'paresia.conf'


@pytest.fixture
def dossier_socket():
    # Les worktrees dépassent parfois la limite des chemins AF_UNIX.
    with tempfile.TemporaryDirectory(prefix='nisaba-') as dossier:
        yield Path(dossier)


# -- configuration -----------------------------------------------------------------------------
def ecrire_conf(chemin, texte):
    chemin.write_text(texte, encoding='utf-8')
    chemin.chmod(0o600)
    return str(chemin)


def test_nisaba_configuration(tmp_path):
    config = configuration(argv=['--config', str(EXEMPLE)], environ={})
    assert config['horaire']['scellement'] == '00:20' and config['horaire']['purge'] == '03:23'
    attendu = {d: {c for dd, c in SCHEMA if dd == d} for d in {d for d, _ in SCHEMA}}
    # Options du socle commun : niveau du journal et métriques.
    attendu['journal'].add('niveau')
    attendu['metriques'] = {'actif', 'dossier', 'periode_s'}
    assert {d: set(v) for d, v in config.items()} == attendu
    # Défauts du code limités à duree et limite.
    assert all(o.defaut is None for (_, _), o in SCHEMA.items() if o.type not in ('duree', 'limite'))
    assert {k: o.defaut for k, o in SCHEMA.items() if o.defaut is not None} == {
        ('socket', 'delai_s'): 30, ('socket', 'max_line'): 65536, ('horaire', 'copie_s'): 60,
        ('horaire', 'conservation_jours'): 365, ('horaire', 'arret_s'): 30, ('etat', 'historique'): 20,
        ('source', 'connexion_s'): 20, ('source', 'rsync_s'): 50, ('ots', 'attente_max_jours'): 3,
        ('ots', 'delai_s'): 120}                                       # T033
    # Surcharge par l'environnement.
    surcharge = configuration(argv=['--config', str(EXEMPLE)], environ={'PARESIA_NISABA_HORAIRE_PURGE': '04:30'})
    assert surcharge['horaire']['purge'] == '04:30'


def test_nisaba_configuration_compte_divergent(tmp_path):
    variables = ('PARESIA_NISABA_DROITS_COMPTE', 'PARESIA_NISABA_JOURNAL_COMPTE_ACL')
    for variable in variables:
        with pytest.raises(ErreurConfiguration) as e:
            configuration(argv=['--config', str(EXEMPLE)], environ={variable: 'autre-compte-test'})
        assert (e.value.code, e.value.section, e.value.cle) == ('config_invalid', 'droits', 'compte')

    # Comparaison exacte : deux comptes qui ne diffèrent que par la casse sont divergents (D111).
    for droits, journal in (('Paresia-Romulus', 'paresia-romulus'), ('paresia-romulus', 'Paresia-Romulus')):
        with pytest.raises(ErreurConfiguration) as e:
            configuration(argv=['--config', str(EXEMPLE)],
                          environ={'PARESIA_NISABA_DROITS_COMPTE': droits,
                                   'PARESIA_NISABA_JOURNAL_COMPTE_ACL': journal})
        assert (e.value.code, e.value.section, e.value.cle) == ('config_invalid', 'droits', 'compte')

    config = configuration(argv=['--config', str(EXEMPLE)],
                           environ={variable: 'autre-compte-test' for variable in variables})
    assert config['droits']['compte'] == config['journal']['compte_acl'] == 'autre-compte-test'
    config['droits']['compte'] = 'compte-divergent-test'
    config['socket']['socket'] = str(tmp_path / 'n.sock')
    config['ctl']['socket'] = str(tmp_path / 'c.sock')
    config['etat']['dossier'] = str(tmp_path / 'etat')
    config['journal']['dossier'] = str(tmp_path / 'journal')

    def horloge_interdite():
        pytest.fail('Initialisation avant validation de la configuration')

    with pytest.raises(ErreurConfiguration) as e:
        Nisaba(config, horloge=horloge_interdite)
    assert (e.value.code, e.value.section, e.value.cle) == ('config_invalid', 'droits', 'compte')
    assert list(tmp_path.iterdir()) == []

    n, *_ = monter(tmp_path)
    assert 'droits' not in n.config
    # Section droits absente : la validation ne s'applique pas, Nisaba(config) se construit sans exception.
    assert isinstance(Nisaba(n.config, horloge=Horloge(), journal=n.journal, sortie=n.sortie), Nisaba)


def test_nisaba_configuration_option_obligatoire_absente(tmp_path):
    texte = EXEMPLE.read_text(encoding='utf-8')
    for domaine, cle in [k for k, o in SCHEMA.items() if o.defaut is None]:
        section = re.search(rf'^\[nisaba\.{domaine}\]$', texte, re.M)
        assert section, domaine
        bloc_fin = re.search(r'^\[', texte[section.end():], re.M)
        bloc = texte[section.start():section.end() + (bloc_fin.start() if bloc_fin else len(texte))]
        sans = re.sub(rf'^{cle} = .*\n', '', bloc, flags=re.M)
        assert sans != bloc, (domaine, cle)
        fichier = ecrire_conf(tmp_path / 'sans.conf', texte.replace(bloc, sans))
        with pytest.raises(ErreurConfiguration) as e:
            lire('nisaba', SCHEMA, argv=['--config', fichier], environ={}, journal=True, metriques=True)
        assert (e.value.code, e.value.section, e.value.cle) == ('config_missing', domaine, cle)


@pytest.mark.parametrize('cle', ['scellement', 'purge'])
@pytest.mark.parametrize('valeur', ['24:00', '7:05', '03:60', '0320', '03:2', 'ab:cd', '03:23:00', '03:23 ', '+3:23'])
def test_nisaba_configuration_horaire_invalide(cle, valeur):
    environ = {f'PARESIA_NISABA_HORAIRE_{cle.upper()}': valeur}
    with pytest.raises(ErreurConfiguration) as e:
        configuration(argv=['--config', str(EXEMPLE)], environ=environ)
    assert (e.value.code, e.value.section, e.value.cle) == ('config_invalid', 'horaire', cle)


def test_nisaba_configuration_sockets_distinctes():
    with pytest.raises(ErreurConfiguration):
        configuration(argv=['--config', str(EXEMPLE)], environ={'PARESIA_NISABA_CTL_SOCKET': '/run/paresia-nisaba/nisaba.sock'})


# -- planificateur -----------------------------------------------------------------------------
def planificateur(horloge=None, arret_s=1):
    echecs = []
    capture, flux = journal_capture()
    p = Planificateur(horloge=horloge or Horloge(), journal=capture, arret_s=arret_s,
                      echec=lambda nom, code, texte: echecs.append((nom, code, texte)))
    return p, echecs, flux


def test_nisaba_planificateur_echeances():
    horloge = Horloge()                  # 2023-11-14 22:13:20 UTC
    p, _, _ = planificateur(horloge)
    appels = []
    p.enregistrer('scellement', lambda: appels.append('s'), quotidien='00:20')
    p.enregistrer('copie', lambda: appels.append('c'), periode=60)
    p.enregistrer('purge', lambda: appels.append('p'), quotidien='22:13')       # déjà passé : lendemain
    assert p.etat()['scellement']['prochaine'] == datetime.datetime(2023, 11, 15, 0, 20, tzinfo=datetime.timezone.utc).timestamp()
    assert p.etat()['purge']['prochaine'] == datetime.datetime(2023, 11, 15, 22, 13, tzinfo=datetime.timezone.utc).timestamp()
    p.pas()
    assert appels == []
    horloge.t += 60
    p.pas()
    assert appels == ['c'] and p.etat()['copie']['prochaine'] == horloge.t + 60
    horloge.t = datetime.datetime(2023, 11, 15, 0, 19, 59, tzinfo=datetime.timezone.utc).timestamp()
    p.pas()
    assert 's' not in appels
    horloge.t += 1
    p.pas()
    assert 's' in appels
    assert p.etat()['scellement']['prochaine'] == datetime.datetime(2023, 11, 16, 0, 20, tzinfo=datetime.timezone.utc).timestamp()
    assert p.etat()['scellement']['resultat'] == 'ok' and p.etat()['scellement']['derniere'] == horloge.t


def test_nisaba_planificateur_rattrapage_et_nom_inconnu():
    p, _, _ = planificateur()
    appels = []
    p.enregistrer('scellement', lambda: appels.append('s'), quotidien='00:20', rattrapage=True)
    p.enregistrer('purge', lambda: appels.append('p'), quotidien='03:23')
    p.pas()
    assert appels == ['s']                       # rattrapage au démarrage seulement pour la tâche qui le demande
    for nom in ('inconnue', '', 'Purge'):
        with pytest.raises(ValueError):
            p.enregistrer(nom, lambda: None, periode=1)
    with pytest.raises(ValueError):
        p.enregistrer('copie', lambda: None)             # ni période ni horaire
    with pytest.raises(ValueError):
        p.enregistrer('horodatage', lambda: None, quotidien='25:00')
    with pytest.raises(ValueError):
        p.executer('copie')                              # non enregistrée


def test_nisaba_planificateur_non_chevauchement():
    horloge = Horloge()
    p, _, _ = planificateur(horloge)
    debut, fin = threading.Event(), threading.Event()

    def longue():
        debut.set()
        fin.wait(5)

    p.enregistrer('copie', longue, periode=60)
    p.enregistrer('purge', lambda: None, quotidien='03:23')
    fil = threading.Thread(target=p.executer, args=('copie',))
    fil.start()
    assert debut.wait(5)
    with pytest.raises(Occupe):
        p.executer('copie')
    with pytest.raises(Occupe):
        p.executer('purge')                      # jamais deux tâches en même temps
    horloge.t += 100_000
    assert p.pas() is False
    fin.set()
    fil.join(5)
    assert p.executer('purge')['resultat'] == 'ok'


def test_nisaba_planificateur_tache_en_echec():
    horloge = Horloge()
    p, echecs, _ = planificateur(horloge)
    p.enregistrer('copie', lambda: 1 / 0, periode=60)
    p.enregistrer('purge', lambda: 2, quotidien='03:23')
    suite = []
    p.enregistrer('scellement', lambda: suite.append(1), periode=60)
    horloge.t += 60
    assert p.pas() is True                        # l'échec ne tue pas le planificateur
    assert ('copie', 'ECHEC_COPIE', 'task_exception') in echecs and suite == [1]
    assert p.etat()['copie']['resultat'] == 'echec'
    assert p.executer('purge') == {'tache': 'purge', 'resultat': 'echec', 'echecs': 2}
    assert p.etat()['copie']['prochaine'] == horloge.t + 60      # replanifiée malgré l'échec


def test_nisaba_planificateur_arret_ordonne():
    horloge = Horloge(time.time())
    p, _, flux = planificateur(horloge, arret_s=3)
    debut, fin = threading.Event(), threading.Event()
    termine = []

    def tache():
        debut.set()
        fin.wait(5)
        termine.append(1)

    p.enregistrer('copie', tache, periode=60, rattrapage=True)
    p.demarrer()
    assert debut.wait(5)
    threading.Timer(0.3, fin.set).start()
    p.arreter()                                   # attend la fin de la tâche en cours
    assert termine == [1] and 'shutdown_task_timeout' not in flux.getvalue()
    # Tâche trop longue : l'attente est bornée par arret_s, la tâche n'est pas interrompue.
    p2, _, flux2 = planificateur(Horloge(time.time()), arret_s=0.3)
    debut2, fin2 = threading.Event(), threading.Event()
    p2.enregistrer('copie', lambda: (debut2.set(), fin2.wait(5)), periode=60, rattrapage=True)
    p2.demarrer()
    assert debut2.wait(5)
    t0 = time.monotonic()
    p2.arreter()
    assert time.monotonic() - t0 < 2 and 'shutdown_task_timeout' in flux2.getvalue()
    fin2.set()


# -- purge -------------------------------------------------------------------------------------
AUJOURDHUI = datetime.date(2023, 11, 14)


def preparer_purge(dossier):
    dossier.mkdir()
    (dossier / 'seals').mkdir()
    (dossier / 'seals' / '2020-01-01.txt').write_text('x')
    (dossier / 'MANIFEST').write_text('m')
    noms = ['journal-2022-11-13.jsonl',      # 366 jours : supprimé
            'journal-2022-11-14.jsonl',      # 365 jours : conservé
            'journal-2022-11-15.jsonl',      # conservé
            'journal-2020-01-01.jsonl.bak', 'journal-2020-1-1.jsonl', 'journal-2020-13-45.jsonl',
            'Journal-2020-01-01.jsonl', 'journal-2020-01-01.jsonl~']
    for nom in noms:
        (dossier / nom).write_text('{}\n')
    (dossier / 'cible').write_text('{}\n')
    os.symlink(dossier / 'cible', dossier / 'journal-2020-01-02.jsonl')
    (dossier / 'journal-2020-01-03.jsonl').mkdir()
    return noms


def test_nisaba_purge(tmp_path):
    dossier = tmp_path / 'j'
    noms = preparer_purge(dossier)
    appels, supprimes, echecs = [], [], []

    def executer(argv):
        appels.append((argv, (dossier / 'journal-2022-11-13.jsonl').exists()))
        return 0, ''

    n = purger(dossier, 365, '/outil/chattr', AUJOURDHUI, supprime=supprimes.append, echec=echecs.append, executer=executer)
    assert n == 1 and supprimes == ['journal-2022-11-13.jsonl'] and echecs == []
    # chattr -i demandé, par argv, avant la suppression (le fichier existait encore), pour ce seul fichier.
    assert appels == [(['/outil/chattr', '-i', '--', str(dossier / 'journal-2022-11-13.jsonl')], True)]
    assert not (dossier / 'journal-2022-11-13.jsonl').exists()
    for nom in noms[1:]:
        assert (dossier / nom).exists(), nom
    assert (dossier / 'MANIFEST').read_text() == 'm' and (dossier / 'seals' / '2020-01-01.txt').exists()
    assert (dossier / 'journal-2020-01-02.jsonl').is_symlink() and (dossier / 'journal-2020-01-03.jsonl').is_dir()
    assert (dossier / 'cible').exists()


def test_nisaba_purge_conservation_maximale(tmp_path):
    dossier = tmp_path / 'j'
    dossier.mkdir()
    (dossier / 'journal-2022-11-13.jsonl').write_text('x')
    supprimes, echecs = [], []
    n = purger(dossier, 36500, '/c', AUJOURDHUI, supprime=supprimes.append, echec=echecs.append,
               executer=lambda a: (0, ''))
    assert n == 0 and supprimes == [] and echecs == []
    assert (dossier / 'journal-2022-11-13.jsonl').exists()


def test_nisaba_purge_seuil_exact(tmp_path):
    dossier = tmp_path / 'j'
    dossier.mkdir()
    for jour in ('2022-11-12', '2022-11-13', '2022-11-14', '2022-11-15'):
        (dossier / f'journal-{jour}.jsonl').write_text('x')
    supprimes = []
    purger(dossier, 365, '/c', AUJOURDHUI, supprime=supprimes.append, echec=lambda t: None, executer=lambda a: (0, ''))
    assert supprimes == ['journal-2022-11-12.jsonl', 'journal-2022-11-13.jsonl']
    supprimes.clear()
    purger(dossier, 1, '/c', AUJOURDHUI, supprime=supprimes.append, echec=lambda t: None, executer=lambda a: (1, ''))
    assert supprimes == ['journal-2022-11-14.jsonl', 'journal-2022-11-15.jsonl']     # chattr en échec : sans effet


def test_nisaba_purge_identifiants_stables(tmp_path):
    echecs = []
    purger(tmp_path / 'absent', 365, '/c', AUJOURDHUI, supprime=lambda n: None, echec=echecs.append,
           executer=lambda a: (0, ''))
    assert echecs == ['list_failed']


def test_nisaba_purge_lien_physique_ignore(tmp_path):
    dossier = tmp_path / 'j'
    dossier.mkdir()
    (dossier / 'journal-2020-01-01.jsonl').write_text('x')
    os.link(dossier / 'journal-2020-01-01.jsonl', tmp_path / 'autre')
    (dossier / 'journal-2020-01-02.jsonl').write_text('y')
    supprimes, echecs, appels = [], [], []
    purger(dossier, 365, '/c', AUJOURDHUI, supprime=supprimes.append, echec=echecs.append,
           executer=lambda a: (appels.append(a), (0, ''))[1])
    assert supprimes == ['journal-2020-01-02.jsonl']
    assert echecs == ['nlink_ignored: journal-2020-01-01.jsonl']
    assert (dossier / 'journal-2020-01-01.jsonl').exists() and len(appels) == 1


def test_nisaba_purge_echec_et_suite(tmp_path, dossier_socket, monkeypatch):
    n, journal, _, horloge, sortie, flux = monter(tmp_path, dossier_socket)
    for jour in ('2020-01-01', '2020-01-02', '2020-01-03'):
        (journal / f'journal-{jour}.jsonl').write_text('x')
    reel = os.unlink

    def unlink(chemin, *args, **kwargs):
        if str(chemin).endswith('journal-2020-01-02.jsonl'):
            raise PermissionError()
        return reel(chemin, *args, **kwargs)

    monkeypatch.setattr(os, 'unlink', unlink)
    n.executer = lambda argv: (0, '')
    resultat = n.planificateur.executer('purge')
    assert resultat == {'tache': 'purge', 'resultat': 'echec', 'echecs': 1}
    assert sortie.getvalue().startswith('<3>ECHEC_PURGE ')
    assert 'journal-2020-01-02.jsonl' in sortie.getvalue()
    assert [e['texte'] for e in n.anneau.entrees('purge')] == ['unlink_failed: journal-2020-01-02.jsonl']
    assert [e['code'] for e in n.anneau.entrees('purge')] == ['ECHEC_PURGE']
    assert (journal / 'journal-2020-01-02.jsonl').exists()
    assert not (journal / 'journal-2020-01-01.jsonl').exists() and not (journal / 'journal-2020-01-03.jsonl').exists()
    assert flux.getvalue().count('journal_purged') == 2


# -- sockets -----------------------------------------------------------------------------------
def test_nisaba_sockets(tmp_path, dossier_socket):
    n, journal, *_ = monter(tmp_path, dossier_socket)
    with n:
        sock, ctl = n.config['socket']['socket'], n.config['ctl']['socket']
        assert stat.S_IMODE(os.stat(ctl).st_mode) == 0o600
        # Socket de Romulus : lecture seulement.
        r = appeler(sock, 'nisaba/state/status')
        assert r['ok'] and 'purge' in r['data']['taches']
        r = appeler(sock, 'nisaba/state/verify')
        assert r['ok'] and r['data']['code'] == 0 and r['data']['lignes']
        for action in ('nisaba/job/run', 'nisaba/acl/check', 'nisaba/acl/apply', 'legal/journal/status'):
            r = appeler(sock, action, task='purge')
            assert not r['ok'] and r['error']['code'] == 'unknown_action', action
        assert appeler(sock, 'nisaba/state/status', x=1)['error']['code'] == 'bad_request'
        # Socket de contrôle.
        assert appeler(ctl, 'nisaba/state/status')['ok']
        r = appeler(ctl, 'nisaba/job/run', task='purge')
        assert r['ok'] and r['data'] == {'tache': 'purge', 'resultat': 'ok', 'echecs': 0}
        assert appeler(ctl, 'nisaba/job/run', task='copie')['error']['code'] == 'not_available'   # T033
        for params in ({}, {'task': 'autre'}, {'task': 1}, {'task': 'purge', 'x': 1}, {'tache': 'purge'}):
            assert appeler(ctl, 'nisaba/job/run', **params)['error']['code'] == 'bad_request', params
        assert appeler(ctl, 'nisaba/acl/check')['error']['code'] == 'not_available'
        n.gestionnaires_ctl['nisaba/acl/check'] = lambda q: {'id': q['id'], 'ok': True, 'data': {'acl': 'ok'}}
        assert appeler(ctl, 'nisaba/acl/check')['data'] == {'acl': 'ok'}
    assert not os.path.exists(sock) and not os.path.exists(ctl)


def test_nisaba_sockets_command_busy(tmp_path, dossier_socket):
    n, *_ = monter(tmp_path, dossier_socket)
    debut, fin = threading.Event(), threading.Event()
    n.planificateur._taches['purge'].fonction = lambda: (debut.set(), fin.wait(5), 0)[2]
    with n:
        ctl = n.config['ctl']['socket']
        fil = threading.Thread(target=appeler, args=(ctl, 'nisaba/job/run'), kwargs={'task': 'purge'})
        fil.start()
        assert debut.wait(5)
        assert appeler(ctl, 'nisaba/job/run', task='purge')['error']['code'] == 'command_busy'
        fin.set()
        fil.join(5)
        assert appeler(ctl, 'nisaba/job/run', task='purge')['ok']


def test_nisaba_sockets_uid_non_admis(tmp_path, dossier_socket):
    n, *_ , flux = monter(tmp_path, dossier_socket)
    n.config['socket']['uid_romulus'] = os.getuid() + 1
    n2 = Nisaba(n.config, horloge=Horloge(), journal=n.journal, sortie=n.sortie)
    with n2:
        with pytest.raises(PairIndisponible):          # connexion fermée sans réponse
            appeler(n.config['socket']['socket'], 'nisaba/state/status')
        assert appeler(n.config['ctl']['socket'], 'nisaba/state/status')['ok']
        assert 'peer_refused' in flux.getvalue()


# -- échecs ------------------------------------------------------------------------------------
def test_nisaba_echecs_journald(tmp_path, dossier_socket):
    n, _, _, _, sortie, _ = monter(tmp_path, dossier_socket)
    n.echec('copie', 'ECHEC_COPIE', 'rsync a échoué\x1b[2J\nsuite')
    n.echec('scellement', 'ECHEC_SCELLEMENT', 'divergence')
    n.echec('scellement', 'ECHEC_ACL', 'acl')
    n.echec('horodatage', 'ECHEC_HORODATAGE', 'preuve en retard')
    n.echec('purge', 'ECHEC_PURGE', 'x' * 1000)
    lignes = sortie.getvalue().split('\n')[:-1]
    assert [ligne.split(' ')[0] for ligne in lignes] == [
        '<3>ECHEC_COPIE', '<3>ECHEC_SCELLEMENT', '<3>ECHEC_ACL', '<4>ECHEC_HORODATAGE', '<3>ECHEC_PURGE']
    assert all('\x1b' not in ligne for ligne in lignes) and len(lignes[0].split('rsync')[0]) < 20
    assert len(lignes[4]) < 300
    for tache, code in (('inconnue', 'ECHEC_COPIE'), ('copie', 'AUTRE')):
        with pytest.raises(ValueError):
            n.echec(tache, code, 'x')
    assert n.metriques.instantane(n.releve())['echecs'][0] == {'tache': 'copie', 'code': 'ECHEC_COPIE', 'n': 1}


# -- hygiène -----------------------------------------------------------------------------------
def test_nisaba_hygiene():
    sources = sorted((RACINE / 'server' / 'nisaba').glob('*.py'))
    assert {s.name for s in sources} == {'__init__.py', '__main__.py', 'ctl.py', 'etat.py', 'metriques.py',
                                         'purge.py', 'verification.py', 'commandes.py', 'copie.py', 'droits.py',
                                         'horodatage.py', 'scellement.py'}
    for source in sources:
        texte = source.read_text(encoding='utf-8')
        assert 'SPDX-License-Identifier: AGPL-3.0-or-later' in texte and 'Suivi des versions' in texte
        for interdit in ('shell=True', 'os.system', 'journalctl', 'systemctl', 'STATE_DIRECTORY', 'os.popen'):
            assert interdit not in texte, (source.name, interdit)
        assert not re.search(r'\b\d{1,3}(?:\.\d{1,3}){3}\b', texte)
        if source.name not in ('__init__.py', 'scellement.py', 'horodatage.py'):
            # seuls écrivent : l'anneau des échecs (StateDirectory=) et, depuis T033, le MANIFEST et seals/
            assert not re.search(r"O_WRONLY|O_RDWR|O_CREAT|write_text|write_bytes|open\([^)]*['\"][wax+]",
                                 texte), source.name
    init = (RACINE / 'server/nisaba/__init__.py').read_text(encoding='utf-8')
    assert init.count('O_WRONLY') == 1 and 'echecs.json' in init


@pytest.mark.parametrize('variable,valeur,cle', [
    ('PARESIA_NISABA_CTL_UID', '1000', ('ctl', 'uid')),
    ('PARESIA_NISABA_HORAIRE_CONSERVATION_JOURS', '36501', ('horaire', 'conservation_jours'))])
def test_nisaba_configuration_valeurs_bornees(variable, valeur, cle):
    with pytest.raises(ErreurConfiguration) as e:
        configuration(argv=['--config', str(EXEMPLE)], environ={variable: valeur})
    assert (e.value.code, e.value.section, e.value.cle) == ('config_invalid', *cle)
    ok = {'PARESIA_NISABA_CTL_UID': '0', 'PARESIA_NISABA_HORAIRE_CONSERVATION_JOURS': '36500'}
    assert configuration(argv=['--config', str(EXEMPLE)], environ={variable: ok[variable]})


def test_nisaba_verification_command_busy(tmp_path, dossier_socket):
    from nisaba_outils import registre
    n, journal, *_ = monter(tmp_path, dossier_socket)
    registre(journal, ['2023-11-13'])
    (journal / 'seals' / '2023-11-13.txt.ots').write_bytes(b'x')
    debut, fin = threading.Event(), threading.Event()
    reel = n.executer

    def executer(argv, *args, **kwargs):
        debut.set()
        fin.wait(5)
        return reel(argv, *args, **kwargs)

    n.executer = executer
    with n:
        sock = n.config['socket']['socket']
        fil = threading.Thread(target=appeler, args=(sock, 'nisaba/state/verify'))
        fil.start()
        assert debut.wait(5)
        assert appeler(sock, 'nisaba/state/verify')['error']['code'] == 'command_busy'
        fin.set()
        fil.join(5)
        assert appeler(sock, 'nisaba/state/verify')['ok']
