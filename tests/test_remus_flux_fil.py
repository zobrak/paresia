# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests de transmission des flux Remus ; dépendances : bibliothèque standard et pytest.
# Suivi des versions
#   3.0.0-alpha.32  2026-11-06  Critères de transmission et de fermeture de T035.
import io
import threading
import time

import pytest

from remus_outils import Enregistreur, Horloge, chemin, configuration, evenements, monter, requete
from server.commun.client import Connexion
from server.commun.jumeaux import Flux
from server.commun.journal import Journal
from server.remus import ErreurOperation, Remus


def fins(r):
    return [e for e in evenements(r.flux_journal) if e['event'] == 'operation_finished']


def attendre(predicat):
    fin = time.monotonic() + 5
    while not predicat():
        assert time.monotonic() < fin
        time.sleep(0.01)


def test_remus_flux_sur_le_fil():
    a = Enregistreur(flux=True)
    a.effet = lambda c: ({'n': n} for n in range(3))
    with monter(a, etats={1: ['green']}) as r, Connexion(chemin(r), 5) as client:
        q = requete()
        lignes = list(client.appeler_flux(q))
        assert lignes == [dict(id=q['id'], ok=True, stream='line', data={'n': n})
                          for n in range(3)] + [dict(id=q['id'], ok=True, stream='end')]
        attendre(lambda: len(fins(r)) == 1)
        assert fins(r)[0]['lines'] == 3 and fins(r)[0]['result'] == 'ok'
        assert r.flux_ouverts() == {} and r._en_cours == 0


@pytest.mark.parametrize('etat,code', [('red', 'relay_light_red'),
                                     ('closed', 'session_closed'),
                                     ('indisponible', 'peer_unavailable')])
def test_remus_flux_fil_raisons(etat, code):
    a = Enregistreur(flux=True)

    def produire(c):
        yield {'n': 1}
        assert c.arret.wait(5)
        yield {'n': 2}

    a.effet = produire
    with monter(a, etats={1: ['green']}) as r, Connexion(chemin(r), 5) as client:
        flux = client.appeler_flux(requete())
        assert next(flux)['data'] == {'n': 1}
        r.faux.etats[1] = [etat]
        r.verifier_flux()
        assert next(flux)['error']['code'] == code
        assert list(flux) == []
        attendre(lambda: len(fins(r)) == 1)
        assert fins(r)[0]['result'] == code
        # Le démon répond encore à une action simple.
        r.actions[a.action.nom] = Enregistreur().action
        r.faux.etats[1] = ['green']
        assert client.appeler(requete())['ok']


@pytest.mark.parametrize('erreur,code', [(RuntimeError('texte-confidentiel'), 'internal_error'),
                                       (ErreurOperation('bad_request'), 'bad_request'),
                                       (ErreurOperation('inconnu'), 'internal_error'),
                                       (None, 'internal_error')])
def test_remus_flux_fil_exception(erreur, code):
    a = Enregistreur(flux=True)

    def produire(c):
        yield {}
        c._raison = 'relay_light_red'
        c.arret.set()
        if erreur is not None:
            raise erreur
        yield 42

    a.effet = produire
    with monter(a, etats={1: ['green']}) as r, Connexion(chemin(r), 5) as client:
        lignes = list(client.appeler_flux(requete()))
        assert lignes[-1]['error']['code'] == code
        attendre(lambda: len(fins(r)) == 1)
        assert 'texte-confidentiel' not in str(lignes) + r.flux_journal.getvalue()
        assert fins(r)[0]['result'] == code


def test_remus_flux_fil_deconnexion():
    a = Enregistreur(flux=True)
    liberer, ferme = threading.Event(), threading.Event()

    def produire(c):
        try:
            yield {}
            assert liberer.wait(5)
            while True:
                yield {}
        finally:
            ferme.set()

    a.effet = produire
    with monter(a, etats={1: ['green']}) as r:
        with Connexion(chemin(r), 5) as client:
            flux = client.appeler_flux(requete())
            assert next(flux)['stream'] == 'line'
            flux.close()
        liberer.set()
        assert ferme.wait(5)
        attendre(lambda: len(fins(r)) == 1)
        assert r.flux_ouverts() == {} and r._en_cours == 0


def test_remus_flux_fil_arret():
    a = Enregistreur(flux=True)

    def produire(c):
        yield {}
        assert c.arret.wait(5)
        yield {}

    a.effet = produire
    with monter(a, etats={1: ['green']}) as r, Connexion(chemin(r), 5) as client:
        flux = client.appeler_flux(requete())
        assert next(flux)['stream'] == 'line'
        r.config['server']['stop_s'] = 0.2
        debut = time.monotonic()
        r.arreter()
        assert time.monotonic() - debut < 3
        assert next(flux)['error']['code'] == 'peer_unavailable'
        attendre(lambda: len(fins(r)) == 1)


