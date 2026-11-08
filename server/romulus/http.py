# SPDX-License-Identifier: AGPL-3.0-or-later
# Frontal HTTP Unix ; dépendances : bibliothèque standard, server.commun.
# Suivi des versions
#   0.1.15  2026-11-08  Journal d'activité : une entrée par requête traitée ou refusée (qui, quoi, résultat).
#   0.1.8  2026-11-07  Chemins, exports et suivis fournis par les déclarations de services : plus de liste d'actions ni de nom de greffon.
#   3.0.0-alpha.41  2026-11-06  Envoi du flux d'événements, comparaison Origin/Host en minuscules ASCII (D85, D111).
#   3.0.0-alpha.41  2026-11-06  Statuts des six codes de signature de bunkerd (D112, codes de signature de bunkerd).
#   3.0.0-alpha.41  2026-11-06  Contrôle Origin (D15) et table STATUTS des codes (T038, D10, D57).
#   3.0.0-alpha.40  2026-11-06  File d'attente d'écoute au moins égale à la limite de connexions.
#   3.0.0-alpha.32  2026-11-06  Transport des exports binaires bornés et audit (T013).
#   3.0.0-alpha  2026-11-05  Filtrage des actions et authentification sans aiguillage.
#   3.0.0-alpha  2026-11-05  Plafonds de connexions, échéance de lecture, en-têtes bornés, umask.
#   3.0.0-alpha  2026-11-05  Cycle 3 : settimeout avant la prise de place (pas de fuite de sémaphore).
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import os
import re
import socket
import socketserver
import struct
import tempfile
import threading
import time

from server.commun.jumeaux import ErreurProtocole, decoder, encoder, verifier_limite
from .flux import FluxEvenements


