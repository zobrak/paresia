# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests du défi signé de Pollux ; dépendances : pytest, cryptography, bibliothèque standard.
# Suivi des versions
#   0.1.1  2026-11-07  Lecture de l'exemple avec les sections journal et métriques du socle.
#   3.0.0-alpha.41  2026-11-06  Défi, ouverture signée, rejeu, fichier des clés, robustesse, cert-authority, refus répété (D20, D28, D38).
import json
import os
from pathlib import Path
import re
import sys
import time
from unittest.mock import patch

import pytest

from aide_sshsig import Signataire, attributs_root, chaine
from server.commun.config import lire
from server.commun.jumeaux import CODES_ERREUR, DETAILS
from server.commun.serveur import ContexteConnexion
from server.pollux import SCHEMA, requete
from server.pollux.session import SCHEMA as SCHEMA_SESSION
from test_pollux_sessions import attendre, brut, code, journal_de, monter

RACINE = Path(__file__).resolve().parents[1]
EXEMPLE = RACINE / 'server' / 'conf' / 'paresia.conf'
IDENTITE = {'admin': 'Alice@site', 'source': '2001:db8::1'}


@pytest.fixture
def banc():
    with monter(max_line=8192) as p:     # une signature RSA de 4096 bits dépasse 512 octets
        p.fichier = Path(p.config['signature']['authorized_keys'])
        yield p


def defier(client, **identite):
    return client.appeler(requete('presence/session/challenge', params=dict(IDENTITE, **identite)))


def ouvrir_signe(client, signature, **identite):
    return client.appeler(requete('presence/session/open', params=dict(
        IDENTITE, signature=signature, **identite)))


def signer(signataire, reponse, admin='Alice@site', **options):
    donnees = reponse['data']
    message = f"paresia-presence/1\n{donnees['challenge']}\n{admin}\n".encode('utf-8')
    return signataire.signer(message, donnees['namespace'], **options)


def fermee(client):
    return client._socket.recv(1) == b''


def raisons(banc):
    return [e['reason'] for e in journal_de(banc) if e['event'] == 'auth_failed']


def refuse(banc, client, signature, attendu, raison=None):
    resultat = ouvrir_signe(client, signature)
    assert code(resultat) == attendu
    assert not banc.appels_r
    assert fermee(client)
    if raison is not None:
        assert raison in raisons(banc)


def test_defi_nominal(banc):
    a = banc.client()
    defi = defier(a)
    assert defi['ok']
    assert set(defi['data']) == {'challenge', 'namespace', 'expires_s'}
    assert re.fullmatch('[0-9a-f]{64}', defi['data']['challenge'])
    assert defi['data']['namespace'] == 'paresia-presence' and defi['data']['expires_s'] == 60
    resultat = ouvrir_signe(a, signer(banc.signataire, defi))
    assert resultat['ok'] and resultat['data']['token'] == banc.jeton
    assert banc.appels_r[0]['params'] == IDENTITE
    assert 'signature' not in json.dumps(banc.appels_r)
    assert 'auth_ok' in [e['event'] for e in journal_de(banc)]
    assert a.appeler(requete('presence/session/ping', resultat['data']['session']))['ok']


@pytest.mark.parametrize('variante', ['ssh-ed25519', 'ecdsa-sha2-nistp256', 'ecdsa-sha2-nistp384',
                                      'ecdsa-sha2-nistp521', 'rsa-sha2-256', 'rsa-sha2-512'])
def test_defi_tous_types(banc, variante):
    cle = Signataire(variante)
    banc.fichier.write_text(cle.ligne('Alice@site'), encoding='utf-8')
    a = banc.client()
    defi = defier(a)
    assert ouvrir_signe(a, signer(cle, defi))['ok']


def test_open_sans_defi(banc):
    a = banc.client()
    refuse(banc, a, 'YQ==', 'challenge_required', 'no_challenge')
    # Sans champ signature : forme invalide, sans fermeture, défi conservé.
    b = banc.client()
    defi = defier(b)
    assert code(b.appeler(requete('presence/session/open', params=IDENTITE))) == 'bad_request'
    assert ouvrir_signe(b, signer(banc.signataire, defi))['ok']


@pytest.mark.parametrize('signature', ['###', 'é', 'A' * 2049, 7, ''])
def test_forme_signature_invalide(banc, signature):
    a = banc.client()
    defi = defier(a)
    assert code(ouvrir_signe(a, signature)) == 'bad_request'
    assert not banc.appels_r
    # Le défi n'est pas consommé par un échec de forme.
    assert ouvrir_signe(a, signer(banc.signataire, defi))['ok']


