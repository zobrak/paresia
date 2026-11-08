# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests d'exécution de l'exécuteur de Remus (T022) avec de faux sudo et docker ; pytest, bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha  2026-11-05  Exécution, sortie, délai, concurrence, journal (T022, exigences 6 à 16).
#   3.0.0-alpha  2026-11-05  Cycle 1 : SIGKILL au groupe, ménage du non-réaperçu, truncated, identifiant borné.
#   3.0.0-alpha  2026-11-05  Cycle 2 : test du fil ignoré explicitement, assertion lisible.
#   3.0.0-alpha  2026-11-05  Cycle 2 : attente bornée du fichier pid (stabilité sous charge), délai élargi.
# Sources vérifiées : sudo(8) (-n, --, relais de signaux), voir server/remus/executeur.py.
import json
import os
from pathlib import Path
import signal
import threading
import time

import pytest

from remus_outils import Banc, commande_mode
from server.remus import executeur as mod
from server.remus.executeur import (Choix, Commande, Entier, Hexadecimal, Param, ParamOption, Texte)

P = ('sudo', '-n', '--', 'docker')


@pytest.fixture
def banc(tmp_path):
    return Banc(tmp_path)


def test_argv_exact(banc):
    c = Commande('c1', P + ('echo', 'fixe', Param('a', Texte('[a-z]+', 8)), ParamOption('--id', 'h', Hexadecimal(4))))
    ex = banc.executeur([c])
    assert ex.lancer('c1', {'a': 'bob'}).data['lines'] == ['fixe|bob']
    assert banc.recu()['argv'] == ['-n', '--', str(banc.docker), 'echo', 'fixe', 'bob']


def test_param_option(banc):
    c = Commande('c1', P + ('echo', ParamOption('--id', 'h', Hexadecimal(4)), ParamOption('--n', 'n', Entier(0, 9))))
    ex = banc.executeur([c])
    assert ex.lancer('c1', {}).data['lines'] == ['']
    assert banc.recu()['argv'][3:] == ['echo']
    assert ex.lancer('c1', {'n': 7, 'h': 'ab12'}).data['lines'] == ['--id|ab12|--n|7']


def test_parametres_inconnus_manquants(banc):
    ex = banc.executeur([commande_mode()])
    for params in ({}, {'mode': 'ok', 'autre': 1}, {'autre': 'ok'}):
        r = ex.lancer('mode', params)
        assert (r.ok, r.code) == (False, 'bad_request')
    assert not banc.trace.exists()
    assert ex.lancer('inconnue', {}).code == 'not_available'
    ev = banc.evenements()
    assert [e['event'] for e in ev].count('command_refused') == 4
    assert 'command_started' not in [e['event'] for e in ev]
    with pytest.raises(TypeError):
        ex.lancer('mode', [])


@pytest.mark.parametrize('valeur', ['-x', '--help', 'a;b', 'a|b', '$(id)', 'a`id`', 'a b', 'a\nb', 'a\x00b',
                                    'é', 'a' * 5000, 5, None, ['a'], True])
def test_injection_refusee(banc, valeur):
    c = Commande('c1', P + ('echo', Param('v', Texte('[a-z0-9]+', 4096))), )
    ex = banc.executeur([c])
    r = ex.lancer('c1', {'v': valeur}, session=3)
    assert (r.ok, r.code) == (False, 'bad_request')
    assert not banc.trace.exists()
    ev = banc.evenements()
    assert ev[-1]['event'] == 'command_refused' and ev[-1]['session'] == 3
    assert 'command_started' not in [e['event'] for e in ev]
    # une valeur non textuelle (5, None, True) peut légitimement apparaître dans le flux
    non_texte = valeur in (5, None, True)
    assert non_texte or str(valeur)[:20] not in banc.flux.getvalue()


def test_gabarit_defaillant_arrete_avant_lancement(banc):
    class Mauvais:
        def valider(self, valeur):
            return '-pirate'
    ex = banc.executeur([Commande('c1', P + ('echo', Param('v', Mauvais())))])
    assert ex.lancer('c1', {'v': 'a'}).code == 'bad_request'
    assert not banc.trace.exists()

    class Instable:
        n = 0

        def valider(self, valeur):
            Instable.n += 1
            return 'a' if Instable.n % 2 else 'b'
    ex = banc.executeur([Commande('c1', P + ('echo', Param('v', Instable())))])
    assert ex.lancer('c1', {'v': 'a'}).code == 'bad_request'
    assert not banc.trace.exists()


