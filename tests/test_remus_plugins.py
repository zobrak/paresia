# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests de Remus enfiché : chargement des fonctions, liste fermée, contrat de sortie, privilèges,
# introspection, non-fermeture ; dépendances : pytest et bibliothèque standard. Aucun sudo réel,
# aucun root, aucun réseau.
# Suivi des versions
#   0.1.7  2026-11-07  Création : fonctions de Remus par manifestes et contrat de sortie (D148, D154).
import ast
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

import pytest

from remus_outils import FauxCastor, appeler, chemin, configuration, evenements, requete
from server import remus as paquet
from server.commun import plugins
from server.commun.config import ErreurConfiguration, lire
from server.commun.journal import Journal
from server.commun.privileges import vers_sudo
from server.remus import Action, Remus, SCHEMA, executeur, fonctions, sudoers
from server.remus.executeur import Choix, Executeur, Hexadecimal, RenduSudo, Variable

MOI = os.geteuid()
RACINE = Path(__file__).resolve().parents[1]
EXEMPLES = RACINE / 'server/remus/exemples/fonctions'
EXECUTEUR = {'sudo': '/usr/bin/sudo', 'docker': '/usr/bin/docker', 'delai_s': 20,
             'kill_grace_s': 1, 'sortie_max': 65536, 'simultanes': 4, 'attente_s': 1}
ACTION = 'exemple/echo/run'
PLUGIN = 'paresia-yin-exemple'


@pytest.fixture
def arbre(tmp_path):
    for nom in ('livre', 'local'):
        (tmp_path / nom).mkdir(mode=0o755)
        os.chmod(tmp_path / nom, 0o755)
    os.chmod(tmp_path, 0o755)
    return tmp_path


def installer(dossier, nom='exemple_echo', delai=None, sortie_max=None, texte=None):
    """Copie la fonction d'exemple (script 0o755, manifeste 0o644)."""
    shutil.copyfile(EXEMPLES / 'exemple_echo', dossier / nom)
    os.chmod(dossier / nom, 0o755)
    manifeste = (EXEMPLES / 'exemple_echo.toml').read_text() if texte is None else texte
    if delai is not None:
        manifeste = manifeste.replace('delai_s = 5', f'delai_s = {delai}')
    if sortie_max is not None:
        manifeste = manifeste.replace('sortie_max = 2048', f'sortie_max = {sortie_max}')
    (dossier / (nom + '.toml')).write_text(manifeste)
    os.chmod(dossier / (nom + '.toml'), 0o644)


def poser(dossier, nom, corps='exit 0', extra='', action=None, delai=5, interpreteur='#!/bin/sh\n'):
    """Fonction en shell POSIX avec son manifeste."""
    (dossier / nom).write_text(interpreteur + corps + '\n')
    os.chmod(dossier / nom, 0o755)
    action = action or f'exemple/essai/{nom}'
    (dossier / (nom + '.toml')).write_text(
        f'format = 1\ngreffon = "{PLUGIN}"\nnom = "{nom}"\naction = "{action}"\n'
        f'delai_s = {delai}\n' + extra)
    os.chmod(dossier / (nom + '.toml'), 0o644)


VIDE = 'printf \'{"ok": true, "data": {}}\''


def options(arbre):
    return {'proprietaires': {MOI}, 'racine_confiance': arbre}


def reglages(arbre, sock, **plugins_):
    config = configuration(sock)
    config['executor'] = dict(EXECUTEUR)
    config['plugins'] = {'fonctions': str(arbre / 'livre'), 'locales': str(arbre / 'local'),
                         'domaine': 'exemple', **plugins_}
    return config


class JournalOrdre(Journal):
    """Journal en mémoire qui note aussi l'ordre des événements dans une liste partagée."""

    def __init__(self, trace=None):
        super().__init__('test', flux=io.StringIO())
        self.trace = [] if trace is None else trace

    def ecrire(self, level, event, **champs):
        self.trace.append(event)
        super().ecrire(level, event, **champs)


@contextlib.contextmanager
def monter(arbre, executeur_=None, lumiere=None, sans_serveur=False, journal=None, **plugins_):
    """Remus chargé depuis l'arbre, avec un faux Castor au vert pour la session 1."""
    with tempfile.TemporaryDirectory(prefix='remus-') as sock:
        faux = FauxCastor(sock)
        faux.etats[1] = ['green']
        config = reglages(arbre, sock, **plugins_)
        config['executor'].update(executeur_ or {})
        config['light'].update(lumiere or {})
        journal = journal or JournalOrdre()
        remus = Remus(config, journal=journal, chargeur=options(arbre))
        remus.config_test, remus.faux, remus.flux_journal = config, faux, journal.flux
        with faux.serveur:
            if sans_serveur:
                yield remus
            else:
                with remus:
                    yield remus


def appel(r, action=ACTION, params=None, session=1):
    return appeler(chemin(r), requete(action, session, params))


def evts(r, nom=None):
    tous = evenements(r.flux_journal)
    return tous if nom is None else [e for e in tous if e['event'] == nom]


def refus_chargement(arbre, **kw):
    with tempfile.TemporaryDirectory(prefix='remus-') as sock:
        config = reglages(arbre, sock)
        with pytest.raises(ErreurConfiguration) as e:
            Remus(config, journal=Journal('test', flux=io.StringIO()), chargeur=options(arbre), **kw)
        assert not os.path.exists(config['server']['socket'])
        return e.value.code


# --- Chargement, catalogue, liste fermée ---------------------------------------------------