def test_defi_ttl_defaut():
    config = lire('pollux', SCHEMA, journal=True, metriques=True, argv=['--config', str(EXEMPLE)], environ={})
    assert config['signature']['challenge_ttl_s'] == 60
    surcharge = lire('pollux', SCHEMA, journal=True, metriques=True, argv=['--config', str(EXEMPLE)],
                     environ={'PARESIA_POLLUX_SIGNATURE_CHALLENGE_TTL_S': '30'})
    assert surcharge['signature']['challenge_ttl_s'] == 30


def test_defi_expire(banc):
    contexte = ContexteConnexion(0, os.getuid(), os.getgid())
    defi = banc._application(requete('presence/session/challenge', params=IDENTITE), contexte)
    banc._defis.discard(contexte)       # la surveillance n'intervient pas : horloge simulée
    contexte.etat['defi']['echeance'] = time.monotonic() - 1
    resultat = banc._application(requete('presence/session/open', params=dict(
        IDENTITE, signature=signer(banc.signataire, defi))), contexte)
    assert code(resultat) == 'challenge_expired'
    assert 'expired' in raisons(banc) and not banc.appels_r
    banc._deconnexion(contexte)


def test_defi_expire_ferme_connexion(banc):
    banc.config['signature']['challenge_ttl_s'] = 0.1
    a = banc.client()
    assert defier(a)['data']['expires_s'] == 0.1
    assert fermee(a)
    assert 'expired' in raisons(banc)


def test_rejeu(banc):
    a, b = banc.client(), banc.client()
    defi = defier(a)
    signature = signer(banc.signataire, defi)
    assert ouvrir_signe(a, signature)['ok']
    # Même connexion : le défi est consommé.
    assert code(ouvrir_signe(a, signature)) == 'bad_request'      # session déjà ouverte
    # Autre connexion avec un autre défi.
    defier(b)
    banc.appels_r.clear()
    refuse(banc, b, signature, 'signature_invalid', 'bad_signature')
    # Même connexion, défi consommé par un échec de signature.
    c = banc.client()
    defier(c)
    assert code(ouvrir_signe(c, signature)) == 'signature_invalid'
    assert code(ouvrir_signe(c, signature)) in ('challenge_required',)


def test_signature_autre_admin(banc):
    autre, inconnu = Signataire(), Signataire()
    with open(banc.fichier, 'a', encoding='utf-8') as f:
        f.write(autre.ligne('bob@site'))
    a = banc.client()
    defi = defier(a)
    # Clé enregistrée sous un autre nom.
    refuse(banc, a, signer(autre, defi), 'signature_invalid', 'key_unknown')
    # Clé non enregistrée.
    b = banc.client()
    refuse(banc, b, signer(inconnu, defier(b)), 'signature_invalid', 'key_unknown')
    # Message d'un autre nom.
    c = banc.client()
    refuse(banc, c, signer(banc.signataire, defier(c), admin='bob@site'), 'signature_invalid',
           'bad_signature')
    # Nom différent de celui du défi.
    d = banc.client()
    defi = defier(d)
    refuse(banc, d, signer(autre, defi, admin='bob@site'), 'signature_invalid')


def test_deux_defis(banc):
    a = banc.client()
    assert defier(a)['ok']
    assert code(defier(a)) == 'challenge_required'
    assert fermee(a)


def test_retrait_cle(banc):
    a = banc.client()
    assert ouvrir_signe(a, signer(banc.signataire, defier(a)))['ok']
    banc.fichier.write_text('', encoding='utf-8')
    banc.appels_r.clear()
    b = banc.client()
    refuse(banc, b, signer(banc.signataire, defier(b)), 'signature_invalid', 'key_unknown')


def non_root(fd):
    valeurs = list(os.fstat(fd))
    valeurs[4] = os.getuid()
    return os.stat_result(valeurs)


