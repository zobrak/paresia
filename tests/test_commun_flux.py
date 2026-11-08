# SPDX-License-Identifier: AGPL-3.0-or-later
# Suivi des versions
#   3.0.0-alpha.29  2026-11-06  Flux sur le fil, refus et fermeture (T027).
import gc
import io
import json
import os
import socket
import threading
import time
from dataclasses import FrozenInstanceError

import pytest

from server.commun.client import Connexion, PairIndisponible
from server.commun.journal import Journal
from server.commun.jumeaux import ACTIONS, Flux, ErreurProtocole, encoder, reponse
from server.commun.serveur import Serveur, ContexteConnexion
from test_jumeaux_transport import SocketMemoire, requete, dossier_socket

ID = requete()['id']


class Elements:
    def __init__(self, elements):
        self.elements = iter(elements)
        self.fermetures = 0
        self.lectures = 0

    def __iter__(self):
        return self

    def __next__(self):
        self.lectures += 1
        return next(self.elements)

    def close(self):
        self.fermetures += 1


def servir(elements, *, identifiant=ID, sock=None, delai=1):
    sock = sock or SocketMemoire(encoder(requete()))
    journal = io.StringIO()
    flux = Flux(identifiant, elements)
    serveur = Serveur('transport-memoire', {os.getuid()}, ACTIONS,
                      lambda *_: flux, gid=os.getgid(), max_line=512, delai=delai,
                      journal=Journal('test', flux=journal))
    serveur._servir(sock, ContexteConnexion(os.getpid(), os.getuid(), os.getgid()))
    return [json.loads(x) for x in sock.sortie.splitlines()], journal.getvalue()


@pytest.fixture
def serveur_flux(dossier_socket):
    journal = io.StringIO()
    def traiter(q, _):
        if q['params'].get('ordinaire'):
            return reponse(q['id'])
        return Flux(q['id'], [reponse(q['id'], i, stream='line') for i in range(3)])
    with Serveur(str(dossier_socket / 's'), {os.getuid()}, ACTIONS, traiter,
                 gid=os.getgid(), journal=Journal('test', flux=journal)) as serveur:
        serveur.capture = journal
        yield serveur


def test_flux_nominal(serveur_flux):
    with Connexion(serveur_flux.chemin) as client:
        lignes = list(client.appeler_flux(requete()))
        assert [x.get('data') for x in lignes] == [0, 1, 2, None]
        assert all(x['id'] == ID for x in lignes)
        assert lignes[-1]['stream'] == 'end'


def test_flux_journal_fin():
    elements = Elements([reponse(ID, i, stream='line') for i in range(3)])
    lignes, journal = servir(elements)
    evenements = [json.loads(x) for x in journal.splitlines()]
    assert len(evenements) == 1
    assert evenements[0]['event'] == 'request_completed'
    assert evenements[0]['lines'] == 3 and evenements[0]['result'] == 'ok'
    assert 'data' not in journal and elements.fermetures == 1


def test_flux_fin_implicite():
    assert servir([])[0] == [reponse(ID, stream='end')]


@pytest.mark.parametrize('premier', [True, False])
def test_flux_erreur_finale(premier):
    avant = [] if premier else [reponse(ID, stream='line')]
    elements = Elements(avant + [reponse(ID, code='relay_light_red'), reponse(ID, stream='line')])
    lignes, journal = servir(elements)
    assert lignes == avant + [reponse(ID, code='relay_light_red')]
    assert elements.lectures == len(lignes) and elements.fermetures == 1
    assert json.loads(journal)['result'] == 'error'


def test_flux_exception_traitement():
    def produire():
        yield reponse(ID, stream='line')
        raise ValueError('diagnostic-prive')
    lignes, journal = servir(produire())
    assert lignes[-1] == reponse(ID, code='internal_error')
    assert 'stream_failed' in journal
    assert 'diagnostic-prive' not in journal + json.dumps(lignes)


INVALIDES = [None, [], {'id': ID, 'ok': 1, 'stream': 'line'},
             reponse('f'*16, stream='line'), dict(reponse(ID, stream='line'), inconnu=1),
             reponse(ID), {'id': ID, 'ok': True, 'stream': 'autre'},
             reponse(ID, code='relay_light_red', stream='line'),
             reponse(ID, object(), stream='line'),
             {'id': ID, 'ok': False, 'error': {'code': 'inconnu'}},
             dict(reponse(ID, code='relay_light_red'), data=1)]


