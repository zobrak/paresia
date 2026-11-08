# SPDX-License-Identifier: AGPL-3.0-or-later
# Vérification SSHSIG ; bibliothèque standard et cryptography (chargée à la demande).
# Suivi des versions
#   3.0.0-alpha.41  2026-11-06  Preuve de possession SSH, types et tailles admis (D20, D28, D38).
"""PROTOCOL.sshsig ; encodages RFC 4251, 4253, 5656, 8709 et 8332.

Le message et l'espace de noms attendus viennent exclusivement de l'appelant.
Aucune donnée cryptographique n'est incluse dans les exceptions.
"""
import base64
import binascii
import hashlib


TYPES = frozenset({b'ssh-ed25519', b'ssh-rsa', b'ecdsa-sha2-nistp256',
                   b'ecdsa-sha2-nistp384', b'ecdsa-sha2-nistp521'})


class SignatureInvalide(ValueError):
    def __init__(self, cause):
        self.cause = cause
        super().__init__(cause)


def decoder_base64(signature, maximum):
    """Contrôle la forme ASCII et la taille du texte transporté, avant tout décodage."""
    if not isinstance(signature, str) or not 0 < len(signature) <= maximum:
        raise SignatureInvalide('bad_format')
    try:
        return base64.b64decode(signature.encode('ascii'), validate=True)
    except (UnicodeError, ValueError, binascii.Error):
        raise SignatureInvalide('bad_format') from None


def chaine(valeur):
    return len(valeur).to_bytes(4, 'big') + valeur


class Lecteur:
    """Lecteur borné : aucune longueur annoncée n'alloue de mémoire."""
    def __init__(self, contenu):
        self.contenu = contenu
        self.position = 0

    def octets(self, taille):
        fin = self.position + taille
        if fin > len(self.contenu):
            raise SignatureInvalide('bad_format')
        valeur = self.contenu[self.position:fin]
        self.position = fin
        return valeur

    def entier(self):
        return int.from_bytes(self.octets(4), 'big')

    def chaine(self):
        return self.octets(self.entier())

    def mpint(self):
        valeur = self.chaine()
        # Entiers strictement positifs, complément à deux minimal (RFC 4251 § 5).
        if (not valeur or valeur[0] & 0x80 or valeur == b'\0'
                or (len(valeur) > 1 and valeur[0] == 0 and not valeur[1] & 0x80)):
            raise SignatureInvalide('bad_format')
        return int.from_bytes(valeur, 'big')

    def fin(self):
        if self.position != len(self.contenu):
            raise SignatureInvalide('bad_format')


def verifier(signature, message, namespace, autoriser, *, maximum=2048):
    """Vérifie le blob base64 ; autoriser(type, blob) contrôle le fichier de confiance.

ImportError reste distinct pour que Pollux réponde not_available. Les autres
échecs portent uniquement une cause technique stable, jamais le blob reçu.
"""
    from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa, utils

    lecteur = Lecteur(decoder_base64(signature, maximum))
    if lecteur.octets(6) != b'SSHSIG' or lecteur.entier() != 1:
        raise SignatureInvalide('bad_format')
    publique, espace, reserve, hachage, interne = (lecteur.chaine() for _ in range(5))
    lecteur.fin()
    if not espace or espace != namespace.encode('utf-8'):
        raise SignatureInvalide('bad_namespace')
    if hachage not in (b'sha256', b'sha512'):
        raise SignatureInvalide('bad_hash')
    cle, sig = Lecteur(publique), Lecteur(interne)
    type_cle = cle.chaine()
    if type_cle not in TYPES:
        raise SignatureInvalide('key_type')
    algorithme, valeur = sig.chaine(), sig.chaine()
    sig.fin()
    admis = (b'rsa-sha2-256', b'rsa-sha2-512') if type_cle == b'ssh-rsa' else (type_cle,)
    if algorithme not in admis:
        raise SignatureInvalide('sig_algorithm')
    donnees = (b'SSHSIG' + chaine(espace) + chaine(reserve) + chaine(hachage)
               + chaine(hashlib.new(hachage.decode('ascii'), message).digest()))
    try:
        if type_cle == b'ssh-ed25519':
            octets = cle.chaine()
            if len(octets) != 32 or len(valeur) != 64:
                raise SignatureInvalide('bad_format')
            publique_crypto = ed25519.Ed25519PublicKey.from_public_bytes(octets)
            arguments = ()
        elif type_cle == b'ssh-rsa':
            e, n = cle.mpint(), cle.mpint()
            if n.bit_length() < 2048:
                raise SignatureInvalide('key_weak')
            publique_crypto = rsa.RSAPublicNumbers(e, n).public_key()
            taille = (publique_crypto.key_size + 7) // 8
            if not 0 < len(valeur) <= taille:
                raise SignatureInvalide('bad_format')
            valeur = valeur.rjust(taille, b'\0')
            arguments = (padding.PKCS1v15(), hashes.SHA256() if algorithme == b'rsa-sha2-256'
                         else hashes.SHA512())
        else:
            courbe = cle.chaine()
            if type_cle != b'ecdsa-sha2-' + courbe:
                raise SignatureInvalide('key_type')
            courbes = {b'nistp256': (ec.SECP256R1, hashes.SHA256),
                       b'nistp384': (ec.SECP384R1, hashes.SHA384),
                       b'nistp521': (ec.SECP521R1, hashes.SHA512)}
            classe, condensat = courbes[courbe]
            publique_crypto = ec.EllipticCurvePublicKey.from_encoded_point(classe(), cle.chaine())
            rs = Lecteur(valeur)
            valeur = utils.encode_dss_signature(rs.mpint(), rs.mpint())
            rs.fin()
            arguments = (ec.ECDSA(condensat()),)
        cle.fin()
        if not autoriser(type_cle, publique):
            raise SignatureInvalide('key_unknown')
        publique_crypto.verify(valeur, donnees, *arguments)
    except InvalidSignature:
        raise SignatureInvalide('bad_signature') from None
    except UnsupportedAlgorithm:
        raise SignatureInvalide('key_type') from None
    except SignatureInvalide:
        raise
    except (ValueError, TypeError, KeyError):
        raise SignatureInvalide('bad_format') from None
