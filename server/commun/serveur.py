# SPDX-License-Identifier: AGPL-3.0-or-later
# Serveur Unix partagé ; dépendances : bibliothèque standard, jumeaux et journal.
# Suivi des versions
#   0.1.5  2026-11-07  Actions admises : contrôle de forme seul, plus de liste centrale (D154).
#   3.0.0-alpha.29  2026-11-06  Flux bornés par ligne et codes du relais (T027).
#   3.0.0-alpha  2026-11-05  Transport hors comparaison du contexte (D16).
#   3.0.0-alpha  2026-11-05  Fermeture publique du contexte (D16).
#   3.0.0-alpha  2026-11-05  Durcissement et corrections du cycle de revue 1.
#   3.0.0-alpha  2026-11-05  Contrôle des pairs et traitement par connexion.
#   3.0.0-alpha  2026-11-05  Socket créée sans droit (umask 0777) puis ouverte au mode final : aucune fenêtre plus large ;
#                      mode facultatif (T005, audit de sécurité).
from dataclasses import dataclass, field
import os
import socket
import struct
import threading
import time

from .journal import Journal
from .catalogue import action_valide
from .jumeaux import (MAX_LINE, Flux, valider_ligne_flux, ErreurProtocole, decoder, encoder,
                      lire_ligne, reponse, valider, verifier_limite,
                      verifier_delai, LectureAvecEcheance)


@dataclass(eq=False)
class ContexteConnexion:
    """Identité vérifiée et état propre à une connexion, même pour un même pid.

    Le démon peut conserver sa session dans etat ; cet état n'est pas journalisé.
    L'objet reste identique pour tous les appels et le rappel de fermeture.
    """
    pid: int
    uid: int
    gid: int
    etat: dict = field(default_factory=dict)
    _transport: object = field(default=None, init=False, repr=False, compare=False)

    def fermer(self):
        """Interrompt la connexion, même en lecture ; idempotent et sans réponse.

        Le fil serveur effectue ensuite la libération et le rappel de fermeture.
        Un contexte non associé à un transport peut aussi être fermé sans effet.
        """
        if self._transport is not None:
            try:
                self._transport.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