@pytest.mark.parametrize('element', INVALIDES)
def test_flux_element_invalide(element):
    elements = Elements([element, reponse(ID, stream='line')])
    assert servir(elements)[0] == [reponse(ID, code='internal_error')]
    assert elements.lectures == 1 and elements.fermetures == 1


def test_flux_mauvais_id():
    elements = Elements([])
    assert servir(elements, identifiant='f'*16)[0] == [reponse(ID, code='internal_error')]
    assert elements.fermetures == 1 and elements.lectures == 0


def test_flux_ligne_trop_longue():
    assert servir([reponse(ID, 'x'*512, stream='line')])[0] == [reponse(ID, code='internal_error')]


@pytest.mark.parametrize('fin', [reponse(ID, stream='end'), reponse(ID, code='relay_light_red')])
def test_flux_close_une_fois(fin):
    elements = Elements([fin, reponse(ID, stream='line')])
    assert servir(elements)[0] == [fin]
    assert elements.fermetures == 1 and elements.lectures == 1


def test_flux_client_deconnecte():
    class Coupe(SocketMemoire):
        def sendall(self, contenu):
            raise BrokenPipeError()
    elements = Elements([reponse(ID, stream='line')])
    lignes, journal = servir(elements, sock=Coupe(encoder(requete())))
    assert not lignes and elements.fermetures == 1
    assert 'stream_aborted' in journal
    assert json.loads(journal.splitlines()[-1])['result'] == 'error'
    assert servir([])[0][-1]['stream'] == 'end'


def test_flux_depassement_ecriture():
    class Depasse(SocketMemoire):
        def sendall(self, contenu):
            raise OverflowError()
    elements = Elements([reponse(ID, stream='line')])
    lignes, journal = servir(elements, sock=Depasse(encoder(requete())))
    assert not lignes and elements.fermetures == 1
    assert 'stream_aborted' in journal


def test_client_socket_fermee_concurremment(dossier_socket):
    connexion = Connexion(str(dossier_socket / 'absent'), 1)
    connexion._socket = object()
    connexion._rompue = False
    # Simule fermer() survenu entre le test de rupture et la lecture.
    class Verrou:
        def __enter__(self):
            connexion._socket = None
        def __exit__(self, *_):
            return False
    connexion._verrou = Verrou()
    with pytest.raises(PairIndisponible):
        connexion.appeler(requete())
    connexion._rompue = False
    with pytest.raises(PairIndisponible):
        connexion.appeler_flux(requete())


def test_flux_duree_non_bornee(serveur_flux):
    def produire(q):
        for _ in range(4):
            time.sleep(0.06)
            yield reponse(q['id'], stream='line')
    serveur_flux.delai = 0.15
    serveur_flux.traiter = lambda q, _: Flux(q['id'], produire(q))
    with Connexion(serveur_flux.chemin, 0.15) as client:
        assert len(list(client.appeler_flux(requete()))) == 5


def test_flux_connexions_independantes(serveur_flux):
    with Connexion(serveur_flux.chemin) as a, Connexion(serveur_flux.chemin) as b:
        fa, fb = a.appeler_flux(requete()), b.appeler_flux(requete(2))
        for la, lb in zip(fa, fb):
            assert la['id'] == ID and lb['id'] == requete(2)['id']


def test_flux_puis_requete(serveur_flux):
    with Connexion(serveur_flux.chemin) as client:
        list(client.appeler_flux(requete()))
        sock = client._socket
        assert client.appeler(requete(2, params={'ordinaire': True}))['ok']
        assert client._socket is sock


@pytest.mark.parametrize('element', [x for x in INVALIDES if not (isinstance(x, dict) and type(x.get('data')) is object)] + [b'{\n', b'x'*513+b'\n'])
def test_client_flux_lignes_invalides(monkeypatch, element):
    entree = element if isinstance(element, bytes) else encoder(element)
    sock = SocketMemoire(entree)
    monkeypatch.setattr(socket, 'socket', lambda *_: sock)
    client = Connexion('transport-memoire', max_line=512)
    with pytest.raises(ErreurProtocole):
        list(client.appeler_flux(requete()))
    assert sock.fermee and client.rompue


