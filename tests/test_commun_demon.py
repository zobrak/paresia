# SPDX-License-Identifier: AGPL-3.0-or-later
# Suivi des versions
#   0.1.5  2026-11-07  Attente bornée et répétée jusqu'à la demande d'arrêt.
#   0.1.5  2026-11-07  Bornes du diagnostic et omission des résolutions en boucle.
#   0.1.5  2026-11-07  Diagnostic des exceptions sans message ni valeur confidentielle.
#   0.1.1  2026-11-07  Étiquettes de langue BCP 47 dans les essais.
#   0.1.1  2026-11-07  Options debug/config, signaux réels et neutralité de check.
#   0.1.1  2026-11-07  Erreurs de données, langues et distinction démarrage/service.
#   0.1.1  2026-11-07  Vérification du socle commun.
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import tempfile
import subprocess
import sys
import pytest
from server.commun import systemd
from server.commun.demon import Cycle, Demon, ErreurDonnees, lancer
from server.commun.config import ErreurConfiguration, Option


@pytest.mark.parametrize('deja_arrete', (False, True))
def test_attendre_reveille_le_fil_principal(deja_arrete):
    attentes, evenements = [], []

    class Evenement:
        def wait(self, timeout=None):
            assert timeout is not None and 0 < timeout <= 0.1
            attentes.append(timeout)
            return deja_arrete or len(attentes) == 3

    class Journal:
        def ecrire(self, niveau, evenement):
            evenements.append((niveau, evenement))

    cycle = Cycle({}, Journal(), textes={})
    cycle.arret = Evenement()
    cycle.attendre()
    assert attentes == [0.1] * (1 if deja_arrete else 3)
    assert evenements == [('debug', 'stop_requested')]


def test_options(capsys):
    d = Demon('test', '0.1.1', {}, lambda *a: pytest.fail('corps appelé'))
    assert lancer(d, ['--help'], {}) == 0
    assert '--check' in capsys.readouterr().out
    assert lancer(d, ['--version'], {}) == 0
    assert '0.1.1' in capsys.readouterr().out
    assert lancer(d, ['--inconnu'], {}) == 64
    assert capsys.readouterr().err
    assert lancer(d, ['--check'], {}) == 0

def test_configuration_invalide(capsys):
    def configurer(**kw):
        raise ErreurConfiguration('config_invalid', 'transport', 'socket')
    assert lancer(Demon('test','0.1.1',{},None,configurer), [], {}) == 78
    assert json.loads(capsys.readouterr().out)['event'] == 'startup_failed'

def test_signal_et_contexte(tmp_path):
    programme = """
from server.commun.demon import Demon, lancer
class Service:
    def __init__(self, config, journal): pass
    def __enter__(self):
        open(__import__('sys').argv[1], 'w').close()
    def __exit__(self, *args): pass
raise SystemExit(lancer(Demon('test', '0.1.1', {}, Demon.depuis_contexte(Service)), [], __import__('os').environ))
"""
    dossier_court = tempfile.TemporaryDirectory(prefix='paresia-')
    adresse = dossier_court.name + '/notify'
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as flux:
        flux.bind(adresse)
        flux.settimeout(5)
        p = subprocess.Popen([sys.executable, '-c', programme, str(tmp_path / 'entre')], env={**os.environ, 'NOTIFY_SOCKET': adresse})
        try:
            assert b'READY=1' in flux.recv(8192)
            assert (tmp_path / 'entre').exists()
            p.send_signal(signal.SIGTERM)
            assert flux.recv(8192) == b'STOPPING=1'
            assert p.wait(timeout=5) == 0
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()


@pytest.mark.parametrize('exception,code', [(OSError(5, 'non affiché'), 71), (RuntimeError('non affiché'), 70)])
def test_codes_erreur(exception, code, capsys):
    def corps(*args):
        raise exception
    assert lancer(Demon('test', '0.1.1', {}, corps), [], {}) == code
    texte = capsys.readouterr().out
    assert 'non affiché' not in texte
    assert json.loads(texte)['event'] == 'startup_failed'