def test_chargement_avant_ecoute_et_catalogue(arbre):
    installer(arbre / 'livre')
    with tempfile.TemporaryDirectory(prefix='remus-') as sock:
        config = reglages(arbre, sock)
        journal = JournalOrdre()
        remus = Remus(config, journal=journal, chargeur=options(arbre))
        assert not os.path.exists(config['server']['socket'])      # rien n'écoute encore
        assert 'plugins_loaded' in journal.trace and 'startup' not in journal.trace
        assert set(remus.actions) == {ACTION}
        assert remus.domaine == 'exemple' and remus.cible == 'principale'
        charge = [e for e in map(json.loads, journal.flux.getvalue().splitlines())
                  if e['event'] == 'plugins_loaded'][0]
        assert (charge['level'], charge['functions'], charge['count'], charge['skipped']) == (
            'info', ['exemple_echo'], 1, 0)


def test_livre_invalide_refuse_avant_ecoute(arbre):
    installer(arbre / 'livre', texte=(EXEMPLES / 'exemple_echo.toml').read_text().replace(
        'format = 1', 'format = 2'))
    assert refus_chargement(arbre) == 'plugin_format_unsupported'


def test_domaine_deduit_et_actions_melees(arbre):
    with tempfile.TemporaryDirectory(prefix='remus-') as sock:
        config = reglages(arbre, sock)
        del config['plugins']['domaine']
        a = Action('relay/state/status', print, print, 1)
        b = Action('autre/objet/action', print, print, 1)
        r = Remus(config, actions={a.nom: a}, journal=Journal('t', flux=io.StringIO()))
        assert r.domaine == 'relay'
        with pytest.raises(ValueError, match='^invalid_server_config$'):
            Remus(config, actions={a.nom: a, b.nom: b}, journal=Journal('t', flux=io.StringIO()))
        config['plugins']['domaine'] = 'autre'
        with pytest.raises(ValueError, match='^invalid_server_config$'):
            Remus(config, actions={a.nom: a}, journal=Journal('t', flux=io.StringIO()))


def test_sans_domaine_rien_n_est_charge(arbre):
    installer(arbre / 'livre')
    with tempfile.TemporaryDirectory(prefix='remus-') as sock:
        config = reglages(arbre, sock)
        del config['plugins']['domaine']
        r = Remus(config, journal=Journal('t', flux=io.StringIO()), chargeur=options(arbre))
        assert r.actions == {} and r.domaine is None


def test_liste_fermee(arbre):
    installer(arbre / 'livre')
    with monter(arbre) as r:
        for action in ('exemple/echo/autre', 'relay/state/metrics', 'castor/light/state',
                       'presence/session/open', 'bunker/identity/list', 'exemple/catalog/autre'):
            assert appel(r, action)['error']['code'] == 'unknown_action'
        assert r.faux.appels == []                    # ni Castor ni traitement sollicités


def test_nom_de_greffon_yin_seulement(arbre):
    installer(arbre / 'livre')
    with monter(arbre) as r:
        liste = appel(r, 'exemple/catalog/list')['data']
        assert {a['plugin'] for a in liste['actions'] if a['action'] == ACTION} == {PLUGIN}
    yang = (EXEMPLES / 'exemple_echo.toml').read_text().replace('paresia-yin-', 'paresia-yang-')
    (arbre / 'livre' / 'exemple_echo.toml').write_text(yang)
    assert refus_chargement(arbre) == 'plugin_manifest_invalid'


# --- Dossier local ---------------------------------------------------------------------

def test_local_defectueux_ignore(arbre):
    installer(arbre / 'livre')
    poser(arbre / 'local', 'bon', corps='printf \'{"ok": true, "data": {}}\'')
    poser(arbre / 'local', 'casse', extra='parametres = 5\n')
    (arbre / 'local' / 'orphelin').write_text('x')
    os.chmod(arbre / 'local' / 'orphelin', 0o755)
    with monter(arbre) as r:
        assert set(r.actions) == {ACTION, 'exemple/essai/bon'}
        rejets = evts(r, 'plugin_rejected')
        assert {e['file'] for e in rejets} == {'casse', 'orphelin'}
        assert all(e['level'] == 'error' and e['scope'] == 'local' for e in rejets)
        assert 'parametres' not in json.dumps(rejets).replace('"parametres"', '')
        assert appel(r, 'exemple/essai/bon')['ok'] is True


def test_local_ne_remplace_pas_une_fonction_livree(arbre):
    installer(arbre / 'livre')
    poser(arbre / 'local', 'autre', action=ACTION, corps='exit 1')
    poser(arbre / 'local', 'exemple_echo', corps='exit 1')
    with monter(arbre) as r:
        assert set(r.actions) == {ACTION}
        assert appel(r, params={'message': 'bonjour'})['data']['echo'] == {'message': 'bonjour'}
        assert [e['code'] for e in evts(r, 'plugin_rejected')] == ['plugin_duplicate'] * 2


def test_dossier_local_en_echec_ne_charge_rien(arbre):
    installer(arbre / 'livre')
    poser(arbre / 'local', 'bon', corps='exit 0')
    os.chmod(arbre / 'local', 0o775)
    with monter(arbre) as r:
        assert set(r.actions) == {ACTION}
        assert [e['file'] for e in evts(r, 'plugin_rejected')] == ['local']
        assert appel(r, 'exemple/essai/bon')['error']['code'] == 'unknown_action'


def test_condition_non_remplie(arbre):
    installer(arbre / 'livre')
    poser(arbre / 'livre', 'absente', extra='[requiert]\nbinaires = ["/nulle/part/outil"]\n')
    poser(arbre / 'local', 'localeabsente', extra='[requiert]\nfichiers = ["/nulle/part"]\n')
    with monter(arbre) as r:
        assert set(r.actions) == {ACTION}
        ecartes = evts(r, 'plugin_skipped')
        assert {e['file'] for e in ecartes} == {'absente', 'localeabsente'}
        assert all(e['level'] == 'warning' for e in ecartes)
        assert evts(r, 'plugins_loaded')[0]['skipped'] == 2
        assert appel(r, 'exemple/essai/absente')['error']['code'] == 'unknown_action'