def test_client_flux_delai_ligne(serveur_flux):
    pret = threading.Event()
    def produire():
        pret.wait(2)
        yield reponse(ID, stream='end')
    serveur_flux.traiter = lambda *_: Flux(ID, produire())
    try:
        with Connexion(serveur_flux.chemin) as client:
            with pytest.raises(PairIndisponible):
                list(client.appeler_flux(requete(), delai_ligne=0.03))
            assert client.rompue
    finally:
        pret.set()


def test_client_flux_connexion_occupee(serveur_flux):
    with Connexion(serveur_flux.chemin) as client:
        flux = client.appeler_flux(requete())
        for appel in (client.appeler, client.appeler_flux):
            with pytest.raises(RuntimeError, match='^stream_open$'):
                appel(requete(2))
        flux.close()


@pytest.mark.parametrize('mode', ['avant', 'apres', 'gc', 'exit'])
def test_client_flux_fermeture_anticipee(serveur_flux, mode):
    client = Connexion(serveur_flux.chemin)
    flux = client.appeler_flux(requete())
    if mode == 'apres':
        next(flux)
    if mode == 'gc':
        del flux
        gc.collect()
    elif mode == 'exit':
        with pytest.raises(GeneratorExit):
            flux.throw(GeneratorExit)
    else:
        flux.close()
    assert client.rompue and client._socket is None
    with pytest.raises(PairIndisponible):
        client.appeler(requete())
    with Connexion(serveur_flux.chemin) as nouveau:
        assert len(list(nouveau.appeler_flux(requete()))) == 4


def test_client_flux_uid_serveur(serveur_flux):
    with Connexion(serveur_flux.chemin, uid_serveur=os.getuid()+1) as client:
        with pytest.raises(PairIndisponible):
            client.appeler_flux(requete())
        assert client.rompue


def test_flux_immuable_et_close():
    flux = Flux(ID, [])
    with pytest.raises(FrozenInstanceError):
        flux.identifiant = 'f'*16
    with pytest.raises(ValueError):
        Flux('invalide', [])
    class Ferme:
        def close(self):
            raise RuntimeError()
    Flux(ID, Ferme()).close()


def test_traitement_sans_flux_inchange(serveur_flux):
    with Connexion(serveur_flux.chemin) as client:
        assert client.appeler(requete(params={'ordinaire': True})) == reponse(ID)
    evenement = json.loads(serveur_flux.capture.getvalue())
    assert evenement['event'] == 'request_completed' and 'lines' not in evenement


@pytest.mark.parametrize('mode', ['avant', 'apres', 'gc', 'exit'])
def test_client_flux_cycle_en_memoire(monkeypatch, mode):
    def creer(*_):
        return SocketMemoire(encoder(reponse(ID, stream='line')) +
                             encoder(reponse(ID, stream='end')))
    monkeypatch.setattr(socket, 'socket', creer)
    client = Connexion('transport-memoire')
    flux = client.appeler_flux(requete())
    sock = client._socket
    assert sock.sortie == encoder(requete())
    for appel in (client.appeler, client.appeler_flux):
        with pytest.raises(RuntimeError, match='^stream_open$'):
            appel(requete())
    if mode == 'apres':
        assert next(flux)['stream'] == 'line'
    if mode == 'gc':
        del flux
        gc.collect()
    elif mode == 'exit':
        with pytest.raises(GeneratorExit):
            flux.throw(GeneratorExit)
    else:
        flux.close()
    assert client.rompue and sock.fermee
    for appel in (client.appeler, client.appeler_flux):
        with pytest.raises(PairIndisponible):
            appel(requete())
    with Connexion('transport-memoire') as nouveau:
        assert len(list(nouveau.appeler_flux(requete()))) == 2


def test_client_flux_fin_libere_sans_lecture_supplementaire(monkeypatch):
    sock = SocketMemoire(encoder(reponse(ID, stream='end')) + encoder(reponse(requete(2)['id'])))
    monkeypatch.setattr(socket, 'socket', lambda *_: sock)
    with Connexion('transport-memoire') as client:
        flux = client.appeler_flux(requete())
        assert next(flux)['stream'] == 'end'
        assert client.appeler(requete(2)) == reponse(requete(2)['id'])
        flux.close()
        assert not client.rompue


@pytest.mark.parametrize('cause', ['delai', 'coupure'])
def test_client_flux_rupture_en_memoire(monkeypatch, cause):
    class Interrompu(SocketMemoire):
        def recv_into(self, destination):
            if cause == 'delai':
                raise TimeoutError()
            return 0
    sock = Interrompu(b'')
    monkeypatch.setattr(socket, 'socket', lambda *_: sock)
    client = Connexion('transport-memoire')
    with pytest.raises(PairIndisponible):
        list(client.appeler_flux(requete()))
    assert client.rompue and sock.fermee


