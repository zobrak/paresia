# Régressions de sécurité ; dépendances : pytest et bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha  2026-11-05  Configuration en couches (T015) : sections [composant.domaine], exemple paresia.conf.
#   3.0.0-alpha  2026-11-05  Corrections du cycle de revue 1.
import io
import json
import os
import secrets
import socket
import stat
import struct
from types import SimpleNamespace

import pytest

from server.commun import jumeaux
from server.commun.client import Connexion, PairIndisponible
from server.commun.config import lire, Option, ErreurConfiguration
from server.commun.journal import Journal
from server.commun.serveur import Serveur, ContexteConnexion
from server.commun.texte import filtrer


def creer_serveur(tmp_path, **options):
    return Serveur(str(tmp_path / 's'), {os.getuid()}, jumeaux.ACTIONS,
                   lambda q, c: jumeaux.reponse(q['id']), gid=os.getgid(), **options)


@pytest.mark.parametrize('limite', [0, -1, True, 16 * 1024 * 1024 + 1, 10**100])
def test_plafond_ligne(limite):
    with pytest.raises(ValueError, match='invalid_max_line'):
        jumeaux.lire_ligne(io.BytesIO(), limite)


@pytest.mark.parametrize('delai', [True, 0, -1, 3600.1, float('inf'), float('nan'), 10**1000])
def test_plafond_delai(delai, tmp_path):
    with pytest.raises(ValueError, match='invalid_timeout'):
        Connexion('inutilise', delai)
    with pytest.raises(ValueError, match='invalid_timeout'):
        creer_serveur(tmp_path, delai=delai)


@pytest.mark.parametrize('limite', [0, -1, True, 1025, 10**1000])
def test_plafond_connexions(limite, tmp_path):
    with pytest.raises(ValueError, match='invalid_connection_limit'):
        creer_serveur(tmp_path, max_connexions=limite)


@pytest.mark.parametrize('type_option,valeur', [('limite', str(16 * 1024 * 1024 + 1)),
                                               ('duree', '3601'), ('duree', '1e300')])
def test_plafonds_config(tmp_path, type_option, valeur):
    fichier = tmp_path / 'conf.ini'
    fichier.write_text('[test.transport]\nvaleur=' + valeur + '\n')
    fichier.chmod(0o600)
    with pytest.raises(ErreurConfiguration, match='config_invalid:transport:valeur'):
        lire('test', {('transport', 'valeur'): Option(type_option)},
             argv=['--config', str(fichier)], environ={})


@pytest.mark.parametrize('caractere', ['\x00', '\u200d', '\u2028', '\u2029', '\ud800', '\ue000'])
def test_categories_filtrees(caractere):
    assert filtrer('a' + caractere + 'b') == 'a\ufffdb'
    flux = io.StringIO()
    Journal('test', flux=flux).ecrire('info', 'test_event', texte=caractere)
    assert json.loads(flux.getvalue())['texte'] == '\ufffd'


@pytest.mark.parametrize('cle', ['privkey', 'seed', 'mnemonic', 'bearer', 'nsec'])
def test_masquage_supplementaire(cle):
    jetable = secrets.token_hex(32)
    flux = io.StringIO()
    Journal('test', flux=flux).ecrire('info', 'test_event', imbrique=[{cle: jetable}])
    assert jetable not in flux.getvalue()
    assert json.loads(flux.getvalue())['imbrique'][0][cle] == '[REDACTED]'


@pytest.mark.parametrize('mode', [0o620, 0o602, 0o666])
def test_ini_permissions(tmp_path, mode):
    fichier = tmp_path / 'conf.ini'
    fichier.write_text('')
    fichier.chmod(mode)
    with pytest.raises(ErreurConfiguration, match='config_unsafe_permissions'):
        lire('test', {}, argv=['--config', str(fichier)], environ={})


def test_ini_proprietaire(tmp_path, monkeypatch):
    fichier = tmp_path / 'conf.ini'
    fichier.write_text('')
    fichier.chmod(0o600)
    with monkeypatch.context() as contexte:
        contexte.setattr(os, 'fstat', lambda fd: SimpleNamespace(
            st_mode=stat.S_IFREG | 0o600, st_uid=os.geteuid() + 1))
        with pytest.raises(ErreurConfiguration, match='config_unsafe_permissions'):
            lire('test', {}, argv=['--config', str(fichier)], environ={})


def test_ini_lien_symbolique(tmp_path):
    fichier = tmp_path / 'conf.ini'
    fichier.write_text('')
    fichier.chmod(0o600)
    lien = tmp_path / 'lien.ini'
    lien.symlink_to(fichier)
    with pytest.raises(ErreurConfiguration, match='config_unreadable'):
        lire('test', {}, argv=['--config', str(lien)], environ={})


class PairMemoire:
    def __init__(self, entree=b''):
        self.entree = io.BytesIO(entree)
        self.sortie = bytearray()
        self.fermee = False

    def settimeout(self, delai):
        self.delai = delai

    def getsockopt(self, *args):
        return struct.pack('3i', os.getpid(), os.getuid(), os.getgid())

    def connect(self, chemin):
        pass

    def recv_into(self, destination):
        return self.entree.readinto(destination)

    def sendall(self, contenu):
        self.sortie.extend(contenu)

    def close(self):
        self.fermee = True


def requete():
    return {'proto': 'jumeaux/1', 'id': '1234567890abcdef', 'session': 0,
            'action': 'presence/session/ping', 'params': {}}


