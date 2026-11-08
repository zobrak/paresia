# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests des flux continus et de l'intégration avec le vrai Castor ; dépendances : pytest et bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha.41  2026-11-06  Refus de Remus sans feu vert récent, horloge de Castor vieillie (D111).
#   3.0.0-alpha.32  2026-11-06  Consommation et fermeture explicites du Flux (T035).
#   3.0.0-alpha  2026-11-05  Critères E et intégration de T021 (hors fil : exigence 19 après T027).
import contextlib
import io
import tempfile
import threading
import time

from castor_outils import appeler as appeler_castor, monter as monter_castor, requete as requete_castor
from remus_outils import PREFIXE, appeler, configuration, evenements, requete, valider_vide
from server.commun.journal import Journal
from server.remus import Action, Remus

PING, FERME = 'castor/light/ping', 'castor/light/close'


@contextlib.contextmanager
def banc(**options):
    """Remus (sans serveur) devant un vrai Castor à horloge fictive."""
    with monter_castor() as (castor, horloge, _):
        with tempfile.TemporaryDirectory(prefix='remus-') as dossier:
            config = configuration(dossier, castor=castor.config['state']['socket'])
            flux = io.StringIO()
            lignes = {}

            def executer(contexte):
                mes = lignes.setdefault(contexte.session, [])
                mes.append('debut')
                while not contexte.arret.wait(0.01):
                    mes.append('ligne')
                yield {'arret': contexte.raison()}

            action = Action(PREFIXE, executer, valider_vide, 1, flux=True)
            remus = Remus(config, actions={PREFIXE: action}, journal=Journal('test', flux=flux))
            remus.castor, remus.horloge_castor, remus.lignes, remus.flux_journal = castor, horloge, lignes, flux
            yield remus


def ping(b, session):
    assert appeler_castor(b.castor.config['tunnel']['socket'],
                          requete_castor(PING, session))['ok'] is True


def consommer(flux):
    try:
        return list(flux)[-1]
    finally:
        flux.close()


def lancer(b, session, attendu=1):
    sortie = {}
    fil = threading.Thread(target=lambda: sortie.update(rep=consommer(b.traiter(requete(session=session)))),
                           daemon=True)
    fil.start()
    for _ in range(200):
        if b.flux_ouverts().get(session) == attendu:
            break
        time.sleep(0.01)
    return fil, sortie


def test_remus_flux_maintenu():
    with banc() as b:
        ping(b, 1)
        fil, sortie = lancer(b, 1)
        for _ in range(3):                      # 3 x 30 s = 90 s d'horloge fictive, pings continus
            b.horloge_castor.t += 30
            ping(b, 1)
            b.verifier_flux()
        assert b.flux_ouverts() == {1: 1} and fil.is_alive()
        b.horloge_castor.t += 36                # plus de ping : le feu se périme
        b.verifier_flux()
        fil.join(10)
        assert sortie['rep']['error']['code'] == 'relay_light_red'
        fin = [e for e in evenements(b.flux_journal) if e['event'] == 'operation_finished']
        assert fin[0]['result'] == 'relay_light_red' and b.flux_ouverts() == {}


def test_remus_flux_arret_feu_rouge():
    with banc() as b:
        ping(b, 1)
        fil, sortie = lancer(b, 1)
        fil2, sortie2 = lancer(b, 1, 2)         # deux flux de la même session : tous arrêtés
        assert b.flux_ouverts() == {1: 2}
        appeler_castor(b.castor.config['tunnel']['socket'], requete_castor(FERME, 1))
        b.verifier_flux()
        fil.join(10)
        fil2.join(10)
        assert sortie['rep']['error']['code'] == 'session_closed'
        assert sortie2['rep']['error']['code'] == 'session_closed'


def test_remus_flux_sessions_independantes():
    with banc() as b:
        ping(b, 1)
        ping(b, 2)
        fil1, s1 = lancer(b, 1)
        fil2, s2 = lancer(b, 2)
        b.horloge_castor.t += 20
        ping(b, 2)
        b.horloge_castor.t += 20                # session 1 expirée, session 2 encore verte
        b.verifier_flux()
        fil1.join(10)
        assert s1['rep']['error']['code'] == 'relay_light_red'
        assert fil2.is_alive() and b.flux_ouverts() == {2: 1}
        b._arreter_flux(2, 'peer_unavailable')
        fil2.join(10)
        assert s2['rep']['error']['code'] == 'peer_unavailable'


def test_remus_flux_castor_injoignable():
    with banc() as b:
        ping(b, 1)
        fil, sortie = lancer(b, 1)
        b.config['castor']['socket'] = b.config['castor']['socket'] + '.absente'
        b.verifier_flux()
        fil.join(10)
        assert sortie['rep']['error']['code'] == 'peer_unavailable'


def test_remus_avec_castor_reel():
    with banc() as b:
        b.config['light'].update(wait_s=1, poll_s=0.1)
        b.config['castor']['delai_s'] = 1
        b.actions[PREFIXE] = Action(PREFIXE, lambda c: {'fait': True}, valider_vide, 1)
        assert b.traiter(requete())['error']['code'] == 'relay_light_red'   # pas de ping
        ping(b, 1)
        assert b.traiter(requete())['data'] == {'fait': True}
        appeler_castor(b.castor.config['tunnel']['socket'], requete_castor(FERME, 1))
        assert b.traiter(requete())['error']['code'] == 'session_closed'


def test_remus_refuse_feu_expire():
    with banc() as b:
        b.config['light'].update(wait_s=1, poll_s=0.1)
        appels = []

        def executer(contexte):
            appels.append(contexte.session)
            return {'fait': True}

        b.actions[PREFIXE] = Action(PREFIXE, executer, valider_vide, 1)
        ping(b, 1)
        assert b.traiter(requete())['data'] == {'fait': True}
        assert appels == [1]
        lumiere = b.castor.config['lights']
        b.horloge_castor.t += lumiere['heartbeat_s'] + lumiere['margin_s']
        assert b.traiter(requete())['error']['code'] == 'relay_light_red'
        assert appels == [1]
        ping(b, 1)
        assert b.traiter(requete())['data'] == {'fait': True}
        assert appels == [1, 1]


def test_remus_flux_inscrit_apres_arret():
    """Un flux inscrit alors que l'arrêt est déjà levé est arrêté dès son inscription."""
    with banc() as b:
        b._arretee.set()                       # arrêt levé après l'admission, avant l'inscription
        sortie = {}
        b._en_cours += 1  # admission simulée avant l'appel direct à _executer
        fil = threading.Thread(
            target=lambda: sortie.update(rep=consommer(b._executer(requete(session=1), b.actions[PREFIXE], {}))),
            daemon=True)
        fil.start()
        fil.join(5)
        assert not fil.is_alive()
        assert sortie['rep']['error']['code'] == 'peer_unavailable' and b.flux_ouverts() == {}
