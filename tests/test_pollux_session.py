# Tests du relais SSH sur Pollux simulé ; dépendances : pytest, bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha.41  2026-11-06  Relais de challenge et de signature, défi, signature et jeton non journalisés, y compris refus (D20, D28).
#   3.0.0-alpha.29  2026-11-06  Chemin de la socket de Pollux : un dossier d'exécution par unité (T016, D40).
#   3.0.0-alpha  2026-11-05  Configuration en couches (T015) : racine injectée, environnement ignoré, lanceur sans chemin de configuration.
#   3.0.0-alpha  2026-11-05  Identité jetable, protocole, délais et confidentialité ; Pollux non sollicité au refus.
#   3.0.0-alpha  2026-11-05  Cas limites d'identité, lanceur exécuté, échéance d'ouverture, blocs, journal de session.
#   3.0.0-alpha  2026-11-05  Échéance d'ouverture absolue : ping avant open et open refusé ne la réarment pas.
#   3.0.0-alpha  2026-11-05  connect borné par open_timeout_s, option -P du lanceur, doublon supprimé, marges de timing.
#   3.0.0-alpha  2026-11-05  D18 : fermeture par Pollux avec requête en attente (3), fin d'entrée (0).
import base64
import json
import os
from pathlib import Path
import secrets
import socket
import stat
import struct
import subprocess
import sys
import threading
import tempfile
import time

import pytest

import server.pollux.session as module_session
from server.commun.config import ErreurConfiguration
from server.commun.jumeaux import ErreurProtocole, encoder
from server.pollux.session import configuration, identite, relayer, main

RACINE = Path(__file__).resolve().parents[1]
EXEMPLE = RACINE / 'server' / 'conf' / 'paresia.conf'


def racine_conf(dossier, contenu=None):
    """Racine système factice contenant paresia.conf (copie de l'exemple par défaut)."""
    racine = dossier / 'etc-paresia'
    racine.mkdir(mode=0o700, exist_ok=True)
    fichier = racine / 'paresia.conf'
    fichier.write_text(EXEMPLE.read_text(encoding='utf-8') if contenu is None else contenu, encoding='utf-8')
    fichier.chmod(0o600)
    return racine


def avec_racine(monkeypatch, racine):
    """main() lit la racine système : on la remplace par un paramètre de fonction."""
    monkeypatch.setattr(module_session, 'configuration',
                        lambda argv=None: configuration(argv, racine_systeme=racine))


def requete(action='open', identifiant='0123456789abcdef', params=None):
    return {'proto': 'jumeaux/1', 'id': identifiant, 'session': 0,
            'action': 'presence/session/' + action, 'params': params or {}}


@pytest.fixture
def contexte(tmp_path, monkeypatch):
    # Clé publique SSH jetable : aucun matériel privé n'est écrit.
    type_cle = b'ssh-ed25519'
    blob = struct.pack('>I', len(type_cle)) + type_cle + struct.pack('>I', 32) + secrets.token_bytes(32)
    cle = base64.b64encode(blob).decode()
    monkeypatch.setattr(module_session.syslog, 'openlog', lambda *args, **kw: None)
    auth = tmp_path / 'auth'
    autorise = tmp_path / 'authorized_keys'
    auth.write_text(f'publickey ssh-ed25519 {cle}\n')
    autorise.write_text(f'restrict,command="/chemin avec espaces/pollux-session" ssh-ed25519 {cle} alice@example.org\n')
    env = {'SSH_USER_AUTH': str(auth), 'SSH_CONNECTION': '2001:db8::1 1234 2001:db8::2 22'}
    dossier = tempfile.TemporaryDirectory(prefix='pollux-')
    config = {'transport': {'socket': str(Path(dossier.name) / 's'), 'timeout_s': 1.0, 'open_timeout_s': 30, 'max_line': 4096},
              'auth': {'authorized_keys': str(autorise), 'max_signature': 2048}}
    journaux = []
    monkeypatch.setattr('server.commun.journal.syslog.syslog', lambda *args: journaux.append(args))
    config['cle'] = cle
    yield config, env, auth, autorise, journaux
    dossier.cleanup()