def test_exceptions_du_chargeur_codes_stables(arbre):
    forme = 'journaliser = [[1]]\n'
    poser(arbre / 'livre', 'inattendu', extra=forme)
    assert refus_chargement(arbre) == 'plugin_manifest_invalid'
    os.remove(arbre / 'livre' / 'inattendu')
    os.remove(arbre / 'livre' / 'inattendu.toml')
    poser(arbre / 'local', 'inattendu', extra=forme)
    poser(arbre / 'local', 'sain')
    with monter(arbre) as r:
        assert set(r.actions) == {'exemple/essai/sain'}
        assert [e['code'] for e in evts(r, 'plugin_rejected')] == ['plugin_manifest_invalid']


def test_forme_reservee(arbre):
    texte = (EXEMPLES / 'exemple_echo.toml').read_text()
    assert 'forme = "ponctuel"' in texte
    for valeur in ('residente', 'x'):
        installer(arbre / 'livre', texte=texte.replace('"ponctuel"', f'"{valeur}"'))
        assert refus_chargement(arbre) == 'plugin_form_unsupported'
    os.remove(arbre / 'livre' / 'exemple_echo.toml')
    os.remove(arbre / 'livre' / 'exemple_echo')
    poser(arbre / 'local', 'etrange', extra='forme = "residente"\n')
    with monter(arbre) as r:
        rejet = evts(r, 'plugin_rejected')[0]
        assert rejet['code'] == 'plugin_form_unsupported' and 'residente' not in json.dumps(evts(r))


def test_demon_refuse_un_dossier_livre_non_sur(arbre):
    """Dossiers appartenant à l'utilisateur d'essai : fatal en production (propriétaire root)."""
    installer(arbre / 'livre')
    with tempfile.TemporaryDirectory(prefix='remus-') as sock:
        d = Path(sock)
        (d / 'paresia.conf').write_text(
            f'[remus.server]\nsocket = {d}/r.sock\nuid = {MOI}\ngid = {os.getgid()}\n'
            f'[remus.castor]\nsocket = {d}/c.sock\nuid = {MOI}\n'
            '[remus.executor]\nsudo = /usr/bin/sudo\ndocker = /usr/bin/docker\n'
            f'[remus.plugins]\nfonctions = {arbre}/livre\nlocales = {arbre}/local\n'
            'domaine = exemple\n')
        os.chmod(d / 'paresia.conf', 0o600)
        env = {k: v for k, v in os.environ.items() if not k.startswith(('PARESIA_', 'NOTIFY_'))}
        env['PYTHONPATH'] = str(RACINE)
        p = subprocess.run([sys.executable, '-P', '-s', '-B', '-m', 'server.remus',
                            '--config', str(d / 'paresia.conf')], cwd=RACINE, env=env,
                           capture_output=True, text=True, timeout=30)
    assert p.returncode == os.EX_CONFIG
    assert 'startup_failed' in p.stdout and 'plugin_unsafe_permissions' in p.stdout
    assert str(arbre) not in p.stdout + p.stderr


def test_delai_des_manifestes_dans_le_controle_de_transport(arbre):
    installer(arbre / 'livre', delai=600)
    with tempfile.TemporaryDirectory(prefix='remus-') as sock:
        config = reglages(arbre, sock)
        with pytest.raises(ErreurConfiguration) as e:
            Remus(config, journal=Journal('t', flux=io.StringIO()), chargeur=options(arbre))
        assert (e.value.code, e.value.section, e.value.cle) == ('config_invalid', 'transport',
                                                                'delai_s')


def test_parametre_inexprimable_par_les_gabarits(arbre):
    negatif = ('[[parametres]]\nnom = "n"\ntype = "entier"\nminimum = -5\nmaximum = 5\n')
    poser(arbre / 'livre', 'negatif', extra=negatif)
    assert refus_chargement(arbre) == 'plugin_manifest_invalid'
    os.remove(arbre / 'livre' / 'negatif')
    os.remove(arbre / 'livre' / 'negatif.toml')
    poser(arbre / 'local', 'negatif', extra=negatif)
    poser(arbre / 'livre', 'sain')
    with monter(arbre) as r:
        assert set(r.actions) == {'exemple/essai/sain'}
        assert evts(r, 'plugin_rejected')[0]['code'] == 'plugin_manifest_invalid'


# --- Paramètres --------------------------------------------------------------------------

MAUVAIS = [{'nombre': True}, {'nombre': False}, {'nombre': 1001}, {'nombre': -1},
           {'nombre': '5'}, {'nombre': 1.0}, {'message': '-x'}, {'message': 'a\x07b'},
           {'message': 'a\nb'}, {'message': ''}, {'message': 'é'}, {'message': 'x' * 65},
           {'message': 5}, {'inconnu': 1}, {'essai': 'x'}, {'essai': '-normal'}, {'essai': ['normal']}]


def test_gabarits_refusent(arbre):
    installer(arbre / 'livre')
    poser(arbre / 'livre', 'requis', action='exemple/essai/requis', corps=VIDE,
          extra='[[parametres]]\nnom = "n"\ntype = "entier"\nminimum = 0\nmaximum = 9\n')
    with monter(arbre) as r:
        for params in MAUVAIS:
            assert appel(r, params=params)['error']['code'] == 'bad_request', params
        assert appel(r, 'exemple/essai/requis', {})['error']['code'] == 'bad_request'
        assert appel(r, 'exemple/essai/requis', {'n': 3})['ok'] is True
        assert len(evts(r, 'operation_refused')) == len(MAUVAIS) + 1
        assert evts(r, 'command_started') == [e for e in evts(r, 'command_started')
                                              if e['command'] == 'requis']


