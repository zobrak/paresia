# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests SSHSIG ; dépendances : pytest, cryptography, OpenSSH facultatif.
# Suivi des versions
#   3.0.0-alpha.41  2026-11-06  Formats, algorithmes et interopérabilité OpenSSH (D28, D38).
import base64
import os
import shutil
import struct
import subprocess

import pytest

from aide_sshsig import Signataire, VARIANTES, chaine
from server.commun.sshsig import SignatureInvalide, verifier


MESSAGE = b'paresia-presence/1\n' + b'0' * 64 + b'\nalice@site\n'


def accepter(signataire, signature, **options):
    verifier(signature, MESSAGE, 'paresia-presence',
             lambda genre, cle: genre == signataire.genre and cle == signataire.blob, **options)


def champs(signature):
    brut = base64.b64decode(signature)
    resultat, pos = [], 10
    while pos < len(brut):
        taille = struct.unpack('>I', brut[pos:pos+4])[0]
        resultat.append(brut[pos+4:pos+4+taille])
        pos += 4 + taille
    assert pos == len(brut)
    return brut[:10], resultat


def remplacer(signature, index, valeur):
    entete, valeurs = champs(signature)
    valeurs[index] = valeur
    return base64.b64encode(entete + b''.join(map(chaine, valeurs))).decode()


@pytest.mark.parametrize('variante', VARIANTES)
@pytest.mark.parametrize('hachage', [b'sha256', b'sha512'])
@pytest.mark.parametrize('reserve', [b'', b'reserve-ignoree'])
def test_sshsig_valide(variante, hachage, reserve):
    cle = Signataire(variante)
    accepter(cle, cle.signer(MESSAGE, hachage=hachage, reserve=reserve))


@pytest.mark.parametrize('cas,cause', [
    ('version', 'bad_format'), ('zero', 'bad_format'), ('magic', 'bad_format'),
    ('namespace', 'bad_namespace'), ('vide', 'bad_namespace'), ('hash', 'bad_hash'),
    ('type', 'key_type'), ('algo', 'sig_algorithm'), ('signature', 'bad_signature'),
    ('message', 'bad_signature'), ('suite', 'bad_format'), ('longueur', 'bad_format'),
    ('base64', 'bad_format'), ('ascii', 'bad_format'), ('taille', 'bad_format'),
    ('cle_suite', 'bad_format'), ('sig_suite', 'bad_format'), ('cle_courte', 'bad_format'),
    ('sig_courte', 'bad_format'), ('inconnue', 'key_unknown'),
])
def test_sshsig_refus(cas, cause):
    cle = Signataire()
    signature = cle.signer(MESSAGE)
    if cas == 'version':
        signature = cle.signer(MESSAGE, version=2)
    elif cas == 'zero':
        signature = cle.signer(MESSAGE, version=0)
    elif cas == 'magic':
        signature = cle.signer(MESSAGE, magic=b'AUTRES')
    elif cas in ('namespace', 'vide'):
        signature = cle.signer(MESSAGE, namespace='autre' if cas == 'namespace' else '')
    elif cas == 'hash':
        signature = cle.signer(MESSAGE, hachage=b'sha1')
    elif cas == 'type':
        signature = cle.signer(MESSAGE, publique=chaine(b'ssh-dss'))
    elif cas == 'algo':
        signature = cle.signer(MESSAGE, algorithme=b'ssh-rsa')
    elif cas == 'message':
        signature = cle.signer(MESSAGE + b'x')
    elif cas == 'signature':
        brut = base64.b64decode(signature)
        signature = base64.b64encode(brut[:-1] + bytes([brut[-1] ^ 1])).decode()
    elif cas == 'suite':
        signature = base64.b64encode(base64.b64decode(signature) + b'x').decode()
    elif cas == 'longueur':
        signature = base64.b64encode(b'SSHSIG\0\0\0\1\xff\xff\xff\xff').decode()
    elif cas == 'base64':
        signature = '###='
    elif cas == 'ascii':
        signature = 'é'
    elif cas == 'taille':
        signature = 'A' * 2049
    elif cas == 'cle_suite':
        signature = remplacer(signature, 0, cle.blob + b'x')
    elif cas == 'sig_suite':
        signature = remplacer(signature, 4, champs(signature)[1][4] + b'x')
    elif cas == 'cle_courte':
        signature = remplacer(signature, 0, chaine(cle.genre) + chaine(b'x' * 31))
    elif cas == 'sig_courte':
        signature = remplacer(signature, 4, chaine(cle.genre) + chaine(b'x' * 63))
    elif cas == 'inconnue':
        cle = Signataire()
    with pytest.raises(SignatureInvalide, match=f'^{cause}$'):
        accepter(cle, signature)