@pytest.mark.parametrize('cas', ['proprietaire', 'groupe', 'autres', 'lien', 'absent', 'repertoire'])
def test_fichier_cles_refus(banc, cas):
    a = banc.client()
    defi = defier(a)
    signature = signer(banc.signataire, defi)
    contenu = banc.fichier.read_text(encoding='utf-8')
    if cas == 'groupe':
        banc.fichier.chmod(0o620)
    elif cas == 'autres':
        banc.fichier.chmod(0o602)
    elif cas == 'lien':
        reel = banc.fichier.with_name('reel')
        reel.write_text(contenu, encoding='utf-8')
        reel.chmod(0o600)
        banc.fichier.unlink()
        banc.fichier.symlink_to(reel)
    elif cas == 'absent':
        banc.fichier.unlink()
    elif cas == 'repertoire':
        banc.fichier.unlink()
        banc.fichier.mkdir()
    if cas == 'proprietaire':
        with patch('server.commun.cles_ssh._attributs', non_root):
            refuse(banc, a, signature, 'signature_invalid', 'keys_file')
    else:
        refuse(banc, a, signature, 'signature_invalid', 'keys_file')


def test_fichier_cles_compte_app_root(banc):
    # Le propriétaire strictement root exclut aussi l'uid du compte app lui-même.
    banc.config['sessions']['uid'] = 0
    a = banc.client()
    refuse(banc, a, signer(banc.signataire, defier(a)), 'signature_invalid', 'keys_file')


@pytest.mark.parametrize('cas,raison', [
    ('ssh-rsa', 'sig_algorithm'), ('faible', 'key_weak'), ('dss', 'key_type'),
    ('sk', 'key_type'), ('certificat', 'key_type'), ('courbe', 'key_type'),
    ('autre_type', 'key_unknown'), ('hachage', 'bad_hash'), ('espace', 'bad_namespace'),
    ('version', 'bad_format'),
])
def test_types_non_admis(banc, cas, raison):
    cle = banc.signataire
    options = {}
    if cas == 'ssh-rsa':
        cle = Signataire('rsa-sha2-256')
        options = {'algorithme': b'ssh-rsa'}
    elif cas == 'faible':
        cle = Signataire('rsa-sha2-256', bits=1024)
    elif cas == 'autre_type':
        cle = Signataire('ecdsa-sha2-nistp256')       # clé enregistrée : ed25519
    elif cas == 'hachage':
        options = {'hachage': b'sha1'}
    elif cas == 'espace':
        options = {'namespace': 'autre'}
    elif cas == 'version':
        options = {'version': 2}
    elif cas != 'courbe':
        nom = {'dss': b'ssh-dss', 'sk': b'sk-ssh-ed25519@openssh.com',
               'certificat': b'ssh-ed25519-cert-v01@openssh.com'}[cas]
        options = {'publique': chaine(nom)}
    else:
        options = {'publique': chaine(b'ecdsa-sha2-nistp224')}
    if cle is not banc.signataire and cas != 'autre_type':
        with open(banc.fichier, 'a', encoding='utf-8') as f:
            f.write(cle.ligne('Alice@site'))
    a = banc.client()
    defi = defier(a)
    espace = options.pop('namespace', None)
    message = f"paresia-presence/1\n{defi['data']['challenge']}\nAlice@site\n".encode('utf-8')
    signature = cle.signer(message, espace or defi['data']['namespace'], **options)
    refuse(banc, a, signature, 'signature_invalid', raison)


def test_fichier_cles_types(banc):
    alice = banc.signataire
    banc.fichier.write_text(
        'sk-ssh-ed25519@openssh.com AAAA Alice@site\n'
        'ssh-dss AAAA Alice@site\n'
        'ssh-ed25519-cert-v01@openssh.com AAAA Alice@site\n'
        '# commentaire\n\n'
        'restrict,command="/chemin avec espaces/outil" ' + alice.ligne('Alice@site'),
        encoding='utf-8')
    a = banc.client()
    assert ouvrir_signe(a, signer(alice, defier(a)))['ok']
    ignorees = [e for e in journal_de(banc) if e['event'] == 'key_ignored']
    assert len(ignorees) == 3 and all(e['reason'] == 'key_type' for e in ignorees)
    assert 'AAAA' not in banc.capture.getvalue()


def test_nom_avec_caractere_de_controle_ignore(banc):
    ligne = banc.signataire.ligne('Alice@site').replace('Alice@site', 'Alice@site\x1b[31m')
    banc.fichier.write_text(ligne, encoding='utf-8')
    a = banc.client()
    refuse(banc, a, signer(banc.signataire, defier(a)), 'signature_invalid', 'key_unknown')


