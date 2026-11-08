# SPDX-License-Identifier: AGPL-3.0-or-later
# Client Unix jumeaux/1 ; dépendances : bibliothèque standard et jumeaux.
# Suivi des versions
#   0.1.5  2026-11-07  Paramètre facultatif actions (ensemble admis) ; sans lui, forme seule (D154).
#   3.0.0-alpha.41  2026-11-06  Attente renouvelable (sur_attente) et rappel apres_envoi pour appeler_flux ; arrêt de la socket à la fermeture (D85, D111).
#   3.0.0-alpha.41  2026-11-06  Rappel facultatif apres_envoi de Connexion.appeler (T038, D100).
#   3.0.0-alpha.29  2026-11-06  Flux bornés par ligne et codes du relais ; socket relue une fois face à fermer() concurrent (T027).
#   3.0.0-alpha  2026-11-05  Robustesse : fermer() atomique face aux fermetures concurrentes, rappel de rupture jamais perdu (T002, cycle 2).
#   3.0.0-alpha  2026-11-05  Surveillance tolérante à la fermeture concurrente (D16).
#   3.0.0-alpha  2026-11-05  Surveillance facultative des ruptures (D16).
#   3.0.0-alpha  2026-11-05  Durcissement et corrections du cycle de revue 1.
#   3.0.0-alpha  2026-11-05  Appels uniques et connexion persistante sans reconnexion.
import socket
import select
import struct
import threading
import time

from .catalogue import action_valide
from .jumeaux import (CODES_ERREUR, MAX_LINE, ErreurProtocole, decoder,
                      encoder, lire_ligne, valider, verifier_limite, reponse,
                      verifier_delai, LectureAvecEcheance, valider_ligne_flux)


class PairIndisponible(Exception):
    """Rupture, délai ou connexion impossible, sans message externe."""
    code = 'peer_unavailable'

    def __init__(self):
        super().__init__(self.code)


class _RappelEchoue(Exception):
    """Transporte l'exception d'un rappel apres_envoi hors des clauses de rupture."""

    def __init__(self, origine):
        super().__init__()
        self.origine = origine


class _LectureFlux(LectureAvecEcheance):
    """Renouvelle l'attente sans perdre les octets de la ligne en cours."""

    def __init__(self, sock, delai, sur_attente):
        super().__init__(sock, time.monotonic() + delai)
        self.delai, self.sur_attente = delai, sur_attente

    def recv_into(self, destination):
        while True:
            try:
                return super().recv_into(destination)
            except TimeoutError:
                if self.sur_attente is None:
                    raise
                try:
                    self.sur_attente()
                except BaseException as erreur:
                    raise _RappelEchoue(erreur) from None
                self.echeance = time.monotonic() + self.delai


def _valider_requete(requete, actions):
    """Avec ensemble : valider ; sans ensemble : forme seule, via action_valide."""
    if actions is None:
        action = requete.get('action') if isinstance(requete, dict) else None
        actions = frozenset({action}) if action_valide(action) else frozenset()
    valider(requete, actions)


