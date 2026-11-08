# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests des opérations de Remus (refus, exécution, arrêt, journal) ; dépendances : pytest et bibliothèque standard.
# Suivi des versions
#   0.1.7  2026-11-07  Journal d'audit : le refus de Remus est provoqué par une session nulle.
#   0.1.7  2026-11-07  Une action absente du catalogue est refusée : unknown_action.
#   3.0.0-alpha  2026-11-05  Critères B et D de T021.
import json
import socket
import threading
import time

from remus_outils import Enregistreur, appeler, chemin, evenements, monter, requete
from server.remus import Action, ErreurOperation


def test_remus_action_absente():
    with monter(Enregistreur()) as r:
        rep = appeler(chemin(r), requete('relay/state/metrics'))
        assert rep['error']['code'] == 'unknown_action'
        assert r.faux.appels == []


def test_remus_action_hors_liste():
    with monter(Enregistreur()) as r:
        for action in ('castor/light/state', 'presence/session/open', 'bunker/identity/list'):
            assert appeler(chemin(r), requete(action))['error']['code'] == 'unknown_action'
        assert r.faux.appels == []


def test_remus_params_invalides():
    a = Enregistreur()
    with monter(a, etats={1: ['green']}) as r:
        assert appeler(chemin(r), requete(session=0))['error']['code'] == 'bad_request'
        assert appeler(chemin(r), requete(params={'x': 1}))['error']['code'] == 'bad_request'
        assert r.faux.appels == [] and not a.appels


def test_remus_params_copie_et_validation():
    recu = []

    def valider(params):
        if set(params) != {'n'} or type(params['n']) is not int:
            raise ErreurOperation('bad_request')
        return {'n': params['n'] + 1}

    a = Enregistreur(valider=valider)
    a.effet = lambda c: recu.append(c.params) or None
    with monter(a, etats={1: ['green']}) as r:
        assert appeler(chemin(r), requete(params={'n': 1}))['ok'] is True
        assert appeler(chemin(r), requete(params={'n': 'x'}))['error']['code'] == 'bad_request'
    assert recu == [{'n': 2}]


def test_remus_operation_menee_a_terme():
    effets = []
    a = Enregistreur()
    a.liberer.clear()
    a.effet = lambda c: effets.append('termine') or {'fait': True}
    with monter(a, etats={1: ['green']}) as r:
        s = socket.socket(socket.AF_UNIX)
        s.connect(chemin(r))
        s.sendall(json.dumps(requete()).encode() + b'\n')
        assert a.entree.wait(5)
        s.close()                                   # client déconnecté
        r.faux.etats[1] = ['closed']                # session fermée, puis feu rouge,
        r.verifier_flux()                           # constatés pendant l'exécution
        r.faux.etats[1] = ['red']
        r.verifier_flux()
        assert effets == []
        a.liberer.set()
        for _ in range(100):
            fin = [e for e in evenements(r.flux_journal) if e['event'] == 'operation_finished']
            if fin:
                break
            time.sleep(0.05)
        assert effets == ['termine']
        assert fin[0]['result'] == 'ok' and 'duration_ms' in fin[0]


def test_remus_exception_action():
    a = Enregistreur()

    def echec(_):
        raise RuntimeError('texte-sensible-12345')

    a.effet = echec
    with monter(a, etats={1: ['green']}) as r:
        rep = appeler(chemin(r), requete())
        assert rep['error']['code'] == 'internal_error'
        assert 'texte-sensible-12345' not in json.dumps(rep) + r.flux_journal.getvalue()
        fin = [e for e in evenements(r.flux_journal) if e['event'] == 'operation_finished']
        assert fin[0]['result'] == 'internal_error'


def test_remus_erreur_operation():
    a = Enregistreur()
    for code, attendu in (('relay_light_red', 'relay_light_red'), ('session_closed', 'session_closed'),
                          ('code_inconnu', 'internal_error')):
        def echec(_, code=code):
            raise ErreurOperation(code)
        a.effet = echec
        with monter(a, etats={1: ['green']}) as r:
            assert appeler(chemin(r), requete())['error']['code'] == attendu
    a.effet = lambda c: 'pas-un-dictionnaire'
    with monter(a, etats={1: ['green']}) as r:
        assert appeler(chemin(r), requete())['error']['code'] == 'internal_error'


def test_remus_arret_ordonne():
    a = Enregistreur()
    a.liberer.clear()
    with monter(a, etats={1: ['green']}) as r:
        sortie = {}
        client = threading.Thread(target=lambda: sortie.update(rep=appeler(chemin(r), requete())))
        client.start()
        assert a.entree.wait(5)
        arret = threading.Thread(target=r.arreter)
        arret.start()
        for _ in range(100):
            if r._arretee.is_set():
                break
            time.sleep(0.02)
        assert r.traiter(requete())['error']['code'] == 'peer_unavailable'
        time.sleep(0.2)
        assert arret.is_alive()                     # attend l'opération en cours
        a.liberer.set()
        arret.join(10)
        client.join(10)
        assert not arret.is_alive() and sortie['rep']['ok'] is True


def test_remus_arret_borne_par_stop_s():
    a = Enregistreur()
    a.liberer.clear()
    with monter(a, etats={1: ['green']}) as r:
        r.config['server']['stop_s'] = 0.5
        client = threading.Thread(target=lambda: appeler(chemin(r), requete()), daemon=True)
        client.start()
        assert a.entree.wait(5)
        debut = time.monotonic()
        r.arreter()
        assert time.monotonic() - debut < 6
        evt = [e for e in evenements(r.flux_journal) if e['event'] == 'shutdown']
        assert evt and evt[0]['remaining'] == 1
        a.liberer.set()
        client.join(10)


def test_remus_journal_audit():
    a = Enregistreur(journaliser=('nom',), valider=lambda p: p)
    with monter(a, etats={1: ['green']}) as r:
        assert appeler(chemin(r), requete(params={'nom': 'visible', 'autre': 'valeur-cachee'}))['ok']
        assert appeler(chemin(r), requete(session=0))['ok'] is False   # refus par Remus
    brut = r.flux_journal.getvalue()
    assert all(json.loads(l) for l in brut.splitlines())
    noms = [e['event'] for e in evenements(r.flux_journal)]
    for attendu in ('startup', 'light_wait', 'operation_started', 'operation_finished',
                    'operation_refused', 'shutdown'):
        assert attendu in noms, attendu
    debut = [e for e in evenements(r.flux_journal) if e['event'] == 'operation_started'][0]
    assert debut['parametres'] == {'nom': 'visible'} and debut['session'] == 1 and 'id' in debut
    assert 'valeur-cachee' not in brut
    attente = [e for e in evenements(r.flux_journal) if e['event'] == 'light_wait'][0]
    assert attente['result'] == 'green' and 'waited_ms' in attente


def test_remus_action_invalide():
    import pytest
    with pytest.raises(ValueError):
        Action('presence/session/open', print, print, 1)
    with pytest.raises(ValueError):
        Action('relay/state/status', print, print, 0)
