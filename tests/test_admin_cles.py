# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests de la clé publique de l'administrateur ; clés jetables générées à l'exécution.
# Suivi des versions
#   3.0.0-alpha.41  2026-11-06  Types admis, refus, commentaire, ligne authorized_keys.
import base64
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
import pytest

from admin.app import cles
from admin.app.cles import ErreurCle, lire_cle_publique, ligne_authorized_keys

RACINE = Path(__file__).resolve().parent.parent
COMMANDE = '/usr/local/libexec/pollux-session'


def _openssh(cle):
    return cle.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode()


def _cles():
    return {
        'ed25519': _openssh(ed25519.Ed25519PrivateKey.generate()),
        'p256': _openssh(ec.generate_private_key(ec.SECP256R1())),
        'p384': _openssh(ec.generate_private_key(ec.SECP384R1())),
        'p521': _openssh(ec.generate_private_key(ec.SECP521R1())),
        'rsa': _openssh(rsa.generate_private_key(public_exponent=65537, key_size=2048)),
    }


CLES = _cles()


def _chaine(donnees):
    if isinstance(donnees, str):
        donnees = donnees.encode()
    return len(donnees).to_bytes(4, 'big') + donnees


def _ligne(type_cle, blob, commentaire='admin@poste'):
    texte = type_cle + ' ' + base64.b64encode(blob).decode()
    return texte + ('' if commentaire is None else ' ' + commentaire)


def _ecrire(tmp_path, contenu, nom='cle.pub'):
    chemin = tmp_path / nom
    chemin.write_bytes(contenu if isinstance(contenu, bytes) else contenu.encode())
    return chemin


def _code(chemin):
    with pytest.raises(ErreurCle) as erreur:
        lire_cle_publique(chemin)
    return erreur.value.code


@pytest.mark.parametrize('nom', list(CLES))
def test_types_admis(tmp_path, nom):
    chemin = _ecrire(tmp_path, CLES[nom] + ' admin.1@poste\n')
    cle = lire_cle_publique(chemin)
    type_cle, encode = CLES[nom].split(' ')
    assert (cle.type, cle.base64, cle.commentaire) == (type_cle, encode, 'admin.1@poste')
    assert ligne_authorized_keys(cle, COMMANDE) == (
        'restrict,command="%s" %s %s admin.1@poste' % (COMMANDE, type_cle, encode))
    assert encode not in repr(cle) and 'SHA256:' in repr(cle)
    assert not cle.empreinte().endswith('=')
    with pytest.raises(Exception):
        cle.commentaire = 'x'


def test_rsa_trop_courte(tmp_path):
    blob = _chaine('ssh-rsa') + _chaine(b'\x01\x00\x01') + _chaine(b'\x00' + b'\xff' * 127)
    assert _code(_ecrire(tmp_path, _ligne('ssh-rsa', blob))) == 'ui_cle_rsa_trop_courte'
    # octet de tête nul : 2047 bits utiles seulement
    blob = _chaine('ssh-rsa') + _chaine(b'\x03') + _chaine(b'\x00\x7f' + b'\xff' * 255)
    assert _code(_ecrire(tmp_path, _ligne('ssh-rsa', blob))) == 'ui_cle_rsa_trop_courte'


@pytest.mark.parametrize('type_cle', [
    'sk-ssh-ed25519@openssh.com', 'ssh-ed25519-cert-v01@openssh.com',
    'ssh-rsa-cert-v01@openssh.com', 'ssh-dss', 'inconnu'])
def test_types_refuses(tmp_path, type_cle):
    ligne = _ligne(type_cle, _chaine(type_cle) + _chaine(b'x' * 32))
    assert _code(_ecrire(tmp_path, ligne)) == 'ui_cle_type_refuse'


def _blob(nom):
    return base64.b64decode(CLES[nom].split(' ')[1])


@pytest.mark.parametrize('cas', [
    'type_different', 'identifiant_different', 'tronque', 'octets_en_trop',
    'base64_invalide', 'deux_lignes', 'sans_blob', 'espace_double'])