class Session:
    def __init__(self, contexte, ecoute=True):
        self.config, self.env, *_ = contexte
        self.serveur = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        if ecoute:
            Path(self.config['transport']['socket']).unlink(missing_ok=True)
            self.serveur.bind(self.config['transport']['socket'])
            self.serveur.listen()
            self.serveur.settimeout(2)
        self.entree, self.ecriture = os.pipe()
        self.lecture, self.sortie = os.pipe()
        self.resultat = []
        self.fil = threading.Thread(target=self.executer)
        self.fil.start()
        self.pollux = None
        self.flux = None
        self.app = os.fdopen(self.lecture, 'rb', buffering=0)

    def executer(self):
        try:
            self.resultat.append(relayer(self.config, entree=self.entree, sortie=self.sortie, environ=self.env))
        finally:
            os.close(self.entree)
            os.close(self.sortie)

    def envoyer(self, objet):
        os.write(self.ecriture, encoder(objet) if isinstance(objet, dict) else objet)

    def recevoir_pollux(self):
        if self.pollux is None:
            self.pollux, _ = self.serveur.accept()
            self.pollux.settimeout(2)
            self.flux = self.pollux.makefile('rb')
        return json.loads(self.flux.readline())

    def repondre(self, objet):
        self.pollux.sendall(encoder(objet))

    def recevoir(self):
        import select
        assert select.select([self.app], [], [], 3)[0]
        ligne = self.app.readline()
        assert ligne.endswith(b'\n')
        return json.loads(ligne)

    def finir(self, code, fermer_entree=False):
        if fermer_entree:
            os.close(self.ecriture)
            self.ecriture = None
        self.fil.join(3)
        assert not self.fil.is_alive()
        assert self.resultat == [code]
        if self.pollux:
            assert self.flux.read() == b''
        # Sortie standard : uniquement des lignes JSON de protocole, une par réponse.
        self.reste = self.app.read() or b''
        for ligne in self.reste.splitlines():
            objet = json.loads(ligne)
            assert isinstance(objet, dict) and {'id', 'ok'} <= set(objet)
        assert not self.reste or self.reste.endswith(b'\n')
        self.nettoyer()

    def nettoyer(self):
        if self.ecriture is not None:
            os.close(self.ecriture)
            self.ecriture = None
        self.fil.join(2)
        if self.flux:
            self.flux.close()
        if self.pollux:
            self.pollux.close()
        self.serveur.close()
        self.app.close()


def ouvrir(session, params=None, action='open'):
    session.envoyer(requete(action, params=params))
    transmis = session.recevoir_pollux()
    reponse = {'id': transmis['id'], 'ok': True, 'data': {'session': 1, 'token': secrets.token_hex(32)}}
    session.repondre(reponse)
    assert session.recevoir() == reponse
    return transmis, reponse


def test_relais_open(contexte):
    session = Session(contexte)
    transmis, _ = ouvrir(session)
    assert transmis['params'] == {'admin': 'alice@example.org', 'source': '2001:db8::1'}
    session.finir(0, True)


def test_params_remplaces(contexte):
    session = Session(contexte)
    transmis, _ = ouvrir(session, {'admin': 'imposteur', 'source': 'invalide'})
    assert transmis['params']['admin'] == 'alice@example.org'
    session.finir(0, True)


def test_session_relais_defi(contexte):
    session = Session(contexte)
    # challenge : params de l'application remplacés, signature ignorée.
    transmis, _ = ouvrir(session, {'admin': 'imposteur', 'signature': 'QUJD'}, action='challenge')
    assert transmis['action'] == 'presence/session/challenge'
    assert transmis['params'] == {'admin': 'alice@example.org', 'source': '2001:db8::1'}
    # open : la signature est relayée, tout autre champ écarté.
    transmis, _ = ouvrir(session, {'admin': 'imposteur', 'source': 'x', 'signature': 'QUJD',
                                   'extra': 1})
    assert transmis['params'] == {'admin': 'alice@example.org', 'source': '2001:db8::1',
                                  'signature': 'QUJD'}
    session.finir(0, True)


@pytest.mark.parametrize('signature', ['A' * 2049, 'é', '###', 7, ''])
def test_session_signature_refusee(contexte, signature):
    session = Session(contexte)
    session.envoyer(requete(params={'signature': signature}))
    resultat = session.recevoir()
    assert resultat['error']['code'] == 'bad_request'
    session.finir(0, True)


def test_admin_depuis_authorized_keys(contexte):
    config, env, *_ = contexte
    assert identite(config['auth']['authorized_keys'], env)['admin'] == 'alice@example.org'


@pytest.mark.parametrize('cas', ['introuvable', 'absent', 'double', 'admin', 'source', 'options', 'ambigu'])
def test_auth_info_refus(contexte, cas):
    _, env, auth, autorise, _ = contexte
    if cas == 'introuvable':
        autorise.write_text('')
    elif cas == 'absent':
        auth.unlink()
    elif cas == 'double':
        auth.write_text(auth.read_text() * 2)
    elif cas == 'admin':
        autorise.write_text(autorise.read_text().replace('alice@example.org', 'nom invalide'))
    elif cas == 'source':
        env['SSH_CONNECTION'] = 'invalide'
    elif cas == 'options':
        autorise.write_text('command="sans fin')
    else:
        autorise.write_text(autorise.read_text() * 2)
    session = Session(contexte)
    session.envoyer(requete())
    assert session.recevoir()['error']['code'] == 'auth_info_unavailable'
    # Pollux non sollicité : aucune connexion n'est en attente.
    session.serveur.setblocking(False)
    with pytest.raises(BlockingIOError):
        session.serveur.accept()
    session.finir(3)