def test_client_flux_uid_avant_envoi(monkeypatch):
    import struct
    class PairIncorrect(SocketMemoire):
        def getsockopt(self, *_):
            return struct.pack('3i', os.getpid(), os.getuid()+1, os.getgid())
    sock = PairIncorrect(b'')
    monkeypatch.setattr(socket, 'socket', lambda *_: sock)
    client = Connexion('transport-memoire', uid_serveur=os.getuid())
    with pytest.raises(PairIndisponible):
        client.appeler_flux(requete())
    assert not sock.sortie and sock.fermee


def test_flux_echeances_et_journal_apres_envoi(monkeypatch):
    horloge = [0]
    monkeypatch.setattr(time, 'monotonic', lambda: horloge[0])
    journal = io.StringIO()
    class Controle(SocketMemoire):
        def sendall(self, contenu):
            assert 'request_completed' not in journal.getvalue()
            super().sendall(contenu)
    def produire():
        for _ in range(3):
            horloge[0] += 2
            yield reponse(ID, stream='line')
    sock = Controle(encoder(requete()))
    serveur = Serveur('transport-memoire', {os.getuid()}, ACTIONS,
                      lambda *_: Flux(ID, produire()), gid=os.getgid(), delai=1,
                      journal=Journal('test', flux=journal))
    serveur._servir(sock, ContexteConnexion(os.getpid(), os.getuid(), os.getgid()))
    assert len(sock.sortie.splitlines()) == 4
    assert json.loads(journal.getvalue())['lines'] == 3


def test_flux_exception_initialisation_iterable():
    class Impossible(Elements):
        def __iter__(self):
            raise ValueError('diagnostic-prive')
    elements = Impossible([])
    lignes, journal = servir(elements)
    assert lignes == [reponse(ID, code='internal_error')]
    assert elements.fermetures == 1 and 'stream_failed' in journal
    assert 'diagnostic-prive' not in journal


def test_client_echeance_renouvelee_par_ligne(monkeypatch):
    horloge = [0]
    monkeypatch.setattr(time, 'monotonic', lambda: horloge[0])
    sock = SocketMemoire(b''.join(encoder(reponse(ID, stream=fin))
                                for fin in ('line', 'line', 'end')))
    monkeypatch.setattr(socket, 'socket', lambda *_: sock)
    with Connexion('transport-memoire', delai=1) as client:
        flux = client.appeler_flux(requete(), delai_ligne=0.5)
        for fin in ('line', 'line', 'end'):
            horloge[0] += 2
            assert next(flux)['stream'] == fin
        assert list(flux) == []


def test_client_second_appel_pendant_lecture(monkeypatch):
    entre, liberer = threading.Event(), threading.Event()
    class Lent(SocketMemoire):
        def recv_into(self, destination):
            entre.set()
            assert liberer.wait(2)
            return super().recv_into(destination)
    sock = Lent(encoder(reponse(ID, stream='end')))
    monkeypatch.setattr(socket, 'socket', lambda *_: sock)
    with Connexion('transport-memoire') as client:
        flux = client.appeler_flux(requete())
        resultats = []
        fil = threading.Thread(target=lambda: resultats.append(next(flux)))
        fil.start()
        try:
            assert entre.wait(2)
            for appel in (client.appeler, client.appeler_flux):
                with pytest.raises(RuntimeError, match='^stream_open$'):
                    appel(requete(2))
        finally:
            liberer.set()
            fil.join(2)
        assert resultats == [reponse(ID, stream='end')]


@pytest.mark.parametrize('delai', [0, -1, True, float('nan'), 3601])
def test_client_delai_invalide(delai):
    with pytest.raises(ValueError):
        Connexion('transport-memoire').appeler_flux(requete(), delai_ligne=delai)


def test_client_requete_invalide_avant_envoi(monkeypatch):
    def interdit(*_):
        pytest.fail('transport ouvert avant validation')
    monkeypatch.setattr(socket, 'socket', interdit)
    client = Connexion('transport-memoire', max_line=512)
    for q in (requete(id='invalide'), requete(params={'texte': 'x'*512})):
        with pytest.raises(ErreurProtocole):
            client.appeler_flux(q)
    assert not client.rompue