def test_executeur_refuse_avec_command_refused(arbre):
    installer(arbre / 'livre')
    flux = io.StringIO()
    charge = fonctions.charger_fonctions(reglages(arbre, '/x'), Journal('t', flux=flux),
                                         **options(arbre))
    script = charge.actions[ACTION].valider.__self__.script
    ex = Executeur(EXECUTEUR, {}, journal=Journal('t', flux=flux))
    for params, raison in (({'nombre': True}, 'invalid_parameter'),
                           ({'zzz': 1}, 'unknown_parameter')):
        resultat = ex.lancer_script(script, params, session=1, identifiant='ab' * 8)
        assert (resultat.ok, resultat.code) == (False, 'bad_request')
    refus = [e for e in map(json.loads, flux.getvalue().splitlines())
             if e['event'] == 'command_refused']
    assert [e['reason'] for e in refus] == ['invalid_parameter', 'unknown_parameter']


# --- Contrat de sortie -----------------------------------------------------------------------

CAS = [('refus', 'not_available', 'ok'), ('refus_inconnu', 'command_failed', 'violated'),
       ('indisponible', 'not_available', 'ok'), ('code3', 'command_failed', 'violated'),
       ('sortie_vide', 'command_failed', 'violated'),
       ('sortie_invalide', 'command_failed', 'violated'),
       ('double_cle', 'command_failed', 'violated'), ('nan', 'command_failed', 'violated'),
       ('controle', 'command_failed', 'violated'), ('trop_long', 'command_failed', 'violated')]


def test_contrat_de_sortie_de_l_exemple(arbre):
    installer(arbre / 'livre')
    with monter(arbre) as r:
        rep = appel(r, params={'message': 'bonjour', 'nombre': 7})
        assert rep['ok'] is True
        data = rep['data']
        script = str(arbre / 'livre' / 'exemple_echo')
        assert data['echo'] == {'message': 'bonjour', 'nombre': 7}
        assert data['argv'] == [script]                      # aucun paramètre dans l'argv
        # ni paramètre dans l'environnement : seulement LC_ALL et le préfixe de privilège
        assert set(data['env']) == {'LC_ALL', 'PARESIA_PRIVILEGE'}
        assert data['env']['LC_ALL'] == 'C'
        assert json.loads(data['env']['PARESIA_PRIVILEGE'])[1:3] == ['-n', '--']
        for essai, code, contrat in CAS:
            rep = appel(r, params={'essai': essai})
            assert rep['ok'] is False and rep['error']['code'] == code, essai
            fin = evts(r, 'command_finished')[-1]
            assert fin['contract'] == contrat and fin['function'] == 'exemple_echo', essai


def test_signal_et_code_sans_json(arbre):
    poser(arbre / 'livre', 'tue', corps='kill -9 $$')
    poser(arbre / 'livre', 'silence', corps='exit 0')
    poser(arbre / 'livre', 'rate', corps='exit 70')
    with monter(arbre) as r:
        for nom in ('tue', 'silence', 'rate'):
            assert appel(r, f'exemple/essai/{nom}')['error']['code'] == 'command_failed'


def test_delai_depasse_arrete_le_groupe(arbre):
    pid = arbre / 'pid'
    poser(arbre / 'livre', 'dort', delai=1,
          corps=f'sleep 60 &\necho $! > {pid}\nsleep 60')
    with monter(arbre) as r:
        debut = time.monotonic()
        assert appel(r, 'exemple/essai/dort')['error']['code'] == 'command_timeout'
        assert time.monotonic() - debut < 10
        petit_fils = int(pid.read_text())
    assert _mort(petit_fils)


def _mort(pid, attente_s=5.0):
    """Vrai si le processus a disparu ou n'est plus qu'un zombie.

    Le petit-fils tué est orphelin : il est adopté par le processus 1, qui, dans un
    conteneur, ne récolte pas toujours ses zombies ; ``kill(pid, 0)`` y réussit alors
    sur un processus déjà terminé. L'état lu dans /proc fait foi.
    """
    fin = time.monotonic() + attente_s
    while True:
        try:
            etat = Path(f'/proc/{pid}/stat').read_text().rpartition(')')[2].split()[0]
        except (FileNotFoundError, ProcessLookupError):
            return True
        if etat in ('Z', 'X'):
            return True
        if time.monotonic() > fin:
            return False
        time.sleep(0.05)


def test_simultaneite(arbre):
    poser(arbre / 'livre', 'lent', corps='sleep 2\nprintf \'{"ok": true, "data": {}}\'')
    with monter(arbre, executeur_={'simultanes': 1, 'attente_s': 0.2}) as r:
        premier = {}
        fil = threading.Thread(target=lambda: premier.update(rep=appel(r, 'exemple/essai/lent')))
        fil.start()
        time.sleep(0.5)
        assert appel(r, 'exemple/essai/lent')['error']['code'] == 'command_busy'
        fil.join(10)
        assert premier['rep']['ok'] is True


def test_sortie_max_de_la_fonction(arbre):
    installer(arbre / 'livre', sortie_max=100)
    with monter(arbre) as r:
        assert appel(r, params={'essai': 'normal'})['error']['code'] == 'command_failed'
        assert appel(r, params={'essai': 'bavard'})['ok'] is True


def test_sortie_max_passe_par_mot_cle(arbre, monkeypatch):
    installer(arbre / 'livre', sortie_max=1500)
    appels = []
    reel = executeur.interpreter_sortie

    def espion(*args, **kw):
        appels.append((args, kw))
        return reel(*args, **kw)

    monkeypatch.setattr(executeur, 'interpreter_sortie', espion)
    with monter(arbre) as r:
        assert appel(r, params={'essai': 'bavard'})['ok'] is True
    assert len(appels) == 1 and appels[0][1] == {'sortie_max': 1500} and len(appels[0][0]) == 3


