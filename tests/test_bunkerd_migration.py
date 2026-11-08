# SPDX-License-Identifier: AGPL-3.0-or-later
# Migration de bunker.json ; dépendances : bibliothèque standard et pytest.
# Suivi des versions
#   0.1.1  2026-11-07  Démarrage sous le socle : codes de sortie 65, configurer sans argument.
#   3.0.0-alpha.32  2026-11-06  T007 : migrations, refus, sauvegardes et ordre de démarrage.
import io
import json
import os
from pathlib import Path
import re
import secrets
import socket
import stat
import threading

import pytest

from bunkerd_outils import banc
from server.bunkerd import __main__ as entree
from server.bunkerd import state
from server.bunkerd.ctl import lier_controle, traiter_connexion
from server.bunkerd.depot import Depot
from server.commun.journal import Journal


@pytest.fixture
def etat(tmp_path):
    depot = Depot(tmp_path)
    flux = io.StringIO()
    journal = Journal('bunkerd', flux=flux)
    return depot, Path(depot.state_file), journal, flux


def ancien(chemin, identites=None):
    if identites is None:
        identites = {'alpha': {'pubkey': secrets.token_hex(32), 'timeout': 900,
                              'extension': {'conserve': [1, True, 'texte']}}}
    chemin.write_text(json.dumps(identites, indent=2, sort_keys=True))
    return identites


def sauvegardes(chemin):
    return sorted(chemin.parent.glob(chemin.name + '.bak-*'))


def test_migration_nominale(etat):
    depot, chemin, journal, flux = etat
    identites = ancien(chemin)
    state.migrer(depot, journal)
    assert depot.load_state() == identites
    assert json.loads(chemin.read_bytes()) == {'format': 1, 'identities': identites}
    assert stat.S_IMODE(chemin.stat().st_mode) == 0o600
    evenement = json.loads(flux.getvalue())
    assert evenement['event'] == 'state_migrated'
    assert (evenement['source_format'], evenement['target_format']) == (0, 1)
    depot.save_state(identites)
    assert depot.load_state() == identites


def test_migration_noms_reserves(etat):
    depot, chemin, journal, _ = etat
    identites = ancien(chemin, {'format': {'timeout': 60}, 'identities': {}})
    state.migrer(depot, journal)
    assert depot.load_state() == identites


def test_migration_sauvegarde(etat):
    depot, chemin, journal, _ = etat
    ancien(chemin)
    original = chemin.read_bytes()
    state.migrer(depot, journal)
    copie, = sauvegardes(chemin)
    assert re.fullmatch(r'bunker.json.bak-format0-\d{8}T\d{6}Z', copie.name)
    assert copie.read_bytes() == original
    assert stat.S_IMODE(copie.stat().st_mode) == 0o600


def test_restauration(etat):
    depot, chemin, journal, _ = etat
    initial = ancien(chemin)
    state.migrer(depot, journal)
    # Le chargeur 1.9.0 voit l'enveloppe comme deux identités : incompatibilité assumée.
    charge_190 = json.loads(chemin.read_bytes())
    assert set(charge_190) == {'format', 'identities'}
    assert charge_190 != initial
    chemin.write_bytes(sauvegardes(chemin)[0].read_bytes())
    assert json.loads(chemin.read_bytes()) == initial == depot.load_state()


def test_sauvegardes_trois(etat, monkeypatch):
    depot, chemin, journal, _ = etat
    dates = ['20260101T000001Z', '20260101T000002Z', '20260101T000003Z', '20260101T000004Z']
    for date in dates:
        monkeypatch.setattr(state, '_horodatage', lambda: date)
        ancien(chemin)
        state.migrer(depot, journal)
    assert [p.name.rsplit('-', 1)[1] for p in sauvegardes(chemin)] == dates[1:]
    # Un recul d'horloge ne doit jamais supprimer la nouvelle sauvegarde.
    monkeypatch.setattr(state, '_horodatage', lambda: '20250101T000000Z')
    ancien(chemin)
    state.migrer(depot, journal)
    assert len(sauvegardes(chemin)) == 3
    assert any('20250101T000000Z' in p.name for p in sauvegardes(chemin))