def test_check_metriques(capsys, tmp_path):
    env = {'PARESIA_TEST_METRIQUES_ACTIF': 'true'}
    d = Demon('test', '0.1.1', {}, None)
    assert lancer(d, ['--check'], env) == 78
    capsys.readouterr()
    env['STATE_DIRECTORY'] = str(tmp_path)
    assert lancer(d, ['--check'], env) == 0
    assert not (tmp_path / 'metriques').exists()


def test_donnees_illisibles_generiques(capsys):
    class DonneesInexploitables(ErreurDonnees):
        pass

    def corps(*args):
        raise DonneesInexploitables('contenu non affichable')

    d = Demon('test', '0.1.1', {}, corps)
    assert lancer(d, [], {}) == os.EX_DATAERR
    sortie = capsys.readouterr()
    evenement = json.loads(sortie.out)
    assert evenement['event'] == 'startup_failed'
    assert evenement['cause'] == 'data_unreadable'
    assert 'contenu non affichable' not in sortie.out + sortie.err


@pytest.mark.parametrize('exception,code', [
    (ErreurDonnees('non affiché'), os.EX_DATAERR),
    (RuntimeError('non affiché'), os.EX_SOFTWARE),
    (OSError(5, 'non affiché'), os.EX_OSERR),
    (ErreurConfiguration('config_invalid', 'transport', 'socket'), os.EX_CONFIG),
])
@pytest.mark.parametrize('notifie', [True, False])
def test_erreur_en_service(exception, code, notifie, monkeypatch, capsys):
    notifications = []

    def notifier(*champs, environ=None):
        notifications.append(champs)
        return notifie

    monkeypatch.setattr(systemd, 'notifier', notifier)
    monkeypatch.setattr(sys.stderr, 'isatty', lambda: True)

    def corps(config, journal, cycle):
        assert cycle.pret() is notifie
        raise exception

    assert lancer(Demon('test', '0.1.1', {}, corps), [], {}) == code
    assert len(notifications) == 1
    assert notifications[0][0] == 'READY=1'
    sortie = capsys.readouterr()
    assert json.loads(sortie.out)['event'] == 'service_failed'
    assert 'startup_failed' not in sortie.out
    assert sortie.err == 'Erreur pendant le fonctionnement de test.\n'
    assert 'non affiché' not in sortie.out + sortie.err


@pytest.mark.parametrize('environ,repere', [
    ({}, 'aide'),
    ({'LANG': 'en-US'}, 'help'),
    ({'LANG': 'fr-FR'}, 'aide'),
    ({'LANG': 'de-DE'}, 'aide'),
    ({'LC_ALL': 'fr-FR', 'LC_MESSAGES': 'en-US', 'LANG': 'en-US'}, 'aide'),
    ({'LC_ALL': '', 'LC_MESSAGES': 'en-US', 'LANG': 'fr-FR'}, 'help'),
    ({'LC_ALL': 'C', 'LANG': 'en-US'}, 'aide'),
])
def test_langue_catalogue(environ, repere, monkeypatch, capsys):
    monkeypatch.setenv('LANG', 'en-US')
    assert lancer(Demon('test', '0.1.1', {}, None), ['--help'], environ) == 0
    attendu = '--help : aide' if repere == 'aide' else '--help: help'
    assert attendu in capsys.readouterr().out


def test_catalogue_charge_une_fois(monkeypatch, capsys):
    lectures, notifications = [], []
    lire_texte = Path.read_text

    def lire_catalogue(chemin, *args, **kw):
        lectures.append(chemin.name)
        return lire_texte(chemin, *args, **kw)

    def notifier(*champs, environ=None):
        notifications.append(champs)
        return True

    monkeypatch.setattr(Path, 'read_text', lire_catalogue)
    monkeypatch.setattr(systemd, 'notifier', notifier)
    monkeypatch.setattr(sys.stderr, 'isatty', lambda: True)

    def corps(config, journal, cycle):
        cycle.pret()
        raise RuntimeError('non affiché')

    assert lancer(Demon('test', '0.1.1', {}, corps), [], {'LANG': 'en-US'}) == os.EX_SOFTWARE
    assert lectures == ['en-US.json']
    assert notifications == [('READY=1', 'STATUS=Service ready')]
    sortie = capsys.readouterr()
    assert sortie.err == 'Error while test was running.\n'


