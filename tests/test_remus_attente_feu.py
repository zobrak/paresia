# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests de l'attente du feu de Remus ; dépendances : pytest et bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha  2026-11-05  Critères C de T021.
import os
import threading

from remus_outils import (Enregistreur, Horloge, appeler, chemin, evenements,
                          monter, requete)


def test_remus_feu_vert_immediat():
    a = Enregistreur()
    with monter(a, etats={1: ['green']}) as r:
        q = requete()
        rep = appeler(chemin(r), q)
        assert rep['ok'] is True and rep['id'] == q['id'] and rep['data'] == {'fait': True}
        assert len(a.appels) == 1 and r.faux.nombre(1) == 1


def test_remus_attente_puis_vert():
    a = Enregistreur()
    h = Horloge()
    with monter(a, etats={1: ['red', 'red', 'red', 'green']}, horloge=h, avec_serveur=False) as r:
        rep = r.traiter(requete())
        assert rep['ok'] is True and len(a.appels) == 1
        assert r.faux.nombre(1) == 4 and h.t - 1000.0 == 0.75


def test_remus_feu_rouge_refus():
    a = Enregistreur()
    h = Horloge()
    with monter(a, etats={1: ['red']}, horloge=h, avec_serveur=False) as r:
        rep = r.traiter(requete())
        assert rep['error']['code'] == 'relay_light_red' and not a.appels
        assert r.faux.nombre(1) <= 5 / 0.25 + 1
        assert h.t - 1000.0 >= 5
        refus = [e for e in evenements(r.flux_journal) if e['event'] == 'operation_refused']
        assert refus[0]['reason'] == 'relay_light_red'


def test_remus_session_fermee():
    a = Enregistreur()
    with monter(a, etats={1: ['closed']}) as r:
        assert appeler(chemin(r), requete())['error']['code'] == 'session_closed'
        assert not a.appels


def test_remus_castor_indisponible():
    a = Enregistreur()
    h = Horloge()
    with monter(a, horloge=h, avec_serveur=False) as r:
        r.faux.serveur.arreter()
        rep = r.traiter(requete())
        assert rep['error']['code'] == 'peer_unavailable' and not a.appels
        assert h.t - 1000.0 >= 5


def test_remus_castor_mauvais_proprietaire():
    a = Enregistreur()
    h = Horloge()
    with monter(a, etats={1: ['green']}, horloge=h, avec_serveur=False) as r:
        r.config['castor']['uid'] = os.getuid() + 1
        rep = r.traiter(requete())
        assert rep['error']['code'] == 'peer_unavailable' and not a.appels


def test_remus_castor_reponse_invalide():
    a = Enregistreur()
    mauvaises = [{'state': 'purple'}, {'state': 'green', 'remaining_s': '3'},
                 {'state': 'green', 'remaining_s': True}, {'state': 'green', 'x': 1},
                 {'remaining_s': 3}, {}]
    for data in mauvaises:
        h = Horloge()
        with monter(a, etats={1: [data]}, horloge=h, avec_serveur=False, wait_s=1) as r:
            rep = r.traiter(requete())
            assert rep['error']['code'] == 'peer_unavailable', data
    assert not a.appels


def test_remus_sessions_independantes():
    a = Enregistreur()
    h = Horloge()
    with monter(a, etats={1: ['green'], 2: ['red']}, horloge=h, avec_serveur=False) as r:
        assert r.traiter(requete(session=2))['error']['code'] == 'relay_light_red'
        assert r.traiter(requete(session=1))['ok'] is True
        assert [c.session for c in a.appels] == [1]
        assert r.faux.nombre(1) == 1  # session 1 jamais interrogée pour 2 et inversement


def test_remus_sessions_concurrentes_sans_interference():
    a = Enregistreur()
    # Horloge réelle : A est vert tout de suite, B reste rouge ; A ne doit pas attendre B.
    with monter(a, etats={1: ['green'], 2: ['red']}, wait_s=1, poll_s=0.1) as r:
        sortie = {}
        fil = threading.Thread(target=lambda: sortie.update(b=appeler(chemin(r), requete(session=2))))
        fil.start()
        rep = appeler(chemin(r), requete(session=1))
        assert rep['ok'] is True and 'b' not in sortie
        fil.join(10)
        assert sortie['b']['error']['code'] == 'relay_light_red'