def test_migration_idempotente(etat):
    depot, chemin, journal, flux = etat
    ancien(chemin)
    state.migrer(depot, journal)
    avant = [(p, p.stat(), p.read_bytes()) for p in chemin.parent.iterdir()]
    evenements = flux.getvalue()
    state.migrer(depot, journal)
    assert flux.getvalue() == evenements
    for fichier, infos, octets in avant:
        assert fichier.stat().st_mtime_ns == infos.st_mtime_ns
        assert fichier.stat().st_ino == infos.st_ino
        assert fichier.read_bytes() == octets


def test_state_absent(etat):
    depot, chemin, journal, flux = etat
    state.migrer(depot, journal)
    assert depot.load_state() == {}
    assert not list(chemin.parent.iterdir())
    assert flux.getvalue() == ''


@pytest.mark.parametrize('octets', [
    b'{', b'[]', b'null', b'false', b'\xff',
    b'{"format":2,"identities":{}}', b'{"format":true,"identities":{}}',
    b'{"format":1.0,"identities":{}}', b'{"format":-1}', b'{"format":0}',
    b'{"format":1,"identities":[]}', b'{"format":1}',
    b'{"alpha":[]}', b'{"alpha":{"pubkey":null}}',
    b'{"alpha":{"pubkey":"AB"}}', b'{"alpha":{"timeout":true}}',
    b'{"alpha":{"timeout":59}}', b'{"alpha":{"timeout":86401}}',
    b'{"alpha":{"timeout":60.0}}', b'{"alpha":{"timeout":"900"}}',
    b'{"alpha":{"x":NaN}}', b'{"alpha":{},"alpha":{}}',
    b'{"alpha\\u001b":{}}', b'{"../alpha":{}}',
])
def test_state_refuse(etat, octets):
    depot, chemin, journal, flux = etat
    chemin.write_bytes(octets)
    avant = chemin.stat()
    with pytest.raises(state.ErreurEtat):
        state.migrer(depot, journal)
    with pytest.raises(state.ErreurEtat):
        depot.load_state()
    assert chemin.read_bytes() == octets
    assert chemin.stat().st_mtime_ns == avant.st_mtime_ns
    assert list(chemin.parent.iterdir()) == [chemin]
    assert flux.getvalue() == ''


@pytest.mark.parametrize('delai', [60, 86400])
def test_state_bornes(etat, delai):
    depot, chemin, journal, _ = etat
    initial = ancien(chemin, {'alpha': {'timeout': delai}})
    state.migrer(depot, journal)
    assert depot.load_state() == initial


@pytest.mark.parametrize('obstacle', ['collision', 'lien', 'permission', 'verification'])
def test_sauvegarde_impossible(etat, monkeypatch, obstacle):
    depot, chemin, journal, _ = etat
    ancien(chemin)
    original = chemin.read_bytes()
    monkeypatch.setattr(state, '_horodatage', lambda: '20260101T000000Z')
    copie = Path(str(chemin) + '.bak-format0-20260101T000000Z')
    if obstacle == 'collision':
        copie.write_bytes(b'conserver')
    elif obstacle == 'lien':
        copie.symlink_to(chemin)
    else:
        ouvrir = os.open

        def echouer(nom, options, *args):
            if str(nom) == str(copie):
                if obstacle == 'permission':
                    raise PermissionError()
                if not options & os.O_WRONLY:
                    copie.write_bytes(b'incomplet')
            return ouvrir(nom, options, *args)

        monkeypatch.setattr(os, 'open', echouer)
    with pytest.raises(state.ErreurEtat):
        state.migrer(depot, journal)
    assert chemin.read_bytes() == original
    if obstacle == 'collision':
        assert copie.read_bytes() == b'conserver'


def test_ecriture_atomique(etat, monkeypatch):
    depot, chemin, journal, _ = etat
    ancien(chemin)
    original = chemin.read_bytes()

    def interrompre(*_):
        raise OSError()

    monkeypatch.setattr(os, 'replace', interrompre)
    with pytest.raises(state.ErreurEtat):
        state.migrer(depot, journal)
    assert chemin.read_bytes() == original
    assert sauvegardes(chemin)[0].read_bytes() == original
    assert not Path(str(chemin) + '.tmp').exists()