def test_environnement_minimal(banc, monkeypatch):
    monkeypatch.setenv('SENTINELLE_PARESIA', 'oui')
    monkeypatch.setenv('PARESIA_X', '1')
    ex = banc.executeur([commande_mode()])
    assert ex.lancer('mode', {'mode': 'ok'}).ok
    assert banc.recu()['env'] == {'LC_ALL': 'C'}


def test_sortie_filtree_par_ligne(banc):
    ex = banc.executeur([commande_mode()])
    r = ex.lancer('mode', {'mode': 'ok'})
    assert r.ok and r.data['truncated'] is False
    lignes = r.data['lines']
    assert lignes[0] == 'une'
    assert lignes[1] == 'ESC\ufffd[31mrouge\ufffd[0m\ufffdtab \ufffdRLO'
    assert lignes[2] == '\xff\xfe' and lignes[3] == 'inv\ufffdalide'
    assert len(lignes) == 4
    for ligne in lignes:
        assert not any(ord(c) < 32 for c in ligne)


def test_sortie_bornee(banc):
    ex = banc.executeur([commande_mode(sortie_max=1000)])
    t = time.monotonic()
    r = ex.lancer('mode', {'mode': 'big'})
    assert r.ok and r.data['truncated'] is True
    assert sum(len(x) for x in r.data['lines']) == 1000
    assert time.monotonic() - t < 15
    assert [e for e in banc.evenements() if e['event'] == 'command_finished'][-1]['truncated'] is True


def test_sortie_choix_flux(banc):
    cs = [commande_mode(f'm_{s}', sortie=s) for s in ('stdout', 'stderr', 'les_deux')]
    ex = banc.executeur(cs)
    assert ex.lancer('m_stdout', {'mode': 'streams'}).data['lines'] == ['sortie']
    assert ex.lancer('m_stderr', {'mode': 'streams'}).data['lines'] == ['erreur']
    assert sorted(ex.lancer('m_les_deux', {'mode': 'streams'}).data['lines']) == ['erreur', 'sortie']
    # 4 Mio sur chaque flux, flux non choisi vidé sans interblocage.
    r = ex.lancer('m_stderr', {'mode': 'big'})
    assert r.ok and r.data['truncated'] is True


def test_codes_sortie(banc):
    ex = banc.executeur([commande_mode(codes_sortie={9: 'command_busy'})])
    assert ex.lancer('mode', {'mode': 'ok'}).code == 'ok'
    r = ex.lancer('mode', {'mode': 'exit3'})
    assert (r.ok, r.code, r.exit_code, r.data) == (False, 'command_failed', 3, None)
    assert 'secret' not in repr(r)
    r = ex.lancer('mode', {'mode': 'exit9'})
    assert (r.code, r.exit_code, r.data) == ('command_busy', 9, None)
    r = ex.lancer('mode', {'mode': 'signal'})
    assert (r.ok, r.code, r.data) == (False, 'command_failed', None)
    assert 'secret' not in banc.flux.getvalue()


def test_delai_depasse(banc):
    ex = banc.executeur([commande_mode(delai_s=0.5)])
    t = time.monotonic()
    r = ex.lancer('mode', {'mode': 'sleep'})
    assert (r.ok, r.code, r.data) == (False, 'command_timeout', None)
    assert time.monotonic() - t < 10
    assert [e for e in banc.evenements() if e['event'] == 'command_finished'][-1]['code'] == 'command_timeout'


def lire_pid(banc, delai=10.0):
    """Attend (borné) que le faux programme ait écrit son pid, puis le renvoie."""
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        try:
            texte = banc.pidfile.read_text()
        except FileNotFoundError:
            texte = ''
        if texte.strip().isdigit():
            return int(texte)
        time.sleep(0.05)
    raise AssertionError('le faux programme n\'a pas écrit son pid')


def test_delai_sigkill(banc):
    # Délai large : sous charge, le faux programme doit avoir installé son ignorance de SIGTERM avant l'échéance.
    ex = banc.executeur([commande_mode(delai_s=5)], kill_grace_s=0.5)
    r = ex.lancer('mode', {'mode': 'ignoreterm'})
    assert r.code == 'command_timeout'
    pid = lire_pid(banc)
    assert inexistant(pid)


def inexistant(pid, attente=3.0):
    """Vrai si le processus n'existe plus (ou n'est plus qu'un zombie en attente de réapage)."""
    fin = time.monotonic() + attente
    while time.monotonic() < fin:
        try:
            etat = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0]
        except (FileNotFoundError, ProcessLookupError):
            return True
        if etat == 'Z':
            return True
        time.sleep(0.05)
    return False