def test_stderr_et_journal(arbre):
    installer(arbre / 'livre')
    with monter(arbre) as r:
        rep = appel(r, params={'essai': 'bavard', 'nombre': 42, 'message': 'privee valeur'})
        assert rep['ok'] is True
        brut = json.dumps(rep) + r.flux_journal.getvalue()
        assert 'MARQUEUR-ERREUR-BAVARDE' not in brut
        assert 'privee valeur' not in r.flux_journal.getvalue()
        assert str(arbre) not in brut and 'exemple_echo.toml' not in r.flux_journal.getvalue()
        debut = [e for e in evts(r, 'command_started')][0]
        assert debut['args'] == {'essai': 'bavard', 'nombre': 42}
        fin = evts(r, 'command_finished')[0]
        assert fin['stderr_bytes'] >= 4096 and fin['stdout_bytes'] > 0
        assert fin['exit_code'] == 0 and fin['result'] == 'ok' and fin['contract'] == 'ok'
        for essai in ('sortie_invalide', 'controle'):
            appel(r, params={'essai': essai})
        assert 'pas du json' not in r.flux_journal.getvalue()


def test_contrat_independant_du_langage(arbre, monkeypatch):
    corps = ('read -r ligne\nprintf \'{"ok": true, "data": {"recu": %s}}\\n\' "$ligne"')
    poser(arbre / 'livre', 'shell', corps=corps,
          extra='[[parametres]]\nnom = "n"\ntype = "entier"\nminimum = 0\nmaximum = 9\n')
    poser(arbre / 'livre', 'refuse', corps='printf \'{"ok": false, "error": {"code": '
          '"not_available"}}\'\nexit 1', extra='erreurs = ["not_available"]\n')
    poser(arbre / 'livre', 'viole', corps='echo pas-json')
    lances = []
    reel = subprocess.Popen

    def espion(argv, **kw):
        lances.append((argv, kw))
        return reel(argv, **kw)

    monkeypatch.setattr(executeur.subprocess, 'Popen', espion)
    with monter(arbre) as r:
        assert appel(r, 'exemple/essai/shell', {'n': 5})['data'] == {'recu': {'n': 5}}
        assert appel(r, 'exemple/essai/refuse')['error']['code'] == 'not_available'
        assert appel(r, 'exemple/essai/viole')['error']['code'] == 'command_failed'
    assert len(lances) == 3
    for argv, kw in lances:
        assert argv == [argv[0]] and os.path.isabs(argv[0])
        assert set(kw['env']) == {'LC_ALL', 'PARESIA_PRIVILEGE'} and kw['env']['LC_ALL'] == 'C'
        assert kw['shell'] is False and kw['cwd'] == '/'
        assert kw['close_fds'] is True and kw['start_new_session'] is True
    source = Path(executeur.__file__).read_text()
    voie = source[source.index('def lancer_script'):source.index('def _signaler')]
    assert not re.search(r'python|PYTHON|PATH|sys\.executable', voie)


# --- Introspection --------------------------------------------------------------------------

def test_introspection(arbre):
    installer(arbre / 'livre')
    with monter(arbre) as r:
        liste = appel(r, 'exemple/catalog/list')
        assert liste['ok'] and liste['data']['proto'] == 'jumeaux/1'
        data = liste['data']
        assert (data['target'], data['domain'], data['format']) == ('principale', 'exemple', 1)
        assert data['actions'] == [
            {'action': 'exemple/catalog/describe', 'plugin': None},
            {'action': 'exemple/catalog/list', 'plugin': None},
            {'action': ACTION, 'plugin': PLUGIN}]
        decrit = appel(r, 'exemple/catalog/describe', {'action': ACTION})['data']
        assert decrit['plugin'] == PLUGIN and decrit['privilege'] == 'utilisateurs'
        assert decrit['delay_s'] == 5 and decrit['errors'] == ['not_available']
        assert [p['name'] for p in decrit['parameters']] == ['message', 'nombre', 'essai']
        nombre = decrit['parameters'][1]
        assert nombre['type'] == 'entier' and nombre['bounds'] == {'minimum': 0, 'maximum': 1000}
        assert nombre['required'] is False
        brut = json.dumps(liste) + json.dumps(decrit)
        for secret in (str(arbre), 'exemple_echo.toml', '/bin/sh', 'journaliser', 'requiert',
                       'commandes', 'yang', 'sortie_max'):
            assert secret not in brut
        erreurs = [
            (appel(r, 'exemple/catalog/list', {'x': 1}), 'bad_request'),
            (appel(r, 'exemple/catalog/describe', {}), 'bad_request'),
            (appel(r, 'exemple/catalog/describe', {'action': ACTION, 'x': 1}), 'bad_request'),
            (appel(r, 'exemple/catalog/describe', {'action': 'pas valide'}), 'bad_request'),
            (appel(r, 'exemple/catalog/describe', {'action': 'exemple/nulle/part'}),
             'unknown_action')]
        for rep, code in erreurs:
            assert rep['error']['code'] == code
        assert r.faux.appels == []                       # aucune attente du feu pour l'introspection


def test_introspection_absente_sans_domaine():
    with tempfile.TemporaryDirectory(prefix='remus-') as sock:
        faux = FauxCastor(sock)
        config = configuration(sock)
        remus = Remus(config, actions={}, journal=Journal('t', flux=io.StringIO()))
        remus.config_test = config
        with faux.serveur, remus:
            for action in ('exemple/catalog/list', 'exemple/catalog/describe'):
                assert appel(remus, action)['error']['code'] == 'unknown_action'


