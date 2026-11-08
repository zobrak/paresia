# SPDX-License-Identifier: AGPL-3.0-or-later
# Flux d'événements HTTP ; dépendances : bibliothèque standard et server.commun.
# Suivi des versions
#   0.1.8  2026-11-07  Plus de constante d'action ni d'option de service : le service du suivi vient de sa déclaration (rôles d'option).
#   3.0.0-alpha.41  2026-11-06  Constante ACTION_SUIVI définie ici, seule définition (importée par aiguillage.py et http.py).
#   3.0.0-alpha.41  2026-11-06  Suivi différé, pings et libération des ressources (D10, D85, D111).
from contextlib import ExitStack
import select
import threading
import time

from server.commun.client import PairIndisponible
from server.commun.jumeaux import ErreurProtocole, encoder

BATTEMENT = b': heartbeat\n\n'


def evenement(data, nom=None):
    """Champs ASCII, JSON sur une ligne et ligne vide terminant l'événement."""
    prefixe = b'' if nom is None else b'event: ' + nom.encode('ascii') + b'\n'
    return prefixe + b'data: ' + encoder(data) + b'\n'


class FluxEvenements:
    """Résultat différé ; le frontal possède l'écriture et le cycle de vie du flux."""

    def __init__(self, aiguillage, params, session, liaison, action):
        self.aiguillage, self.params, self.session = aiguillage, params, session
        self.liaison, self.action = liaison, action
        self.codes = liaison.service.codes
        self._fin = threading.Event()
        self.termine = threading.Event()
        self._verrou = threading.Lock()
        self._code = None
        self._connexion = None
        self._fil = None

    def arreter(self, code='peer_unavailable'):
        with self._verrou:
            if self._code is None:
                self._code = code
            self._fin.set()
            if self._connexion is not None:
                self._connexion.fermer()

    def _session_fermee(self):
        self.arreter('session_closed')

    def _verifier(self):
        if self._code is not None:
            raise ErreurProtocole(self._code)

    def _ping(self):
        self._verifier()
        try:
            self.aiguillage._pinguer(self.session)
        except Exception as erreur:
            code = getattr(erreur, 'code', 'internal_error')
            self.arreter(code if code in self.codes else 'internal_error')
        self._verifier()

    def _pinger(self):
        while not self._fin.wait(self.aiguillage._delai_ping(self.session)):
            try:
                self._ping()
            except Exception:
                self.arreter(self._code or 'internal_error')
                return

    def _apres_envoi(self):
        self._ping()
        self._fil = threading.Thread(target=self._pinger, daemon=True)
        self._fil.start()

    def servir(self, requete):
        """Première réponse validée avant les en-têtes ; nettoyage sur toute issue."""
        aiguillage, liaison = self.aiguillage, self.liaison
        if not aiguillage._places_flux.acquire(blocking=False):
            raise ErreurProtocole('command_busy')
        debut = time.monotonic()
        raison = 'internal_error'
        lecteur = None
        inscrit = False
        sessions = requete.server.sessions

        def ecrire(contenu):
            nonlocal raison
            try:
                requete._fin_ecriture = time.monotonic() + requete.server.delai
                requete._delai_ecriture()
                requete.wfile.write(contenu)
            except OSError:
                raison = 'client_disconnected'
                self.arreter()
                raise

        def attendre():
            nonlocal raison
            self._verifier()
            if requete._reponse_commencee:
                ecrire(BATTEMENT)
            else:
                # Aucun octet HTTP avant la première ligne ; détecter néanmoins
                # une fermeture complète du client pendant l'attente de Remus.
                sondage = select.poll()
                sondage.register(requete.connection, select.POLLHUP | select.POLLERR)
                if sondage.poll(0):
                    raison = 'client_disconnected'
                    self.arreter()
                    raise BrokenPipeError()

        try:
            self._connexion = aiguillage._connexion(liaison)
            requete.server.inscrire_flux(self)
            inscrit = True
            sessions.abonner(self.session, self._session_fermee)
            self._verifier()
            aiguillage.journal.ecrire('info', 'follow_started', session=self.session)
            lecteur = self._connexion.appeler_flux(
                aiguillage._enveloppe(self.action, self.params, self.session),
                delai_ligne=liaison.valeur('battement') + liaison.valeur('ping_delai'),
                apres_envoi=self._apres_envoi, sur_attente=attendre)
            while True:
                try:
                    ligne = next(lecteur)
                except PairIndisponible:
                    raise ErreurProtocole(self._code or 'peer_unavailable') from None
                except ErreurProtocole:
                    raise ErreurProtocole(self._code or 'internal_error') from None
                self._verifier()
                if not ligne['ok']:
                    code = ligne['error']['code']
                    raise ErreurProtocole(code if code in self.codes else 'internal_error')
                contenu = (evenement({}, 'end') if ligne['stream'] == 'end'
                           else evenement(ligne.get('data')))
                if not requete._reponse_commencee:
                    try:
                        requete._entetes_succes('text/event-stream', None)
                    except OSError:
                        raison = 'client_disconnected'
                        raise
                ecrire(contenu)
                if ligne['stream'] == 'end':
                    raison = 'end'
                    return
        except Exception as erreur:
            self._fin.set()
            if raison == 'client_disconnected':
                return
            code = self._code or ('peer_unavailable' if isinstance(erreur, PairIndisponible)
                                 else getattr(erreur, 'code', 'internal_error'))
            if code not in self.codes:
                code = 'internal_error'
            raison = {'relay_light_red': 'light_red', 'session_closed': 'session_closed',
                      'peer_unavailable': 'peer_unavailable'}.get(code, 'internal_error')
            if code in liaison.service.ping_oubli:
                with aiguillage._verrou:
                    aiguillage._pings.pop(self.session, None)
            if not requete._reponse_commencee:
                raise ErreurProtocole(code) from None
            try:
                ecrire(evenement({'code': code}, 'error'))
            except OSError:
                pass
        finally:
            self._fin.set()
            # Tous les nettoyages restent dus même si l'un d'eux lève.
            with ExitStack() as nettoyage:
                if inscrit:
                    nettoyage.callback(requete.server.desinscrire_flux, self)
                nettoyage.callback(self.termine.set)
                nettoyage.callback(aiguillage._places_flux.release)
                nettoyage.callback(aiguillage.journal.ecrire,
                    'info', 'follow_stopped', session=self.session, reason=raison,
                    duration_ms=max(0, int((time.monotonic() - debut) * 1000)))
                nettoyage.callback(sessions.desabonner, self.session, self._session_fermee)
                if self._fil is not None:
                    nettoyage.callback(self._fil.join)
                if lecteur is not None:
                    nettoyage.callback(lecteur.close)
                if self._connexion is not None:
                    nettoyage.callback(self._connexion.fermer)