def test_delai_sigkill_petit_fils(banc):
    # Le chef meurt au SIGTERM ; le petit-fils l'ignore : SIGKILL au groupe quand même.
    ex = banc.executeur([commande_mode(delai_s=5)], kill_grace_s=0.5)
    r = ex.lancer('mode', {'mode': 'petitfils'})
    assert r.code == 'command_timeout'
    pid = lire_pid(banc)
    assert inexistant(pid)


def test_delai_truncated_journalise(banc):
    ex = banc.executeur([commande_mode(delai_s=2, sortie_max=1000)], kill_grace_s=0.5)
    r = ex.lancer('mode', {'mode': 'bigsleep'})
    assert (r.code, r.data) == ('command_timeout', None)
    fin = [e for e in banc.evenements() if e['event'] == 'command_finished'][-1]
    assert fin['code'] == 'command_timeout' and fin['truncated'] is True


def test_kill_refuse_journalise(banc, monkeypatch):
    reel = os.killpg
    groupes = []

    def refuse(pid, sig):
        groupes.append(pid)
        raise PermissionError('refus')
    monkeypatch.setattr(os, 'killpg', refuse)
    ex = banc.executeur([commande_mode(delai_s=0.5)], kill_grace_s=0.2)
    try:
        r = ex.lancer('mode', {'mode': 'sleep'})
        assert r.code == 'command_timeout'
        evenements = banc.evenements()
        refus = [e for e in evenements if e['event'] == 'kill_denied']
        assert [e['signal'] for e in refus] == ['SIGTERM', 'SIGKILL']
        assert all(e['command'] == 'mode' for e in refus)
        assert 'sleep' not in banc.flux.getvalue() and str(banc.docker) not in banc.flux.getvalue()
    finally:
        monkeypatch.setattr(os, 'killpg', reel)
        for groupe in groupes[:1]:
            reel(groupe, signal.SIGKILL)


def test_delai_process_not_reaped(banc, monkeypatch):
    reel = mod.subprocess.Popen
    porte = threading.Event()

    class Tetu(reel):
        def wait(self, timeout=None):
            if timeout is None and not porte.is_set():
                porte.wait(10)
            elif timeout is not None and timeout < 5:
                raise mod.subprocess.TimeoutExpired('x', timeout)
            return super().wait(timeout)
    monkeypatch.setattr(mod.subprocess, 'Popen', Tetu)
    ex = banc.executeur([commande_mode(delai_s=0.3)], kill_grace_s=0.2, simultanes=1, attente_s=0.2)
    r = ex.lancer('mode', {'mode': 'sleep'})
    assert r.code == 'command_timeout'
    assert 'process_not_reaped' in [e['event'] for e in banc.evenements()]
    # Processus non réaperçu : l'emplacement reste occupé.
    assert ex.lancer('mode', {'mode': 'ok'}).code == 'command_busy'
    porte.set()
    fin = time.monotonic() + 5
    while time.monotonic() < fin:
        if ex.lancer('mode', {'mode': 'ok'}).ok:
            break
        time.sleep(0.1)
    else:
        pytest.fail('emplacement jamais libéré après le réapage')


def test_identifiant_borne(banc):
    ex = banc.executeur([commande_mode()])
    assert ex.lancer('mode', {'mode': 'ok'}, identifiant='i' * 128).ok
    with pytest.raises(TypeError):
        ex.lancer('mode', {'mode': 'ok'}, identifiant='i' * 129)


def test_simultanes(banc):
    ex = banc.executeur([commande_mode(delai_s=5)], simultanes=1, attente_s=0.3)
    fil = threading.Thread(target=lambda: ex.lancer('mode', {'mode': 'lent'}))
    fil.start()
    time.sleep(0.4)
    r = ex.lancer('mode', {'mode': 'ok'})
    assert (r.ok, r.code) == (False, 'command_busy')
    fil.join()
    assert ex.lancer('mode', {'mode': 'ok'}).ok


def attendre(condition, delai=10.0):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if condition():
            return True
        time.sleep(0.05)
    return False


def test_operation_non_annulee(banc):
    ex = banc.executeur([commande_mode(delai_s=10)])
    # Résultat ignoré : le client a disparu ; aucune attente bloquante sur le fil.
    threading.Thread(target=lambda: ex.lancer('mode', {'mode': 'lent'}, session=42), daemon=True).start()
    assert attendre(banc.effet.exists)
    assert attendre(lambda: any(e['event'] == 'command_finished' for e in banc.evenements()))
    assert banc.effet.read_text() == 'fait'
    fin = [e for e in banc.evenements() if e['event'] == 'command_finished']
    assert fin[0]['session'] == 42 and fin[0]['code'] == 'ok'


