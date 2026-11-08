# SPDX-License-Identifier: AGPL-3.0-or-later
# Encadrement et enveloppes jumeaux/1 ; dépendances : bibliothèque standard, texte.
# Suivi des versions
#   0.1.17  2026-11-08  ACTIONS calculé du catalogue du noyau ; domaines de greffons retirés.
#   0.1.15  2026-11-08  Domaine kernel (administration du noyau, servi par Romulus).
#   0.1.5  2026-11-07  valider() contre un ensemble admis (forme MOTIF_ACTION) ; charger_json_strict.
#   3.0.0-alpha.41  2026-11-06  Code origin_refused (contrôle Origin de Romulus, T038, D15).
#   3.0.0-alpha.40  2026-11-06  Domaine nisaba (T031, D87).
#   3.0.0-alpha.32  2026-11-06  Codes des exports binaires de Romulus (T013).
#   3.0.0-alpha.29  2026-11-06  Flux bornés par ligne et codes du relais (T027).
#   3.0.0-alpha  2026-11-05  Codes d'erreur des opérations d'identités de bunkerd (T005).
#   3.0.0-alpha  2026-11-05  Durcissement et corrections du cycle de revue 1.
#   3.0.0-alpha  2026-11-05  Validation, réponses et lecture bornée.
from dataclasses import dataclass
import json
import re
import time

from .catalogue import MOTIF_ACTION
from .noyau import CATALOGUE_NOYAU
from .texte import filtrer

PROTO = 'jumeaux/1'
MAX_LINE = 1024 * 1024
PLAFOND_LIMITE = 16 * 1024 * 1024
PLAFOND_DELAI = 3600
ACTIONS = frozenset(CATALOGUE_NOYAU.actions)
# Détails fixes : aucune donnée de la requête ni exception externe n'est interpolée.
DETAILS = {
    'challenge_required': 'Challenge required',
    'challenge_expired': 'Challenge expired',
    'signature_invalid': 'Invalid signature',
    'export_too_large': 'Export too large',
    'export_busy': 'Export busy',
    'command_failed': 'Command failed',
    'command_timeout': 'Command timed out',
    'command_busy': 'Too many concurrent commands',
    'unknown_action': 'Action not allowed',
    'bad_request': 'Invalid request',
    'internal_error': 'Internal error',
    'peer_unavailable': 'Peer unavailable',
    'token_missing': 'Token required',
    'token_unknown': 'Unknown token',
    'token_conflict': 'Conflicting tokens',
    'origin_refused': 'Origin refused',
    'body_too_large': 'Body too large',
    'not_available': 'Operation unavailable',
    'session_limit': 'Session limit reached',
    'auth_info_unavailable': 'Authentication information unavailable',
    'line_too_long': 'Line too long',
    'protocol_version_mismatch': 'Incompatible protocol version',
    'session_closed': 'Session closed',
    'relay_light_red': 'Relay light red',
    'invalid_identity': 'Invalid identity name',
    'unknown_identity': 'Unknown identity',
    'identity_exists': 'Identity already exists',
    'identity_unlocked': 'Identity is unlocked',
    'invalid_relays': 'Invalid relay list',
    'invalid_ncryptsec': 'Invalid encrypted key',
    'invalid_client': 'Invalid client key',
    'client_not_authorized': 'Client not authorized',
    'invalid_timeout': 'Invalid timeout',
    'confirmation_mismatch': 'Confirmation mismatch',
    'relay_identity_protected': 'Relay identity cannot be removed',
    'not_relay_key': 'Identity is not the relay key',
    'bad_passphrase': 'Passphrase refused',
    'invalid_pubkeys': 'Invalid public key list',
    'invalid_passphrase': 'Invalid passphrase',
    'pubkey_mismatch': 'Public key mismatch',
    'log_n_too_high': 'Key derivation cost too high',
}
CODES_ERREUR = frozenset(DETAILS)


class ErreurProtocole(Exception):
    """Erreur stable ; fermer indique si le transport doit être interrompu."""

    def __init__(self, code='bad_request', identifiant=None, fermer=False):
        super().__init__(code)
        self.code = code
        self.identifiant = identifiant
        self.fermer = fermer


def verifier_limite(max_line):
    if type(max_line) is not int or not 1 <= max_line <= PLAFOND_LIMITE:
        raise ValueError('invalid_max_line')


def verifier_delai(delai):
    if type(delai) not in (int, float) or not 0 < delai <= PLAFOND_DELAI:
        raise ValueError('invalid_timeout')


class LectureAvecEcheance:
    """Échéance monotone commune aux lectures et à l'envoi de la réponse.

    Le traitement métier doit respecter cette échéance s'il bloque ; aucun
    mécanisme Python sûr ne permet d'interrompre arbitrairement son fil.
    """
    def __init__(self, sock, echeance):
        self.sock, self.echeance = sock, echeance

    def regler_delai(self):
        restant = self.echeance - time.monotonic()
        if restant <= 0:
            raise TimeoutError()
        self.sock.settimeout(restant)

    def recv_into(self, destination):
        self.regler_delai()
        return self.sock.recv_into(destination)