def test_defi_non_journalise(banc):
    a = banc.client()
    defi = defier(a)
    signature = signer(banc.signataire, defi)
    resultat = ouvrir_signe(a, signature)
    assert resultat['ok']
    b = banc.client()
    defi_b = defier(b)
    ouvrir_signe(b, 'A' * 40)
    journal = banc.capture.getvalue()
    for secret in (defi['data']['challenge'], defi_b['data']['challenge'], signature, banc.jeton):
        assert secret not in journal
    assert 'challenge_issued' in journal
    # Signature valide d'un autre administrateur, refusée : rien de sensible dans le journal.
    ouvertures = journal.count('auth_ok')
    autre = Signataire()
    banc.fichier.write_text(banc.signataire.ligne('Alice@site') + autre.ligne('bob@site'),
                            encoding='utf-8')
    c = banc.client()
    defi_c = defier(c)
    signature_c = signer(autre, defi_c, admin='bob@site')
    assert code(ouvrir_signe(c, signature_c, admin='bob@site')) == 'signature_invalid'
    journal = banc.capture.getvalue()
    for secret in (defi_c['data']['challenge'], signature_c):
        assert secret not in journal
    assert raisons(banc)[-1] == 'bad_signature'
    assert journal.count('auth_ok') == ouvertures


def test_ecart_identite_defi_open(banc):
    autre = Signataire()
    banc.fichier.write_text(banc.signataire.ligne('Alice@site') + autre.ligne('bob@site'),
                            encoding='utf-8')
    # (a) administrateur différent à l'ouverture, signé par ce dernier sur son propre message.
    a = banc.client()
    defi = defier(a)
    signature = signer(autre, defi, admin='bob@site')
    assert code(ouvrir_signe(a, signature, admin='bob@site')) == 'signature_invalid'
    assert not banc.appels_r and fermee(a)
    # (b) source différente, signature valide d'Alice.
    b = banc.client()
    defi = defier(b)
    signature = signer(banc.signataire, defi)
    assert code(ouvrir_signe(b, signature, source='2001:db8::2')) == 'signature_invalid'
    assert not banc.appels_r and fermee(b)


def test_sans_cryptography(banc):
    a = banc.client()
    defi = defier(a)
    signature = signer(banc.signataire, defi)
    with patch.dict(sys.modules, {'cryptography.exceptions': None}):
        refuse(banc, a, signature, 'not_available', 'not_available')
    # Pollux reste vivant.
    b = banc.client()
    assert ouvrir_signe(b, signer(banc.signataire, defier(b)))['ok']


def test_robustesse_defi(banc):
    section = 'sessions'
    sock = banc.config[section]['socket']
    import socket as s
    from server.commun.jumeaux import decoder, lire_ligne
    for contenu, attendu in (
            (b'pas json\n', 'bad_request'),
            (json.dumps(dict(requete('presence/session/challenge', params=IDENTITE),
                             proto='jumeaux/2')).encode() + b'\n', 'protocol_version_mismatch'),
            (json.dumps(dict(requete('presence/session/challenge', params=IDENTITE),
                             inconnu=1)).encode() + b'\n', 'bad_request')):
        with s.socket(s.AF_UNIX, s.SOCK_STREAM) as c:
            c.settimeout(2)
            c.connect(sock)
            c.sendall(contenu)
            assert decoder(lire_ligne(c))['error']['code'] == attendu
    a = banc.client()
    for params in ({'admin': 'a'}, dict(IDENTITE, signature='YQ=='), dict(IDENTITE, extra=1),
                   {'admin': 'a\n', 'source': '127.0.0.1'}):
        assert code(a.appeler(requete('presence/session/challenge', params=params))) == 'bad_request'
    assert code(a.appeler(requete('presence/session/challenge', 4, params=IDENTITE))) == 'bad_request'
    assert defier(a)['ok'] and not banc.appels_r


def test_conf_exemple_pollux():
    config = lire('pollux', SCHEMA, journal=True, metriques=True, argv=['--config', str(EXEMPLE)], environ={})
    session = lire('pollux-session', SCHEMA_SESSION, argv=['--config', str(EXEMPLE)], environ={})
    assert config['signature']['namespace'] == 'paresia-presence'
    assert config['signature']['authorized_keys'] == session['auth']['authorized_keys']
    assert config['signature']['max_signature'] == session['auth']['max_signature'] == 2048
    assert '[pollux.signature]' in EXEMPLE.read_text(encoding='utf-8')
    surcharge = lire('pollux', SCHEMA, journal=True, metriques=True, argv=['--config', str(EXEMPLE)], environ={
        'PARESIA_POLLUX_SIGNATURE_NAMESPACE': 'autre',
        'PARESIA_POLLUX_SIGNATURE_AUTHORIZED_KEYS': '/etc/paresia/cles',
        'PARESIA_POLLUX_SIGNATURE_MAX_SIGNATURE': '4096'})
    assert surcharge['signature']['namespace'] == 'autre'
    assert surcharge['signature']['authorized_keys'] == '/etc/paresia/cles'
    assert surcharge['signature']['max_signature'] == 4096


