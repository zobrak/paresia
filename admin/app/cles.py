# SPDX-License-Identifier: AGPL-3.0-or-later
# Clé publique de l'administrateur et ligne authorized_keys ; dépendances : bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha.41  2026-11-06  Lecture bornée de la clé publique et ligne à remettre à root.
import base64
import binascii
from dataclasses import dataclass
import hashlib
import os
import re
import stat

PLAFOND = 16 * 1024
TYPES_ECDSA = ('nistp256', 'nistp384', 'nistp521')
TYPES = ('ssh-ed25519', 'ssh-rsa') + tuple('ecdsa-sha2-' + i for i in TYPES_ECDSA)


class ErreurCle(Exception):
    """Erreur portant un code de catalogue ui_cle_* ; jamais de contenu du fichier."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ClePublique:
    type: str
    base64: str
    commentaire: str

    def empreinte(self):
        """SHA-256 du blob, base64 sans bourrage (format de ssh-keygen -l)."""
        blob = base64.b64decode(self.base64)
        condensat = base64.b64encode(hashlib.sha256(blob).digest()).decode('ascii')
        return 'SHA256:' + condensat.rstrip('=')

    def __repr__(self):
        return 'ClePublique(type=%r, empreinte=%r)' % (self.type, self.empreinte())


def _chaine(blob, position):
    """Chaîne SSH (uint32 de longueur puis octets) ; retourne (octets, position)."""
    if position + 4 > len(blob):
        raise ErreurCle('ui_cle_illisible')
    taille = int.from_bytes(blob[position:position + 4], 'big')
    fin = position + 4 + taille
    if fin > len(blob):
        raise ErreurCle('ui_cle_illisible')
    return blob[position + 4:fin], fin


def _controler_blob(type_cle, blob):
    """Analyse selon RFC 4253 § 6.6, RFC 5656 § 3.1 et RFC 8709."""
    annonce, position = _chaine(blob, 0)
    if annonce != type_cle.encode('ascii'):
        raise ErreurCle('ui_cle_illisible')
    if type_cle == 'ssh-ed25519':
        cle, position = _chaine(blob, position)
        if len(cle) != 32:
            raise ErreurCle('ui_cle_illisible')
    elif type_cle == 'ssh-rsa':
        _, position = _chaine(blob, position)
        module, position = _chaine(blob, position)
        longueur = int.from_bytes(module, 'big').bit_length()
        if position != len(blob):
            raise ErreurCle('ui_cle_illisible')
        if longueur < 2048:
            raise ErreurCle('ui_cle_rsa_trop_courte')
    else:
        identifiant, position = _chaine(blob, position)
        if identifiant != type_cle.removeprefix('ecdsa-sha2-').encode('ascii'):
            raise ErreurCle('ui_cle_illisible')
        point, position = _chaine(blob, position)
        if not point:
            raise ErreurCle('ui_cle_illisible')
    if position != len(blob):
        raise ErreurCle('ui_cle_illisible')


def _lire(chemin):
    try:
        descripteur = os.open(chemin, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except (OSError, ValueError, TypeError):
        raise ErreurCle('ui_cle_illisible') from None
    try:
        if not stat.S_ISREG(os.fstat(descripteur).st_mode):
            raise ErreurCle('ui_cle_illisible')
        contenu = b''
        while len(contenu) <= PLAFOND:
            morceau = os.read(descripteur, PLAFOND + 1 - len(contenu))
            if not morceau:
                break
            contenu += morceau
        return contenu
    except OSError:
        raise ErreurCle('ui_cle_illisible') from None
    finally:
        os.close(descripteur)


def lire_cle_publique(chemin):
    """Charge et contrôle la clé publique ; aucune clé privée n'est acceptée."""
    contenu = _lire(chemin)
    if contenu.startswith(b'-----BEGIN') or b'PRIVATE KEY' in contenu:
        raise ErreurCle('ui_cle_privee_refusee')
    if len(contenu) > PLAFOND:
        raise ErreurCle('ui_cle_illisible')
    try:
        texte = contenu.decode('utf-8')
    except UnicodeError:
        raise ErreurCle('ui_cle_illisible') from None
    texte = texte.removesuffix('\n')
    if '\n' in texte:
        raise ErreurCle('ui_cle_illisible')
    champs = texte.split(' ', 2)
    if len(champs) < 2 or not champs[0] or not champs[1]:
        raise ErreurCle('ui_cle_illisible')
    type_cle, encode = champs[0], champs[1]
    commentaire = champs[2] if len(champs) == 3 else ''
    if type_cle not in TYPES:
        raise ErreurCle('ui_cle_type_refuse')
    try:
        blob = base64.b64decode(encode, validate=True)
    except (binascii.Error, ValueError):
        raise ErreurCle('ui_cle_illisible') from None
    if base64.b64encode(blob).decode('ascii') != encode:
        raise ErreurCle('ui_cle_illisible')
    _controler_blob(type_cle, blob)
    if not re.fullmatch(r'[A-Za-z0-9._@-]{1,64}', commentaire):
        raise ErreurCle('ui_cle_commentaire_invalide')
    return ClePublique(type_cle, encode, commentaire)


def ligne_authorized_keys(cle, commande):
    """Ligne à remettre à root, reconstruite à partir des champs contrôlés."""
    if not isinstance(commande, str) or not re.fullmatch(r'/[A-Za-z0-9._/-]+', commande):
        raise ErreurCle('ui_cle_commande_invalide')
    return 'restrict,command="%s" %s %s %s' % (
        commande, cle.type, cle.base64, cle.commentaire)