def test_catalogue_indisponible_repli_francais(monkeypatch, capsys):
    lectures = []
    lire_texte = Path.read_text

    def lire_catalogue(chemin, *args, **kw):
        lectures.append(chemin.name)
        if chemin.name == 'en-US.json':
            raise FileNotFoundError()
        return lire_texte(chemin, *args, **kw)

    monkeypatch.setattr(Path, 'read_text', lire_catalogue)
    assert lancer(Demon('test', '0.1.1', {}, None), ['--help'], {'LANG': 'en-US'}) == 0
    assert '--help : aide' in capsys.readouterr().out
    assert lectures == ['en-US.json', 'fr-FR.json']


@pytest.mark.parametrize('debug', [False, True])
def test_option_debug_et_configuration_confidentielle(debug, capsys):
    jetable = secrets.token_urlsafe(32)
    schema = {('general', 'secret'): Option('texte')}

    def corps(config, journal, cycle):
        assert config['general']['secret'] == jetable
        journal.ecrire('debug', 'trace_essai', token=config['general']['secret'])

    env = {'PARESIA_TEST_GENERAL_SECRET': jetable}
    assert lancer(Demon('test', '0.1.1', schema, corps), ['--debug'] if debug else [], env) == 0
    sortie = capsys.readouterr()
    assert jetable not in sortie.out + sortie.err
    evenements = [json.loads(ligne) for ligne in sortie.out.splitlines()]
    traces = [e for e in evenements if e['event'] == 'trace_essai']
    if debug:
        assert len(traces) == 1
        assert traces[0]['level'] == 'debug'
        assert traces[0]['token'] == '[REDACTED]'
        assert any(e['event'] == 'config_read' and e['section'] == 'general' and e['option'] == 'secret'
                   for e in evenements)
    else:
        assert not traces
        assert not any(e['level'] == 'debug' for e in evenements)


@pytest.mark.parametrize('mode,invalide,code,cause', [
    (0o600, False, 0, None),
    (0o666, False, os.EX_CONFIG, 'config_unsafe_permissions'),
    (0o600, True, os.EX_CONFIG, 'config_invalid'),
])
def test_option_config_fichier(tmp_path, capsys, mode, invalide, code, cause):
    # Valeur de compte factice, régénérée pour chaque cas.
    valeur = ('!' if invalide else 'compte_') + secrets.token_hex(16)
    fichier = tmp_path / 'essai.conf'
    fichier.write_text(f'[test]\ncompte = {valeur}\n', encoding='utf-8')
    fichier.chmod(mode)
    schema = {('general', 'compte'): Option('compte')}

    def corps(*args):
        pytest.fail('corps appelé pendant la vérification')

    assert lancer(Demon('test', '0.1.1', schema, corps), ['--config', str(fichier), '--check'], {}) == code
    sortie = capsys.readouterr()
    assert valeur not in sortie.out + sortie.err
    if cause is None:
        assert sortie.out == sortie.err == ''
    else:
        evenement = json.loads(sortie.out)
        assert evenement['event'] == 'startup_failed'
        assert evenement['cause'] == cause
        if invalide:
            assert (evenement['section'], evenement['option']) == ('general', 'compte')


def test_option_config_sans_argument(capsys):
    assert lancer(Demon('test', '0.1.1', {}, None), ['--config'], {}) == os.EX_USAGE
    sortie = capsys.readouterr()
    assert sortie.out == ''
    assert '--config' in sortie.err