def test_defi_filtrage_i18n(banc):
    fr = json.loads((RACINE / 'i18n' / 'fr-FR.json').read_text(encoding='utf-8'))
    en = json.loads((RACINE / 'i18n' / 'en-US.json').read_text(encoding='utf-8'))
    for cle in ('challenge_required', 'challenge_expired', 'signature_invalid'):
        assert fr[cle] and en[cle] and DETAILS[cle]
    a = banc.client()
    resultat = a.appeler(requete('presence/session/open', params=dict(IDENTITE, signature='YQ==')))
    texte = json.dumps(resultat, ensure_ascii=False)
    assert not re.search('[\x00-\x1f\x7f-\x9f]', resultat['error']['detail'])
    assert 'YQ==' not in texte


def test_defi_sans_client_particulier():
    nom = 'bit' + 'warden'
    for dossier in ('server', 'tests'):
        for fichier in (RACINE / dossier).rglob('*.py'):
            assert nom not in fichier.read_text(encoding='utf-8').lower(), fichier


def test_codes_defi():
    document = (RACINE / 'docs' / 'protocole.md').read_text(encoding='utf-8')
    for cle in ('challenge_required', 'challenge_expired', 'signature_invalid'):
        assert cle in CODES_ERREUR and f'`{cle}`' in document


def test_cert_authority_ignoree(banc):
    alice = banc.signataire
    banc.fichier.write_text('cert-authority,restrict ' + alice.ligne('Alice@site'), encoding='utf-8')
    a = banc.client()
    refuse(banc, a, signer(alice, defier(a)), 'signature_invalid', 'key_unknown')
    assert [e['reason'] for e in journal_de(banc) if e['event'] == 'key_ignored'] == ['cert_authority']
    # Sans cette option, la même ligne est acceptée.
    banc.fichier.write_text('restrict ' + alice.ligne('Alice@site'), encoding='utf-8')
    b = banc.client()
    assert ouvrir_signe(b, signer(alice, defier(b)))['ok']


@pytest.mark.parametrize('options', ['Cert-Authority', 'CERT-AUTHORITY', 'from="a,b",cert-authority,restrict'])
def test_cert_authority_casse_et_options(banc, options):
    alice = banc.signataire
    banc.fichier.write_text(options + ' ' + alice.ligne('Alice@site'), encoding='utf-8')
    a = banc.client()
    refuse(banc, a, signer(alice, defier(a)), 'signature_invalid', 'key_unknown')
    assert [e['reason'] for e in journal_de(banc) if e['event'] == 'key_ignored'] == ['cert_authority']


def test_cert_authority_dans_valeur_citee_non_ignoree(banc):
    alice = banc.signataire
    banc.fichier.write_text('command="x,cert-authority" ' + alice.ligne('Alice@site'), encoding='utf-8')
    a = banc.client()
    assert ouvrir_signe(a, signer(alice, defier(a)))['ok']
    assert not [e for e in journal_de(banc) if e['event'] == 'key_ignored']


def test_options_guillemet_non_ferme_ignore():
    from server.commun.cles_ssh import _options_cert_authority
    with pytest.raises(ValueError):
        _options_cert_authority('command="x,cert-authority')
    assert _options_cert_authority('command="a\\"b,cert-authority"') is False
    assert _options_cert_authority('cert-authorityX,restrict') is False


def test_refus_repete_ne_rearme_pas_fermeture(banc):
    contexte = ContexteConnexion(0, os.getuid(), os.getgid())
    banc._application(requete('presence/session/open', params=dict(IDENTITE, signature='YQ==')), contexte)
    premiere = banc._fermetures[contexte]
    time.sleep(0.01)
    banc._application(requete('presence/session/open', params=dict(IDENTITE, signature='YQ==')), contexte)
    assert banc._fermetures[contexte] == premiere
    banc._deconnexion(contexte)