def lire_ligne(source, max_line=MAX_LINE):
    """Lit recv_into (socket) ou readinto (flux binaire non tamponné).

    La limite inclut le LF. Le tampon fixe contient au plus max_line octets.
    À saturation, le dernier octet est réutilisé pour détecter un dépassement,
    sans conserver max_line + 1 octets. Aucun préchargement de la ligne suivante.
    EOF sans LF est illisible ; EOF entre deux lignes renvoie None.
    """
    verifier_limite(max_line)
    tampon = bytearray(max_line)
    lire = source.recv_into if hasattr(source, 'recv_into') else source.readinto
    position = 0
    with memoryview(tampon) as vue:
        while True:
            index = min(position, max_line - 1)
            with vue[index:index + 1] as destination:
                taille = lire(destination)
            if not taille:
                if position:
                    raise ErreurProtocole()
                return None
            if position == max_line:
                raise ErreurProtocole('line_too_long', fermer=True)
            position += 1
            if tampon[index] == 10:
                break
    del tampon[position:]
    return tampon


def _objet_unique(paires):
    objet = {}
    for cle, valeur in paires:
        if cle in objet:
            raise ValueError('duplicate_field')
        objet[cle] = valeur
    return objet


def _constante_interdite(_):
    raise ValueError('invalid_number')


def charger_json_strict(octets):
    """JSON strict (UTF-8) : refuse doublons, NaN et Infinity ; ValueError('invalid_json') sinon."""
    try:
        return json.loads(octets.decode('utf-8'), object_pairs_hook=_objet_unique,
                          parse_constant=_constante_interdite)
    except (ValueError, UnicodeError, RecursionError, AttributeError):
        raise ValueError('invalid_json') from None


def decoder(ligne):
    """JSON strict : refuse également doublons, NaN et Infinity."""
    try:
        objet = charger_json_strict(ligne)
    except ValueError:
        raise ErreurProtocole() from None
    if not isinstance(objet, dict):
        raise ErreurProtocole()
    return objet


def id_valide(identifiant):
    return isinstance(identifiant, str) and re.fullmatch(r'[0-9a-fA-F]{16}', identifiant) is not None


def valider(requete, actions_admises):
    """Valide l'enveloppe ; chaque démon valide ensuite ses propres params.

    L'action doit avoir la forme MOTIF_ACTION et appartenir à actions_admises, qui
    doit être un ensemble (set ou frozenset) : aucun repli sur la seule forme.
    """
    if type(actions_admises) not in (set, frozenset):
        raise ValueError('invalid_actions')
    if not isinstance(requete, dict) or not id_valide(requete.get('id')):
        raise ErreurProtocole()
    identifiant = requete['id']
    proto = requete.get('proto')
    if not isinstance(proto, str) or not re.fullmatch(r'jumeaux/[0-9]+', proto):
        raise ErreurProtocole(identifiant=identifiant)
    if proto.split('/')[1].lstrip('0') != '1':
        raise ErreurProtocole('protocol_version_mismatch', identifiant, True)
    if set(requete) != {'proto', 'id', 'session', 'action', 'params'}:
        raise ErreurProtocole(identifiant=identifiant)
    if (type(requete['session']) is not int or requete['session'] < 0
            or not isinstance(requete['params'], dict) or 'session' in requete['params']):
        raise ErreurProtocole(identifiant=identifiant)
    action = requete['action']
    if (not isinstance(action, str) or MOTIF_ACTION.match(action) is None
            or action not in actions_admises):
        raise ErreurProtocole('unknown_action', identifiant)
    return requete


def reponse(identifiant, data=None, *, code=None, stream=None):
    """Construit une réponse ; les détails proviennent exclusivement de DETAILS."""
    if identifiant is not None and not id_valide(identifiant):
        raise ValueError('invalid_id')
    resultat = {'id': identifiant, 'ok': code is None}
    if code is not None:
        resultat['error'] = {'code': code, 'detail': filtrer(DETAILS[code])}
    elif data is not None:
        resultat['data'] = data
    if stream is not None:
        if stream not in ('line', 'end'):
            raise ValueError('invalid_stream')
        resultat['stream'] = stream
    return resultat


def encoder(objet):
    return (json.dumps(objet, ensure_ascii=True, allow_nan=False,
                       separators=(',', ':')) + '\n').encode('utf-8')


@dataclass(frozen=True)
class Flux:
    """Réponses consommées à la demande ; fermeture confiée au serveur."""
    identifiant: str
    reponses: object

    def __post_init__(self):
        if not id_valide(self.identifiant):
            raise ValueError('invalid_id')

    def __iter__(self):
        return iter(self.reponses)

    def close(self):
        try:
            fermer = getattr(self.reponses, 'close', None)
            if fermer is not None:
                fermer()
        except Exception:
            pass


def valider_ligne_flux(resultat, identifiant):
    """Valide une ligne et remplace tout détail distant par le détail fixe."""
    if (not isinstance(resultat, dict) or resultat.get('id') != identifiant
            or type(resultat.get('ok')) is not bool):
        raise ErreurProtocole()
    if resultat['ok']:
        if (set(resultat) - {'id', 'ok', 'data', 'stream'}
                or resultat.get('stream') not in ('line', 'end')):
            raise ErreurProtocole()
        return resultat
    erreur = resultat.get('error')
    if (set(resultat) != {'id', 'ok', 'error'} or not isinstance(erreur, dict)
            or set(erreur) - {'code', 'detail'}
            or not isinstance(erreur.get('code'), str)
            or erreur['code'] not in CODES_ERREUR
            or ('detail' in erreur and not isinstance(erreur['detail'], str))):
        raise ErreurProtocole()
    return reponse(identifiant, code=erreur['code'])
