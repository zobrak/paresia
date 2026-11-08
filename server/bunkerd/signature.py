# SPDX-License-Identifier: AGPL-3.0-or-later
# Signature de la liste de sourdine du relais (bunker/relay-key/sign-mute-list) ; dépendances : bibliothèque
# standard, python3-cryptography (ChaCha20-Poly1305 et multiplication scalaire secp256k1, importées à
# l'appel, B1).
# Suivi des versions
#   3.0.0-alpha.32  2026-11-06  Première version (T006) : NIP-49 (déchiffrement), NIP-01, BIP-340.
#   3.0.0-alpha.32  2026-11-06  Cycle 1 : verrou dédié au déchiffrement et à la pause de 2 s ; signature vérifiée avant retour.
#   3.0.0-alpha.41  2026-11-06  Multiplication par un scalaire secret confiée à cryptography (D111).
#
# Sérialisation du déchiffrement : un verrou propre à Signataire (distinct du verrou global de
# profil, qui n'est pas tenu) entoure le scrypt et la pause de 2 s qui suit un bad_passphrase. Un
# seul déchiffrement est donc en cours à la fois (mémoire bornée à un scrypt, au plus 1 Gio) et
# les essais de passphrase sont espacés d'au moins 2 s ; les autres actions (identity/list...)
# restent servies pendant le scrypt et la pause. Une signature produite est vérifiée (BIP-340)
# avant d'être renvoyée ; un échec lève internal_error, sans secret.
#
# Limite de l'effacement (exigence 9) : la passphrase, la clé déchiffrée et la clé dérivée sont
# conservées dans des bytearray remis à zéro dans un finally ; Python ne permet pas d'effacer
# les chaînes, entiers et objets bytes intermédiaires (résultat de scrypt, entiers de la courbe),
# qui restent en mémoire jusqu'à leur libération par le ramasse-miettes. Rien n'est écrit sur
# disque, ni dans l'environnement, ni transmis à un processus externe.
# Multiplication scalaire (D111) : le produit du générateur par un scalaire secret (d0 et k0)
# est fait par la bibliothèque (ec.derive_private_key), qui suit l'échelle de Montgomery d'OpenSSL
# pour secp256k1 ; la version requise du paquet libssl3t64 est 3.5.7-1~deb13u3 ou plus (elle contient
# le correctif de la fuite de la voie générique). Cela n'établit pas un temps constant du programme
# entier. Restent en Python, donc non garantis à temps constant : les opérations modulaires sur entiers
# ((k + e*d) % _N, _N - d0) ; le passage du secret par un entier Python ; le scalaire, que cryptography
# ne marque pas BN_FLG_CONSTTIME ; l'effacement (entiers Python et objet clé privée de cryptography non
# effaçables par le programme). _multiplier et _additionner ne servent plus qu'à des valeurs publiques.
# Si cryptography ou son module de courbes manque : not_available, jamais de repli en Python pur pour
# un scalaire secret. Résidu admis ; seul Romulus, sur une socket locale à accès restreint, peut
# provoquer le calcul.
import hashlib
import hmac
import json
import os
import struct
import threading
import time
import unicodedata

from .formats import BECH32, HEX64_RE, NCRYPTSEC_RE, somme_bech32_valide
from .operations import Operations, Refus

ACTION = "relay-key/sign-mute-list"
KIND = 10000                       # liste de sourdine (NIP-51) ; seul kind signable
MAX_CLES = 500
PLAFOND_LOG_N = 20                 # 128 x 2^20 x 8 = 1 Gio (RFC 7914) ; défaut et maximum de l'option log_n
PAUSE_ECHEC = 2.0                  # secondes après une passphrase refusée
OCTETS_NCRYPTSEC = 91              # 1 version + 1 log_n + 16 sel + 24 nonce + 1 sécurité + 48 chiffré
CHAMPS = frozenset({"identity", "passphrase", "pubkeys"})