def minuscules_ascii(texte):
    """D111 : aucune équivalence Unicode dans la comparaison de l'origine."""
    return texte.translate(str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'))

PREFIXE_API = '/api/admin/'
# Statut HTTP de chaque code d'erreur pouvant atteindre le client (RFC 9110, § 15.5 et 15.6).
# Tout code absent donne internal_error (500). session_limit, auth_info_unavailable,
# line_too_long et protocol_version_mismatch n'atteignent jamais le client HTTP.
STATUTS = {
    'bad_request': 400, 'token_conflict': 400,
    'origin_refused': 403, 'session_closed': 403,
    'token_missing': 403, 'token_unknown': 403,
    'unknown_action': 404, 'unknown_identity': 404, 'client_not_authorized': 404,
    'identity_exists': 409, 'identity_unlocked': 409, 'relay_identity_protected': 409, 'pubkey_mismatch': 409,
    'body_too_large': 413,
    'export_too_large': 422, 'invalid_identity': 422, 'invalid_relays': 422,
    'invalid_ncryptsec': 422, 'invalid_client': 422, 'invalid_timeout': 422,
    'confirmation_mismatch': 422, 'not_relay_key': 422, 'bad_passphrase': 422,
    'invalid_pubkeys': 422, 'invalid_passphrase': 422, 'log_n_too_high': 422,
    'internal_error': 500, 'not_available': 501, 'command_failed': 502,
    'export_busy': 503, 'peer_unavailable': 503, 'relay_light_red': 503,
    'command_busy': 503, 'command_timeout': 504,
}
TAILLE_BLOC = 65536
NOM_EXPORT = re.compile(r'requisition-[0-9]{8}-[0-9]{6}\.tar\.gz')


@dataclass(frozen=True)
class ExportBinaire:
    """Production différée : produire(destination) écrit le gzip par blocs.

    Le producteur retourne {'count': entier positif, 'periode': (date, date)}.
    Il ferme son compresseur avant de retourner, sans fermer la destination.
    Romulus possède le fichier ; aucun nom ni en-tête n'est fourni par l'action.
    """

    produire: object


@dataclass(frozen=True)
class _ArchiveBinaire:
    fichier: object
    taille: int
    sha256: str
    nom: str
    count: int
    periode: tuple
    type_contenu: str = 'application/gzip'


class _DestinationExport:
    """Écriture séquentielle bornée ; aucun accès au fichier pour le producteur."""

    def __init__(self, fichier, maximum):
        self._fichier, self._maximum = fichier, maximum
        self._empreinte = hashlib.sha256()
        self._taille = 0
        self._depasse = False
        self._echec = False

    def write(self, donnees):
        if self._echec:
            raise OSError('export_write_failed')
        vue = memoryview(donnees).cast('B')
        if self._depasse or len(vue) > self._maximum - self._taille:
            self._depasse = True
            raise ErreurProtocole('export_too_large')
        # Même une écriture volumineuse ne nécessite aucune copie de l'archive.
        try:
            for debut in range(0, len(vue), TAILLE_BLOC):
                bloc = vue[debut:debut + TAILLE_BLOC]
                if self._fichier.write(bloc) != len(bloc):
                    raise OSError('export_write_failed')
                self._empreinte.update(bloc)
                self._taille += len(bloc)
        except OSError:
            self._echec = True
            raise
        return len(vue)

    def tell(self):
        return self._taille

    def flush(self):
        if self._echec:
            raise OSError('export_write_failed')
        try:
            self._fichier.flush()
        except OSError:
            self._echec = True
            raise


def _nom_export():
    return datetime.now(timezone.utc).strftime('requisition-%Y%m%d-%H%M%S.tar.gz')


@contextmanager
def _preparer_export(export, maximum):
    """Prépare entièrement la réponse ; ferme le fichier sur toute issue."""
    verifier_limite(maximum)
    nom = _nom_export()
    with tempfile.TemporaryFile(mode='w+b') as fichier:
        destination = _DestinationExport(fichier, maximum)
        bilan = export.produire(destination)
        # Un producteur qui intercepte le dépassement ne peut livrer un préfixe.
        if destination._depasse:
            raise ErreurProtocole('export_too_large')
        if (type(bilan) is not dict or set(bilan) != {'count', 'periode'}
                or type(bilan['count']) is not int or bilan['count'] <= 0):
            raise ValueError('invalid_export_metadata')
        periode = bilan['periode']
        if (type(periode) is not tuple or len(periode) != 2
                or any(type(jour) is not date for jour in periode)
                or periode[0] > periode[1]):
            raise ValueError('invalid_export_period')
        destination.flush()
        fichier.seek(0)
        yield _ArchiveBinaire(fichier, destination.tell(),
                              destination._empreinte.hexdigest(), nom,
                              bilan['count'], tuple(jour.isoformat() for jour in periode))


class EcheanceLecture(Exception):
    """Échéance globale de lecture de la requête dépassée."""


class EnteteExcessif(Exception):
    """Trop d'en-têtes, ou en-têtes trop volumineux."""


class Lecture:
    """Remplace rfile : échéance monotone globale et bornes des en-têtes.

    Lit directement la socket (tampon propre) : l'échéance est contrôlée avant
    chaque recv, y compris lorsqu'une ligne arrive octet par octet.
    """

    def __init__(self, connexion, delai, echeance, max_octets, max_lignes):
        self._connexion, self._delai = connexion, delai
        self._echeance = echeance
        self._max_octets, self._max_lignes = max_octets, max_lignes
        self._entetes, self._octets, self._lignes = True, 0, 0
        self._tampon = b''

    def _recevoir(self):
        reste = self._echeance - time.monotonic()
        if reste <= 0:
            raise EcheanceLecture()
        self._connexion.settimeout(min(self._delai, reste))
        return self._connexion.recv(65536)

    def readline(self, taille=-1):
        limite = taille if taille is not None and taille >= 0 else float('inf')
        while True:
            fin = self._tampon.find(b'\n') + 1
            if fin and fin <= limite:
                ligne, self._tampon = self._tampon[:fin], self._tampon[fin:]
                break
            if len(self._tampon) >= limite:
                ligne, self._tampon = self._tampon[:int(limite)], self._tampon[int(limite):]
                break
            donnees = self._recevoir()
            if not donnees:
                ligne, self._tampon = self._tampon, b''
                break
            self._tampon += donnees
            if self._entetes and self._octets + len(self._tampon) > self._max_octets + 65536:
                raise EnteteExcessif()
        if self._entetes:
            self._octets += len(ligne)
            self._lignes += 1
            if self._octets > self._max_octets or self._lignes > self._max_lignes + 1:
                raise EnteteExcessif()
            if ligne in (b'\r\n', b'\n', b'') and self._lignes > 1:
                self._entetes = False
        return ligne

    def read(self, taille=-1):
        while taille < 0 or len(self._tampon) < taille:
            donnees = self._recevoir()
            if not donnees:
                break
            self._tampon += donnees
        if taille < 0:
            taille = len(self._tampon)
        resultat, self._tampon = self._tampon[:taille], self._tampon[taille:]
        return resultat

    def close(self):
        pass


class Requete(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def setup(self):
        super().setup()
        serveur = self.server
        self.rfile.close()
        self.rfile = Lecture(self.connection, serveur.delai,
                             time.monotonic() + serveur.echeance, serveur.max_header_bytes,
                             serveur.max_headers)

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except EnteteExcessif:
            self._repondre(400, 'bad_request')
        except EcheanceLecture:
            self.close_connection = True
            self.server.journal.ecrire('warning', 'http_read_deadline')

    def log_message(self, *_):
        # http.server journalise normalement la ligne brute, potentiellement secrète.
        pass

    def __getattr__(self, nom):
        if nom.startswith('do_'):
            return self._traiter
        raise AttributeError(nom)

    def send_error(self, code, message=None, explain=None):
        # Les erreurs du parseur HTTP ne doivent jamais reprendre ses diagnostics.
        self._repondre(400, 'bad_request')

    def _adresse(self):
        valeurs = self.headers.get_all(self.server.entete_adresse, []) if hasattr(self, 'headers') else []
        if len(valeurs) == 1:
            try:
                if len(valeurs[0]) <= 64 and '%' not in valeurs[0]:
                    return str(ipaddress.ip_address(valeurs[0])), False
            except ValueError:
                pass
        return self.server.adresse_repli, True

    def _audit(self, code, statut, session, taille=None):
        """Entrée du journal d'activité, une seule par requête ; jamais d'effet sur la réponse."""
        activite = self.server.activite
        if activite is None or getattr(self, '_audite', False):
            return
        self._audite = True
        try:
            chemin = getattr(self, 'path', '')
            action = chemin[len(PREFIXE_API):] if chemin in self.server.chemins else None
            debut = getattr(self, '_debut', None)
            duree = 0 if debut is None else int((activite.monotone() - debut) * 1000)
            identite = self.server.sessions.identite(session) if session else None
            if identite is not None:
                admin, source = identite
            else:
                admin = None
                adresse, repli = self._adresse()
                source = None if repli else adresse
            executee = getattr(self, '_execute', False)
            activite.requete('action' if executee or code == 'ok' else 'refusal', action, code,
                             session=session, admin=admin, source=source, duree_ms=duree,
                             args=activite.args_pour(action, getattr(self, '_params', None))
                             if executee else None)
            champs = {'session': session or 0, 'step': 'received', 'ok': code == 'ok',
                      'http_status': statut, 'peer_uid': self.server.uid}
            if code != 'ok':
                champs['code'] = code
            if taille is not None:
                champs['bytes'] = taille
            activite.protocole(**champs)
        except Exception:
            pass

    def _repondre(self, statut, code, session=None):
        adresse, repli = self._adresse()
        action = (self.path[len(PREFIXE_API):]
                  if getattr(self, 'path', '') in self.server.chemins else None)
        self.server.journal.ecrire('info' if statut == 501 else 'warning',
                                  'http_request' if session is not None else 'http_refused',
                                  session=session, address=adresse, address_fallback=repli,
                                  action=action, result=code)
        contenu = encoder({'ok': False, 'error': {'code': code}})
        self._audit(code, statut, session, len(contenu))
        self.close_connection = True
        self.send_response_only(statut)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(contenu)))
        self.send_header('Connection', 'close')
        if statut == 405:
            self.send_header('Allow', 'POST')
        self.end_headers()
        if getattr(self, 'command', None) != 'HEAD':
            self.wfile.write(contenu)

    def handle_expect_100(self):
        # Aucun accusé intermédiaire avant validation de la requête.
        self._traiter()
        return False

    def _delai_ecriture(self):
        reste = self._fin_ecriture - time.monotonic()
        if reste <= 0:
            raise TimeoutError()
        self.connection.settimeout(min(self.server.delai, reste))

    def _entetes_succes(self, type_contenu, taille, supplementaires=()):
        entetes = [('Content-Type', type_contenu),
                   ('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'),
                   ('Connection', 'close'), *supplementaires]
        if taille is not None:
            entetes.insert(1, ('Content-Length', str(taille)))
        # Valider l'ensemble avant le premier octet, y compris les contrôles ASCII.
        if any(not isinstance(v, str) or not v or any(not 32 <= ord(c) <= 126 for c in v)
               for paire in entetes for v in paire):
            raise ValueError('invalid_export_header')
        self.close_connection = True
        self._fin_ecriture = time.monotonic() + self.server.delai
        self._delai_ecriture()
        self.send_response_only(200)
        for nom, valeur in entetes:
            self.send_header(nom, valeur)
        # end_headers écrit sur la socket : aucun second statut en cas de coupure.
        self._reponse_commencee = True
        self.end_headers()

    def _repondre_binaire(self, archive):
        if (not isinstance(archive.nom, str) or not NOM_EXPORT.fullmatch(archive.nom)
                or archive.type_contenu != 'application/gzip'
                or not isinstance(archive.sha256, str)
                or not re.fullmatch('[0-9a-f]{64}', archive.sha256)
                or type(archive.taille) is not int
                or not 0 < archive.taille <= self.server.export_max_octets):
            raise ValueError('invalid_export_response')
        self._entetes_succes(archive.type_contenu, archive.taille, (
            ('Content-Disposition', 'attachment; filename="' + archive.nom + '"'),
            ('X-Paresia-Sha256', archive.sha256)))
        reste = archive.taille
        while reste:
            bloc = archive.fichier.read(min(TAILLE_BLOC, reste))
            if not bloc:
                raise OSError('export_read_failed')
            self._delai_ecriture()
            self.wfile.write(bloc)
            reste -= len(bloc)

    def _executer_action(self, action, params, numero):
        traiter = self.server.actions.get(action)
        if traiter is None:
            return self._repondre(501, 'not_available', numero)
        export = action in self.server.exports
        place = False
        self._reponse_commencee = False
        self._execute = True
        try:
            if export:
                place = self.server._exports.acquire(blocking=False)
                if not place:
                    raise ErreurProtocole('export_busy')
            resultat = traiter(params, numero)
            if isinstance(resultat, FluxEvenements):
                if action not in self.server.suivis:
                    raise ErreurProtocole('unknown_action')
                self._audit('ok', 200, numero)
                resultat.servir(self)
            elif isinstance(resultat, ExportBinaire):
                if not export:
                    raise ErreurProtocole('unknown_action')
                with _preparer_export(resultat, self.server.export_max_octets) as archive:
                    self._repondre_binaire(archive)
                    self._audit('ok', 200, numero, archive.taille)
                self.server.journal.ecrire(
                    'info', 'export_delivered', session=numero, action=action,
                    size=archive.taille, sha256=archive.sha256,
                    count=archive.count, period=archive.periode)
            else:
                if (type(resultat) is not dict or resultat.get('ok') is not True
                        or set(resultat) - {'ok', 'data'}):
                    raise ValueError('invalid_action_response')
                # Pour l'export, seul le cas vide peut emprunter la voie JSON.
                if export and (resultat != {'ok': True, 'data': {'count': 0}}
                               or type(resultat['data']['count']) is not int):
                    raise ValueError('invalid_empty_export')
                contenu = encoder(resultat)
                self._entetes_succes('application/json', len(contenu))
                self._delai_ecriture()
                self.wfile.write(contenu)
                self._audit('ok', 200, numero, len(contenu))
        except Exception as erreur:
            code = (erreur.code if isinstance(erreur, ErreurProtocole)
                    and erreur.code in STATUTS else 'internal_error')
            if export:
                self.server.journal.ecrire('warning', 'export_failed',
                                          session=numero, action=action, code=code)
            self.close_connection = True
            if not self._reponse_commencee:
                self._repondre(STATUTS[code], code, numero)
            else:
                self._audit(code, 200, numero)
        finally:
            if place:
                self.server._exports.release()

    def _jeton(self):
        entetes = self.headers.get_all('X-Admin-Token', [])
        cookies = []
        for valeur in self.headers.get_all('Cookie', []):
            for partie in valeur.split(';'):
                nom, sep, contenu = partie.strip().partition('=')
                if nom == 'admin_token' and sep:
                    cookies.append(contenu.strip().strip('"'))
        if len(entetes) > 1 or len(cookies) > 1:
            return None, 'bad_request'
        if entetes and cookies and not hmac.compare_digest(
                entetes[0].encode('utf-8'), cookies[0].encode('utf-8')):
            return None, 'token_conflict'
        valeurs = entetes or cookies
        if not valeurs:
            return None, 'token_missing'
        numero = self.server.sessions.verifier(valeurs[0])
        return numero, None if numero is not None else 'token_unknown'

    def _origine_valide(self):
        # D15, RFC 6454 : un seul Host, un seul Origin, partie après « :// » égale à Host.
        hotes = self.headers.get_all('Host', [])
        origines = self.headers.get_all('Origin', [])
        if len(hotes) != 1 or len(origines) != 1 or not hotes[0]:
            return False
        _, separateur, reste = origines[0].partition('://')
        return bool(separateur) and minuscules_ascii(reste) == minuscules_ascii(hotes[0])

    def _traiter(self):
        numero = None
        self._debut = self.server.activite.monotone() if self.server.activite else None
        try:
            if self.command != 'POST':
                return self._repondre(405, 'bad_request')
            if self.path not in self.server.chemins:
                return self._repondre(404, 'unknown_action')
            numero, erreur = self._jeton()
            if erreur:
                return self._repondre(400 if erreur in {'bad_request', 'token_conflict'} else 403, erreur)
            longueurs = self.headers.get_all('Content-Length', [])
            if (self.headers.get_all('Transfer-Encoding') or len(longueurs) > 1
                    or (longueurs and not re.fullmatch(r'[0-9]{1,20}', longueurs[0]))):
                return self._repondre(400, 'bad_request', numero)
            longueur = int(longueurs[0]) if longueurs else 0
            if longueur > self.server.max_body:
                return self._repondre(413, 'body_too_large', numero)
            if not self._origine_valide():
                return self._repondre(403, 'origin_refused', numero)
            corps = self.rfile.read(longueur)
            if len(corps) != longueur:
                return self._repondre(400, 'bad_request', numero)
            params = decoder(corps) if corps else {}
            if 'session' in params:
                return self._repondre(400, 'bad_request', numero)
            self._params = params
            return self._executer_action(self.path[len(PREFIXE_API):], params, numero)
        except (EcheanceLecture, EnteteExcessif):
            raise
        except (ErreurProtocole, TimeoutError):
            if not getattr(self, '_reponse_commencee', False):
                self._repondre(400, 'bad_request', numero)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            # Même un échec du journal après l'envoi ne doit pas ajouter de JSON.
            if not getattr(self, '_reponse_commencee', False):
                self._repondre(500, 'internal_error', numero)