def test_illisible(tmp_path, cas):
    type_cle = 'ssh-ed25519'
    blob = _blob('ed25519')
    if cas == 'type_different':
        contenu = _ligne('ecdsa-sha2-nistp256', blob)
    elif cas == 'identifiant_different':
        p256 = _blob('p256')
        faux = p256[:p256.rindex(b'nistp256', 0, 40)] + b'nistp384' + p256[p256.rindex(b'nistp256', 0, 40) + 8:]
        assert faux.count(b'nistp384') == 1 and faux.count(b'nistp256') == 1
        contenu = _ligne('ecdsa-sha2-nistp256', faux)
    elif cas == 'tronque':
        contenu = _ligne(type_cle, blob[:-1])
    elif cas == 'octets_en_trop':
        contenu = _ligne(type_cle, blob + b'\x00')
    elif cas == 'base64_invalide':
        contenu = type_cle + ' @@@@ admin'
    elif cas == 'deux_lignes':
        contenu = CLES['ed25519'] + ' a\n' + CLES['ed25519'] + ' b\n'
    elif cas == 'sans_blob':
        contenu = type_cle
    else:
        contenu = type_cle + '  ' + base64.b64encode(blob).decode() + ' a'
    assert _code(_ecrire(tmp_path, contenu)) == 'ui_cle_illisible'


def test_illisible_fichier(tmp_path):
    long = CLES['ed25519'] + ' ' + 'a' * (16 * 1024)
    assert _code(_ecrire(tmp_path, long)) == 'ui_cle_illisible'
    cible = _ecrire(tmp_path, CLES['ed25519'] + ' a')
    lien = tmp_path / 'lien.pub'
    lien.symlink_to(cible)
    assert _code(lien) == 'ui_cle_illisible'
    assert _code(tmp_path) == 'ui_cle_illisible'
    fifo = tmp_path / 'fifo'
    os.mkfifo(fifo)
    assert _code(fifo) == 'ui_cle_illisible'
    assert _code(tmp_path / 'absent') == 'ui_cle_illisible'
    assert _code(_ecrire(tmp_path, b'\xff\xfe', 'binaire')) == 'ui_cle_illisible'


def test_cle_privee_refusee(tmp_path):
    entete = '-----' + 'BEGIN ' + 'OPENSSH ' + 'PRIVATE ' + 'KEY-----\n'
    secret = 'zzcorpszz'
    for contenu in (entete + secret + '\n', entete + secret * 5000,
                    'x ' + 'PRIVATE ' + 'KEY ' + secret):
        with pytest.raises(ErreurCle) as erreur:
            lire_cle_publique(_ecrire(tmp_path, contenu))
        assert erreur.value.code == 'ui_cle_privee_refusee'
        assert secret not in str(erreur.value) and secret not in repr(erreur.value)


@pytest.mark.parametrize('commentaire', [
    None, '', 'a' * 65, 'a b', 'a\x07b', 'a\x1bb', 'admin\r', 'adm!n', 'é'])
def test_commentaire_invalide(tmp_path, commentaire):
    contenu = CLES['ed25519'].split(' ')
    ligne = ' '.join(contenu[:2]) + ('' if commentaire is None else ' ' + commentaire)
    assert _code(_ecrire(tmp_path, ligne + '\n')) == 'ui_cle_commentaire_invalide'


def test_commentaire_limite(tmp_path):
    ligne = CLES['ed25519'] + ' ' + 'a' * 64
    assert lire_cle_publique(_ecrire(tmp_path, ligne)).commentaire == 'a' * 64


@pytest.mark.parametrize('commande', [
    'a"b', '/a b', 'relatif/pollux', '', '/a\\b', '/a"; rm', None])
def test_commande_invalide(tmp_path, commande):
    cle = lire_cle_publique(_ecrire(tmp_path, CLES['ed25519'] + ' a'))
    with pytest.raises(ErreurCle) as erreur:
        ligne_authorized_keys(cle, commande)
    assert erreur.value.code == 'ui_cle_commande_invalide'


def test_catalogues():
    codes = {'ui_cle_illisible', 'ui_cle_type_refuse', 'ui_cle_rsa_trop_courte',
             'ui_cle_commentaire_invalide', 'ui_cle_privee_refusee',
             'ui_cle_commande_invalide'}
    catalogues = [json.loads((RACINE / 'i18n' / (langue + '.json')).read_text('utf-8'))
                  for langue in ('fr-FR', 'en-US')]
    for catalogue in catalogues:
        assert all(catalogue.get(code) for code in codes)
    assert set(catalogues[0]) == set(catalogues[1])
    cles_ui = [k for k in catalogues[0] if k.startswith('ui_')]
    positions = [i for i, k in enumerate(catalogues[0]) if k.startswith('ui_')]
    assert positions == list(range(positions[0], positions[0] + len(cles_ui)))


def test_sans_import_graphique_ni_cryptography():
    source = (RACINE / 'admin' / 'app' / 'cles.py').read_text('utf-8')
    assert 'cryptography' not in source and 'PyQt6' not in source
    assert cles.PLAFOND == 16384