def test_entree_standard(banc):
    sans = commande_mode()
    avec = Commande('avec', P + ('stdin', ), entree=10)
    ex = banc.executeur([sans, avec])
    assert ex.lancer('mode', {'mode': 'stdin'}).data['lines'] == ['0']
    assert ex.lancer('avec', {}, entree=b'12345').data['lines'] == ['5']
    assert ex.lancer('avec', {}, entree=b'x' * 11).code == 'bad_request'
    assert ex.lancer('mode', {'mode': 'stdin'}, entree=b'a').code == 'bad_request'
    assert ex.lancer('avec', {}).data['lines'] == ['0']
    with pytest.raises(TypeError):
        ex.lancer('avec', {}, entree='texte')
    assert '12345' not in banc.flux.getvalue()


def test_journal_audit(banc):
    c = Commande('c1', P + ('echo', Param('a', Texte('[a-z]+', 9), journalisable=True),
                            ParamOption('--id', 'h', Hexadecimal(4))))
    ex = banc.executeur([c])
    assert ex.lancer('c1', {'a': 'visible', 'h': 'ab12'}, session=7, identifiant='req1').ok
    ex.lancer('c1', {'a': 'x', 'h': 'ZZZZ'}, session=7)
    for ligne in banc.flux.getvalue().splitlines():
        json.loads(ligne)
    ev = banc.evenements()
    debut, fin, refus = ev[0], ev[1], ev[2]
    assert debut['event'] == 'command_started' and debut['args'] == {'a': 'visible'}
    assert debut['command'] == 'c1' and debut['session'] == 7 and debut['id'] == 'req1'
    assert fin['event'] == 'command_finished' and fin['code'] == 'ok' and fin['exit_code'] == 0
    assert fin['truncated'] is False and fin['duration_ms'] >= 0 and 'args' not in fin
    assert refus['event'] == 'command_refused' and refus['reason'] == 'invalid_parameter'
    brut = banc.flux.getvalue()
    assert 'ab12' not in brut and 'ZZZZ' not in brut and str(banc.docker) not in brut
    assert 'echo' not in brut and 'visible|' not in brut


def test_programme_absent(banc):
    ex = banc.executeur([commande_mode()])
    ex.configuration['docker'] = str(banc.dossier / 'absent')
    r = ex.lancer('mode', {'mode': 'ok'})
    assert (r.ok, r.code) == (False, 'command_failed')
    evenements = banc.evenements()
    assert 'program_missing' in [e['event'] for e in evenements]
    fin = [e for e in evenements if e['event'] == 'command_finished'][-1]
    assert fin['code'] == 'command_failed' and fin['exit_code'] is None and fin['truncated'] is False
    assert 'absent' not in json.dumps(evenements) and 'Traceback' not in json.dumps(evenements)
    ex.configuration['docker'] = str(banc.docker)
    ex.configuration['sudo'] = str(banc.dossier)  # un dossier n'est pas un fichier exécutable
    assert ex.lancer('mode', {'mode': 'ok'}).code == 'command_failed'


def test_source_sans_shell_ni_chemin_fige():
    import ast
    import re
    source = Path(mod.__file__).read_text()
    arbre = ast.parse(source)
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Call):
            nom = ast.unparse(noeud.func)
            assert nom not in ('eval', 'exec', 'os.system', 'os.popen')
    for interdit in ('shell=True', 'os.system', 'os.popen', 'eval(', 'exec('):
        assert interdit not in re.sub(r'#.*', '', re.sub(r'""".*?"""', '', source, flags=re.S))
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str) and noeud.value.startswith('/'):
            assert noeud.value == '/' or '\n' in noeud.value  # seules exceptions : docstrings


def test_codes_executeur_dans_socle():
    jumeaux = pytest.importorskip('server.commun.jumeaux')
    if not set(mod.CODES_EXECUTEUR) <= set(jumeaux.DETAILS):
        pytest.skip('T027 non fusionnée : codes absents du socle')
    assert set(mod.CODES_EXECUTEUR) <= jumeaux.CODES_ERREUR


def test_codes_executeur_sur_le_fil():
    pytest.skip("à écrire après la fusion de T027 (passage des codes sur le fil)")