def test_relais_ping(contexte):
    session = Session(contexte)
    ouvrir(session)
    ping = requete('ping', 'fedcba9876543210')
    session.envoyer(ping)
    assert session.recevoir_pollux() == ping
    session.repondre({'id': ping['id'], 'ok': True})
    assert session.recevoir()['id'] == ping['id']
    session.finir(0, True)


def test_fin_sans_ping(contexte):
    session = Session(contexte)
    ouvrir(session)
    session.finir(1)


def test_depart_compteur(contexte):
    session = Session(contexte)
    time.sleep(.8)
    assert session.fil.is_alive()
    session.envoyer(requete())
    transmis = session.recevoir_pollux()
    time.sleep(.3)
    session.repondre({'id': transmis['id'], 'ok': True})
    session.recevoir()
    time.sleep(.3)
    assert session.fil.is_alive()
    session.finir(1)


def test_fin_sans_reponse(contexte):
    session = Session(contexte)
    session.envoyer(requete())
    session.recevoir_pollux()
    session.finir(1)


def test_fin_stdin(contexte):
    session = Session(contexte)
    ouvrir(session)
    session.finir(0, True)


def test_fin_socket_pollux(contexte):
    session = Session(contexte)
    ouvrir(session)
    session.pollux.shutdown(socket.SHUT_RDWR)
    session.finir(0)


def test_fermeture_pollux_requete_en_attente(contexte):
    session = Session(contexte)
    session.envoyer(requete())
    session.recevoir_pollux()
    session.pollux.shutdown(socket.SHUT_RDWR)
    session.finir(3)


def test_fin_entree_sans_attente_code_0(contexte):
    session = Session(contexte)
    ouvrir(session)
    session.finir(0, True)


@pytest.mark.parametrize('ligne,code', [(b'pas json\n', 'bad_request'), (b'[]\n', 'bad_request'),
    (encoder({'id': '0123456789abcdef'}), 'bad_request'),
    (encoder(requete('interdit')), 'unknown_action'),
    (encoder(requete(params={'session': 5})), 'bad_request')])
def test_lignes_invalides(contexte, ligne, code):
    session = Session(contexte)
    session.envoyer(ligne)
    assert session.recevoir()['error']['code'] == code
    ouvrir(session)
    session.finir(0, True)


def test_ligne_trop_longue_session(contexte):
    session = Session(contexte)
    session.envoyer(b'x' * 4097)
    assert session.recevoir()['error']['code'] == 'line_too_long'
    session.finir(3)


def test_connect_borne_par_open_timeout(contexte):
    # Socket d'écoute dont le backlog est plein et qui n'accepte pas.
    contexte[0]['transport']['open_timeout_s'] = .4
    contexte[0]['transport']['timeout_s'] = 30
    chemin = contexte[0]['transport']['socket']
    serveur = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    serveur.bind(chemin)
    serveur.listen(0)
    bouchons = []
    try:
        for _ in range(4):
            bouchon = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            bouchon.setblocking(False)
            try:
                bouchon.connect(chemin)
            except BlockingIOError:
                bouchons.append(bouchon)
                break
            bouchons.append(bouchon)
        assert bouchons and bouchons[-1].fileno() >= 0
        session = Session(contexte, False)
        debut = time.monotonic()
        session.envoyer(requete())
        session.fil.join(5)
        assert not session.fil.is_alive()
        assert time.monotonic() - debut < 3
        assert session.resultat in ([1], [2])
        session.nettoyer()
    finally:
        for bouchon in bouchons:
            bouchon.close()
        serveur.close()


def test_pollux_injoignable(contexte):
    session = Session(contexte, False)
    session.envoyer(requete())
    assert session.recevoir()['error']['code'] == 'peer_unavailable'
    session.finir(2)


def test_config_session(contexte, tmp_path, capfd, monkeypatch):
    racine = racine_conf(tmp_path)
    config = configuration(racine_systeme=racine)
    assert config['transport']['timeout_s'] == 90
    assert config['transport']['open_timeout_s'] == 30
    assert configuration([], racine_systeme=racine) == config
    # Aucun argument n'est accepté, --config comprise.
    with pytest.raises(ErreurConfiguration, match='config_invalid_arguments'):
        configuration(['--config', str(racine / 'paresia.conf')], racine_systeme=racine)
    avec_racine(monkeypatch, racine)
    assert main(['--inconnu']) == 3
    assert capfd.readouterr().err == ''


def test_version_incompatible(contexte):
    session = Session(contexte)
    objet = requete()
    objet['proto'] = 'jumeaux/2'
    session.envoyer(objet)
    assert session.recevoir()['error']['code'] == 'protocol_version_mismatch'
    session.finir(3)


def test_ligne_partielle_ne_bloque_pas_delai(contexte):
    session = Session(contexte)
    ouvrir(session)
    session.envoyer(b'{')
    session.finir(1)


