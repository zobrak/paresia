# Transport persistant Pollux ; dépendances : bibliothèque standard, server.commun.
# Suivi des versions
#   3.0.0-alpha  2026-11-05  Attente sans expiration entre deux messages de présence.
#   3.0.0-alpha  2026-11-05  Fermeture sûre et umask restrictif à la création de la socket.
import os
import select
import threading
import time

from server.commun.jumeaux import (ErreurProtocole, LectureAvecEcheance, decoder,
                                  encoder, lire_ligne, reponse, valider)
from server.commun.serveur import Serveur


class Presence(Serveur):
    """Réutilise l'acceptation T001 ; aucun ping n'est envoyé à Romulus.

    Le délai commence au premier octet disponible, pas pendant l'inactivité de
    Pollux. EOF et arrêt du serveur déclenchent toujours la révocation D9.
    """

    def demarrer(self):
        # umask est global au processus : restauré même en cas d'erreur.
        ancien = os.umask(0o117)
        try:
            return super().demarrer()
        finally:
            os.umask(ancien)

    def _servir(self, connexion, contexte):
        try:
            while not self._arret.is_set():
                if not select.select([connexion], [], [], .1)[0]:
                    continue
                lecture = LectureAvecEcheance(connexion, time.monotonic() + self.delai)
                fermer = False
                try:
                    ligne = lire_ligne(lecture, self.max_line)
                    if ligne is None:
                        break
                    requete = valider(decoder(ligne), self.actions)
                except ErreurProtocole as erreur:
                    resultat = reponse(erreur.identifiant, code=erreur.code)
                    fermer = erreur.fermer
                else:
                    try:
                        resultat = self.traiter(requete, contexte)
                        encoder(resultat)
                    except Exception:
                        resultat = reponse(requete['id'], code='internal_error')
                    self.journal.ecrire('info', 'presence_request', action=requete['action'],
                                        session=requete['session'],
                                        result='ok' if resultat['ok'] else resultat['error']['code'])
                lecture.regler_delai()
                connexion.sendall(encoder(resultat))
                if fermer:
                    break
        except OSError:
            pass
        finally:
            connexion.close()
            try:
                if self.fermeture is not None:
                    self.fermeture(contexte)
            except Exception:
                self.journal.ecrire('error', 'connection_cleanup_failed')
            finally:
                with self._verrou:
                    self._connexions.discard(connexion)
                    self._fils.discard(threading.current_thread())
