# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests du plugin writePolicy server/strfry/journal_legal.py (T040, D95) ; clés factices générées à l'exécution.
# Suivi des versions
#   3.0.0-alpha.40  2026-11-06  Création (T040).
#   3.0.0-alpha.41  2026-11-06  Liste noire : conservation sur erreur d'accès, alertes (D110).
import ast
import errno
import json
import os
import random
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from server.strfry import journal_legal as jl

MODULE = Path(jl.__file__)
RACINE = MODULE.parent.parent.parent
ALEA = random.Random(40)


def hexa(n):
    return ''.join(ALEA.choice('0123456789abcdef') for _ in range(n))


def requete(kind=1, source='IP4', info='203.0.113.7', recu=1700000001, tags=None, content='x', pubkey=None, **extra):
    ev = {'id': hexa(64), 'pubkey': pubkey or hexa(64), 'created_at': 1700000000, 'kind': kind,
          'tags': tags or [], 'content': content, 'sig': hexa(128)}
    r = {'type': 'new', 'event': ev, 'receivedAt': recu, 'sourceType': source, 'sourceInfo': info}
    r.update(extra)
    return r


def ligne(r):
    return json.dumps(r).encode() + b'\n'


@pytest.fixture
def dossiers(tmp_path):
    journal = tmp_path / 'journal'
    journal.mkdir()
    return journal, tmp_path / 'blocklist.txt'


def etat_de(dossiers, **kw):
    journal, liste = dossiers
    return jl.Etat(str(journal), str(liste), jl.analyser_kinds(jl.DEFAUT_UNJOURNALED_KINDS), **kw)


def env_de(dossiers):
    journal, liste = dossiers
    env = dict(os.environ)
    env.update(JOURNAL_DIR=str(journal), BLOCKLIST_FILE=str(liste))
    env.pop('UNJOURNALED_KINDS', None)
    return env


def lancer(dossiers, entree, **kw):
    p = subprocess.run([sys.executable, str(MODULE)], input=entree, capture_output=True, env=env_de(dossiers),
                       timeout=30, **kw)
    return p


def lignes_journal(dossiers):
    journal, _ = dossiers
    res = []
    for f in sorted(journal.glob('journal-*.jsonl')):
        res += [json.loads(x) for x in f.read_text(encoding='utf-8').splitlines()]
    return res


def reponse(sortie):
    return [json.loads(x) for x in sortie.decode().splitlines()]


def test_plugin_vecteur_journal_ip4(dossiers):
    r = requete()
    p = lancer(dossiers, ligne(r))
    assert p.returncode == 0
    assert reponse(p.stdout) == [{'id': r['event']['id'], 'action': 'accept'}]
    attendu = ('{"t":"2023-11-14T22:13:21Z","connexion":"203.0.113.7","protocoles":"TCP/IP, TLS, WebSocket, '
               'Nostr NIP-01","contenu":"%s","nature":"creation","auteur":"%s"}'
               % (r['event']['id'], r['event']['pubkey']))
    fichiers = list(dossiers[0].glob('journal-*.jsonl'))
    assert len(fichiers) == 1
    assert fichiers[0].read_text() == attendu + '\n'
    assert p.stdout.decode().strip() == '{"id":"%s","action":"accept"}' % r['event']['id']


def test_plugin_vecteur_tor(dossiers):
    lancer(dossiers, ligne(requete(source='IP6', info='fc00:dead:beef::1')))
    (e,) = lignes_journal(dossiers)
    assert e['protocoles'] == 'Tor, WebSocket, Nostr NIP-01'
    assert e['connexion'] == 'fc00:dead:beef::1'


@pytest.mark.parametrize('kind,nature', [
    (0, 'creation_ou_modification'), (3, 'creation_ou_modification'), (5, 'suppression'),
    (10002, 'creation_ou_modification'), (20000, 'creation'), (30023, 'creation_ou_modification'),
    (1, 'creation'), (1059, 'creation')])