def test_detail_filtre(contexte):
    session = Session(contexte)
    session.envoyer(requete())
    transmis = session.recevoir_pollux()
    session.repondre({'id': transmis['id'], 'ok': False,
                      'error': {'code': 'bad_request', 'detail': 'a\u001bb'}})
    assert session.recevoir()['error']['detail'] == 'a\ufffdb'
    session.finir(0, True)


def test_close(contexte):
    session = Session(contexte)
    ouvrir(session)
    session.envoyer(requete('close'))
    transmis = session.recevoir_pollux()
    session.repondre({'id': transmis['id'], 'ok': True})
    assert session.recevoir()['ok']
    session.finir(0)


def test_ping_rearme_compteur(contexte):
    session = Session(contexte)
    ouvrir(session)
    for index in range(3):
        time.sleep(.3)
        session.envoyer(requete('ping', f'{index:016x}'))
        transmis = session.recevoir_pollux()
        session.repondre({'id': transmis['id'], 'ok': True})
        session.recevoir()
    assert session.fil.is_alive()
    session.finir(0, True)


def test_reponse_autre_id_ne_rearme_pas(contexte):
    session = Session(contexte)
    # Sans open : aucun compteur de ping, uniquement celui de chaque requête.
    session.envoyer(requete('ping', '0000000000000001'))
    session.recevoir_pollux()
    time.sleep(.35)
    session.envoyer(requete('ping', '0000000000000002'))
    transmis = session.recevoir_pollux()
    session.repondre({'id': transmis['id'], 'ok': True})
    session.recevoir()
    session.finir(1)


def test_reponse_non_sollicitee(contexte):
    session = Session(contexte)
    session.envoyer(requete())
    session.recevoir_pollux()
    session.repondre({'id': '0000000000000000', 'ok': True})
    assert session.recevoir()['error']['code'] == 'bad_request'
    session.finir(3)


def _cle_jetable(type_cle=b'ssh-ed25519'):
    blob = struct.pack('>I', len(type_cle)) + type_cle + struct.pack('>I', 32) + secrets.token_bytes(32)
    return base64.b64encode(blob).decode()


def _refuse(contexte):
    config, env, *_ = contexte
    with pytest.raises(ErreurProtocole) as erreur:
        identite(config['auth']['authorized_keys'], env)
    assert erreur.value.code == 'auth_info_unavailable'


def test_authorized_keys_multilignes(contexte):
    config, env, _, autorise, _ = contexte
    cle = config['cle']
    autorise.write_text('\n'.join([
        '# commentaire', '', '   ',
        f'ssh-ed25519 {_cle_jetable()} autre',
        f'ssh-rsa {_cle_jetable(b"ssh-rsa")} rsa',
        f'restrict,command="a \\"b\\" c" ssh-ed25519 {cle} bob',
        f'# ssh-ed25519 {cle} fantome',
        f'restrict ssh-ed25519 {_cle_jetable()} dernier', '']))
    assert identite(config['auth']['authorized_keys'], env)['admin'] == 'bob'


def test_cle_dupliquee_refusee(contexte):
    config, _, _, autorise, _ = contexte
    autorise.write_text(f'ssh-ed25519 {config["cle"]} alice\nrestrict ssh-ed25519 {config["cle"]} bob\n')
    _refuse(contexte)


def test_options_antislash(contexte):
    config, env, _, autorise, _ = contexte
    # Comme OpenSSH, seul \" échappe : dans x\\" le guillemet est échappé, la ligne est
    # donc non terminée (refus), et non fermée par une paire \\ inventée.
    autorise.write_text(f'command="x\\\\" ssh-ed25519 {config["cle"]} carol\n')
    _refuse(contexte)
    autorise.write_text(f'command="x\\\\\\" y" ssh-ed25519 {config["cle"]} carol\n')
    assert identite(config['auth']['authorized_keys'], env)['admin'] == 'carol'


def test_cle_comparee_par_octets(contexte):
    config, env, _, autorise, _ = contexte
    # Même texte base64 mais bourrage différent : refusé par validation, ligne ignorée.
    autorise.write_text(f'ssh-ed25519 {config["cle"]}x dave\nssh-ed25519 {config["cle"]} erin\n')
    assert identite(config['auth']['authorized_keys'], env)['admin'] == 'erin'


@pytest.mark.parametrize('commentaire', ['ali\x07ce', 'al ice extra', 'alicé', 'a/b', 'ali\rce', '', 'x' * 65])
def test_commentaire_invalide(contexte, commentaire):
    config, _, _, autorise, _ = contexte
    autorise.write_text(f'ssh-ed25519 {config["cle"]} {commentaire}\n')
    _refuse(contexte)


def test_admin_limites(contexte):
    config, env, _, autorise, _ = contexte
    autorise.write_text(f'ssh-ed25519 {config["cle"]} {"a" * 64}\n')
    assert identite(config['auth']['authorized_keys'], env)['admin'] == 'a' * 64
    autorise.write_text(f'ssh-ed25519 {config["cle"]} {"a" * 65}\n')
    _refuse(contexte)
    autorise.write_text(f'ssh-ed25519 {config["cle"]} A.b_c@d-9\n')
    assert identite(config['auth']['authorized_keys'], env)['admin'] == 'A.b_c@d-9'