def test_sshsig_troncatures():
    cle = Signataire()
    brut = base64.b64decode(cle.signer(MESSAGE))
    for taille in range(len(brut)):
        with pytest.raises(SignatureInvalide):
            accepter(cle, base64.b64encode(brut[:taille]).decode())


@pytest.mark.parametrize('genre', [b'ssh-dss', b'sk-ssh-ed25519@openssh.com',
    b'sk-ecdsa-sha2-nistp256@openssh.com', b'ssh-ed25519-cert-v01@openssh.com',
    b'ecdsa-sha2-nistp224'])
def test_types_non_admis(genre):
    cle = Signataire()
    with pytest.raises(SignatureInvalide, match='^key_type$'):
        accepter(cle, cle.signer(MESSAGE, publique=chaine(genre)))


@pytest.mark.parametrize('variante', ['rsa-sha2-256', 'rsa-sha2-512'])
def test_rsa_refus(variante):
    faible = Signataire(variante, bits=1024)
    with pytest.raises(SignatureInvalide, match='^key_weak$'):
        accepter(faible, faible.signer(MESSAGE))
    cle = Signataire(variante)
    with pytest.raises(SignatureInvalide, match='^sig_algorithm$'):
        accepter(cle, cle.signer(MESSAGE, algorithme=b'ssh-rsa'))


@pytest.mark.parametrize('rs', [chaine(b'\x80') + chaine(b'\1'),
    chaine(b'\0\1') + chaine(b'\1'), chaine(b'') + chaine(b'\1'),
    chaine(b'\1') + chaine(b'\1') + b'x'])
def test_ecdsa_mpint_refus(rs):
    cle = Signataire('ecdsa-sha2-nistp256')
    signature = remplacer(cle.signer(MESSAGE), 4, chaine(cle.genre) + chaine(rs))
    with pytest.raises(SignatureInvalide, match='^bad_format$'):
        accepter(cle, signature)


@pytest.mark.parametrize('variante', VARIANTES)
def test_signature_type_different(variante):
    cle = Signataire(variante)
    autre = b'ecdsa-sha2-nistp256' if cle.genre == b'ssh-ed25519' else b'ssh-ed25519'
    with pytest.raises(SignatureInvalide, match='^sig_algorithm$'):
        accepter(cle, cle.signer(MESSAGE, algorithme=autre))


@pytest.mark.parametrize('genre,bits', [('ed25519', None), ('ecdsa', 256),
                                      ('ecdsa', 384), ('ecdsa', 521), ('rsa', 4096)])
def test_sshsig_interop_openssh(genre, bits, tmp_path):
    executable = shutil.which('ssh-keygen')
    if executable is None:
        pytest.skip('Interopérabilité ignorée : ssh-keygen (openssh-client) absent')
    chemin = tmp_path / 'identite-jetable'
    commande = [executable, '-q', '-t', genre, '-N', '', '-f', str(chemin)]
    if bits:
        commande += ['-b', str(bits)]
    try:
        subprocess.run(commande, check=True, capture_output=True, timeout=30)
        chemin.chmod(0o600)  # réinitialise un éventuel masque ACL hérité du dossier
        # Aucun agent : la clé jetable est lue dans le fichier.
        environnement = {k: v for k, v in os.environ.items() if k != 'SSH_AUTH_SOCK'}
        resultat = subprocess.run([executable, '-Y', 'sign', '-f', str(chemin),
                                   '-n', 'paresia-presence'], input=MESSAGE, env=environnement,
                                  check=True, capture_output=True, timeout=10)
        lignes = resultat.stdout.splitlines()
        assert lignes[0] == b'-----BEGIN SSH SIGNATURE-----'
        assert lignes[-1] == b'-----END SSH SIGNATURE-----'
        signature = b''.join(lignes[1:-1]).decode('ascii')
        publique = chemin.with_suffix('.pub').read_bytes().split()
        verifier(signature, MESSAGE, 'paresia-presence',
                 lambda genre, blob: genre == publique[0] and blob == base64.b64decode(publique[1]))
    finally:
        chemin.unlink(missing_ok=True)
        chemin.with_suffix('.pub').unlink(missing_ok=True)
