# Tests additifs D16 ; dépendances : pytest, bibliothèque standard et socle.
# Suivi des versions
#   3.0.0-alpha  2026-11-05  Fermeture concurrente de Connexion (T002, cycle 2).
#   3.0.0-alpha  2026-11-05  Notification hors appel et fermeture par contexte.
import io
import os
from pathlib import Path
import tempfile
import threading
import time

import pytest

from server.commun.client import Connexion, PairIndisponible
from server.commun.journal import Journal
from server.commun.jumeaux import ACTIONS, reponse
from server.commun.serveur import Serveur
from server.pollux import requete


@pytest.mark.parametrize('mode', ['contexte', 'arret', 'volontaire', 'pendant_appel'])
def test_notification_rupture(mode):
    with tempfile.TemporaryDirectory(prefix='notification-') as dossier:
        contextes, notifications = [], []
        termine = threading.Event()

        def traiter(q, contexte):
            contextes.append(contexte)
            if mode == 'pendant_appel':
                contexte.fermer()
            return reponse(q['id'])

        def rupture(client):
            notifications.append(client)
            # Le rappel peut prendre le verrou client sans interblocage.
            with client._verrou:
                termine.set()

        serveur = Serveur(str(Path(dossier) / 's'), {os.getuid()}, ACTIONS, traiter,
                          gid=os.getgid(), journal=Journal('test', flux=io.StringIO()))
        with serveur, Connexion(serveur.chemin, 1, rupture=rupture) as client:
            if mode == 'pendant_appel':
                with pytest.raises(PairIndisponible):
                    client.appeler(requete('presence/session/ping'))
            else:
                for _ in range(10):
                    assert client.appeler(requete('presence/session/ping'))['ok']
                if mode == 'volontaire':
                    client.fermer()
                    assert not termine.wait(0.15)
                    return
                if mode == 'contexte':
                    contextes[0].fermer()
                    contextes[0].fermer()
                else:
                    serveur.arreter()
            assert termine.wait(2)
            assert client.rompue
            time.sleep(0.1)
            assert notifications == [client]
            with pytest.raises(PairIndisponible):
                client.appeler(requete('presence/session/ping'))


def test_fermeture_concurrente():
    with tempfile.TemporaryDirectory(prefix='concurrente-') as dossier:
        notifications, erreurs = [], []
        serveur = Serveur(str(Path(dossier) / 's'), {os.getuid()}, ACTIONS,
                          lambda q, _: reponse(q['id']), gid=os.getgid(),
                          journal=Journal('test', flux=io.StringIO()))
        with serveur:
            client = Connexion(serveur.chemin, 1, rupture=notifications.append)
            assert client.appeler(requete('presence/session/ping', 1))['ok']
            barriere = threading.Barrier(2)

            def fermer():
                try:
                    barriere.wait(2)
                    for _ in range(200):
                        client.fermer()
                except Exception as e:
                    erreurs.append(e)

            fils = [threading.Thread(target=fermer) for _ in range(2)]
            for fil in fils:
                fil.start()
            for fil in fils:
                fil.join(3)
            time.sleep(0.3)
        assert not erreurs and client.rompue
        assert notifications == []  # fermeture volontaire : pas de notification