def test_plugin_natures(dossiers, kind, nature):
    lancer(dossiers, ligne(requete(kind=kind)))
    (e,) = lignes_journal(dossiers)
    assert e['nature'] == nature


def test_plugin_suppression_vise(dossiers):
    a, b = hexa(64), hexa(64)
    tags = [['e', a], ['p', hexa(64)], ['e', b], ['a', '30023:' + hexa(64) + ':x'], ['e']]
    lancer(dossiers, ligne(requete(kind=5, tags=tags)) + ligne(requete(kind=5, tags=[['e', a]])))
    e1, e2 = lignes_journal(dossiers)
    assert list(e1) == ['t', 'connexion', 'protocoles', 'contenu', 'nature', 'auteur', 'vise', 'vise_adressables']
    assert e1['vise'] == [a, b]
    assert e1['vise_adressables'] == [tags[3][1]]
    assert 'vise_adressables' not in e2 and e2['vise'] == [a]


@pytest.mark.parametrize('source', ['Import', 'Sync', 'Stored', 'Stream'])
def test_plugin_sourcetype_non_reseau(dossiers, source):
    r = requete(source=source)
    p = lancer(dossiers, ligne(r))
    assert reponse(p.stdout) == [{'id': r['event']['id'], 'action': 'accept'}]
    assert lignes_journal(dossiers) == []


@pytest.mark.parametrize('kind', [20001, 22242, 27235])
def test_plugin_rapide_aucune_ecriture(dossiers, kind, monkeypatch):
    appels = []
    reel = os.open
    monkeypatch.setattr(os, 'open', lambda *a, **k: appels.append(a) or reel(*a, **k))
    r = requete(kind=kind)
    rep = jl.traiter(ligne(r), etat_de(dossiers))
    assert json.loads(rep) == {'id': r['event']['id'], 'action': 'accept'}
    assert appels == []
    assert list(dossiers[0].iterdir()) == []


def test_plugin_rapide_un_seul_stat(dossiers, monkeypatch):
    appels = []
    reel = os.stat
    monkeypatch.setattr(os, 'stat', lambda *a, **k: appels.append(a) or reel(*a, **k))
    etat = etat_de(dossiers)
    for kind in (20001, 1, 22242):
        appels.clear()
        jl.traiter(ligne(requete(kind=kind)), etat)
        assert len(appels) == 1


def test_plugin_aucun_sous_processus(dossiers):
    arbre = ast.parse(MODULE.read_text(encoding='utf-8'))
    for n in ast.walk(arbre):
        if isinstance(n, ast.Import):
            assert all(a.name.split('.')[0] not in ('subprocess', 'pickle', 'importlib') for a in n.names)
        if isinstance(n, ast.ImportFrom):
            assert n.module.split('.')[0] not in ('subprocess', 'pickle', 'importlib')
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                assert f.id not in ('eval', 'exec', '__import__')
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == 'os':
                assert f.attr not in ('system', 'popen', 'fork') and not f.attr.startswith(('exec', 'spawn'))
    # À l'exécution : un processus fils qui charge le plugin, traite trente requêtes de chaque chemin.
    code = (
        "import sys, json\n"
        "sys.path.insert(0, %r)\n"
        "from server.strfry import journal_legal as jl\n"
        "e = jl.Etat(sys.argv[1], sys.argv[2], jl.analyser_kinds(jl.DEFAUT_UNJOURNALED_KINDS))\n"
        "for k in [20001, 1, 20001, 5] * 30:\n"
        "    r = {'type': 'new', 'event': {'id': 'a' * 64, 'pubkey': 'b' * 64, 'kind': k, 'tags': []},\n"
        "         'receivedAt': 1, 'sourceType': 'IP4', 'sourceInfo': '203.0.113.7'}\n"
        "    jl.traiter(json.dumps(r), e)\n"
        "print('subprocess' in sys.modules)\n" % str(RACINE))
    p = subprocess.run([sys.executable, '-c', code, str(dossiers[0]), str(dossiers[1])],
                       capture_output=True, text=True, timeout=30)
    assert p.stdout.strip() == 'False', p.stderr