def test_introspection_controle_l_uid_du_pair(arbre):
    installer(arbre / 'livre')
    with tempfile.TemporaryDirectory(prefix='remus-') as sock:
        config = reglages(arbre, sock)
        config['server']['uid'] = MOI + 1
        remus = Remus(config, journal=Journal('t', flux=io.StringIO()), chargeur=options(arbre))
        remus.config_test = config
        with remus:
            assert appel(remus, 'exemple/catalog/list') is None


# --- Privilèges ----------------------------------------------------------------------------

PRIV = ('[[parametres]]\nnom = "mode"\ntype = "choix"\nvaleurs = ["a", "b"]\n'
        '[[parametres]]\nnom = "ident"\ntype = "hexadecimal"\nlongueur = 8\n'
        '[[commandes_privilegiees]]\noperation = "restart"\narguments = ["cible"]\n'
        '[[commandes_privilegiees]]\noperation = "exec"\n'
        'arguments = ["cible", "outil", {parametre = "mode"}, {parametre = "ident"}]\n')
ATTENDU = sudoers.generer_sudoers((
    RenduSudo('x', ('/usr/bin/docker', 'restart', 'cible')),
    RenduSudo('y', ('/usr/bin/docker', 'exec', 'cible', 'outil', Variable('mode', Choix('a', 'b')),
                    Variable('ident', Hexadecimal(8))))), 'chef')
# Deux variables à 17 valeurs : 289 règles, au-delà de la limite du générateur.
REFUSE = ''.join(f'[[parametres]]\nnom = "{n}"\ntype = "choix"\nvaleurs = ['
                 + ', '.join(f'"v{i}"' for i in range(17)) + ']\n' for n in ('p', 'q')) + (
    '[[commandes_privilegiees]]\noperation = "exec"\n'
    'arguments = ["cible", "outil", {parametre = "p"}, {parametre = "q"}]\n')


def configurer_env(monkeypatch, arbre, texte_plugins=None):
    fichier = arbre / 'paresia.conf'
    fichier.write_text(
        f'[remus.server]\nsocket = /run/x/r.sock\nuid = 1\ngid = 2\n'
        '[remus.castor]\nsocket = /run/x/c.sock\nuid = 3\n'
        '[remus.executor]\nsudo = /usr/bin/sudo\ndocker = /usr/bin/docker\n'
        f'[remus.plugins]\nfonctions = {arbre}/livre\nlocales = {arbre}/local\ndomaine = exemple\n')
    os.chmod(fichier, 0o644)
    monkeypatch.setenv('PARESIA_REMUS_CONFIG', str(fichier))


def test_sudoers_cli_regles_des_manifestes(arbre, monkeypatch, capsys):
    configurer_env(monkeypatch, arbre)
    assert sudoers.main([], **options(arbre)) == 0
    assert capsys.readouterr().out == sudoers.ENTETE                     # dossiers vides
    poser(arbre / 'livre', 'priv', extra=PRIV)
    installer(arbre / 'livre')
    assert sudoers.main([], **options(arbre)) == 0
    sortie = capsys.readouterr()
    assert sortie.out == ATTENDU and sortie.err == ''
    regles = [l for l in sortie.out.splitlines() if l and not l.startswith('#')]
    assert regles[0] == 'chef ALL=(root) NOPASSWD: /usr/bin/docker restart cible'
    assert len(regles) == 1 + 2


def test_sudoers_cli_forme_refusee_sans_sortie_partielle(arbre, monkeypatch, capsys):
    configurer_env(monkeypatch, arbre)
    poser(arbre / 'livre', 'priv', extra=PRIV)
    poser(arbre / 'livre', 'trop', extra=REFUSE)
    assert sudoers.main([], **options(arbre)) == 1
    sortie = capsys.readouterr()
    assert sortie.out == '' and sortie.err == 'plugin_privileges_rejected\n'


def test_forme_refusee_local_ignore_livre_fatal(arbre):
    poser(arbre / 'local', 'trop', extra=REFUSE)
    poser(arbre / 'local', 'priv', extra=PRIV)
    with monter(arbre) as r:
        assert set(r.actions) == {'exemple/essai/priv'}
        assert [(e['code'], e['file']) for e in evts(r, 'plugin_rejected')] == [
            ('plugin_privileges_rejected', 'trop')]
    os.remove(arbre / 'local' / 'trop')
    os.remove(arbre / 'local' / 'trop.toml')
    poser(arbre / 'livre', 'trop', extra=REFUSE)
    assert refus_chargement(arbre) == 'plugin_privileges_rejected'


def test_rappel_de_privileges_toujours_passe(arbre, monkeypatch):
    poser(arbre / 'livre', 'priv', extra=PRIV)
    appels = []
    reel = plugins.charger

    def espion(*args, **kw):
        appels.append(kw.get('verifier_privileges'))
        return reel(*args, **kw)

    monkeypatch.setattr(plugins, 'charger', espion)
    with monter(arbre, sans_serveur=True):
        pass
    config = {'plugins': {'fonctions': str(arbre / 'livre'), 'locales': str(arbre / 'local'),
                          'domaine': 'exemple'}, 'executor': EXECUTEUR}
    fonctions.regles_sudoers(config, **options(arbre))
    fonctions.charger_fonctions(config, Journal('t', flux=io.StringIO()), **options(arbre))
    assert len(appels) == 3 and all(callable(a) for a in appels)
    # Le rappel ne retourne True que si le générateur a produit le fichier.
    assert appels[0](vers_sudo(reel('yin', 'exemple', arbre / 'livre', arbre / 'local',
                                    codes_connus={'command_failed', 'not_available'},
                                    proprietaires={MOI}, racine_confiance=arbre,
                                    verifier_privileges=lambda d: True)
                               .fonctions['exemple/essai/priv'].commandes)) is True
    assert appels[0]([{'verbe': 'exec', 'elements': ['-x']}]) is False
    assert appels[0]('pas une description') is False