class ErreurSignature(Exception):
    """Échec interne portant un code stable de DETAILS."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def effacer(*tampons):
    for tampon in tampons:
        if isinstance(tampon, bytearray):
            tampon[:] = b"\x00" * len(tampon)


# -- BIP-340 (implémentation de référence, secp256k1) ----------------------------------------
_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_G = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
      0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)


def _additionner(a, b):
    if a is None:
        return b
    if b is None:
        return a
    if a[0] == b[0] and a[1] != b[1]:
        return None
    if a == b:
        lam = (3 * a[0] * a[0] * pow(2 * a[1], -1, _P)) % _P
    else:
        lam = ((b[1] - a[1]) * pow(b[0] - a[0], -1, _P)) % _P
    x = (lam * lam - a[0] - b[0]) % _P
    return x, (lam * (a[0] - x) - a[1]) % _P


def _multiplier(point, k):
    resultat = None
    for i in range(256):
        if (k >> i) & 1:
            resultat = _additionner(resultat, point)
        point = _additionner(point, point)
    return resultat


def _multiplier_secret(k):
    """k·G pour un scalaire secret 1 <= k <= _N - 1 : (x, y), calculé par la bibliothèque."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ec import SECP256K1, derive_private_key
    except ImportError:
        raise ErreurSignature("not_available") from None
    nombres = derive_private_key(k, SECP256K1()).public_key().public_numbers()
    return nombres.x, nombres.y


def _hache_etiquetee(etiquette, message):
    h = hashlib.sha256(etiquette.encode()).digest()
    return hashlib.sha256(h + h + message).digest()


def cle_publique(secret):
    """Clé publique x seule (32 octets) d'une clé secrète de 32 octets ; ErreurSignature sinon."""
    d0 = int.from_bytes(secret, "big")
    if not 1 <= d0 <= _N - 1:
        raise ErreurSignature("bad_passphrase")
    return _multiplier_secret(d0)[0].to_bytes(32, "big")


def signer_schnorr(message, secret, aleatoire):
    """Signature BIP-340 de message (32 octets) ; secret et aleatoire : 32 octets."""
    d0 = int.from_bytes(secret, "big")
    if not 1 <= d0 <= _N - 1:
        raise ErreurSignature("bad_passphrase")
    p = _multiplier_secret(d0)
    d = d0 if p[1] % 2 == 0 else _N - d0
    px = p[0].to_bytes(32, "big")
    t = (d ^ int.from_bytes(_hache_etiquetee("BIP0340/aux", aleatoire), "big")).to_bytes(32, "big")
    k0 = int.from_bytes(_hache_etiquetee("BIP0340/nonce", t + px + message), "big") % _N
    if k0 == 0:
        raise ErreurSignature("bad_passphrase")
    r = _multiplier_secret(k0)
    k = k0 if r[1] % 2 == 0 else _N - k0
    rx = r[0].to_bytes(32, "big")
    e = int.from_bytes(_hache_etiquetee("BIP0340/challenge", rx + px + message), "big") % _N
    return rx + ((k + e * d) % _N).to_bytes(32, "big")