def test_plugin_kind_usurpe(dossiers):
    piege = '{"kind":20001}'
    lancer(dossiers, ligne(requete(kind=1, content=piege, tags=[['t', '"kind":20001']])))
    assert len(lignes_journal(dossiers)) == 1
    for faux in (True, 1.0, '20001'):
        etat = etat_de(dossiers)
        r = requete(kind=faux)
        assert json.loads(jl.traiter(ligne(r), etat))['action'] == 'accept'
    assert len(lignes_journal(dossiers)) == 4


def test_plugin_latence_chemin_rapide(dossiers):
    if os.environ.get('PARESIA_TESTS_SANS_CHRONO') == '1':
        pytest.skip('chronométrage désactivé')
    etat = etat_de(dossiers)
    entrees = [ligne(requete(kind=20001)) for _ in range(5000)]
    debut = time.perf_counter()
    for e in entrees:
        jl.traiter(e, etat)
    moyenne = (time.perf_counter() - debut) / len(entrees)
    assert moyenne < 0.001
    assert list(dossiers[0].iterdir()) == []


@pytest.mark.parametrize('kind', [1, 20001, 22242, 20000])
def test_plugin_banni_refuse_tous_kinds(dossiers, kind):
    banni = hexa(64)
    dossiers[1].write_text(banni + '\n')
    r = requete(kind=kind, pubkey=banni)
    p = lancer(dossiers, ligne(r))
    assert reponse(p.stdout) == [{'id': r['event']['id'], 'action': 'reject',
                                  'msg': 'blocked: auteur banni de ce relais'}]
    assert lignes_journal(dossiers) == []


def test_plugin_liste_noire_rechargee(dossiers):
    etat = etat_de(dossiers)
    cle = hexa(64)
    assert json.loads(jl.traiter(ligne(requete(kind=20001, pubkey=cle)), etat))['action'] == 'accept'
    dossiers[1].write_text(cle + '\n')
    assert json.loads(jl.traiter(ligne(requete(kind=20001, pubkey=cle)), etat))['action'] == 'reject'
    dossiers[1].write_text('')
    assert json.loads(jl.traiter(ligne(requete(kind=20001, pubkey=cle)), etat))['action'] == 'accept'


def test_plugin_liste_noire_absente_ou_invalide(dossiers, capfd):
    cle = hexa(64)
    etat = etat_de(dossiers)
    assert json.loads(jl.traiter(ligne(requete(pubkey=cle)), etat))['action'] == 'accept'
    dossiers[1].write_text('%s\n%s\nzz\n#%s\n' % (cle.upper(), cle[:63], cle))
    assert json.loads(jl.traiter(ligne(requete(pubkey=cle)), etat))['action'] == 'accept'
    assert 'ECHEC_LISTE_NOIRE lignes invalides 3' in capfd.readouterr().err
    dossiers[1].write_text(cle + '\n')
    if os.geteuid() != 0:
        dossiers[1].chmod(0)
        etat2 = etat_de(dossiers)
        assert json.loads(jl.traiter(ligne(requete(pubkey=cle)), etat2))['action'] == 'accept'
        assert 'ECHEC_LISTE_NOIRE lecture impossible' in capfd.readouterr().err
        dossiers[1].chmod(0o600)