def test_rendu_d_essai_avant_l_entree_au_catalogue(arbre, monkeypatch):
    poser(arbre / 'livre', 'priv', extra=PRIV)
    journal = JournalOrdre()
    reel = sudoers.generer_sudoers

    def espion(commandes, compte):
        journal.trace.append('generer')
        return reel(commandes, compte)

    monkeypatch.setattr(sudoers, 'generer_sudoers', espion)
    with monter(arbre, journal=journal, sans_serveur=True) as r:
        assert set(r.actions) == {'exemple/essai/priv'}
    assert journal.trace.index('generer') < journal.trace.index('plugin_loaded')


def test_rappel_defaillant_ne_charge_jamais(arbre, monkeypatch):
    poser(arbre / 'local', 'priv', extra=PRIV)

    def casse(commandes, compte):
        raise RuntimeError('panne')

    monkeypatch.setattr(sudoers, 'generer_sudoers', casse)
    with monter(arbre, sans_serveur=True) as r:
        assert r.actions == {}
        assert evts(r, 'plugin_rejected')[0]['code'] == 'plugin_privileges_rejected'
    os.remove(arbre / 'local' / 'priv')
    os.remove(arbre / 'local' / 'priv.toml')
    poser(arbre / 'livre', 'priv', extra=PRIV)
    assert refus_chargement(arbre) == 'plugin_privileges_rejected'


def test_aucun_objet_du_chargeur_divulgue(arbre):
    poser(arbre / 'livre', 'priv', extra='journaliser = ["mode"]\n' + PRIV,
          corps='printf \'{"ok": true, "data": {}}\'')
    with monter(arbre) as r:
        assert appel(r, 'exemple/essai/priv', {'mode': 'a', 'ident': 'abcdef01'})['ok'] is True
        assert appel(r, 'exemple/essai/priv', {'mode': 'z'})['error']['code'] == 'bad_request'
        marqueur = str(arbre)
        journal = r.flux_journal.getvalue()
        assert marqueur not in journal and 'outil' not in journal and 'docker' not in journal
        action = r.actions['exemple/essai/priv']
        script = action.valider.__self__.script
        for objet in (script, action.valider.__self__, r.repertoire):
            assert marqueur not in repr(objet) + str(objet) and 'outil' not in repr(objet)
        assert 'chemin=' not in repr(script) and 'commandes' not in repr(script)
    chargement = plugins.charger('yin', 'exemple', arbre / 'livre', arbre / 'local',
                                 codes_connus={'command_failed', 'not_available'},
                                 proprietaires={MOI}, racine_confiance=arbre,
                                 verifier_privileges=lambda d: True)
    fonction = chargement.fonctions['exemple/essai/priv']
    avant = copy.deepcopy(fonction.commandes)
    description = vers_sudo(fonction.commandes)
    memoire = copy.deepcopy(description)
    rendus = fonctions.rendre(description, '/usr/bin/docker', 'x')
    assert fonction.commandes == avant and description == memoire
    variable = rendus[1].elements[4]
    with pytest.raises(AttributeError):
        variable.gabarit.valeurs = ('z',)
    with pytest.raises(AttributeError):
        variable.nom = 'z'
    description[1]['elements'][2]['bornes']['valeurs'] = ['z']
    assert fonction.commandes == avant


def test_contrat_du_rappel_dans_le_chargeur_fonction_non_modifiee(arbre):
    """Les bornes reçues sont copiées : modifier le rendu ne touche pas l'objet du chargeur."""
    poser(arbre / 'livre', 'priv', extra=PRIV)
    chargement = plugins.charger('yin', 'exemple', arbre / 'livre', arbre / 'local',
                                 codes_connus={'command_failed', 'not_available'},
                                 proprietaires={MOI}, racine_confiance=arbre,
                                 verifier_privileges=lambda d: True)
    commandes = chargement.fonctions['exemple/essai/priv'].commandes
    variable = commandes[1].elements[2]
    avant = (variable.nom, variable.type, dict(variable.bornes))
    fonctions.rendre(vers_sudo(commandes), '/usr/bin/docker', 'x')
    assert (variable.nom, variable.type, dict(variable.bornes)) == avant


# --- Borne contre les expressions régulières coûteuses ---------------------------------------

class EspionMotif:
    def __init__(self, reel):
        self.reel, self.appels = reel, []

    def fullmatch(self, valeur):
        self.appels.append(valeur)
        return self.reel.fullmatch(valeur)


def test_borne_de_longueur_avant_le_motif(arbre):
    poser(arbre / 'livre', 'motif', corps='printf \'{"ok": true, "data": {}}\'', extra=(
        '[[parametres]]\nnom = "v"\ntype = "texte"\nmotif = "(a+)+$"\nlongueur_max = 20\n'))
    with monter(arbre) as r:
        gabarit = r.actions['exemple/essai/motif'].valider.__self__.script.gabarits['v'][0]
        espion = EspionMotif(gabarit._regex)
        object.__setattr__(gabarit, '_regex', espion)
        debut = time.monotonic()
        trop_long = 'a' * 26 + '!'
        assert appel(r, 'exemple/essai/motif', {'v': trop_long})['error']['code'] == 'bad_request'
        assert time.monotonic() - debut < 5
        assert espion.appels == []                                  # motif non évalué
        for valeur in (123, ['a'], None, True):
            assert appel(r, 'exemple/essai/motif', {'v': valeur})['error']['code'] == 'bad_request'
        assert espion.appels == []
        assert appel(r, 'exemple/essai/motif', {'v': 'a' * 20})['ok'] is True
        assert espion.appels == ['a' * 20] * 2          # Remus puis l'exécuteur
        refus = evts(r, 'operation_refused')
        assert len(refus) == 5 and all(e['reason'] == 'bad_request' for e in refus)