class FrontalHTTP(ThreadingHTTPServer):
    address_family = socket.AF_UNIX
    daemon_threads = True

    def __init__(self, configuration, sessions, journal, *, chemins=frozenset(),
                 exports=frozenset(), suivis=frozenset(), activite=None):
        """chemins : chemins complets routables (`/api/admin/<action>`) ; exports : actions à
        réponse binaire ; suivis : actions servies en flux différé. Tous vides par défaut."""
        self.sessions, self.journal = sessions, journal
        self.activite = activite
        self.exports, self.suivis = frozenset(exports), frozenset(suivis)
        self.chemins = (frozenset(chemins) | {PREFIXE_API + a for a in self.exports}
                        | {PREFIXE_API + a for a in self.suivis})
        self.uid = configuration['uid_lighttpd']
        self.gid = configuration['gid']
        self.delai = configuration['timeout_s']
        self.max_body = configuration['max_body']
        self.echeance = configuration['read_deadline_s']
        self.max_headers = configuration['max_headers']
        self.max_header_bytes = configuration['max_header_bytes']
        # Les appels directs (dont T004) peuvent omettre les nouvelles options.
        self.export_max_octets = configuration.get('export_max_octets', 8388608)
        self.export_max_simultanes = configuration.get('export_max_simultanes', 2)
        verifier_limite(self.export_max_octets)
        verifier_limite(self.export_max_simultanes)
        self._exports = threading.BoundedSemaphore(self.export_max_simultanes)
        self._flux = set()
        self._verrou_flux = threading.Lock()
        self._arret_flux = False
        # Enregistrement interne avant démarrage : action -> callable(params, session).
        self.actions = {}
        self._places = threading.BoundedSemaphore(configuration['max_connexions'])
        # File d'écoute (listen) au moins égale à la limite : une rafale n'est pas perdue.
        self.request_queue_size = max(self.request_queue_size,
                                      configuration['max_connexions'])
        self.entete_adresse = configuration['client_ip_header']
        self.adresse_repli = configuration['fallback_ip']
        self._identite = None
        self._fil = None
        super().__init__(configuration['socket'], Requete, bind_and_activate=False)

    def server_bind(self):
        # HTTPServer.server_bind suppose une adresse TCP (hôte, port).
        # umask est global au processus : restauré même en cas d'erreur.
        ancien = os.umask(0o117)
        try:
            socketserver.TCPServer.server_bind(self)
        finally:
            os.umask(ancien)
        attributs = os.stat(self.server_address)
        self._identite = (attributs.st_dev, attributs.st_ino)
        os.chmod(self.server_address, 0o660)
        os.chown(self.server_address, -1, self.gid)

    def verify_request(self, request, client_address):
        try:
            pair = struct.unpack('3i', request.getsockopt(socket.SOL_SOCKET,
                                                        socket.SO_PEERCRED, 12))
            if pair[1] == self.uid:
                # settimeout avant acquire : une erreur ne doit pas perdre de place.
                request.settimeout(self.delai)
                if not self._places.acquire(blocking=False):
                    self.journal.ecrire('warning', 'http_connection_limit')
                    return False
                return True
        except OSError:
            pass
        self.journal.ecrire('warning', 'http_peer_refused',
                            address=self.adresse_repli, address_fallback=True)
        return False

    def process_request(self, request, client_address):
        # La place prise dans verify_request est rendue à la fin du fil.
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._places.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._places.release()

    def handle_error(self, request, client_address):
        self.journal.ecrire('error', 'http_connection_failed')

    def demarrer(self):
        try:
            self.server_bind()
            self.server_activate()
            self._fil = threading.Thread(target=self.serve_forever, daemon=True)
            self._fil.start()
        except BaseException:
            self.server_close()
            raise
        return self

    def server_close(self):
        super().server_close()
        if self._identite is not None:
            try:
                attributs = os.stat(self.server_address, follow_symlinks=False)
                if (attributs.st_dev, attributs.st_ino) == self._identite:
                    os.unlink(self.server_address)
            except FileNotFoundError:
                pass
            self._identite = None

    def inscrire_flux(self, flux):
        with self._verrou_flux:
            if self._arret_flux:
                raise ErreurProtocole('peer_unavailable')
            self._flux.add(flux)

    def desinscrire_flux(self, flux):
        with self._verrou_flux:
            self._flux.discard(flux)

    def arreter(self):
        with self._verrou_flux:
            self._arret_flux = True
            flux = tuple(self._flux)
        for suivi in flux:
            suivi.arreter()
        for suivi in flux:
            suivi.termine.wait()
        if self._fil is not None:
            self.shutdown()
            self._fil.join()
            self._fil = None
        self.server_close()