def verifier_schnorr(message, cle, sig):
    """Vérification BIP-340 (message 32 octets, cle x seule 32 octets, sig 64 octets)."""
    x = int.from_bytes(cle, "big")
    if x >= _P:
        return False
    y = pow((x ** 3 + 7) % _P, (_P + 1) // 4, _P)
    if y * y % _P != (x ** 3 + 7) % _P:
        return False
    r, s = int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")
    if r >= _P or s >= _N:
        return False
    e = int.from_bytes(_hache_etiquetee("BIP0340/challenge", sig[:32] + cle + message), "big") % _N
    droite = _multiplier((x, _P - y if y % 2 == 0 else y), e) if e else None
    point = _additionner(_multiplier(_G, s), droite)
    return point is not None and point[1] % 2 == 0 and point[0] == r


# -- NIP-49 (version 2, XChaCha20-Poly1305, scrypt) ------------------------------------------
def _hchacha20(cle, nonce16):
    masque = 0xFFFFFFFF
    x = list(struct.unpack("<4I", b"expand 32-byte k")) + list(struct.unpack("<8I", cle)) \
        + list(struct.unpack("<4I", nonce16))

    def tourner(valeur, c):
        return ((valeur << c) & masque) | (valeur >> (32 - c))

    def quart(a, b, c, d):
        x[a] = (x[a] + x[b]) & masque
        x[d] = tourner(x[d] ^ x[a], 16)
        x[c] = (x[c] + x[d]) & masque
        x[b] = tourner(x[b] ^ x[c], 12)
        x[a] = (x[a] + x[b]) & masque
        x[d] = tourner(x[d] ^ x[a], 8)
        x[c] = (x[c] + x[d]) & masque
        x[b] = tourner(x[b] ^ x[c], 7)

    for _ in range(10):
        quart(0, 4, 8, 12)
        quart(1, 5, 9, 13)
        quart(2, 6, 10, 14)
        quart(3, 7, 11, 15)
        quart(0, 5, 10, 15)
        quart(1, 6, 11, 12)
        quart(2, 7, 8, 13)
        quart(3, 4, 9, 14)
    return struct.pack("<8I", *x[0:4], *x[12:16])


def decoder_ncryptsec(texte):
    """ncryptsec (bech32, somme de contrôle comprise) -> 91 octets ; bad_passphrase si altéré."""
    if not isinstance(texte, str) or not NCRYPTSEC_RE.fullmatch(texte):
        raise ErreurSignature("bad_passphrase")
    donnees = [BECH32.index(c) for c in texte[len("ncryptsec1"):]]
    hrp = "ncryptsec"
    valeurs = [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp] + donnees
    if not somme_bech32_valide(valeurs):
        raise ErreurSignature("bad_passphrase")
    accumulateur, bits, sortie = 0, 0, bytearray()
    for element in donnees[:-6]:
        accumulateur = (accumulateur << 5) | element
        bits += 5
        while bits >= 8:
            bits -= 8
            sortie.append((accumulateur >> bits) & 0xFF)
        accumulateur &= (1 << bits) - 1
    if len(sortie) != OCTETS_NCRYPTSEC or accumulateur != 0:
        raise ErreurSignature("bad_passphrase")
    return bytes(sortie)


def _scrypt(mot, sel, log_n):
    n = 1 << log_n
    # maxmem explicite : 128 x r x (N + p + 2) octets (OpenSSL) plus une marge de 1 Mio.
    return hashlib.scrypt(mot, salt=sel, n=n, r=8, p=1, maxmem=128 * 8 * (n + 1 + 2) + (1 << 20), dklen=32)


def dechiffrer(ncryptsec, passphrase, plafond):
    """Clé secrète (bytearray de 32 octets) ; lève ErreurSignature (code de DETAILS)."""
    donnees = decoder_ncryptsec(ncryptsec)
    version, log_n = donnees[0], donnees[1]
    if version != 2 or log_n < 1:
        raise ErreurSignature("bad_passphrase")
    if log_n > plafond:
        raise ErreurSignature("log_n_too_high")
    sel, nonce, securite, chiffre = donnees[2:18], donnees[18:42], donnees[42:43], donnees[43:]
    try:
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
    except ImportError:
        raise ErreurSignature("not_available") from None
    mot = bytearray(unicodedata.normalize("NFKC", passphrase).encode("utf-8"))
    cle = bytearray()
    sous_cle = bytearray()
    try:
        cle = bytearray(_scrypt(bytes(mot), sel, log_n))
        sous_cle = bytearray(_hchacha20(bytes(cle), nonce[:16]))
        try:
            clair = ChaCha20Poly1305(bytes(sous_cle)).decrypt(b"\x00\x00\x00\x00" + nonce[16:], chiffre, securite)
        except InvalidTag:
            raise ErreurSignature("bad_passphrase") from None
        return bytearray(clair)
    finally:
        effacer(mot, cle, sous_cle)


# -- Action --------------------------------------------------------------------------------
def cles_valides(valeur):
    if not isinstance(valeur, list) or len(valeur) > MAX_CLES:
        raise Refus("invalid_pubkeys", "")
    for cle in valeur:
        if not isinstance(cle, str) or not HEX64_RE.fullmatch(cle):
            raise Refus("invalid_pubkeys", "")
    if len(set(valeur)) != len(valeur):
        raise Refus("invalid_pubkeys", "")
    return valeur


def phrase_valide(valeur):
    if not isinstance(valeur, str) or not valeur:
        raise Refus("invalid_passphrase", "")
    try:
        unicodedata.normalize("NFKC", valeur).encode("utf-8")
    except UnicodeEncodeError:
        raise Refus("invalid_passphrase", "") from None
    return valeur


class Signataire:
    """Construit, signe et renvoie la liste de sourdine ; rien n'est conservé.

    pause, horloge et aleatoire ne sont injectés que par les tests (pause : attente de 2 s après
    une passphrase refusée, dans le fil de la connexion, hors verrou).
    """

    def __init__(self, ops, plafond_log_n=PLAFOND_LOG_N, *, pause=time.sleep, horloge=time.time,
                 aleatoire=os.urandom):
        self.ops = ops
        self.plafond = plafond_log_n
        self.pause = pause
        self.horloge = horloge
        self.aleatoire = aleatoire
        self.verrou_dechiffrement = threading.Lock()      # distinct du verrou global de profil

    def signer(self, params):
        """Renvoie {"event": {...}} ou lève Refus ; params a déjà ses trois champs, sans autre."""
        ops = self.ops
        identite = Operations.identite(params["identity"])
        passphrase = phrase_valide(params["passphrase"])
        cles = cles_valides(params["pubkeys"])
        if identite != ops.relay_identity:
            raise Refus("not_relay_key", "")
        with ops.sup.lock:                                  # lecture seule sous le verrou global
            ops.existante(identite)
            ncryptsec = ops.depot.read_profile(identite).get("sec")
            connue = ops.depot.load_state().get(identite, {}).get("pubkey")
        if not isinstance(connue, str) or not HEX64_RE.fullmatch(connue):
            raise Refus("pubkey_mismatch", "")
        secret = bytearray()
        try:
            with self.verrou_dechiffrement:      # un seul scrypt et une seule pause à la fois
                try:
                    secret = dechiffrer(ncryptsec, passphrase, self.plafond)  # hors verrou global
                    publique = cle_publique(secret).hex()
                except ErreurSignature as erreur:
                    if erreur.code == "bad_passphrase":
                        self.pause(PAUSE_ECHEC)
                    raise Refus(erreur.code, "") from None
            if not hmac.compare_digest(publique.encode(), connue.encode()):
                raise Refus("pubkey_mismatch", "")
            return {"event": self._evenement(publique, cles, secret)}
        finally:
            effacer(secret)

    def _evenement(self, publique, cles, secret):
        cree = int(self.horloge())
        etiquettes = [["p", cle] for cle in cles]
        serie = json.dumps([0, publique, cree, KIND, etiquettes, ""], separators=(",", ":"),
                           ensure_ascii=False).encode("utf-8")
        identifiant = hashlib.sha256(serie).digest()
        try:
            signature = signer_schnorr(identifiant, secret, self.aleatoire(32))
        except ErreurSignature as erreur:
            raise Refus(erreur.code, "") from None
        if not verifier_schnorr(identifiant, bytes.fromhex(publique), signature):
            raise RuntimeError("internal_error")      # sans secret ; admin.py journalise internal_error
        return {"id": identifiant.hex(), "pubkey": publique, "created_at": cree, "kind": KIND,
                "tags": etiquettes, "content": "", "sig": signature.hex()}