# --- Non-fermeture ---------------------------------------------------------------------------

def test_option_cible(arbre):
    installer(arbre / 'livre')
    with monter(arbre, cible='secondaire') as r:
        assert appel(r, 'exemple/catalog/list')['data']['target'] == 'secondaire'
        sans_cible = appel(r, ACTION, {'message': 'x'})
    with monter(arbre) as r:
        assert appel(r, 'exemple/catalog/list')['data']['target'] == 'principale'
        assert appel(r, ACTION, {'message': 'x'})['data'] == sans_cible['data']
    for mauvaise in ('Majuscule', '1x', 'a' * 33, 'a-b', ''):
        with tempfile.TemporaryDirectory(prefix='remus-') as sock:
            config = reglages(arbre, sock, cible=mauvaise)
            with pytest.raises(ErreurConfiguration) as e:
                Remus(config, journal=Journal('t', flux=io.StringIO()), chargeur=options(arbre))
            assert (e.value.code, e.value.cle) == ('config_invalid', 'cible')


def test_option_domaine_refuse_les_domaines_reserves(arbre):
    for mauvais in ('castor', 'presence', 'Rel', '9x', 'a-b'):
        with tempfile.TemporaryDirectory(prefix='remus-') as sock:
            config = reglages(arbre, sock, domaine=mauvais)
            with pytest.raises(ErreurConfiguration) as e:
                Remus(config, journal=Journal('t', flux=io.StringIO()), chargeur=options(arbre))
            assert (e.value.code, e.value.cle) == ('config_invalid', 'domaine')


def test_variables_d_environnement_de_la_section(tmp_path):
    os.chmod(tmp_path, 0o755)
    env = {'PARESIA_REMUS_PLUGINS_FONCTIONS': '/a/livre', 'PARESIA_REMUS_PLUGINS_LOCALES': '/a/loc',
           'PARESIA_REMUS_PLUGINS_DOMAINE': 'exemple', 'PARESIA_REMUS_PLUGINS_CIBLE': 'cible_2'}
    sections = {('plugins', cle): SCHEMA[('plugins', cle)] for cle in
                ('fonctions', 'locales', 'domaine', 'cible')}
    lu = lire('remus', sections, argv=[], racine_systeme=tmp_path / 'vide', environ=env)
    assert lu['plugins'] == {'fonctions': '/a/livre', 'locales': '/a/loc', 'domaine': 'exemple',
                             'cible': 'cible_2'}
    sans = lire('remus', sections, argv=[], racine_systeme=tmp_path / 'vide', environ={})
    assert sans['plugins'] == {'fonctions': None, 'locales': None, 'domaine': None, 'cible': None}
    assert fonctions.options_plugins(sans).cible == 'principale'
    assert fonctions.options_plugins(sans).fonctions == fonctions.DOSSIER_LIVRE


def test_plusieurs_domaines_refuses_par_remus_non_par_le_repertoire(arbre):
    from server.commun.catalogue import Catalogue, Repertoire
    Repertoire([Catalogue('c', 'un'), Catalogue('c', 'deux'), Catalogue('d', 'un')])
    a, b = Action('un/x/y', print, print, 1), Action('deux/x/y', print, print, 1)
    with tempfile.TemporaryDirectory(prefix='remus-') as sock:
        with pytest.raises(ValueError, match='^invalid_server_config$'):
            Remus(configuration(sock), actions={a.nom: a, b.nom: b},
                  journal=Journal('t', flux=io.StringIO()))


def test_reponses_sans_contrepartie_yang(arbre):
    installer(arbre / 'livre')
    with monter(arbre) as r:
        brut = json.dumps(appel(r, 'exemple/catalog/list')) + json.dumps(
            appel(r, 'exemple/catalog/describe', {'action': ACTION}))
        assert 'yang' not in brut and PLUGIN in brut
    for source in Path(paquet.__file__).parent.glob('*.py'):
        assert not re.search(r'paresia-yang|yang', source.read_text()), source.name


def test_aucun_chargement_de_code_de_greffon():
    arbre_ast = ast.parse(Path(fonctions.__file__).read_text())
    for noeud in ast.walk(arbre_ast):
        if isinstance(noeud, ast.Import):
            assert not {a.name.split('.')[0] for a in noeud.names} & {
                'importlib', 'pkgutil', 'runpy', 'subprocess', 'imp'}
        if isinstance(noeud, ast.ImportFrom):
            assert (noeud.module or '').split('.')[0] not in {
                'importlib', 'pkgutil', 'runpy', 'subprocess', 'imp'}
        if isinstance(noeud, ast.Call):
            nom = getattr(noeud.func, 'id', getattr(noeud.func, 'attr', ''))
            assert nom not in {'eval', 'exec', '__import__', 'import_module', 'entry_points',
                               'Popen', 'system', 'popen', 'spawn'}
            assert not any(k.arg == 'shell' for k in noeud.keywords)
    assert 'entry_points' not in Path(fonctions.__file__).read_text()


def test_neutralite_du_noyau_de_remus():
    motif = re.compile(r'strfry|bunker|nisaba|legal|relay/')
    for source in Path(paquet.__file__).parent.glob('*.py'):
        assert not motif.search(source.read_text()), source.name


def test_exemple_non_installe_ni_configure():
    for chemin_ in (RACINE / 'deploy').rglob('*'):
        if chemin_.is_file() and chemin_.stat().st_size < 1_000_000:
            try:
                texte = chemin_.read_text()
            except UnicodeDecodeError:
                continue
            assert 'exemple_echo' not in texte, chemin_
    conf = (RACINE / 'server/conf/paresia-relais.conf').read_text()
    assert 'exemple_echo' not in conf and not re.search(r'(?m)^domaine = exemple', conf)
    assert re.search(r'(?m)^domaine = relay$', conf)
