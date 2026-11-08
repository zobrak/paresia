# SPDX-License-Identifier: AGPL-3.0-or-later
# Signature du défi de présence par ssh-keygen (clé privée servie par l'agent SSH) ;
# dépendances : bibliothèque standard seulement.
# Suivi des versions
#   0.1.12  2026-11-08  Message du défi, retrait de l'armure et signature par ssh-keygen.
import base64
import binascii
import math
import os
from pathlib import Path
import re
import subprocess

ESPACE = 'paresia-presence'
MAX_SIGNATURE = 2048
_HEXA = re.compile(r'[0-9a-f]{64}')
_ADMIN = re.compile(r'[A-Za-z0-9._@-]{1,64}')
_DEBUT = b'-----BEGIN SSH SIGNATURE-----'
_FIN = b'-----END SSH SIGNATURE-----'
_PREFIXE = b'SSHSIG\x00\x00\x00\x01'


class ErreurSignature(Exception):
    """Porte seulement une clé de catalogue ui_presence_* ; jamais de sortie d'outil."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def message_defi(defi, admin):
    """Octets signés, construits par l'application seule."""
    if (not isinstance(defi, str) or _HEXA.fullmatch(defi) is None
            or not isinstance(admin, str) or _ADMIN.fullmatch(admin) is None):
        raise ErreurSignature('ui_presence_defi_invalide')
    return f'paresia-presence/1\n{defi}\n{admin}\n'.encode('utf-8')


def extraire_signature(enveloppe):
    """Retire seulement l'armure OpenSSH ; refuse tout préfixe, suffixe ou bruit."""
    if not isinstance(enveloppe, bytes) or len(enveloppe) > MAX_SIGNATURE + 256:
        raise ErreurSignature('ui_presence_signature_echec')
    lignes = enveloppe.splitlines()
    if len(lignes) < 3 or lignes[0] != _DEBUT or lignes[-1] != _FIN:
        raise ErreurSignature('ui_presence_signature_echec')
    contenu = b''.join(lignes[1:-1])
    try:
        if not 0 < len(contenu) <= MAX_SIGNATURE:
            raise ValueError()
        blob = base64.b64decode(contenu, validate=True)
        if not blob.startswith(_PREFIXE):
            raise ValueError()
        return contenu.decode('ascii')
    except (ValueError, UnicodeError, binascii.Error):
        raise ErreurSignature('ui_presence_signature_echec') from None


def _delai_valide(delai_s):
    return type(delai_s) in (int, float) and math.isfinite(delai_s) and delai_s > 0


def signer(defi, admin, namespace, cle_publique, ssh_keygen, delai_s):
    """ssh-keygen -Y sign : le chemin désigne la clé publique dont l'agent détient la privée.

    Aucune clé privée n'est lue, aucun fichier n'est écrit ; le message passe par
    l'entrée standard, la sortie et l'erreur de ssh-keygen ne sont jamais exposées.
    """
    if namespace != ESPACE:
        raise ErreurSignature('ui_presence_espace_refuse')
    contenu = message_defi(defi, admin)
    if not _delai_valide(delai_s):
        raise ErreurSignature('ui_presence_defi_delai')
    if (not isinstance(cle_publique, (str, os.PathLike)) or Path(cle_publique).suffix != '.pub'
            or not isinstance(ssh_keygen, (str, os.PathLike)) or not os.fspath(ssh_keygen)
            or not os.environ.get('SSH_AUTH_SOCK')):
        raise ErreurSignature('ui_presence_signature_echec')
    commande = [os.fspath(ssh_keygen), '-Y', 'sign', '-n', ESPACE,
                '-f', str(Path(cle_publique).absolute())]
    try:
        resultat = subprocess.run(commande, input=contenu, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, timeout=delai_s, check=False)
    except subprocess.TimeoutExpired:
        raise ErreurSignature('ui_presence_defi_delai') from None
    except (OSError, ValueError):
        raise ErreurSignature('ui_presence_signature_echec') from None
    if resultat.returncode:
        raise ErreurSignature('ui_presence_signature_echec')
    return extraire_signature(resultat.stdout)