def test_uid_serveur_avant_envoi(monkeypatch):
    pair = PairMemoire()
    monkeypatch.setattr(socket, 'socket', lambda *a: pair)
    with Connexion('inutilise', uid_serveur=os.getuid() + 1) as client:
        with pytest.raises(PairIndisponible, match='^peer_unavailable$'):
            client.appeler(requete())
    assert pair.fermee
    assert not pair.sortie


def test_overflow_socket(monkeypatch):
    pair = PairMemoire()
    def deborder(delai):
        raise OverflowError()
    pair.settimeout = deborder
    monkeypatch.setattr(socket, 'socket', lambda *a: pair)
    with Connexion('inutilise') as client:
        with pytest.raises(PairIndisponible, match='^peer_unavailable$'):
            client.appeler(requete())
    assert pair.fermee


def test_echeance_totale_serveur(tmp_path, monkeypatch):
    horloge = [0.0]
    monkeypatch.setattr(jumeaux.time, 'monotonic', lambda: horloge[0])
    pair = PairMemoire(jumeaux.encoder(requete()))
    lecture = pair.recv_into
    def lent(destination):
        horloge[0] += 0.4
        return lecture(destination)
    pair.recv_into = lent
    serveur = creer_serveur(tmp_path, delai=1, journal=Journal('test', flux=io.StringIO()))
    serveur._servir(pair, ContexteConnexion(os.getpid(), os.getuid(), os.getgid()))
    assert pair.fermee
    assert not pair.sortie
    assert pair.entree.tell() == 3


def test_echeance_totale_client(monkeypatch):
    horloge = [0.0]
    monkeypatch.setattr(jumeaux.time, 'monotonic', lambda: horloge[0])
    pair = PairMemoire(jumeaux.encoder(jumeaux.reponse(requete()['id'])))
    lecture = pair.recv_into
    def lent(destination):
        horloge[0] += 0.4
        return lecture(destination)
    pair.recv_into = lent
    monkeypatch.setattr(socket, 'socket', lambda *a: pair)
    with Connexion('inutilise', delai=1) as client:
        with pytest.raises(PairIndisponible, match='^peer_unavailable$'):
            client.appeler(requete())
    assert pair.fermee
    assert pair.entree.tell() == 3


def test_echec_demarrage_fil_continue(tmp_path, monkeypatch):
    from server.commun import serveur as module
    flux = io.StringIO()
    serveur = creer_serveur(tmp_path, journal=Journal('test', flux=flux))
    pairs = [PairMemoire(), PairMemoire()]
    attente = iter(pairs)
    class Ecoute:
        def accept(self):
            try:
                return next(attente), None
            except StopIteration:
                raise OSError()
    serveur._socket = Ecoute()
    demarres = []
    class Fil:
        def __init__(self, **kwargs):
            self.pair = kwargs['args'][0]
        def start(self):
            demarres.append(self.pair)
            if len(demarres) == 1:
                raise RuntimeError('indisponible')
    monkeypatch.setattr(module.threading, 'Thread', Fil)
    serveur._accepter()
    assert demarres == pairs
    assert pairs[0].fermee
    assert pairs[0] not in serveur._connexions
    assert len(serveur._connexions) == len(serveur._fils) == 1
    assert 'connection_start_failed' in flux.getvalue()


def test_plafond_connexions_applique(tmp_path):
    flux = io.StringIO()
    serveur = creer_serveur(tmp_path, max_connexions=1, journal=Journal('test', flux=flux))
    existante, nouvelle = PairMemoire(), PairMemoire()
    serveur._connexions.add(existante)
    class Ecoute:
        def accept(self):
            serveur._arret.set()
            return nouvelle, None
    serveur._socket = Ecoute()
    serveur._accepter()
    assert nouvelle.fermee
    assert not existante.fermee
    assert serveur._connexions == {existante}
    assert 'connection_limit' in flux.getvalue()


def test_requete_invalide_non_journalisee(tmp_path):
    marqueur = secrets.token_hex(24)
    objet = dict(requete(), inconnu=marqueur)
    pair = PairMemoire(jumeaux.encoder(objet) + jumeaux.encoder(requete()))
    flux = io.StringIO()
    serveur = creer_serveur(tmp_path, journal=Journal('test', flux=flux))
    serveur._servir(pair, ContexteConnexion(os.getpid(), os.getuid(), os.getgid()))
    assert marqueur not in flux.getvalue()
    assert 'inconnu' not in flux.getvalue()
    assert len(pair.sortie.splitlines()) == 2
    assert json.loads(pair.sortie.splitlines()[0])['error']['code'] == 'bad_request'


def test_bornes_superieures_acceptees(tmp_path):
    jumeaux.verifier_limite(16 * 1024 * 1024)
    jumeaux.verifier_delai(3600)
    serveur = creer_serveur(tmp_path, max_connexions=1024, delai=3600,
                            max_line=16 * 1024 * 1024)
    assert serveur.max_connexions == 1024
    fichier = tmp_path / 'conf.ini'
    fichier.write_text('[test.transport]\nlimite=16777216\ndelai=3600\n')
    fichier.chmod(0o600)
    resultat = lire('test', {('transport', 'limite'): Option('limite'),
                            ('transport', 'delai'): Option('duree')},
                    argv=['--config', str(fichier)], environ={})
    assert resultat['transport'] == {'limite': 16777216, 'delai': 3600}