def test_plugin_une_reponse_par_requete_sans_blocage(dossiers):
    p = subprocess.Popen([sys.executable, str(MODULE)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, env=env_de(dossiers))
    try:
        for kind in (1, 20001, 1059):
            r = requete(kind=kind)
            p.stdin.write(ligne(r))
            p.stdin.flush()
            lu = []

            t = threading.Thread(target=lambda: lu.append(p.stdout.readline()))
            t.start()
            t.join(5)
            assert lu, 'aucune réponse avant l\'envoi suivant'
            assert json.loads(lu[0]) == {'id': r['event']['id'], 'action': 'accept'}
    finally:
        p.stdin.close()
        p.wait(timeout=10)
        p.stdout.close()
        p.stderr.close()
    assert p.returncode == 0


def test_plugin_entree_illisible(dossiers):
    r = requete()
    p = lancer(dossiers, b'pas du json\n' + b'{"event":{"id":3}}\n' + ligne(r))
    assert b'ECHEC_JOURNAL' in p.stderr
    assert reponse(p.stdout) == [{'id': r['event']['id'], 'action': 'accept'}]


def test_plugin_champ_inutilisable_accepte(dossiers):
    r = requete()
    del r['receivedAt']
    p = lancer(dossiers, ligne(r))
    assert reponse(p.stdout) == [{'id': r['event']['id'], 'action': 'accept'}]
    assert b'ECHEC_JOURNAL' in p.stderr
    assert lignes_journal(dossiers) == []


def test_plugin_eof_sortie_propre(dossiers):
    p = lancer(dossiers, b'')
    assert p.returncode == 0 and p.stdout == b''


def test_plugin_echec_ecriture_accepte(dossiers, tmp_path):
    env = env_de(dossiers)
    env['JOURNAL_DIR'] = str(tmp_path / 'absent')
    r = requete()
    p = subprocess.run([sys.executable, str(MODULE)], input=ligne(r), capture_output=True, env=env, timeout=30)
    assert reponse(p.stdout) == [{'id': r['event']['id'], 'action': 'accept'}]
    assert b'ECHEC_JOURNAL ecriture impossible dans' in p.stderr
    assert r['event']['id'].encode() in p.stderr


@pytest.mark.parametrize('umask', [0o022, 0o077])
def test_plugin_fichier_du_jour_utc(dossiers, tmp_path, umask):
    journal = tmp_path / ('journal-%03o' % umask)
    journal.mkdir()
    d = (journal, dossiers[1])
    # L'umask est fixé dans le fils seulement ; celui du processus de test n'est pas modifié.
    fixer = lambda m=umask: os.umask(m)
    for _ in range(2):
        p = lancer(d, ligne(requete()), preexec_fn=fixer)
        assert p.returncode == 0
    jour = time.strftime('%Y-%m-%d', time.gmtime())
    f = journal / ('journal-%s.jsonl' % jour)
    assert [x.name for x in journal.iterdir()] == [f.name]
    assert len(f.read_text().splitlines()) == 2
    assert stat.S_IMODE(f.stat().st_mode) == 0o640


def test_plugin_fichier_du_jour_vide_preexistant_garde_son_mode(dossiers):
    jour = time.strftime('%Y-%m-%d', time.gmtime())
    f = dossiers[0] / ('journal-%s.jsonl' % jour)
    f.write_text('')
    f.chmod(0o600)
    p = lancer(dossiers, ligne(requete()), preexec_fn=lambda: os.umask(0o022))
    assert p.returncode == 0
    assert len(f.read_text().splitlines()) == 1
    assert stat.S_IMODE(f.stat().st_mode) == 0o600


def test_plugin_lien_symbolique_refuse(dossiers):
    jour = time.strftime('%Y-%m-%d', time.gmtime())
    cible = dossiers[0].parent / 'cible'
    cible.write_text('')
    (dossiers[0] / ('journal-%s.jsonl' % jour)).symlink_to(cible)
    r = requete()
    p = lancer(dossiers, ligne(r))
    assert reponse(p.stdout) == [{'id': r['event']['id'], 'action': 'accept'}]
    assert b'ECHEC_JOURNAL' in p.stderr
    assert cible.read_text() == ''


def test_plugin_aucun_caractere_de_controle(dossiers):
    info = 'a\nb\x00c\x1b[31m\x7f\x85 d'
    p = lancer(dossiers, ligne(requete(info=info)))
    assert p.returncode == 0
    brut = next(dossiers[0].glob('journal-*.jsonl')).read_bytes().decode('utf-8')
    assert brut.count('\n') == 1 and brut.endswith('\n')
    assert not any(ord(c) < 32 or 0x7f <= ord(c) <= 0x9f or c in '  ' for c in brut[:-1])
    assert json.loads(brut)['connexion'] == info


def test_plugin_echec_ecriture_stderr_sans_controle(dossiers, tmp_path):
    env = env_de(dossiers)
    env['JOURNAL_DIR'] = str(tmp_path / 'absent')
    p = subprocess.run([sys.executable, str(MODULE)], input=ligne(requete(info='x\ny\x1bz')),
                       capture_output=True, env=env, timeout=30)
    assert p.stderr.count(b'\n') == 1 and b'\x1b' not in p.stderr


def test_plugin_substitution_isolee_garde_la_ligne(dossiers):
    r = requete(kind=5, tags=[['e', hexa(63) + '\ud800']])
    brut = ligne(r)
    assert b'\\ud800' in brut
    p = lancer(dossiers, brut)
    assert reponse(p.stdout) == [{'id': r['event']['id'], 'action': 'accept'}]
    assert len(lignes_journal(dossiers)) == 1
    assert b'ECHEC_JOURNAL' not in p.stderr
    assert b'\\ud800' in next(dossiers[0].glob('journal-*.jsonl')).read_bytes()


def test_plugin_liste_noire_crlf_et_espaces(dossiers):
    banni = hexa(64)
    dossiers[1].write_bytes(('\r\n' + banni + ' \t\r\n\r\n' + hexa(64) + '\r\n').encode())
    r = requete(kind=1, pubkey=banni)
    p = lancer(dossiers, ligne(r))
    assert reponse(p.stdout) == [{'id': r['event']['id'], 'action': 'reject',
                                  'msg': 'blocked: auteur banni de ce relais'}]
    assert b'ECHEC_LISTE_NOIRE' not in p.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason='root ignore les droits')