def test_migration_relais(etat):
    depot, chemin, journal, flux = etat
    ancien(chemin)
    Path(depot.profile_dir).mkdir(parents=True)
    profil = Path(depot.profile_path('alpha'))
    contenu = json.dumps({'relays': ['wss://relais.example', 'ws://relais.example',
                                    'ws://relais.onion', 'ftp://relais.example']}).encode()
    profil.write_bytes(contenu)
    state.migrer(depot, journal)
    assert profil.read_bytes() == contenu
    lignes = [json.loads(ligne) for ligne in flux.getvalue().splitlines()]
    alertes = [ligne for ligne in lignes if ligne['event'] == 'relay_nonconforming']
    assert [(e['identity'], e['relay_index']) for e in alertes] == [('alpha', 1), ('alpha', 3)]
    assert 'relais.example' not in flux.getvalue()


def test_state_messages_i18n(etat, monkeypatch, capsys):
    depot, chemin, _, _ = etat
    racine = Path(__file__).resolve().parents[1]
    fr = json.loads((racine / 'i18n/fr-FR.json').read_text())
    en = json.loads((racine / 'i18n/en-US.json').read_text())
    assert fr.keys() == en.keys()
    for code in ('state_unreadable', 'state_migration_failed'):
        assert code in fr
        assert state.message(code) == fr[code]
    chemin.write_bytes(b'{"alpha\\u001b[31m": {}}')
    monkeypatch.setattr(entree, 'configuration', lambda **_: {'etat': {'home': depot.home},
                                                        'outils': {'nak': 'inutilise'}})
    assert entree.main() == 65
    sorties = capsys.readouterr()
    assert sorties.err.strip() == fr['state_unreadable']
    assert '\x1b' not in sorties.out + sorties.err
    assert 'alpha' not in sorties.out + sorties.err
    assert json.loads(sorties.out.splitlines()[0])['cause'] == 'invalid_identity'
    assert not Path(depot.profile_dir).exists()
    monkeypatch.setattr(Path, 'read_text', lambda *_args, **_kw: (_ for _ in ()).throw(OSError()))
    assert state.message('state_unreadable') == 'state_unreadable'


@pytest.mark.skipif(os.getuid() != 0, reason='ctl.sock réservé à root')
def test_state_apres_migration(tmp_path):
    with banc(tmp_path) as b:
        b.profil('alpha')
        ancien(Path(b.depot.state_file), {'alpha': {'timeout': 1200}})
        with b.sup.lock:
            state.migrer(b.depot, b.journal)
        serveur = lier_controle(str(b.socks / 'ctl.sock'))

        def servir():
            connexion, _ = serveur.accept()
            traiter_connexion(b.ops, connexion)

        thread = threading.Thread(target=servir)
        thread.start()
        try:
            with socket.socket(socket.AF_UNIX) as client:
                client.settimeout(5)
                client.connect(str(b.socks / 'ctl.sock'))
                client.sendall(b'{"cmd":"list"}\n')
                reponse = json.loads(client.recv(65536))
            assert reponse['identities'][0]['timeout'] == 1200
        finally:
            serveur.close()
            thread.join(timeout=5)
        b.demarrer_admin()
        assert b.appeler('timeout', {'identity': 'alpha', 'minutes': 3})['ok']
        assert b.depot.load_state()['alpha']['timeout'] == 180
        assert json.loads(Path(b.depot.state_file).read_bytes())['format'] == 1


def test_state_avant_ecoute(tmp_path, monkeypatch, capsys):
    with banc(tmp_path) as b:
        chemin = Path(b.depot.state_file)
        chemin.write_bytes(b'[]')
        monkeypatch.setattr(entree, 'configuration', lambda **_: b.config)

        def interdit(*_args, **_kw):
            pytest.fail('écoute ou thread avant validation')

        monkeypatch.setattr(entree, 'lier_controle', interdit)
        monkeypatch.setattr(entree, 'demarrer_web', interdit)
        monkeypatch.setattr(entree, 'demarrer_administration', interdit)
        monkeypatch.setattr(threading.Thread, 'start', interdit)
        assert entree.main() == 65
        assert not list(b.socks.iterdir())
        assert chemin.read_bytes() == b'[]'
        assert not sauvegardes(chemin)
    capsys.readouterr()