@pytest.mark.parametrize('connexion,attendu', [
    ('192.0.2.1 1234 192.0.2.2 22', '192.0.2.1'),
    ('2001:db8::1 1234 2001:db8::2 22', '2001:db8::1'),
    ('fe80::1%eth0 1234 fe80::2 22', None), ('', None), ('   ', None), ('999.1.1.1 1 2 3', None)])
def test_source(contexte, connexion, attendu):
    config, env, *_ = contexte
    env['SSH_CONNECTION'] = connexion
    if attendu is None:
        _refuse(contexte)
    else:
        assert identite(config['auth']['authorized_keys'], env)['source'] == attendu


def test_variables_absentes(contexte):
    config, env, *_ = contexte
    del env['SSH_USER_AUTH']
    _refuse(contexte)
    env['SSH_USER_AUTH'] = contexte[2].as_posix()
    del env['SSH_CONNECTION']
    _refuse(contexte)


def test_fichier_ssh_user_auth_suspect(contexte, tmp_path):
    _, env, auth, *_ = contexte
    reel = tmp_path / 'reel'
    reel.write_text(auth.read_text())
    lien = tmp_path / 'lien'
    lien.symlink_to(reel)
    env['SSH_USER_AUTH'] = str(lien)
    _refuse(contexte)
    env['SSH_USER_AUTH'] = str(tmp_path)
    _refuse(contexte)
    env['SSH_USER_AUTH'] = str(auth)
    auth.chmod(0o666)
    _refuse(contexte)
    auth.chmod(0o620)
    _refuse(contexte)
    auth.chmod(0o600)
    assert identite(contexte[0]['auth']['authorized_keys'], env)['admin']


def test_authorized_keys_suspect(contexte, tmp_path):
    config, env, _, autorise, _ = contexte
    copie = tmp_path / 'copie'
    copie.write_text(autorise.read_text())
    lien = tmp_path / 'lien-ak'
    lien.symlink_to(copie)
    config['auth']['authorized_keys'] = str(lien)
    _refuse(contexte)
    config['auth']['authorized_keys'] = str(tmp_path)
    _refuse(contexte)
    config['auth']['authorized_keys'] = str(autorise)
    autorise.chmod(0o664)
    _refuse(contexte)
    autorise.chmod(0o602)
    _refuse(contexte)
    autorise.chmod(0o600)
    assert identite(str(autorise), env)['admin']


def test_proprietaire_inconnu(contexte, monkeypatch):
    # Fichier SSH_USER_AUTH appartenant à un autre utilisateur que l'euid : refusé.
    monkeypatch.setattr(module_session.os, 'geteuid', lambda: os.stat(contexte[2]).st_uid + 1)
    _refuse(contexte)


@pytest.mark.parametrize('action', ['ping', 'close'])
def test_params_non_vides_ping_close(contexte, action):
    session = Session(contexte)
    ouvrir(session)
    session.envoyer(requete(action, params={'x': 1}))
    assert session.recevoir()['error']['code'] == 'bad_request'
    session.finir(0, True)


def test_pollux_refuse_connexion(contexte):
    session = Session(contexte, False)
    session.serveur.bind(session.config['transport']['socket'])
    session.envoyer(requete())
    assert session.recevoir()['error']['code'] == 'peer_unavailable'
    session.finir(2)


@pytest.mark.parametrize('brut', [b'illisible\n', encoder({'id': 'REMPLACE', 'ok': True, 'extra': 1}),
                                  encoder({'id': 'REMPLACE', 'ok': 'oui'})])
def test_reponse_pollux_invalide(contexte, brut):
    session = Session(contexte)
    session.envoyer(requete())
    transmis = session.recevoir_pollux()
    session.pollux.sendall(brut.replace(b'REMPLACE', transmis['id'].encode()))
    assert session.recevoir()['error']['code'] == 'bad_request'
    session.finir(3)


# --- échéance d'ouverture ---

def test_ouverture_jamais_envoyee(contexte):
    contexte[0]['transport']['open_timeout_s'] = .3
    session = Session(contexte)
    session.finir(1)


def test_ouverture_refusee_puis_silence(contexte):
    contexte[0]['transport']['open_timeout_s'] = .4
    session = Session(contexte)
    session.envoyer(requete())
    transmis = session.recevoir_pollux()
    session.repondre({'id': transmis['id'], 'ok': False,
                      'error': {'code': 'session_limit', 'detail': 'x'}})
    assert session.recevoir()['error']['code'] == 'session_limit'
    session.finir(1)


def test_ouverture_refusee_ne_rearme_pas(contexte):
    contexte[0]['transport']['open_timeout_s'] = .5
    session = Session(contexte)
    debut = time.monotonic()
    time.sleep(.3)
    session.envoyer(requete())
    transmis = session.recevoir_pollux()
    session.repondre({'id': transmis['id'], 'ok': False,
                      'error': {'code': 'session_limit', 'detail': 'x'}})
    session.recevoir()
    session.finir(1)
    assert time.monotonic() - debut < .75