def test_plugin_journal_en_lecture_seule(dossiers):
    dossiers[0].chmod(0o500)
    try:
        r = requete()
        p = lancer(dossiers, ligne(r))
    finally:
        dossiers[0].chmod(0o700)
    assert reponse(p.stdout) == [{'id': r['event']['id'], 'action': 'accept'}]
    assert b'ECHEC_JOURNAL ecriture impossible dans' in p.stderr


def _action(etat, cle, kind=1):
    return json.loads(jl.traiter(ligne(requete(kind=kind, pubkey=cle)), etat))['action']


def _cassee(dossiers):
    """Remplace le fichier de la liste par un dossier : la lecture lève une OSError même sous root."""
    dossiers[1].unlink()
    dossiers[1].mkdir()


def _alertes(capfd, mot='lecture impossible'):
    return [x for x in capfd.readouterr().err.splitlines() if x.startswith('ECHEC_LISTE_NOIRE ' + mot)]


def test_plugin_liste_noire_erreur_transitoire_conserve_la_liste(dossiers, capfd):
    banni, autre = hexa(64), hexa(64)
    dossiers[1].write_text(banni + '\n')
    etat = etat_de(dossiers)
    assert _action(etat, banni) == 'reject'
    _cassee(dossiers)
    assert _action(etat, banni) == 'reject'
    assert _action(etat, autre) == 'accept'
    assert len(_alertes(capfd)) == 1


def test_plugin_liste_noire_supprimee_apres_lecture(dossiers, capfd):
    banni = hexa(64)
    dossiers[1].write_text(banni + '\n')
    etat = etat_de(dossiers)
    assert _action(etat, banni) == 'reject'
    dossiers[1].unlink()
    assert _action(etat, banni) == 'reject'
    alertes = _alertes(capfd)
    assert len(alertes) == 1 and alertes[0].endswith(' : ENOENT')


def test_plugin_liste_noire_retablie_remplace(dossiers, capfd):
    ancien, nouveau = hexa(64), hexa(64)
    dossiers[1].write_text(ancien + '\n')
    etat = etat_de(dossiers)
    assert _action(etat, ancien) == 'reject'
    _cassee(dossiers)
    assert _action(etat, ancien) == 'reject'
    dossiers[1].rmdir()
    dossiers[1].write_text(nouveau + '\n')
    assert _action(etat, ancien) == 'accept'
    assert _action(etat, nouveau) == 'reject'
    dossiers[1].write_text('')
    assert _action(etat, nouveau) == 'accept'
    capfd.readouterr()