@pytest.mark.parametrize('numero', [signal.SIGTERM, signal.SIGINT, signal.SIGHUP])
def test_signaux_corps_en_service(numero):
    programme = '''
import signal
from server.commun.demon import Demon, lancer

signal.signal(signal.SIGHUP, signal.SIG_DFL)

def corps(config, journal, cycle):
    assert signal.getsignal(signal.SIGHUP) == signal.SIG_DFL
    cycle.pret()
    cycle.attendre()

def configurer(**kwargs):
    return {}

raise SystemExit(lancer(Demon('test', '0.1.1', {}, corps, configurer)))
'''
    with tempfile.TemporaryDirectory(prefix='paresia-') as dossier:
        adresse = str(Path(dossier) / 'notify')
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as flux:
            flux.bind(adresse)
            flux.settimeout(5)
            processus = subprocess.Popen(
                [sys.executable, '-c', programme],
                cwd=Path(__file__).resolve().parents[1],
                env={'NOTIFY_SOCKET': adresse}, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            try:
                assert b'READY=1' in flux.recv(8192).splitlines()
                processus.send_signal(numero)
                if numero == signal.SIGHUP:
                    assert processus.wait(timeout=5) == -signal.SIGHUP
                    flux.settimeout(0.1)
                    with pytest.raises(TimeoutError):
                        flux.recv(8192)
                else:
                    assert flux.recv(8192) == b'STOPPING=1'
                    assert processus.wait(timeout=5) == 0
            finally:
                if processus.poll() is None:
                    processus.kill()
                processus.communicate(timeout=5)


def test_check_sans_notification_ni_metriques(tmp_path):
    appels = []
    dossier_metriques = tmp_path / 'metriques'

    def corps(*args):
        appels.append(True)

    with tempfile.TemporaryDirectory(prefix='paresia-') as dossier:
        adresse = str(Path(dossier) / 'notify')
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as flux:
            flux.bind(adresse)
            flux.settimeout(0.1)
            env = {'NOTIFY_SOCKET': adresse, 'PARESIA_TEST_METRIQUES_ACTIF': 'true',
                   'PARESIA_TEST_METRIQUES_DOSSIER': str(dossier_metriques)}
            assert lancer(Demon('test', '0.1.1', {}, corps), ['--check'], env) == 0
            with pytest.raises(TimeoutError):
                flux.recv(8192)
    assert appels == []
    assert not dossier_metriques.exists()
    assert not list(tmp_path.rglob('*.prom'))


@pytest.mark.parametrize('mode', ('info', 'option', 'configuration'))
@pytest.mark.parametrize('en_service', (False, True))
@pytest.mark.parametrize('genre,code,cause', [
    ('interne', 70, 'internal_error'), ('systeme', 71, 'os_error'),
    ('donnees', 65, 'data_unreadable'), ('configuration', 78, 'config_invalid'),
])
def test_detail_exception_sans_valeur(mode, en_service, genre, code, cause, capsys, monkeypatch):
    sentinelle = secrets.token_urlsafe(32)
    erreurs = {
        'interne': RuntimeError(sentinelle),
        'systeme': OSError(5, sentinelle),
        'donnees': ErreurDonnees(sentinelle),
        'configuration': ErreurConfiguration('config_invalid', 'transport', 'socket'),
    }
    erreur = erreurs[genre]
    erreur.args = (sentinelle,)
    monkeypatch.setattr(sys.stderr, 'isatty', lambda: True)

    def configurer(**kwargs):
        return {'journal': {'niveau': 'debug' if mode == 'configuration' else 'info'},
                'general': {'valeur': sentinelle}}

    def corps(config, journal, cycle):
        if en_service:
            cycle.pret()
        raise erreur

    arguments = ['--debug'] if mode == 'option' else []
    assert lancer(Demon('test', '0.1.1', {}, corps, configurer), arguments, {}) == code
    sortie = capsys.readouterr()
    assert sentinelle not in sortie.out + sortie.err
    assert 'internal_error_detail' not in sortie.err
    evenements = [json.loads(ligne) for ligne in sortie.out.splitlines()]
    echecs = [e for e in evenements if e['level'] == 'error']
    assert len(echecs) == 1
    assert {k: v for k, v in echecs[0].items() if k not in ('ts', 'component', 'level')} == {
        'event': 'service_failed' if en_service else 'startup_failed', 'cause': cause,
        'section': 'transport' if genre == 'configuration' else None,
        'option': 'socket' if genre == 'configuration' else None,
        'errno': 5 if genre == 'systeme' else None}
    details = [e for e in evenements if e['event'] == 'internal_error_detail']
    if mode == 'info':
        assert not details
    else:
        assert len(details) == 1
        detail = details[0]
        assert set(detail) == {'ts', 'component', 'level', 'event', 'classe', 'pile'}
        assert detail['level'] == 'debug'
        assert detail['classe'] == type(erreur).__name__
        assert len(detail['pile']) == 1
        fichier, ligne, fonction = detail['pile'][0]
        assert fichier == 'commun/demon.py' and fonction == 'lancer'
        assert type(ligne) is int and ligne > 0
        assert str(Path(__file__).resolve().parents[1]) not in sortie.out


def test_detail_exception_avant_configuration(tmp_path, capsys):
    from server.commun.version import lire_version

    def version():
        return lire_version(tmp_path)

    assert lancer(Demon('test', version, {}, None), ['--debug'], {}) == 70
    sortie = capsys.readouterr()
    evenements = [json.loads(ligne) for ligne in sortie.out.splitlines()]
    assert [e['event'] for e in evenements] == ['startup_failed', 'internal_error_detail']
    assert evenements[1]['classe'] == 'RuntimeError'
    assert [cadre[0] for cadre in evenements[1]['pile']] == ['commun/demon.py', 'commun/version.py']
    assert 'version_unreadable' not in sortie.out + sortie.err
    assert str(tmp_path) not in sortie.out + sortie.err


def test_detail_recursion_borne(capsys):
    from server.commun import demon

    sentinelle = secrets.token_urlsafe(32)
    classe = type('ExceptionDeDiagnostic' * 5, (RuntimeError,), {})
    espace = {'erreur': classe(sentinelle)}
    # Code d'essai en mémoire, attribué au paquet sans écrire dans server/.
    source = ('def lever():\n    raise erreur\n'
              'def recursion(n):\n    if n:\n        recursion(n - 1)\n'
              '    else:\n        lever()\n')
    exec(compile(source, demon.__file__, 'exec'), espace)

    def corps(*args):
        espace['recursion'](80)

    assert lancer(Demon('test', '0.1.1', {}, corps), ['--debug'], {}) == 70
    sortie = capsys.readouterr()
    detail = next(json.loads(l) for l in sortie.out.splitlines()
                  if json.loads(l)['event'] == 'internal_error_detail')
    assert len(detail['pile']) == 16
    assert detail['pile'][-1] == ['commun/demon.py', 2, 'lever']
    assert all(c[2] == 'recursion' for c in detail['pile'][:-1])
    assert detail['classe'] == classe.__name__[:64]
    assert len(detail['classe']) == 64
    assert sentinelle not in sortie.out + sortie.err


def test_detail_resolution_runtimeerror(monkeypatch, capsys):
    from server.commun import demon

    chemin = Path(demon.__file__).parent / 'cadre_simule.py'
    espace = {}
    exec(compile('def corps(*args):\n    raise ValueError()\n', str(chemin), 'exec'), espace)
    resoudre = Path.resolve
    omissions = []

    def resolution(self, *args, **kwargs):
        if self == chemin:
            omissions.append(True)
            raise RuntimeError()
        return resoudre(self, *args, **kwargs)

    monkeypatch.setattr(Path, 'resolve', resolution)
    assert lancer(Demon('test', '0.1.1', {}, espace['corps']), ['--debug'], {}) == 70
    evenements = [json.loads(l) for l in capsys.readouterr().out.splitlines()]
    echec = next(e for e in evenements if e['event'] == 'startup_failed')
    assert {k: v for k, v in echec.items() if k not in ('ts', 'component', 'level')} == {
        'event': 'startup_failed', 'cause': 'internal_error', 'section': None,
        'option': None, 'errno': None}
    detail = next(e for e in evenements if e['event'] == 'internal_error_detail')
    assert omissions == [True]
    assert detail['classe'] == 'ValueError'
    assert len(detail['pile']) == 1
    assert detail['pile'][0][0] == 'commun/demon.py'
    assert detail['pile'][0][2] == 'lancer'