def test_ping_avant_open_puis_silence(contexte):
    contexte[0]['transport']['open_timeout_s'] = .4
    session = Session(contexte)
    session.envoyer(requete('ping', '0000000000000009'))
    transmis = session.recevoir_pollux()
    session.repondre({'id': transmis['id'], 'ok': True})
    session.recevoir()
    session.finir(1)


def test_ping_avant_open_repete_ne_maintient_pas(contexte):
    contexte[0]['transport']['open_timeout_s'] = .6
    session = Session(contexte)
    debut = time.monotonic()
    for numero in range(1, 5):
        if not session.fil.is_alive():
            break
        try:
            session.envoyer(requete('ping', '%016d' % numero))
            transmis = session.recevoir_pollux()
            session.repondre({'id': transmis['id'], 'ok': True})
            session.recevoir()
        except Exception:
            break
        time.sleep(.2)
    session.finir(1)
    assert time.monotonic() - debut < 1.1


def test_ligne_partielle_avant_open(contexte):
    contexte[0]['transport']['open_timeout_s'] = .3
    session = Session(contexte)
    session.envoyer(b'{"proto"')
    session.finir(1)


def test_open_timeout_suspendu_apres_open(contexte):
    contexte[0]['transport']['open_timeout_s'] = .3
    session = Session(contexte)
    ouvrir(session)
    time.sleep(.45)
    assert session.fil.is_alive()
    session.finir(0, True)


# --- blocs ---

def test_deux_lignes_un_write(contexte):
    session = Session(contexte)
    un, deux = requete('ping', '0000000000000001'), requete('ping', '0000000000000002')
    session.envoyer(encoder(un) + encoder(deux))
    assert session.recevoir_pollux() == un
    assert session.recevoir_pollux() == deux
    for objet in (un, deux):
        session.repondre({'id': objet['id'], 'ok': True})
    assert [session.recevoir()['id'], session.recevoir()['id']] == [un['id'], deux['id']]
    session.finir(0, True)


def test_ligne_valide_puis_morceaux(contexte):
    session = Session(contexte)
    ping = encoder(requete('ping', '0000000000000001'))
    session.envoyer(ping[:10])
    time.sleep(.05)
    session.envoyer(ping[10:] + encoder(requete('ping', '0000000000000002'))[:5])
    assert session.recevoir_pollux()['id'] == '0000000000000001'
    session.finir(1)


def _requete_taille(taille):
    base = encoder(requete(params={'p': ''}))
    objet = requete(params={'p': 'a' * (taille - len(base))})
    brut = encoder(objet)
    assert len(brut) == taille
    return brut


def test_ligne_pres_de_max_line(contexte):
    contexte[0]['transport']['max_line'] = 1 << 20
    contexte[0]['transport']['timeout_s'] = 5
    session = Session(contexte)
    session.envoyer(_requete_taille(1 << 20))
    transmis = session.recevoir_pollux()
    assert transmis['params'] == {'admin': 'alice@example.org', 'source': '2001:db8::1'}
    session.repondre({'id': transmis['id'], 'ok': True, 'data': {'session': 1, 'token': 'a' * 8}})
    session.recevoir()
    session.finir(0, True)


def test_ligne_au_dela_de_max_line(contexte):
    contexte[0]['transport']['max_line'] = 1 << 20
    contexte[0]['transport']['timeout_s'] = 5
    session = Session(contexte)
    try:
        session.envoyer(_requete_taille((1 << 20) + 1))
    except BrokenPipeError:
        pass
    assert session.recevoir()['error']['code'] == 'line_too_long'
    session.finir(3)


def test_erreur_vidangee_avant_sortie(contexte):
    session = Session(contexte)
    session.envoyer(requete())
    transmis = session.recevoir_pollux()
    session.repondre({'id': transmis['id'], 'ok': False,
                      'error': {'code': 'session_limit', 'detail': 'x'}})
    session.pollux.shutdown(socket.SHUT_RDWR)
    assert session.recevoir()['error']['code'] == 'session_limit'
    session.finir(0)


# --- journal ---

def _journaux(contexte):
    return [json.loads(args[1]) for args in contexte[-1]]


def test_jeton_non_journalise_session(contexte, capfd):
    # Chemin nominal puis fermeture après la réponse à open.
    session = Session(contexte)
    _, reponse = ouvrir(session)
    jeton = reponse['data']['token']
    session.pollux.shutdown(socket.SHUT_RDWR)
    session.finir(0)
    # Chemin d'erreur : réponse invalide portant un jeton.
    session = Session(contexte)
    session.envoyer(requete())
    transmis = session.recevoir_pollux()
    jeton2 = secrets.token_hex(32)
    session.repondre({'id': transmis['id'], 'ok': True, 'data': {'token': jeton2}, 'extra': 1})
    session.recevoir()
    session.finir(3)
    # Chemin d'erreur : délai dépassé après open.
    session = Session(contexte)
    _, reponse3 = ouvrir(session)
    session.finir(1)
    texte = repr(contexte[-1])
    assert contexte[-1]
    for secret in (jeton, jeton2, reponse3['data']['token']):
        assert secret not in texte
    sortie = capfd.readouterr()
    assert sortie.err == '' and sortie.out == ''