def test_plugin_liste_noire_sans_liste_connue(dossiers, capfd):
    cle = hexa(64)
    etat = etat_de(dossiers)
    assert _action(etat, cle) == 'accept'
    assert _alertes(capfd) == []
    dossiers[1].mkdir()
    assert _action(etat, cle) == 'accept'
    assert len(_alertes(capfd)) == 1


def test_plugin_liste_noire_alerte_une_fois_par_episode(dossiers, capfd):
    cle = hexa(64)
    dossiers[1].write_text(cle + '\n')
    etat = etat_de(dossiers)
    assert _action(etat, cle) == 'reject'
    _cassee(dossiers)
    for _ in range(1000):
        assert _action(etat, cle) == 'reject'
    assert len(_alertes(capfd)) == 1
    dossiers[1].rmdir()
    dossiers[1].write_text(cle + '\n')
    assert _action(etat, cle) == 'reject'
    _cassee(dossiers)
    assert _action(etat, cle) == 'reject'
    assert len(_alertes(capfd)) == 1


def test_plugin_liste_noire_erreur_simulee_eio(dossiers, capfd, monkeypatch):
    cle = hexa(64)
    dossiers[1].write_text(cle + '\n')
    etat = etat_de(dossiers)
    assert _action(etat, cle) == 'reject'
    reel = os.stat

    def stat_en_echec(chemin, *a, **k):
        if str(chemin) == str(dossiers[1]):
            raise OSError(errno.EIO, 'simulee')
        return reel(chemin, *a, **k)

    monkeypatch.setattr(os, 'stat', stat_en_echec)
    assert _action(etat, cle) == 'reject'
    alertes = _alertes(capfd)
    assert len(alertes) == 1 and alertes[0].endswith(' : EIO')


def test_plugin_liste_noire_lignes_invalides_alertees(dossiers, capfd):
    a, b = hexa(64), hexa(64)
    dossiers[1].write_text('%s\n\n%s\nINVALIDE-texte\n%s\n# commentaire\n%s\n' % (a, hexa(63), b, a.upper()))
    etat = etat_de(dossiers)
    assert _action(etat, a) == 'reject'
    assert _action(etat, b) == 'reject'
    assert _action(etat, b) == 'reject'
    sortie = capfd.readouterr().err
    alertes = [x for x in sortie.splitlines() if x.startswith('ECHEC_LISTE_NOIRE lignes invalides')]
    assert alertes == ['ECHEC_LISTE_NOIRE lignes invalides 3 : 3 4 7']
    assert 'INVALIDE' not in sortie and a.upper() not in sortie and 'commentaire' not in sortie


def test_plugin_liste_noire_lignes_invalides_dix_numeros(dossiers, capfd):
    dossiers[1].write_text(''.join('x%d\n' % i for i in range(15)))
    etat = etat_de(dossiers)
    assert _action(etat, hexa(64)) == 'accept'
    assert _alertes(capfd, 'lignes invalides') == ['ECHEC_LISTE_NOIRE lignes invalides 15 : 1 2 3 4 5 6 7 8 9 10']


def test_plugin_liste_noire_un_seul_stat_pendant_erreur(dossiers, monkeypatch, capfd):
    cle = hexa(64)
    dossiers[1].write_text(cle + '\n')
    etat = etat_de(dossiers)
    appels = []
    reel = os.stat
    monkeypatch.setattr(os, 'stat', lambda *a, **k: appels.append(a) or reel(*a, **k))
    for etape in ('lue', 'cassee', 'cassee', 'retablie'):
        if etape == 'cassee' and dossiers[1].is_file():
            _cassee(dossiers)
        if etape == 'retablie':
            dossiers[1].rmdir()
            dossiers[1].write_text(cle + '\n')
        appels.clear()
        jl.traiter(ligne(requete()), etat)
        assert len(appels) == 1
    capfd.readouterr()