def test_remus_flux_fil_sessions_independantes():
    a = Enregistreur(flux=True)
    portes = {1: threading.Event(), 2: threading.Event()}

    def produire(c):
        yield {'session': c.session}
        assert portes[c.session].wait(5)
        yield {'suite': c.session}

    a.effet = produire
    with monter(a, etats={1: ['green'], 2: ['green']}) as r:
        with Connexion(chemin(r), 5) as c1, Connexion(chemin(r), 5) as c2:
            f1, f2 = c1.appeler_flux(requete()), c2.appeler_flux(requete(session=2))
            assert next(f1)['data'] == {'session': 1}
            assert next(f2)['data'] == {'session': 2}
            r.faux.etats[1] = ['red']
            r.verifier_flux()
            portes[1].set()
            assert next(f1)['error']['code'] == 'relay_light_red'
            assert r.flux_ouverts().get(2) == 1
            portes[2].set()
            assert [x.get('stream') for x in f2] == ['line', 'end']


def test_remus_flux_fermeture_explicitement(sans_socket):
    a = Enregistreur(flux=True)
    a.effet = lambda c: iter(())
    with sans_socket(a) as r:
        flux = r.traiter(requete())
        assert isinstance(flux, Flux)
        assert list(flux) == []
        assert r.flux_ouverts() == {1: 1} and r._en_cours == 1
        assert fins(r) == []
        flux.close()
        flux.close()
        assert len(fins(r)) == 1 and r._en_cours == 0
        assert r.flux_ouverts() == {}


def test_remus_flux_fermeture_avant_lecture(sans_socket):
    a = Enregistreur(flux=True)
    with sans_socket(a) as r:
        flux = r.traiter(requete())
        flux.close()
        assert not a.appels
        assert r._en_cours == 0 and r.flux_ouverts() == {}
        assert len(fins(r)) == 1


def test_remus_flux_fil_refus_initial():
    a = Enregistreur(flux=True)
    with monter(a, etats={1: ['red']}, horloge=Horloge()) as r:
        resultat = r.traiter(requete())
        assert resultat['error']['code'] == 'relay_light_red'
        assert not a.appels and r.flux_ouverts() == {} and r._en_cours == 0


def test_remus_sans_flux_inchange():
    a = Enregistreur()
    with monter(a, etats={1: ['green']}) as r, Connexion(chemin(r), 5) as client:
        q = requete()
        assert client.appeler(q) == {'id': q['id'], 'ok': True, 'data': {'fait': True}}


@pytest.fixture
def sans_socket(tmp_path):
    """Exerce l'objet Remus sans ouvrir de transport."""
    import contextlib

    @contextlib.contextmanager
    def construire(a):
        journal = io.StringIO()
        r = Remus(configuration(str(tmp_path)), actions={a.action.nom: a.action},
                  journal=Journal('test', flux=journal))
        r.flux_journal = journal
        r._etat_feu = lambda session: 'green'
        yield r

    return construire


def test_remus_flux_arret_borne_sans_transport(sans_socket):
    a = Enregistreur(flux=True)
    a.effet = lambda c: iter(({},))
    with sans_socket(a) as r:
        r.config['server']['stop_s'] = 0.05
        flux = r.traiter(requete())
        debut = time.monotonic()
        r.arreter()
        assert 0.04 <= time.monotonic() - debut < 1
        assert list(flux)[0]['error']['code'] == 'peer_unavailable'
        assert r._en_cours == 1
        flux.close()
        assert r._en_cours == 0


@pytest.mark.parametrize('mode,attendu', [('vide', None), ('invalide', 'internal_error'),
                                         ('exception', 'internal_error'),
                                         ('operation', 'bad_request')])
def test_remus_flux_iterateur_sans_transport(sans_socket, mode, attendu):
    a = Enregistreur(flux=True)

    def produire(c):
        if mode == 'exception':
            raise RuntimeError('texte-confidentiel')
        if mode == 'operation':
            c._raison = 'relay_light_red'
            c.arret.set()
            raise ErreurOperation('bad_request')
        if mode == 'invalide':
            yield 42

    a.effet = produire
    with sans_socket(a) as r:
        flux = r.traiter(requete())
        lignes = list(flux)
        assert (lignes[-1]['error']['code'] if lignes else None) == attendu
        assert r.flux_ouverts() == {1: 1}
        flux.close()
        assert fins(r)[0]['result'] == (attendu or 'ok')
        assert 'texte-confidentiel' not in str(lignes) + r.flux_journal.getvalue()
