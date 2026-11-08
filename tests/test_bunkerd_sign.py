# Tests de bunker/relay-key/sign-mute-list (T006) ; dépendances : pytest, bibliothèque standard, python3-cryptography.
# Suivi des versions
#   3.0.0-alpha.32  2026-11-06  Première version (T006) : BIP-340, NIP-49, NIP-01, refus, secrets, hors verrou.
#   3.0.0-alpha.41  2026-11-06  Multiplication scalaire secrète confiée à cryptography (D111) : équivalence, module de courbe absent.
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import threading
import unicodedata

import pytest
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

from bunkerd_outils import banc
from server.bunkerd import configuration, signature
from server.bunkerd.admin import Administration
from server.bunkerd.formats import BECH32
from server.commun.config import ErreurConfiguration

RACINE = Path(__file__).resolve().parents[1]
VECTEURS = RACINE / 'tests/vecteurs'
EXEMPLE = str(RACINE / 'server/conf/paresia.conf')
RELAIS = 'relais'
ACTION = 'bunker/relay-key/sign-mute-list'
CLES = ['%064x' % (i + 1) for i in range(3)]


# -- outils : bech32, NIP-49 (chiffrement), vérification BIP-340 -----------------------------------
def _polymod(valeurs):
    generateur = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    somme = 1
    for v in valeurs:
        haut = somme >> 25
        somme = ((somme & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            somme ^= generateur[i] if (haut >> i) & 1 else 0
    return somme


def bech32_ncryptsec(octets):
    bits = ''.join(format(o, '08b') for o in octets)
    bits += '0' * (-len(bits) % 5)
    donnees = [int(bits[i:i + 5], 2) for i in range(0, len(bits), 5)]
    hrp = 'ncryptsec'
    base = [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp] + donnees
    reste = _polymod(base + [0] * 6) ^ 1
    somme = [(reste >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + '1' + ''.join(BECH32[v] for v in donnees + somme)


def blob_nip49(secret, phrase, log_n, version=2, securite=2):
    sel, nonce = os.urandom(16), os.urandom(24)
    n = 1 << log_n
    cle = hashlib.scrypt(unicodedata.normalize('NFKC', phrase).encode(), salt=sel, n=n, r=8, p=1,
                         maxmem=128 * 8 * (n + 4) + (1 << 20), dklen=32)
    sous = signature._hchacha20(cle, nonce[:16])
    chiffre = ChaCha20Poly1305(sous).encrypt(b'\0\0\0\0' + nonce[16:], bytes(secret), bytes([securite]))
    return bytes([version, log_n]) + sel + nonce + bytes([securite]) + chiffre


def chiffrer(secret, phrase, log_n=2):
    return bech32_ncryptsec(blob_nip49(secret, phrase, log_n))


def verifier(cle, message, sig):
    """Vérification BIP-340 de référence (le résultat attendu vient du CSV officiel)."""
    p, n, g = signature._P, signature._N, signature._G
    x = int.from_bytes(cle, 'big')
    if x >= p:
        return False
    y = pow((x ** 3 + 7) % p, (p + 1) // 4, p)
    if y * y % p != (x ** 3 + 7) % p:
        return False
    point = (x, y if y % 2 == 0 else p - y)
    r, s = int.from_bytes(sig[:32], 'big'), int.from_bytes(sig[32:], 'big')
    if r >= p or s >= n:
        return False
    e = int.from_bytes(signature._hache_etiquetee('BIP0340/challenge', sig[:32] + cle + message), 'big') % n
    gauche = signature._multiplier(g, s)
    droite = signature._multiplier((point[0], p - point[1]), e) if e else None
    resultat = signature._additionner(gauche, droite)
    return resultat is not None and resultat[1] % 2 == 0 and resultat[0] == r


def lire_vecteur_nip49():
    valeurs = {}
    for ligne in (VECTEURS / 'nip49-vecteur.txt').read_text(encoding='utf-8').splitlines():
        if not ligne or ligne.startswith('#'):
            continue
        cle, _, valeur = ligne.partition('=')
        valeurs[cle.strip()] = valeur.replace('scan-secrets: vecteur-public', '').replace('#', '').strip()
    return valeurs


# -- préparation d'un banc --------------------------------------------------------------------
class Cas:
    def __init__(self, b, phrase='phrase de test ' + os.urandom(4).hex(), log_n=2, connue=True):
        self.b, self.phrase = b, phrase
        self.secret = os.urandom(32)
        self.publique = signature.cle_publique(self.secret).hex()
        self.ncryptsec = chiffrer(self.secret, phrase, log_n)
        b.depot.write_profile(RELAIS, {'clients': [], 'sec': self.ncryptsec, 'relays': ['wss://relais.example']})
        if connue:
            etat = b.depot.load_state()
            etat.setdefault(RELAIS, {})['pubkey'] = self.publique
            b.depot.save_state(etat)
        self.pauses = []
        self.admin = Administration(b.ops, b.journal, 20, pause=self.pauses.append,
                                    horloge=lambda: 1700000000.7, aleatoire=lambda n: bytes(range(n)))

    def appeler(self, **params):
        base = {'identity': RELAIS, 'passphrase': self.phrase, 'pubkeys': list(CLES)}
        base.update(params)
        requete = {'id': os.urandom(8).hex(), 'session': 7, 'action': ACTION, 'params': base}
        return self.admin.traiter(requete, None)


def code(reponse):
    assert reponse['ok'] is False, reponse
    return reponse['error']['code']


@pytest.fixture
def cas(tmp_path):
    with banc(tmp_path, GENERAL_RELAY_IDENTITY=RELAIS) as b:
        yield Cas(b)


# -- BIP-340 et NIP-49 -------------------------------------------------------------------------
def test_bip340_vecteurs():
    with open(VECTEURS / 'bip340-test-vectors.csv', newline='', encoding='utf-8') as f:
        lignes = list(csv.DictReader(f))
    assert len(lignes) >= 19
    for ligne in lignes:
        cle, message = bytes.fromhex(ligne['public key']), bytes.fromhex(ligne['message'])
        sig = bytes.fromhex(ligne['signature'])
        assert verifier(cle, message, sig) == (ligne['verification result'] == 'TRUE'), ligne['index']
        if ligne['secret key']:
            secret = bytes.fromhex(ligne['secret key'])
            assert signature.cle_publique(secret) == cle
            assert signature.signer_schnorr(message, secret, bytes.fromhex(ligne['aux_rand'])) == sig


def test_multiplication_secrete_equivalente():
    n = signature._N
    scalaires = [1, 2, n - 1, n - 2]
    scalaires += [int.from_bytes(os.urandom(32), 'big') % (n - 1) + 1 for _ in range(64)]
    for k in scalaires:
        assert signature._multiplier_secret(k) == signature._multiplier(signature._G, k)


def test_secret_sans_calcul_python(monkeypatch):
    with open(VECTEURS / 'bip340-test-vectors.csv', newline='', encoding='utf-8') as f:
        ligne = next(r for r in csv.DictReader(f) if r['secret key'])
    secret, message = bytes.fromhex(ligne['secret key']), bytes.fromhex(ligne['message'])
    sig = bytes.fromhex(ligne['signature'])

    def interdit(*args):
        raise RuntimeError('calcul python')

    monkeypatch.setattr(signature, '_multiplier', interdit)
    assert signature.cle_publique(secret) == bytes.fromhex(ligne['public key'])
    assert signature.signer_schnorr(message, secret, bytes.fromhex(ligne['aux_rand'])) == sig
    with pytest.raises(RuntimeError):
        signature.verifier_schnorr(message, bytes.fromhex(ligne['public key']), sig)


def test_nip49_vecteurs():
    v = lire_vecteur_nip49()
    assert v['log_n'] == '16'
    secret = signature.dechiffrer(v['ncryptsec'], v['password'], 20)
    assert bytes(secret).hex() == v['cle_privee_hex']
    entree, sortie = bytes.fromhex(v['nfkc_entree_utf8_hex']), bytes.fromhex(v['nfkc_sortie_utf8_hex'])
    assert unicodedata.normalize('NFKC', entree.decode()).encode() == sortie
    # La phrase non normalisée et sa forme NFKC déchiffrent la même clé.
    secret = os.urandom(32)
    ncryptsec = chiffrer(secret, sortie.decode())
    assert bytes(signature.dechiffrer(ncryptsec, entree.decode(), 20)) == secret
    # Chiffrer puis déchiffrer une clé de test.
    assert bytes(signature.dechiffrer(chiffrer(secret, 'autre'), 'autre', 20)) == secret


def test_nip49_refus():
    secret = os.urandom(32)
    for blob in (blob_nip49(secret, 'x', 2, version=1), blob_nip49(secret, 'x', 2)[:-1],
                 blob_nip49(secret, 'x', 2) + b'\0'):
        with pytest.raises(signature.ErreurSignature) as erreur:
            signature.dechiffrer(bech32_ncryptsec(blob), 'x', 20)
        assert erreur.value.code == 'bad_passphrase'
    haut = bytearray(blob_nip49(secret, 'x', 2))
    haut[1] = 21
    with pytest.raises(signature.ErreurSignature) as erreur:
        signature.dechiffrer(bech32_ncryptsec(bytes(haut)), 'x', 20)
    assert erreur.value.code == 'log_n_too_high'
    # log_n 20 admis : seul le contrôle du plafond est exercé (aucun scrypt de 1 Gio ici).
    haut[1] = 20
    original = signature._scrypt
    try:
        signature._scrypt = lambda *a: (_ for _ in ()).throw(RuntimeError('atteint'))
        with pytest.raises(RuntimeError):
            signature.dechiffrer(bech32_ncryptsec(bytes(haut)), 'x', 20)
    finally:
        signature._scrypt = original
    with pytest.raises(signature.ErreurSignature) as erreur:
        signature.dechiffrer(chiffrer(secret, 'bonne'), 'mauvaise', 20)
    assert erreur.value.code == 'bad_passphrase'


# -- événement ---------------------------------------------------------------------------------
def test_evenement_nip01(cas):
    reponse = cas.appeler()
    evenement = reponse['data']['event']
    assert list(evenement) == ['id', 'pubkey', 'created_at', 'kind', 'tags', 'content', 'sig']
    assert evenement['kind'] == 10000 and evenement['content'] == ''
    assert evenement['tags'] == [['p', c] for c in CLES]
    assert evenement['created_at'] == 1700000000 and evenement['pubkey'] == cas.publique
    serie = json.dumps([0, cas.publique, 1700000000, 10000, [['p', c] for c in CLES], ''],
                       separators=(',', ':'), ensure_ascii=False).encode()
    assert evenement['id'] == hashlib.sha256(serie).hexdigest()
    assert re.fullmatch('[0-9a-f]{128}', evenement['sig'])


def test_signature_verifiable(cas):
    evenement = cas.appeler(pubkeys=[])['data']['event']
    assert evenement['tags'] == []
    assert verifier(bytes.fromhex(evenement['pubkey']), bytes.fromhex(evenement['id']),
                    bytes.fromhex(evenement['sig']))


def test_sign_pubkeys(cas):
    assert cas.appeler(pubkeys=[])['ok']
    cinq_cents = ['%064x' % (i + 1) for i in range(500)]
    assert cas.appeler(pubkeys=cinq_cents)['ok']
    for mauvais in (cinq_cents + ['%064x' % 999], ['ab' * 32, 'ab' * 32], ['AB' * 32],
                    ['npub1' + 'q' * 58], ['ab' * 31], 'ab' * 32, [1], [None], [['ab' * 32]], None,
                    ['ab' * 32 + '\n']):
        assert code(cas.appeler(pubkeys=mauvais)) == 'invalid_pubkeys', mauvais
    assert cas.pauses == []


def test_sign_refus(cas, monkeypatch):
    assert code(cas.appeler(identity='autre')) == 'not_relay_key'
    assert code(cas.appeler(identity='Bad Name')) == 'invalid_identity'
    assert code(cas.appeler(passphrase='')) == 'invalid_passphrase'
    assert code(cas.appeler(passphrase=3)) == 'invalid_passphrase'
    assert code(cas.appeler(passphrase='\ud800')) == 'invalid_passphrase'
    assert code(cas.appeler(event={'kind': 1})) == 'bad_request'
    requete = {'id': os.urandom(8).hex(), 'session': 1, 'action': ACTION, 'params': {'identity': RELAIS}}
    assert code(cas.admin.traiter(requete, None)) == 'bad_request'
    assert cas.pauses == []
    # Passphrase fausse : pause de 2 s, aucun événement.
    reponse = cas.appeler(passphrase='fausse')
    assert code(reponse) == 'bad_passphrase' and 'data' not in reponse and cas.pauses == [2.0]
    # ncryptsec altéré.
    profil = cas.b.depot.read_profile(RELAIS)
    altere = profil['sec'][:-1] + ('q' if profil['sec'][-1] != 'q' else 'p')
    cas.b.depot.write_profile(RELAIS, dict(profil, sec=altere))
    assert code(cas.appeler()) == 'bad_passphrase' and cas.pauses == [2.0, 2.0]
    cas.b.depot.write_profile(RELAIS, profil)
    # log_n trop haut : refus avant tout scrypt, sans pause.
    monkeypatch.setattr(signature, '_scrypt', lambda *a: pytest.fail('scrypt appelé'))
    haut = bytearray(blob_nip49(cas.secret, cas.phrase, 2))
    haut[1] = 21
    cas.b.depot.write_profile(RELAIS, dict(profil, sec=bech32_ncryptsec(bytes(haut))))
    assert code(cas.appeler()) == 'log_n_too_high' and len(cas.pauses) == 2
    cas.b.depot.write_profile(RELAIS, profil)
    # Clé publique inconnue : refus sans déchiffrement (scrypt interdit ci-dessus).
    etat = cas.b.depot.load_state()
    etat[RELAIS].pop('pubkey')
    cas.b.depot.save_state(etat)
    assert code(cas.appeler()) == 'pubkey_mismatch'
    monkeypatch.undo()
    # Clé dérivée différente de la clé connue.
    etat[RELAIS]['pubkey'] = signature.cle_publique(os.urandom(32)).hex()
    cas.b.depot.save_state(etat)
    assert code(cas.appeler()) == 'pubkey_mismatch'
    # Identité de relais absente du bunker.
    cas.b.depot.remove_profile(RELAIS)
    assert code(cas.appeler()) == 'unknown_identity'


def test_sign_sans_secret(cas, capfd):
    reponses = [cas.appeler(), cas.appeler(passphrase='fausse'), cas.appeler(pubkeys=['x'])]
    secrets_ = [cas.phrase, 'fausse', cas.secret.hex(), cas.ncryptsec]
    sortie = json.dumps(reponses) + cas.b.flux.getvalue()
    sortie += ''.join(capfd.readouterr())
    for valeur in secrets_:
        assert valeur not in sortie
    lignes = [ligne for ligne in cas.b.lignes_journal() if ligne['event'] == 'admin_operation']
    assert [ligne['result'] for ligne in lignes] == ['ok', 'error', 'error']
    assert lignes[0]['keys'] == 3 and lignes[0]['identity'] == RELAIS and lignes[0]['action'] == ACTION
    assert lignes[1]['code'] == 'bad_passphrase' and lignes[2]['code'] == 'invalid_pubkeys'


def lire_arbre(racine):
    return {str(p.relative_to(racine)): p.read_bytes() for p in sorted(Path(racine).rglob('*')) if p.is_file()}


def test_sign_sans_trace(cas):
    avant = lire_arbre(cas.b.home)
    assert cas.appeler()['ok']
    assert code(cas.appeler(passphrase='fausse')) == 'bad_passphrase'
    assert lire_arbre(cas.b.home) == avant
    # Identité déverrouillée (nak simulé, qui annonce sa propre clé publique) : signature possible.
    assert cas.b.sup.start_identity(RELAIS, bytearray(cas.b.phrase.encode()))['ok']
    etat = cas.b.depot.load_state()
    etat[RELAIS]['pubkey'] = cas.publique
    cas.b.depot.save_state(etat)
    avant = lire_arbre(cas.b.home)
    assert cas.appeler()['ok']
    assert lire_arbre(cas.b.home) == avant
    cas.b.sup.tout_verrouiller('shutdown')


def test_sign_hors_verrou(tmp_path, monkeypatch):
    with banc(tmp_path, GENERAL_RELAY_IDENTITY=RELAIS) as b:
        cas = Cas(b)
        assert b.demarrer_admin() is not None
        debut, liberer = threading.Event(), threading.Event()
        reel = signature._scrypt

        def lent(*args):
            debut.set()
            assert liberer.wait(10)
            return reel(*args)

        monkeypatch.setattr(signature, '_scrypt', lent)
        resultat = {}
        fil = threading.Thread(target=lambda: resultat.update(b.appeler(
            'relay-key/sign-mute-list', {'identity': RELAIS, 'passphrase': cas.phrase, 'pubkeys': CLES})))
        fil.start()
        try:
            assert debut.wait(10)
            liste = b.appeler('identity/list')
            assert liste['ok'] and liste['data']['identities'][0]['relay_key'] is True
        finally:
            liberer.set()
            fil.join(10)
        assert resultat['ok'] and resultat['data']['event']['pubkey'] == cas.publique


def test_sign_sans_cryptography(cas, monkeypatch):
    monkeypatch.setitem(sys.modules, 'cryptography.hazmat.primitives.ciphers.aead', None)
    assert code(cas.appeler()) == 'not_available'
    assert cas.pauses == []
    liste = cas.admin.traiter({'id': os.urandom(8).hex(), 'session': 1, 'action': 'bunker/identity/list',
                               'params': {}}, None)
    assert liste['ok']


def test_sign_sans_module_courbe(cas, monkeypatch):
    monkeypatch.setitem(sys.modules, 'cryptography.hazmat.primitives.asymmetric.ec', None)
    with pytest.raises(signature.ErreurSignature) as erreur:
        signature.cle_publique(os.urandom(32))
    assert erreur.value.code == 'not_available'
    assert code(cas.appeler()) == 'not_available'
    assert cas.pauses == []
    liste = cas.admin.traiter({'id': os.urandom(8).hex(), 'session': 1, 'action': 'bunker/identity/list',
                               'params': {}}, None)
    assert liste['ok']


def test_secret_hors_intervalle_sans_cryptography(monkeypatch):
    def interdit(k):
        raise AssertionError('cryptography appelée')

    monkeypatch.setattr(signature, '_multiplier_secret', interdit)
    for valeur in (0, signature._N, 2 ** 256 - 1):
        secret = valeur.to_bytes(32, 'big')
        with pytest.raises(signature.ErreurSignature) as erreur:
            signature.cle_publique(secret)
        assert erreur.value.code == 'bad_passphrase'
        with pytest.raises(signature.ErreurSignature) as erreur:
            signature.signer_schnorr(bytes(32), secret, bytes(32))
        assert erreur.value.code == 'bad_passphrase'


def test_vecteurs_scan():
    spec = importlib.util.spec_from_file_location('scan_secrets', RACINE / 'tools/hooks/scan_secrets.py')
    scan = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scan)
    for fichier in ('bip340-test-vectors.csv', 'nip49-vecteur.txt'):
        texte = (VECTEURS / fichier).read_text(encoding='utf-8')
        trouvailles = []
        scan.scan_text('tests/vecteurs/' + fichier, texte, trouvailles)
        assert trouvailles == [], fichier           # accepté comme le crochet le permet
    texte = (VECTEURS / 'nip49-vecteur.txt').read_text(encoding='utf-8')
    hors = []
    scan.scan_text('src/nip49.txt', texte, hors)    # même contenu hors du dossier : refusé
    assert hors


def test_sign_sans_controles(cas):
    reponse = cas.appeler(identity='rel\x1b[31mais')
    assert code(reponse) == 'invalid_identity'
    sortie = json.dumps(reponse) + cas.b.flux.getvalue()
    assert '\x1b' not in sortie and 'rel' not in cas.b.flux.getvalue().replace('relay', '')
    assert 'identity' not in cas.b.lignes_journal()[-1]


# -- configuration et source -------------------------------------------------------------------
def test_option_log_n():
    def lire(valeur):
        return configuration(['--config', EXEMPLE], {'PARESIA_BUNKERD_SIGNATURE_LOG_N': valeur})
    assert lire('20')['signature']['log_n'] == 20
    assert lire('12')['signature']['log_n'] == 12
    for mauvais in ('21', '0', '-1', 'x'):
        with pytest.raises(ErreurConfiguration) as erreur:
            lire(mauvais)
        assert erreur.value.code == 'config_invalid'
    with pytest.raises(ErreurConfiguration) as erreur:
        lire('21')
    assert '21' not in str(erreur.value)
    assert configuration(['--config', EXEMPLE], {})['signature']['log_n'] == 20


def test_signature_sans_lecture_directe_de_la_configuration():
    texte = (RACINE / 'server/bunkerd/signature.py').read_text()
    for interdit in ('configparser', 'os.environ', 'getenv', 'subprocess', 'nak '):
        assert interdit not in texte


# -- cycle 1 : exactitude, maxmem, concurrence, vérification -----------------------------------
def test_reponse_succes_champs_exacts(cas):
    reponse = cas.appeler()
    assert reponse['ok'] is True and list(reponse['data']) == ['event']
    assert sorted(reponse['data']['event']) == sorted(
        ['id', 'pubkey', 'created_at', 'kind', 'tags', 'content', 'sig'])


def test_scrypt_maxmem_explicite(monkeypatch):
    appels = []
    reel = hashlib.scrypt

    def espion(*args, **kwargs):
        appels.append(kwargs)
        return reel(*args, **kwargs)

    monkeypatch.setattr(signature.hashlib, 'scrypt', espion)
    secret = os.urandom(32)
    ncryptsec = chiffrer(secret, 'p', 4)
    del appels[:]                       # le chiffrement du test appelle aussi scrypt
    assert bytes(signature.dechiffrer(ncryptsec, 'p', 20)) == secret
    assert len(appels) == 1 and appels[0]['n'] == 16 and appels[0]['maxmem'] >= 128 * 8 * 16
    assert isinstance(appels[0]['maxmem'], int)


def test_deux_signatures_simultanees(tmp_path):
    with banc(tmp_path, GENERAL_RELAY_IDENTITY=RELAIS) as b:
        cas = Cas(b)
        resultats = [None, None]
        jeux = [list(CLES), CLES[:1]]

        def lancer(i):
            resultats[i] = cas.appeler(pubkeys=jeux[i])

        fils = [threading.Thread(target=lancer, args=(i,)) for i in range(2)]
        for fil in fils:
            fil.start()
        for fil in fils:
            fil.join(30)
        for i in range(2):
            evenement = resultats[i]['data']['event']
            assert evenement['tags'] == [['p', c] for c in jeux[i]] and evenement['pubkey'] == cas.publique
            assert verifier(bytes.fromhex(evenement['pubkey']), bytes.fromhex(evenement['id']),
                            bytes.fromhex(evenement['sig']))


def test_pause_ne_bloque_pas_les_autres_operations(tmp_path):
    with banc(tmp_path, GENERAL_RELAY_IDENTITY=RELAIS) as b:
        cas = Cas(b)
        debut, liberer = threading.Event(), threading.Event()

        def pause(secondes):
            debut.set()
            assert liberer.wait(10)

        cas.admin.signataire.pause = pause
        resultat = {}
        fil = threading.Thread(target=lambda: resultat.update(cas.appeler(passphrase='fausse')))
        fil.start()
        try:
            assert debut.wait(10)
            requete = {'id': os.urandom(8).hex(), 'session': 1, 'action': 'bunker/identity/list', 'params': {}}
            assert cas.admin.traiter(requete, None)['ok']
        finally:
            liberer.set()
            fil.join(10)
        assert resultat['error']['code'] == 'bad_passphrase'


def test_dechiffrements_serialises(tmp_path, monkeypatch):
    with banc(tmp_path, GENERAL_RELAY_IDENTITY=RELAIS) as b:
        cas = Cas(b)
        actifs, maximum, verrou = [0], [0], threading.Lock()
        reel = signature.dechiffrer

        def suivi(*args):
            with verrou:
                actifs[0] += 1
                maximum[0] = max(maximum[0], actifs[0])
            try:
                threading.Event().wait(0.05)
                return reel(*args)
            finally:
                with verrou:
                    actifs[0] -= 1

        monkeypatch.setattr(signature, 'dechiffrer', suivi)
        pauses_actives = [0]
        pauses_max = [0]

        def pause(secondes):
            with verrou:
                pauses_actives[0] += 1
                pauses_max[0] = max(pauses_max[0], pauses_actives[0])
            threading.Event().wait(0.05)
            with verrou:
                pauses_actives[0] -= 1

        cas.admin.signataire.pause = pause
        phrases = [cas.phrase, 'fausse', cas.phrase, 'fausse']
        fils = [threading.Thread(target=cas.appeler, kwargs={'passphrase': p}) for p in phrases]
        for fil in fils:
            fil.start()
        for fil in fils:
            fil.join(30)
        assert maximum[0] == 1 and pauses_max[0] == 1


def test_signature_verifiee_avant_retour(cas, monkeypatch):
    # Une signature corrompue n'est jamais renvoyée : erreur interne, sans secret.
    reel = signature.signer_schnorr
    monkeypatch.setattr(signature, 'signer_schnorr',
                        lambda *a: bytes([reel(*a)[0] ^ 1]) + reel(*a)[1:])
    with pytest.raises(RuntimeError) as erreur:
        cas.appeler()
    assert cas.phrase not in str(erreur.value) and cas.secret.hex() not in str(erreur.value)
    lignes = [ligne for ligne in cas.b.lignes_journal() if ligne['event'] == 'admin_operation']
    assert lignes[-1]['code'] == 'internal_error'
    monkeypatch.setattr(signature, 'signer_schnorr', reel)
    assert cas.appeler()['ok']