class Serveur:
    """Serveur synchrone, un fil par connexion.

    traiter(requete, contexte) renvoie une réponse construite avec reponse().
    contexte est un ContexteConnexion. fermeture(contexte) est appelée à la fin d'une connexion
    admise, pour permettre au démon de libérer ses sessions. Flux accepté également.
    chemin, uids_admis et gid sont obligatoires ; mode de la socket : 0660 par défaut, ou un
    mode plus restrictif (au plus 0660, lecture et écriture du propriétaire). La socket est créée
    sans aucun droit, puis le groupe et le mode final sont posés : jamais plus ouverte que le mode final.
    max_connexions : 64 par défaut, de 1 à 1024 ; delai : au plus 3600 s.
    demarrer() lie la socket avant de rendre la main ; arreter() ferme les pairs.
    Le dossier parent doit être administré par le déploiement ; une socket ou
    un fichier préexistant n'est jamais supprimé à l'ouverture.
    """

    def __init__(self, chemin, uids_admis, actions_admises, traiter, *, gid,
                 max_line=MAX_LINE, delai=30, journal=None, fermeture=None,
                 max_connexions=64, mode=0o660):
        verifier_limite(max_line)
        self.uids = frozenset(uids_admis)
        self.actions = frozenset(actions_admises)
        if any(type(uid) is not int or uid < 0 for uid in self.uids):
            raise ValueError('invalid_uid')
        if type(gid) is not int or gid < 0 or not all(action_valide(a) for a in self.actions):
            raise ValueError('invalid_server_config')
        verifier_delai(delai)
        if type(max_connexions) is not int or not 1 <= max_connexions <= 1024:
            raise ValueError('invalid_connection_limit')
        if type(mode) is not int or mode & ~0o660 or (mode & 0o600) != 0o600:
            raise ValueError('invalid_server_config')
        self.mode = mode
        self.max_connexions = max_connexions
        self.chemin = os.fspath(chemin)
        self.gid = gid
        self.traiter = traiter
        self.fermeture = fermeture
        self.max_line = max_line
        self.delai = delai
        self.journal = journal if journal is not None else Journal('jumeaux')
        self._arret = threading.Event()
        self._verrou = threading.Lock()
        self._connexions = set()
        self._fils = set()
        self._socket = None
        self._identite = None

    def demarrer(self):
        if self._socket is not None:
            raise RuntimeError('server_already_started')
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            ancien = os.umask(0o777)        # bind crée la socket sans aucun droit
            try:
                sock.bind(self.chemin)
            finally:
                os.umask(ancien)
            stat = os.stat(self.chemin)
            self._identite = (stat.st_dev, stat.st_ino)
            os.chown(self.chemin, -1, self.gid)
            os.chmod(self.chemin, self.mode)
            sock.listen()
            sock.settimeout(0.1)
        except BaseException:
            sock.close()
            self._supprimer_socket()
            raise
        self._socket = sock
        self._arret.clear()
        self._fil = threading.Thread(target=self._accepter, daemon=True)
        self._fil.start()
        return self

    def _supprimer_socket(self):
        if self._identite is not None:
            try:
                stat = os.stat(self.chemin, follow_symlinks=False)
                if (stat.st_dev, stat.st_ino) == self._identite:
                    os.unlink(self.chemin)
            except FileNotFoundError:
                pass
            self._identite = None

    def _accepter(self):
        while not self._arret.is_set():
            try:
                connexion, _ = self._socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                pair = struct.unpack('3i', connexion.getsockopt(
                    socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
            except OSError:
                connexion.close()
                self.journal.ecrire('warning', 'peercred_unavailable')
                continue
            if pair[1] not in self.uids:
                connexion.close()
                self.journal.ecrire('warning', 'peer_refused', uid=pair[1])
                continue
            with self._verrou:
                plein = len(self._connexions) >= self.max_connexions
            if plein:
                connexion.close()
                self.journal.ecrire('warning', 'connection_limit')
                continue
            contexte = ContexteConnexion(*pair)
            contexte._transport = connexion
            fil = None
            try:
                connexion.settimeout(self.delai)
                fil = threading.Thread(target=self._servir, args=(connexion, contexte), daemon=True)
                with self._verrou:
                    self._connexions.add(connexion)
                    self._fils.add(fil)
                fil.start()
            except (RuntimeError, OSError, OverflowError):
                connexion.close()
                with self._verrou:
                    self._connexions.discard(connexion)
                    self._fils.discard(fil)
                self.journal.ecrire('error', 'connection_start_failed')

    def _servir(self, connexion, contexte):
        try:
            while not self._arret.is_set():
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
                    except Exception:
                        resultat = reponse(requete['id'], code='internal_error')
                    if isinstance(resultat, Flux):
                        self._servir_flux(connexion, requete, resultat)
                        continue
                    try:
                        if (not isinstance(resultat, dict) or resultat.get('id') != requete['id']
                                or type(resultat.get('ok')) is not bool or 'stream' in resultat):
                            raise ValueError('invalid_handler_response')
                        if not resultat['ok']:
                            resultat = reponse(requete['id'], code=resultat['error']['code'])
                        elif set(resultat) - {'id', 'ok', 'data'}:
                            raise ValueError('invalid_handler_response')
                        # Vérifie la sérialisation avant toute écriture.
                        encoder(resultat)
                    except Exception:
                        resultat = reponse(requete['id'], code='internal_error')
                    self.journal.ecrire('info', 'request_completed', id=requete['id'],
                                        action=requete['action'], session=requete['session'],
                                        result='ok' if resultat['ok'] else 'error')
                lecture.regler_delai()
                connexion.sendall(encoder(resultat))
                if fermer:
                    break
        except (OSError, OverflowError):
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

    def _servir_flux(self, connexion, requete, flux):
        # arreter() coupe le transport ; seul le traitement peut réveiller
        # un itérable bloqué dans l'attente de nouvelles données.
        lignes, succes = 0, False
        try:
            try:
                elements = (iter(flux) if flux.identifiant == requete['id'] else
                            iter([reponse(requete['id'], code='internal_error')]))
            except Exception:
                self.journal.ecrire('error', 'stream_failed')
                elements = iter([reponse(requete['id'], code='internal_error')])
            while True:
                try:
                    resultat = next(elements)
                except StopIteration:
                    resultat = reponse(requete['id'], stream='end')
                except Exception:
                    self.journal.ecrire('error', 'stream_failed')
                    resultat = reponse(requete['id'], code='internal_error')
                try:
                    resultat = valider_ligne_flux(resultat, requete['id'])
                    contenu = encoder(resultat)
                    if len(contenu) > self.max_line:
                        raise ValueError('line_too_long')
                except Exception:
                    resultat = reponse(requete['id'], code='internal_error')
                    contenu = encoder(resultat)
                if len(contenu) > self.max_line:
                    raise OSError('line_too_long')
                LectureAvecEcheance(connexion, time.monotonic() + self.delai).regler_delai()
                connexion.sendall(contenu)
                if resultat.get('stream') == 'line':
                    lignes += 1
                else:
                    succes = resultat.get('stream') == 'end'
                    break
        except (OSError, OverflowError):
            self.journal.ecrire('warning', 'stream_aborted')
            raise
        finally:
            flux.close()
            self.journal.ecrire('info', 'request_completed', id=requete['id'],
                                action=requete['action'], session=requete['session'],
                                result='ok' if succes else 'error', lines=lignes)

    def arreter(self):
        if self._socket is None:
            return
        self._arret.set()
        self._socket.close()
        self._fil.join()
        with self._verrou:
            connexions, fils = list(self._connexions), list(self._fils)
        for connexion in connexions:
            try:
                connexion.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        for fil in fils:
            fil.join(timeout=self.delai)
        self._socket = None
        self._supprimer_socket()

    def __enter__(self):
        return self.demarrer()

    def __exit__(self, *_):
        self.arreter()