class Connexion:
    """Appels successifs sérialisés ; après rupture, aucune reconnexion implicite.

    Une réponse de protocole invalide lève ErreurProtocole et ferme la connexion.
    Un EOF, un échec réseau ou un délai lève PairIndisponible. L'appelant décide
    de créer une nouvelle connexion. delai borne chaque appel complet (≤ 3600 s).
    uid_serveur, si fourni, est vérifié via SO_PEERCRED avant tout envoi.
    """

    def __init__(self, chemin, delai=30, *, max_line=MAX_LINE, uid_serveur=None,
                 rupture=None, actions=None):
        verifier_limite(max_line)
        verifier_delai(delai)
        if uid_serveur is not None and (type(uid_serveur) is not int or not 0 <= uid_serveur < 2**32 - 1):
            raise ValueError('invalid_uid')
        self.uid_serveur = uid_serveur
        self.actions = None if actions is None else frozenset(actions)
        self.chemin, self.delai, self.max_line = chemin, delai, max_line
        self._flux_ouvert = False
        self._socket = None
        self._rompue = False
        self._verrou = threading.Lock()
        self._rappel_rupture = rupture
        self._fin_surveillance = threading.Event()
        self._echec = threading.Event()
        self._surveillance = None

    @property
    def rompue(self):
        """Vrai après une rupture ou une fermeture explicite."""
        return self._rompue

    def _surveiller(self):
        """Rappel rupture(connexion), une fois, hors verrou, sans lire les données.

        Surveillance Linux de HUP/RDHUP/ERR, également entre les appels.
        Elle démarre au premier appel de appeler() (pas à la construction).
        Aucun fil si rupture est absent ; fermer() volontaire ne notifie pas.
        Une fermeture concurrente (OSError, ValueError du sondage) est ignorée.
        Le rappel ne doit pas lever ; ses exceptions sont contenues sans texte.
        """
        while True:
            self._fin_surveillance.wait(0.05)
            if self._echec.is_set():
                break
            if self._fin_surveillance.is_set():
                return
            if not self._verrou.acquire(blocking=False):
                continue
            try:
                tube = self._socket
                if tube is not None:
                    sondage = select.poll()
                    sondage.register(tube, select.POLLRDHUP | select.POLLHUP | select.POLLERR)
                    if sondage.poll(0):
                        self._echec.set()
                        self.fermer()
            except Exception:
                # Fermeture concurrente ou erreur de sondage : le rappel reste dû
                # si une rupture a été constatée (_echec), sinon on réessaie.
                continue
            finally:
                self._verrou.release()
        try:
            self._rappel_rupture(self)
        except Exception:
            pass

    def fermer(self):
        self._fin_surveillance.set()
        self._rompue = True
        sock, self._socket = self._socket, None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except (OSError, AttributeError):
                pass
            try:
                sock.close()
            except OSError:
                pass

    def appeler(self, requete, *, apres_envoi=None):
        """Un appel ; apres_envoi() est rappelé une fois, sans argument, juste après l'envoi.

        Si le rappel lève, la connexion est fermée (rupture constatée) et l'exception
        se propage telle quelle, sans lire de réponse.
        """
        if self._flux_ouvert:
            raise RuntimeError('stream_open')
        _valider_requete(requete, self.actions)
        contenu = encoder(requete)
        if len(contenu) > self.max_line:
            raise ErreurProtocole('line_too_long', requete['id'], True)
        with self._verrou:
            if self._flux_ouvert:
                raise RuntimeError('stream_open')
            if self._rompue:
                raise PairIndisponible()
            if self._rappel_rupture is not None and self._surveillance is None:
                self._surveillance = threading.Thread(target=self._surveiller, daemon=True)
                self._surveillance.start()
            echeance = time.monotonic() + self.delai
            try:
                if self._socket is None:
                    self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    self._socket.settimeout(self.delai)
                    self._socket.connect(self.chemin)
                    if self.uid_serveur is not None:
                        pair = struct.unpack('3i', self._socket.getsockopt(
                            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
                        if pair[1] != self.uid_serveur:
                            raise ConnectionError()
                sock = self._socket
                if sock is None:
                    raise ConnectionError()
                lecture = LectureAvecEcheance(sock, echeance)
                lecture.regler_delai()
                sock.sendall(contenu)
                if apres_envoi is not None:
                    try:
                        apres_envoi()
                    except BaseException as erreur:
                        raise _RappelEchoue(erreur) from None
                ligne = lire_ligne(lecture, self.max_line)
                if ligne is None:
                    raise ConnectionError()
                resultat = decoder(ligne)
                if (resultat.get('id') != requete['id'] or type(resultat.get('ok')) is not bool
                        or set(resultat) - {'id', 'ok', 'data', 'error'}):
                    raise ErreurProtocole()
                if resultat['ok']:
                    if 'error' in resultat:
                        raise ErreurProtocole()
                else:
                    erreur = resultat.get('error')
                    if (not isinstance(erreur, dict) or set(erreur) - {'code', 'detail'}
                            or not isinstance(erreur.get('code'), str)
                            or erreur['code'] not in CODES_ERREUR or 'data' in resultat
                            or ('detail' in erreur and not isinstance(erreur['detail'], str))):
                        raise ErreurProtocole()
                    # Les détails du pair ne sont jamais propagés tels quels.
                    resultat = reponse(requete['id'], code=erreur['code'])
                return resultat
            except _RappelEchoue as echec:
                self._echec.set()
                self.fermer()
                raise echec.origine
            except (OSError, OverflowError):
                self._echec.set()
                self.fermer()
                raise PairIndisponible() from None
            except ErreurProtocole:
                self._echec.set()
                self.fermer()
                raise

    def appeler_flux(self, requete, *, delai_ligne=None, apres_envoi=None, sur_attente=None):
        """Réserve la connexion ; apres_envoi suit l'envoi, avant toute lecture.

        Sans sur_attente, un délai ferme le flux. Sinon sur_attente() renouvelle
        l'attente et conserve la ligne partielle. Le délai composé (battement
        et marge) admet deux délais unitaires. Toute exception d'un rappel
        ferme la connexion et se propage sans transformation.
        """
        if self._flux_ouvert:
            raise RuntimeError('stream_open')
        delai = self.delai if delai_ligne is None else delai_ligne
        verifier_delai(delai / 2 if sur_attente is not None and type(delai) in (int, float)
                       else delai)
        _valider_requete(requete, self.actions)
        identifiant = requete['id']
        contenu = encoder(requete)
        if len(contenu) > self.max_line:
            raise ErreurProtocole('line_too_long', identifiant, True)
        with self._verrou:
            if self._flux_ouvert:
                raise RuntimeError('stream_open')
            if self._rompue:
                raise PairIndisponible()
            if self._rappel_rupture is not None and self._surveillance is None:
                self._surveillance = threading.Thread(target=self._surveiller, daemon=True)
                self._surveillance.start()
            try:
                echeance = time.monotonic() + self.delai
                if self._socket is None:
                    self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    self._socket.settimeout(self.delai)
                    self._socket.connect(self.chemin)
                    if self.uid_serveur is not None:
                        pair = struct.unpack('3i', self._socket.getsockopt(
                            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
                        if pair[1] != self.uid_serveur:
                            raise ConnectionError()
                sock = self._socket
                if sock is None:
                    raise ConnectionError()
                LectureAvecEcheance(sock, echeance).regler_delai()
                sock.sendall(contenu)
                if apres_envoi is not None:
                    try:
                        apres_envoi()
                    except BaseException as erreur:
                        raise _RappelEchoue(erreur) from None
            except _RappelEchoue as echec:
                self._echec.set()
                self.fermer()
                raise echec.origine
            except (OSError, OverflowError):
                self._echec.set()
                self.fermer()
                raise PairIndisponible() from None
            self._flux_ouvert = True
        lecteur = self._lire_flux(identifiant, delai, sur_attente)
        # Amorçage : close() et le ramasse-miettes exécutent enfin le finally,
        # même si l'appelant n'a encore demandé aucune réponse.
        next(lecteur)
        return lecteur

    def _lire_flux(self, identifiant, delai, sur_attente=None):
        termine = False
        try:
            yield None
            while True:
                with self._verrou:
                    if self._rompue:
                        raise PairIndisponible()
                    try:
                        sock = self._socket
                        if sock is None:
                            raise ConnectionError()
                        lecture = _LectureFlux(sock, delai, sur_attente)
                        ligne = lire_ligne(lecture, self.max_line)
                        if ligne is None:
                            raise ConnectionError()
                        resultat = valider_ligne_flux(decoder(ligne), identifiant)
                    except _RappelEchoue as echec:
                        raise echec.origine
                    except (OSError, OverflowError):
                        self._echec.set()
                        raise PairIndisponible() from None
                    except ErreurProtocole:
                        self._echec.set()
                        raise
                    termine = not resultat['ok'] or resultat['stream'] == 'end'
                    if termine:
                        self._flux_ouvert = False
                yield resultat
                if termine:
                    return
        finally:
            if not termine:
                self.fermer()
                self._flux_ouvert = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.fermer()


def appeler(chemin, requete, delai=30, *, uid_serveur=None, actions=None):
    """Un appel et une connexion, toujours fermée avant le retour."""
    with Connexion(chemin, delai, uid_serveur=uid_serveur, actions=actions) as connexion:
        return connexion.appeler(requete)