def test_defi_signature_non_journalises_session(contexte, capfd):
    session = Session(contexte)
    session.envoyer(requete('challenge'))
    transmis = session.recevoir_pollux()
    defi = secrets.token_hex(32)
    reponse = {'id': transmis['id'], 'ok': True, 'data': {'challenge': defi, 'namespace': 'ns', 'expires_s': 30}}
    session.repondre(reponse)
    assert session.recevoir() == reponse
    signature = base64.b64encode(secrets.token_bytes(48)).decode()
    # Chemin nominal : signature acceptée, jeton rendu.
    transmis, ouverte = ouvrir(session, {'signature': signature})
    jeton = ouverte['data']['token']
    assert transmis['params']['signature'] == signature
    session.finir(0, True)
    # Chemin d'erreur : signature refusée par le relais (Pollux).
    session = Session(contexte)
    session.envoyer(requete('challenge'))
    transmis = session.recevoir_pollux()
    session.repondre({'id': transmis['id'], 'ok': True,
                      'data': {'challenge': defi, 'namespace': 'ns', 'expires_s': 30}})
    session.recevoir()
    signature2 = base64.b64encode(secrets.token_bytes(48)).decode()
    session.envoyer(requete(params={'signature': signature2}))
    transmis = session.recevoir_pollux()
    session.repondre({'id': transmis['id'], 'ok': False, 'error': {'code': 'signature_invalid'}})
    assert session.recevoir()['error']['code'] == 'signature_invalid'
    session.finir(0, True)
    texte = repr(contexte[-1])
    # Le relais ne journalise pas auth_failed (événement de Pollux) : seules l'ouverture
    # réussie et les fins de session apparaissent, la signature refusée n'ajoute rien.
    # Deux session_ended : un par session de ce test (chemin nominal puis chemin d'erreur),
    # chacune terminée par finir(0, True) ; un seul session_opened, l'ouverture refusée
    # n'en produit pas.
    assert [e['event'] for e in _journaux(contexte)] == ['session_opened', 'session_ended', 'session_ended']
    for secret in (defi, signature, signature2, jeton):
        assert secret not in texte
    sortie = capfd.readouterr()
    assert sortie.err == '' and sortie.out == ''


def test_evenements_session(contexte):
    session = Session(contexte)
    ouvrir(session)
    session.finir(0, True)
    evenements = _journaux(contexte)
    ouverte = [e for e in evenements if e['event'] == 'session_opened'][0]
    assert ouverte['admin'] == 'alice@example.org' and ouverte['source'] == '2001:db8::1'
    assert ouverte['session'] == 1 and 'token' not in ouverte and 'data' not in ouverte
    fin = [e for e in evenements if e['event'] == 'session_ended']
    assert len(fin) == 1 and fin[0]['exit_code'] == 0 and fin[0]['result'] == 'normal'


def test_pollux_session_ignore_environnement(tmp_path, monkeypatch):
    """Aucune variable PARESIA_POLLUX_SESSION_* (ni _CONFIG) n'agit sur pollux-session."""
    racine = racine_conf(tmp_path)
    attendu = configuration(racine_systeme=racine)
    autre = tmp_path / 'pirate.conf'
    autre.write_text('[pollux-session.transport]\nsocket = /tmp/pirate.sock\n')
    autre.chmod(0o600)
    for nom, valeur in {'PARESIA_POLLUX_SESSION_CONFIG': str(autre),
                        'PARESIA_POLLUX_SESSION_TRANSPORT_SOCKET': '/tmp/pirate.sock',
                        'PARESIA_POLLUX_SESSION_TRANSPORT_TIMEOUT_S': '0.1',
                        'PARESIA_POLLUX_SESSION_AUTH_AUTHORIZED_KEYS': '/tmp/pirate',
                        'XDG_CONFIG_HOME': str(tmp_path), 'HOME': str(tmp_path)}.items():
        monkeypatch.setenv(nom, valeur)
    assert configuration(racine_systeme=racine) == attendu
    assert attendu['transport']['socket'] == '/run/paresia-pollux/pollux.sock'


def test_main_erreurs(contexte, tmp_path, monkeypatch, capfd):
    avec_racine(monkeypatch, tmp_path / 'absente')
    assert main([]) == 3
    assert main(['--config', str(EXEMPLE)]) == 3
    monkeypatch.setattr(module_session, 'relayer',
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError('valeur-sensible-xyz')))
    avec_racine(monkeypatch, racine_conf(tmp_path))
    assert main([]) == 3
    evenements = _journaux(contexte)
    assert [e['event'] for e in evenements] == ['configuration_error', 'configuration_error', 'internal_error']
    assert evenements[0]['cause'] == 'config_missing'
    assert evenements[1]['cause'] == 'config_invalid_arguments'
    assert 'valeur-sensible-xyz' not in repr(contexte[-1]) and 'message' not in evenements[2]
    assert capfd.readouterr().err == ''


