# SPDX-License-Identifier: AGPL-3.0-or-later
# Signatures jetables de test ; dépendances : cryptography et bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha.41  2026-11-06  Constructeur indépendant SSHSIG et fichier public temporaire (D28).
import base64
import hashlib
import os
from pathlib import Path
import struct
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa, utils


VARIANTES = ('ssh-ed25519', 'ecdsa-sha2-nistp256', 'ecdsa-sha2-nistp384',
             'ecdsa-sha2-nistp521', 'rsa-sha2-256', 'rsa-sha2-512')


def chaine(valeur):
    return struct.pack('>I', len(valeur)) + valeur


def mpint(nombre):
    octets = nombre.to_bytes((nombre.bit_length() + 7) // 8, 'big')
    if octets and octets[0] & 128:
        octets = b'\0' + octets
    return chaine(octets)


class Signataire:
    """Clé privée uniquement en mémoire ; seul le blob public est écrit par le banc."""
    def __init__(self, variante='ssh-ed25519', *, bits=2048):
        self.variante = variante
        if variante == 'ssh-ed25519':
            self.privee = ed25519.Ed25519PrivateKey.generate()
        elif variante.startswith('ecdsa-'):
            courbe, self.hash_ec = {
                'ecdsa-sha2-nistp256': (ec.SECP256R1, hashes.SHA256),
                'ecdsa-sha2-nistp384': (ec.SECP384R1, hashes.SHA384),
                'ecdsa-sha2-nistp521': (ec.SECP521R1, hashes.SHA512),
            }[variante]
            self.privee = ec.generate_private_key(courbe())
        else:
            self.privee = rsa.generate_private_key(public_exponent=65537, key_size=bits)
        self.pub = self.privee.public_key().public_bytes(
            serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
        self.genre, b64 = self.pub.split()
        self.blob = base64.b64decode(b64)

    def ligne(self, admin='alice@site'):
        return self.pub.decode('ascii') + ' ' + admin + '\n'

    def signer(self, message, namespace='paresia-presence', *, hachage=b'sha512',
               reserve=b'', version=1, algorithme=None, publique=None, magic=b'SSHSIG'):
        espace = namespace.encode('utf-8')
        donnees = (magic + chaine(espace) + chaine(reserve) + chaine(hachage)
                   + chaine(hashlib.new(hachage.decode('ascii'), message).digest()))
        algo = algorithme or self.variante.encode('ascii')
        if self.genre == b'ssh-ed25519':
            signature = self.privee.sign(donnees)
        elif self.genre == b'ssh-rsa':
            condensat = {b'rsa-sha2-256': hashes.SHA256, b'rsa-sha2-512': hashes.SHA512,
                         b'ssh-rsa': hashes.SHA1}.get(algo, hashes.SHA512)
            signature = self.privee.sign(donnees, padding.PKCS1v15(), condensat())
        else:
            der = self.privee.sign(donnees, ec.ECDSA(self.hash_ec()))
            r, s = utils.decode_dss_signature(der)
            signature = mpint(r) + mpint(s)
        blob = (magic + struct.pack('>I', version)
                + chaine(self.blob if publique is None else publique) + chaine(espace)
                + chaine(reserve) + chaine(hachage) + chaine(chaine(algo) + chaine(signature)))
        return base64.b64encode(blob).decode('ascii')

    def presence(self, defi, admin='alice@site'):
        message = f"paresia-presence/1\n{defi['challenge']}\n{admin}\n".encode('utf-8')
        return self.signer(message, defi['namespace'])


def attributs_root(fd):
    valeurs = list(os.fstat(fd))
    valeurs[4] = 0
    return os.stat_result(valeurs)


def preparer_cles(config, dossier, admin):
    signataire = Signataire()
    chemin = Path(dossier) / 'authorized_keys'
    chemin.write_text(signataire.ligne(admin), encoding='utf-8')
    chemin.chmod(0o600)
    config['signature']['authorized_keys'] = str(chemin)
    return signataire


def proprietaire_root():
    return patch('server.commun.cles_ssh._attributs', attributs_root)


def ouverture(client, admin, params=None):
    from server.pollux import requete
    if params:
        return client.appeler(requete('presence/session/open', params=params))
    identite = {'admin': admin, 'source': '2001:db8::1'}
    # Une seconde ouverture teste encore la forme/session sans demander un second défi.
    if not hasattr(client, 'preuve'):
        defi = client.appeler(requete('presence/session/challenge', params=identite))
        if not defi['ok']:
            return defi
        client.preuve = client.signataire.presence(defi['data'], admin)
    return client.appeler(requete('presence/session/open',
                                 params=dict(identite, signature=client.preuve)))