def test_configuration_manquante_nomme_l_option(contexte, tmp_path, monkeypatch):
    racine = racine_conf(tmp_path, '[pollux-session.transport]\nsocket = /run/x/p.sock\n')
    avec_racine(monkeypatch, racine)
    assert main([]) == 3
    evenement = _journaux(contexte)[-1]
    assert (evenement['cause'], evenement['section'], evenement['option']) == ('config_missing', 'auth', 'authorized_keys')
    assert '/run/x' not in repr(contexte[-1])


# --- lanceur ---

def _lanceur_factice(tmp_path):
    factice = tmp_path / 'python-factice'
    factice.write_text('#!/bin/sh\nfor a in "$@"; do echo "ARG:$a"; done\n/usr/bin/env\n')
    factice.chmod(0o755)
    script = tmp_path / 'pollux-session'
    script.write_text((RACINE / 'server/bin/pollux-session').read_text()
                      .replace('/usr/bin/python3', str(factice)))
    script.chmod(0o755)
    return script


def test_lanceur_pollux_session(tmp_path):
    script = _lanceur_factice(tmp_path)
    env = {'PATH': '/usr/bin:/bin', 'SSH_USER_AUTH': '/run/auth', 'SSH_CONNECTION': '192.0.2.1 1 192.0.2.2 22',
           'LD_PRELOAD': '/tmp/x.so', 'PYTHONWARNINGS': 'error', 'PYTHONSTARTUP': '/tmp/s',
           'PARESIA_POLLUX_SESSION_AUTH_AUTHORIZED_KEYS': '/tmp/pirate',
           'PARESIA_POLLUX_SESSION_CONFIG': '/tmp/pirate.conf', 'PYTHONPATH': '/tmp/pirate'}
    sortie = subprocess.run(['/bin/sh', str(script), '--config', '/tmp/pirate.conf', 'autre'], env=env,
                            capture_output=True, text=True, cwd=str(tmp_path), timeout=20)
    assert sortie.returncode == 0, sortie.stderr
    lignes = sortie.stdout.splitlines()
    assert [ligne for ligne in lignes if ligne.startswith('ARG:')] == [
        'ARG:-P', 'ARG:-s', 'ARG:-B', 'ARG:-m', 'ARG:server.pollux.session']
    variables = dict(ligne.split('=', 1) for ligne in lignes if '=' in ligne and not ligne.startswith('ARG:'))
    variables.pop('PWD', None)
    assert set(variables) == {'PATH', 'PYTHONSAFEPATH', 'PYTHONPATH', 'SSH_USER_AUTH', 'SSH_CONNECTION'}
    assert not any(nom.startswith('PARESIA_') for nom in variables)
    assert variables['PYTHONPATH'] == '/usr/local/lib/paresia'
    assert variables['PYTHONSAFEPATH'] == '1'
    assert variables['SSH_USER_AUTH'] == '/run/auth'
    assert '/tmp/pirate' not in sortie.stdout and 'LD_PRELOAD' not in sortie.stdout


@pytest.mark.parametrize('retirer', ['SSH_USER_AUTH', 'SSH_CONNECTION'])
@pytest.mark.parametrize('vide', [False, True])
def test_lanceur_sans_info_ssh(tmp_path, retirer, vide):
    script = _lanceur_factice(tmp_path)
    env = {'PATH': '/usr/bin:/bin', 'SSH_USER_AUTH': '/run/auth', 'SSH_CONNECTION': '192.0.2.1 1 192.0.2.2 22'}
    if vide:
        env[retirer] = ''
    else:
        del env[retirer]
    sortie = subprocess.run(['/bin/sh', str(script)], env=env, capture_output=True, text=True, timeout=20)
    assert sortie.returncode == 3 and sortie.stdout == '' and sortie.stderr == ''


def test_lanceur_statique():
    script = (RACINE / 'server/bin/pollux-session').read_text()
    assert '/usr/bin/python3 -P -s -B -m server.pollux.session' in script
    assert 'CONFIG' not in script and '.ini' not in script
    assert '$@' not in script and '$*' not in script
    assert ' -I ' not in script and ' -E ' not in script
    assert os.stat(RACINE / 'server/bin/pollux-session').st_mode & stat.S_IXUSR


def test_python_systeme_supporte_safepath():
    resultat = subprocess.run(['/usr/bin/python3', '-c', 'import sys; print(sys.flags.safe_path)'],
                              env={'PYTHONSAFEPATH': '1'}, capture_output=True, text=True, timeout=20)
    assert resultat.stdout.strip() == 'True'
