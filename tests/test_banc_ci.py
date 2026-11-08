# SPDX-License-Identifier: AGPL-3.0-or-later
# Vérifications hors ligne du banc CI ; dépendances : pytest, bibliothèque standard.
#   0.1.18 · 2026-11-08 · Dépendances de vérification limitées à pytest.
# Suivi des versions : 0.1.1 · 2026-11-07 · Moteur enregistré, scénario et artefacts.
#   0.1.2 · 2026-11-07 · Moteur enregistré : réponse du contrôle des dossiers d'état.
#   0.1.1 · 2026-11-07 · Copie du fichier tmpfiles et création avant démarrage du tunnel.
#   0.1.1 · 2026-11-07 · Diagnostics des sockets après échec, sans divulgation.
#   0.1.1 · 2026-11-07 · Ordre SSH, versions antérieures admises et délai de fermeture configuré.
#   0.1.1 · 2026-11-07 · Diagnostic filtré des échecs ; démarrage SSH sans réinitialisation.
#   0.1.5 · 2026-11-07 · Présence de la version dans les deux images.
#   0.1.5 · 2026-11-07 · Lecture effective de VERSION selon les cibles des images.
import configparser
import hashlib
import importlib.util
import ipaddress
import json
from pathlib import Path, PurePosixPath
import re
import secrets
import shlex
import shutil
import subprocess
import threading

import pytest

from banc import journal, orchestrateur as banc

RACINE = Path(__file__).resolve().parents[1]
JETON = 'a' * 64


def evenement(component, event, **champs):
    return '2026-11-07T00:00:00 hote service[1]: ' + json.dumps(
        dict(level='info', component=component, event=event, **champs), separators=(',', ':'))


def exemple(numero=42):
    lignes = ['Accepted publickey for tunnel from 192.0.2.10 port 40000',
              'Accepted publickey for app from 192.0.2.1 port 40001']
    for etape, attendus in journal.ATTENDUS.items():
        for composant, event, champs in attendus:
            lignes.append(evenement(composant, event, session=numero, connexion='connexion', **champs))
    return '\n'.join(lignes)


@pytest.mark.parametrize('etape', journal.ETAPES)
def test_evenements_et_absence(etape):
    assert journal.observer(etape, exemple(), 42)
    with pytest.raises(ValueError, match=etape):
        journal.observer(etape, '', 42)
    if etape != 'E0':
        with pytest.raises(ValueError, match=etape):
            journal.observer(etape, exemple(), 99)


def test_ordre_et_champs():
    lignes = exemple().splitlines()
    lignes[2], lignes[3] = lignes[3], lignes[2]
    with pytest.raises(ValueError, match='E1'):
        journal.observer('E1', '\n'.join(lignes), 42)
    with pytest.raises(ValueError, match='E3'):
        journal.observer('E3', exemple().replace('not_available', 'peer_unavailable'), 42)
    with pytest.raises(ValueError, match='E5'):
        journal.observer('E5', exemple().replace('"reason":"close"', '"reason":"timeout"'), 42)


@pytest.mark.parametrize('texte', [JETON, '-----BEGIN ' + 'OPENSSH PRIVATE KEY-----',
                                    '{"token":"valeur"}', '{"signature": "valeur"}',
                                    '{"challenge":{"valeur":"x"}}', '{"token" : 42}'])
def test_secret_refuse(texte):
    with pytest.raises(journal.SecretPresent):
        journal.verifier(texte, [JETON])


def test_filtrage_et_champs_vides():
    assert journal.verifier('{"token": "", "signature":"", "challenge":""}')
    assert journal.verifier('un\x1b[31m\u202e\ue000\nz') == 'un�[31m��\nz'
    assert journal.verifier(exemple()) == exemple()
    assert journal.verifier('image sha256:' + JETON)
    with pytest.raises(journal.SecretPresent):
        journal.verifier('image sha256:' + JETON, [JETON])


@pytest.mark.parametrize('option', ['--aide', '--version'])
def test_cli_sans_moteur(monkeypatch, capsys, option):
    monkeypatch.setattr(banc, 'moteur', lambda *a, **k: pytest.fail('moteur appelé'))
    with pytest.raises(SystemExit) as fin:
        banc.main([option])
    assert fin.value.code == 0
    sortie = capsys.readouterr().out
    assert ((RACINE / 'VERSION').read_text().strip() if option == '--version' else 'Sous-commandes') in sortie


def test_cli_inconnue(capsys):
    assert banc.main(['inconnue']) == 2
    assert 'Arguments invalides' in capsys.readouterr().err


def test_moteur_absent(monkeypatch, tmp_path):
    def absent(*args, **kwargs):
        raise FileNotFoundError()
    monkeypatch.setattr(banc.subprocess, 'run', absent)
    assert banc.main(['--sortie', str(tmp_path), 'construire']) == 69


def test_point_unique_moteur(monkeypatch):
    appels = []
    def run(args, **kw):
        appels.append((args, kw))
        return subprocess.CompletedProcess(args, 0, '', '')
    monkeypatch.setattr(banc.subprocess, 'run', run)
    banc.moteur(['exec', '-i', 'banc-paresia-admin', 'curl', '-H', '@-'], input=JETON, timeout=12)
    args, kw = appels[0]
    assert args[0] == 'docker' and JETON not in ' '.join(args)
    assert kw['input'] == JETON and kw['timeout'] == 12
    assert not kw.get('shell', False)


class Enregistreur:
    def __init__(self):
        self.appels = []
        self.refus = None

    def __call__(self, args, **kw):
        self.appels.append((args, kw))
        texte, erreur, code = '', '', 0
        if 'is-system-running' in args:
            texte = 'degraded\n'
        elif 'is-active' in args:
            texte = 'active\n'
        elif '/usr/bin/cat' in args and args[-1].endswith('.pub'):
            texte = 'ssh-ed25519 publique\n'
        elif '--failed' in args:
            texte = 'castor.service failed\n'
        elif '--version' in args:
            texte = 'systemd 257\n'
        elif '/usr/bin/stat' in args and args[-1].startswith('/var/lib/paresia-'):
            compte = 'chef' if args[-1].endswith('remus') else args[-1].rsplit('/', 1)[1]
            texte = compte + ':' + compte + ' 711\n'
        elif '-V' in args:
            erreur = 'OpenSSH\n'
        if self.refus and 'start' in args and self.refus in args:
            code, erreur = 1, 'refus de démarrage\n'
        if 'status' in args:
            code, texte = 3, 'unité arrêtée\n'
        return subprocess.CompletedProcess(args, code, texte, erreur)


def preparer(monkeypatch, tmp_path):
    moteur = Enregistreur()
    monkeypatch.setattr(banc, 'moteur', moteur)
    b = banc.Banc(tmp_path / 'journal')
    dossier = tmp_path / 'client'
    dossier.mkdir()
    (dossier / 'client.pub').write_text('ssh-ed25519 publique commentaire-originel')
    monkeypatch.setattr(b, 'creer_client', lambda: dossier)
    return b, moteur


def test_demarrage_conforme(monkeypatch, tmp_path):
    b, moteur = preparer(monkeypatch, tmp_path)
    b.demarrer()
    commandes = [a for a, _ in moteur.appels]
    runs = [a for a in commandes if a[0] == 'run']
    assert len(runs) == 2
    assert sum('--privileged' in a for a in commandes) == 2
    assert [a[a.index('-p') + 1] for a in runs if '-p' in a] == ['127.0.0.1:2222:22']
    assert ['network', 'create', '--subnet', '192.0.2.0/24', banc.RESEAU] in commandes
    assert {a[a.index('--ip') + 1] for a in runs} == {'192.0.2.10', '192.0.2.200'}
    for a in runs:
        assert a[a.index('--name') + 1].startswith(banc.PREFIXE)
        assert a[-2].startswith(banc.PREFIXE)
        assert a[-1] == '/sbin/init'
        assert '--cgroupns=private' in a and 'container=docker' in a
        assert a[a.index('--stop-signal') + 1] == 'SIGRTMIN+3'
        assert {a[i + 1] for i, v in enumerate(a) if v == '--tmpfs'} == {'/run', '/run/lock', '/tmp'}
        assert not any(v in ('-v', '--volume') for v in a)
        assert {a[i + 1] for i, v in enumerate(a) if v == '--mount'} <= set(banc.MONTAGES_HOTE)
    assert [a[-1] for a in commandes if 'start' in a] == [
        'ssh.service', 'castor.service', 'remus.service', 'ssh.service', 'romulus.service',
        'pollux.service', 'paresia-tunnel.service']
    assert all('enable' not in a for a in commandes)
    assert all(JETON not in ' '.join(a) for a in commandes)
    journal_banc = (b.sortie / 'scenario.txt').read_text()
    assert 'degraded' in journal_banc
    assert any(a[-3:] == ['/usr/bin/systemctl', '--failed', '--no-pager'] for a in commandes)
    assert 'castor.service failed' in journal_banc
    assert all(kw['timeout'] > 0 for _, kw in moteur.appels)
    poses = [(a, kw['input']) for a, kw in moteur.appels if kw.get('input')]
    assert any('restrict,port-forwarding,from="192.0.2.10",command="/bin/false"' in s for _, s in poses)
    assert any('restrict,command="/usr/local/bin/pollux-session"' in s for _, s in poses)
    assert any(s == 'restrict,command="/usr/local/bin/pollux-session" ssh-ed25519 publique banc\n'
               for _, s in poses)


def test_unite_refusee_diagnostic_sans_contournement(monkeypatch, tmp_path):
    b, moteur = preparer(monkeypatch, tmp_path)
    moteur.refus = 'castor.service'
    with pytest.raises(banc.Echec) as fin:
        b.demarrer()
    assert fin.value.etape == 'castor.service'
    assert any('status' in a and 'castor.service' in a for a, _ in moteur.appels)
    assert any('30' in a and 'castor.service' in a for a, _ in moteur.appels)
    assert not any('remus.service' in a and 'start' in a for a, _ in moteur.appels)
    assert 'Aucun contournement' in (b.sortie / 'scenario.txt').read_text()


@pytest.mark.parametrize('role', ('admin', 'relais'))
def test_ssh_cles_puis_repertoires_puis_demarrage(monkeypatch, tmp_path, role):
    b, moteur = preparer(monkeypatch, tmp_path)
    b.demarrer()
    prefixe = ['exec', banc.CONTENEURS[role]]
    commandes = [a[len(prefixe):] for a, _ in moteur.appels if a[:len(prefixe)] == prefixe]
    generation = ['/usr/bin/ssh-keygen', '-A']
    repertoires = ['/usr/bin/install', '-d', '-o', 'root', '-g', 'root',
                   '-m', '0755', '/run/sshd', '/run/sudo']
    demarrage = ['/usr/bin/systemctl', 'start', 'ssh.service']
    assert commandes.count(generation) == commandes.count(repertoires) == commandes.count(demarrage) == 1
    assert commandes.index(generation) < commandes.index(repertoires) < commandes.index(demarrage)
    assert all('reset-failed' not in a for a, _ in moteur.appels)
    image = (RACINE / 'tests/banc' / (role + '.containerfile')).read_text()
    assert 'RUN /usr/bin/systemctl --no-reload disable ssh.service ssh.socket' in image


def test_demarrage_commande_refusee_conserve_diagnostic(monkeypatch, tmp_path):
    b, moteur = preparer(monkeypatch, tmp_path)
    commande = ['exec', banc.CONTENEURS['relais'], '/usr/bin/install', '-d', '-o', 'root',
                '-g', 'root', '-m', '0755', '/run/sshd', '/run/sudo']
    lignes = [f'erreur-{n:02d}' for n in range(25)]
    lignes[-1] += ' : accès refusé\x1b'

    def refuser(args, **kw):
        resultat = moteur(args, **kw)
        if args == commande:
            return subprocess.CompletedProcess(args, 1, 'sortie standard non exportée', '\n'.join(lignes) + '\n')
        return resultat

    monkeypatch.setattr(banc, 'moteur', refuser)
    with pytest.raises(banc.Echec) as fin:
        b.demarrer()
    assert fin.value.code == 1 and fin.value.etape == 'demarrer'
    texte = (b.sortie / 'scenario.txt').read_text()
    assert 'Commande en échec : docker ' + ' '.join(commande) in texte
    assert 'Code de retour : 1' in texte
    assert 'Dernières lignes de stderr :\n' + journal.verifier('\n'.join(lignes[-20:])) in texte
    assert all(ligne not in texte for ligne in lignes[:5])
    assert 'sortie standard non exportée' not in texte and '\x1b' not in texte
    assert journal.verifier(texte) == texte
    assert not any('start' in a for a, _ in moteur.appels)


@pytest.mark.parametrize('stderr_sensible', (False, True))
def test_diagnostic_ne_divulgue_pas_entree_ni_jeton(monkeypatch, tmp_path, stderr_sensible):
    jeton = secrets.token_hex(32)
    erreur = 'refus de transport' + (': ' + jeton if stderr_sensible else '')

    def refuser(args, **kw):
        assert kw['input'] == jeton
        return subprocess.CompletedProcess(args, 1, jeton, erreur)

    monkeypatch.setattr(banc, 'moteur', refuser)
    b = banc.Banc(tmp_path)
    b.jetons.append(jeton)
    with pytest.raises(banc.Echec) as fin:
        b.executer('admin', '/usr/bin/curl', '-H', '@-', input=jeton)
    assert fin.value.code == 1
    texte = (tmp_path / 'scenario.txt').read_text()
    assert 'Code de retour : 1' in texte and '/usr/bin/curl -H @-' in texte
    assert jeton not in texte
    assert (banc._MESSAGES['secret'] if stderr_sensible else 'refus de transport') in texte
    assert journal.verifier(texte, [jeton]) == texte


def test_arret_vide_et_cible(monkeypatch, tmp_path):
    moteur = Enregistreur()
    monkeypatch.setattr(banc, 'moteur', moteur)
    b = banc.Banc(tmp_path)
    b.arreter()
    b.arreter()
    for args, _ in moteur.appels:
        assert 'prune' not in args
        assert args[-1].startswith(banc.PREFIXE)
    def absent(args, **kw):
        erreur = 'No such container' if args[0] == 'rm' else 'not found' if args[0] == 'network' else 'No such image'
        return subprocess.CompletedProcess(args, 1, '', erreur)
    monkeypatch.setattr(banc, 'moteur', absent)
    b.arreter()


def test_jeton_uniquement_stdin(monkeypatch, tmp_path):
    moteur = Enregistreur()
    def reponse(args, **kw):
        moteur(args, **kw)
        return subprocess.CompletedProcess(args, 0, '{"error":{"code":"not_available"}} 501\n', '')
    monkeypatch.setattr(banc, 'moteur', reponse)
    b = banc.Banc(tmp_path)
    b.jetons.append(JETON)
    assert b.requete(JETON)[1] == 501
    args, kw = moteur.appels[0]
    assert JETON not in ' '.join(args)
    assert '-i' in args and args[args.index('-H') + 1] == '@-'
    assert kw['input'] == 'X-Admin-Token: ' + JETON + '\nOrigin: http://localhost\n'
    assert JETON not in (tmp_path / 'scenario.txt').read_text()


def test_requete_jouee_par_uid_lighttpd(monkeypatch, tmp_path):
    config = configparser.ConfigParser()
    config.read(RACINE / 'server/conf/paresia.conf')
    uid = config['romulus.http'].getint('uid_lighttpd')
    assert pwd_nom(uid) == banc.UTILISATEUR_HTTP != 'nobody'
    moteur = Enregistreur()
    corps = '{"error":{"code":"not_available"}} 501\n'
    def reponse(args, **kw):
        moteur(args, **kw)
        return subprocess.CompletedProcess(args, 0, corps, '')
    monkeypatch.setattr(banc, 'moteur', reponse)
    banc.Banc(tmp_path).requete(JETON)
    args, kw = moteur.appels[0]
    assert args[args.index('/usr/sbin/runuser') + 1:args.index('/usr/sbin/runuser') + 3] == ['-u', pwd_nom(uid)]
    assert 'nobody' not in args
    assert 'X-Admin-Token: ' + JETON in kw['input'] and 'Origin: http://localhost' in kw['input']
    assert all(JETON not in a for a in args)


def pwd_nom(uid):
    # Identifiants statiques de Debian (base-passwd) utilisés par le banc.
    return {33: 'www-data', 65534: 'nobody'}[uid]


def test_curl_sans_reponse_nomme_e3(monkeypatch, tmp_path):
    for sortie, code in (('', 0), ('illisible', 0), ('', 7)):
        monkeypatch.setattr(banc, 'moteur', lambda a, s=sortie, c=code, **k: subprocess.CompletedProcess(a, c, s, ''))
        b = banc.Banc(tmp_path)
        b.etape = 'E3'
        with pytest.raises(banc.Echec) as fin:
            b.requete(JETON)
        assert fin.value.etape == 'E3'


def test_journal_absent_et_secret(monkeypatch, tmp_path):
    def absent(args, **kw):
        return subprocess.CompletedProcess(args, 1, '', 'conteneur absent')
    monkeypatch.setattr(banc, 'moteur', absent)
    assert banc.main(['--sortie', str(tmp_path), 'journal']) == 1
    assert all((tmp_path / nom).exists() for nom in ('backend-admin.txt', 'backend-relais.txt', 'scenario.txt'))
    def secret(args, **kw):
        return subprocess.CompletedProcess(args, 0, JETON, '')
    monkeypatch.setattr(banc, 'moteur', secret)
    assert banc.main(['--sortie', str(tmp_path), 'journal']) == 1
    assert JETON not in (tmp_path / 'scenario.txt').read_text()
    assert not (tmp_path / 'backend-admin.txt').exists()


def test_delais_configuration():
    config = configparser.ConfigParser()
    config.read(RACINE / 'server/conf/paresia-relais.conf')
    section = config['castor.lights']
    assert banc.HEARTBEAT_S == section.getint('heartbeat_s')
    assert banc.MARGIN_S == section.getint('margin_s')
    assert banc.VERIFICATION_S == section.getint('verification_s')
    assert banc.DELAI_SILENCE == sum(section.getint(n) for n in ('heartbeat_s', 'margin_s', 'verification_s')) + 10
    assert banc.CLOSED_S == section.getint('closed_s')
    assert banc.MARGE_FERMETURE_S > 0
    assert banc.DELAI_FERMETURE == section.getint('closed_s') + banc.MARGE_FERMETURE_S


def verifier_version_suivie(texte, plafond):
    # Versions stables X.Y.Z : comparer les entiers, jamais les chaînes (« 10 » et « 9 »).
    semver = r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)'
    courante = re.fullmatch(semver, plafond)
    suivie = re.search(r'^# Suivi des versions : ' + semver + r'(?=\s|$)', texte, re.MULTILINE)
    assert courante is not None and suivie is not None
    assert tuple(map(int, suivie.groups())) <= tuple(map(int, courante.groups()))


@pytest.mark.parametrize('numero', ('0.1.0', '0.1.9', '0.1.10'))
def test_version_suivie_anterieure_ou_egale(numero):
    verifier_version_suivie('# Suivi des versions : ' + numero + ' · création.', '0.1.10')


@pytest.mark.parametrize('ligne', (
    '# Suivi des versions : 0.1.11 · future.',
    '# Suivi des versions : 00.1.0 · invalide.',
    '# Suivi des versions : 0.1 · incomplète.',
    '# Suivi des versions : absente ; autre référence 0.1.0.',
    '# Version : 0.1.0',
))
def test_version_suivie_invalide_ou_future(ligne):
    with pytest.raises(AssertionError):
        verifier_version_suivie(ligne, '0.1.10')


def test_fichiers_et_images():
    version = (RACINE / 'VERSION').read_text().strip()
    for fichier in [*sorted((RACINE / 'tests/banc').glob('*.py')),
                    *sorted((RACINE / 'tests/banc').glob('*.containerfile'))]:
        if fichier.name in ('client.py', '__init__.py'):
            continue
        texte = fichier.read_text()
        assert fichier.name == fichier.name.lower()
        assert 'SPDX-License-Identifier: AGPL-3.0-or-later' in texte
        verifier_version_suivie(texte, version)
        assert not re.search(r'T0\d{2}', texte)
        assert 'shell' + '=True' not in texte
        assert 'fr' + '_FR' not in texte and 'en' + '_US' not in texte
        for adresse in re.findall(r'(?<![\d.])\d+(?:\.\d+){3}(?![\d.])', texte):
            ip = ipaddress.ip_address(adresse)
            privees = (ipaddress.ip_network((10 << 24, 8)),
                       ipaddress.ip_network(((172 << 24) | (16 << 16), 12)),
                       ipaddress.ip_network(((192 << 24) | (168 << 16), 16)))
            assert not any(ip in plage for plage in privees)
        if fichier.suffix == '.containerfile':
            assert 'FROM debian:trixie' in texte
            for ligne in texte.splitlines():
                if ligne.startswith('COPY '):
                    mots = [m for m in ligne.split()[1:] if not m.startswith('--')]
                    assert all(m == 'VERSION' or m.startswith(('deploy/', 'server/')) for m in mots[:-1])
                if ligne.startswith('RUN '):
                    assert not re.search(r'(sed|tee|>)\s*.*(?:/etc/paresia|/etc/systemd/system|/etc/ssh/sshd_config.d)', ligne)
            assert 'ssh-keygen -A' not in texte


def test_dossiers_etat_controles_apres_demarrage(monkeypatch, tmp_path):
    b, moteur = preparer(monkeypatch, tmp_path)
    b.demarrer()
    commandes = [a for a, _ in moteur.appels]
    for role, demons in banc.DOSSIERS_ETAT.items():
        for demon in demons:
            stat = ['exec', banc.CONTENEURS[role], '/usr/bin/stat', '-c', '%U:%G %a', '/var/lib/paresia-' + demon]
            assert stat in commandes
            unite = [i for i, a in enumerate(commandes) if a[-2:] == ['start', demon + '.service']]
            assert unite and unite[0] < commandes.index(stat)


def test_tmpfiles_du_tunnel_installe_avant_demarrage(monkeypatch, tmp_path):
    image = (RACINE / 'tests/banc/admin.containerfile').read_text()
    source = 'deploy/backend-admin/etc/tmpfiles.d/paresia-tunnel.conf'
    cible = '/etc/tmpfiles.d/paresia-tunnel.conf'
    copies = [l for l in image.splitlines() if l.startswith('COPY ') and cible in l]
    assert len(copies) == 1 and [m for m in copies[0].split() if not m.startswith('--')] == ['COPY', source, cible]
    assert 'RuntimeDirectory' not in (RACINE / 'deploy/backend-admin/etc/systemd/system/paresia-tunnel.service').read_text()
    b, moteur = preparer(monkeypatch, tmp_path)
    b.demarrer()
    commandes = [a for a, _ in moteur.appels]
    creation = ['exec', banc.CONTENEURS['admin'], '/usr/bin/systemd-tmpfiles', '--create', cible]
    demarrage = ['exec', banc.CONTENEURS['admin'], '/usr/bin/systemctl', 'start', 'paresia-tunnel.service']
    assert commandes.count(creation) == 1
    assert commandes.index(creation) < commandes.index(demarrage)


def test_workflow_verifications_inchange():
    texte = (RACINE / '.github/workflows/ci.yml').read_text()
    # Empreinte du bloc livré, stable après commit et sur un checkout CI sans historique.
    bloc = texte.split('  verifications:\n', 1)[1].split('  banc:\n', 1)[0]
    assert hashlib.sha256(bloc.encode()).hexdigest() == '1de70946af6962e3b06a44effeee1a7e0a35119ac1f272192f77f6464fa53fb9'
    job = texte.split('  banc:\n', 1)[1]
    assert 'runs-on: ubuntu-latest' in job and 'container:' not in job
    assert 'permissions:\n      contents: read\n' in job
    assert re.search(r'timeout-minutes: [1-9]\d*', job)
    assert job.count('if: always()') >= 3
    assert 'actions/upload-artifact@v7' in job and 'if-no-files-found: error' in job
    assert 'secrets.' not in job and '--privileged' not in job
    assert 'container:\n      image: debian:trixie' in texte
    assert [m.group(1) for m in re.finditer(r'run: python3 -m banc.orchestrateur (\w+)', job)] == [
        'construire', 'demarrer', 'scenario', 'journal', 'arreter']


class SessionSimulee:
    def __init__(self, numero):
        self.numero = numero
        self.fermetures = 0
        self.ouverte = False
        self.delai_s = 1
        self._arret = threading.Event()
        self._fil = None

    def ouvrir(self):
        self.ouverte = True

    def jeton(self):
        assert self.ouverte
        return ('a' if self.numero == 42 else 'b') * 64

    def fermer(self):
        self.fermetures += 1

    def verifier(self):
        assert self.ouverte


def scenario_simule(monkeypatch, tmp_path):
    b, moteur = preparer(monkeypatch, tmp_path)
    sessions = [SessionSimulee(42), SessionSimulee(43)]
    restantes = iter(sessions)
    monkeypatch.setattr(b, 'session', lambda: next(restantes))
    def lire(role, unite=None):
        texte = exemple(42) + '\n' + exemple(43)
        if b.etape == 'E5 bis':
            texte = '\n'.join(l for l in texte.splitlines()
                              if not ('"session":43' in l and 'session_closed' in l))
        return texte
    monkeypatch.setattr(b, 'lire', lire)
    def requete(jeton):
        if b.etape == 'E6':
            return {'error': {'code': 'token_unknown'}}, 403
        return {'error': {'code': 'not_available'}}, 501
    monkeypatch.setattr(b, 'requete', requete)
    nombre = [0]
    def sonde(numero):
        if b.etape == 'E4':
            return {'data': {'state': 'green'}}
        if b.etape == 'E5':
            nombre[0] += 1
            if nombre[0] == 1:
                return {'error': {'code': 'session_closed'}}
        return {'data': {'state': 'red'}}
    monkeypatch.setattr(b, 'sonde', sonde)
    monkeypatch.setattr(banc.time, 'sleep', lambda _: None)
    return b, sessions


def test_scenario_complet_hors_ligne(monkeypatch, tmp_path):
    b, sessions = scenario_simule(monkeypatch, tmp_path)
    b.scenario()
    texte = (b.sortie / 'scenario.txt').read_text()
    for etape in journal.ETAPES:
        assert etape + ' : observée' in texte
    assert len(set(b.jetons)) == 2
    assert all(s.fermetures for s in sessions)
    assert all(j not in texte for j in b.jetons)


def test_e3_diagnostic_tunnel_sans_secret(monkeypatch, tmp_path):
    b, sessions = scenario_simule(monkeypatch, tmp_path)
    jeton = secrets.token_hex(32)
    monkeypatch.setattr(sessions[0], 'jeton', lambda: jeton)
    monkeypatch.setattr(b, 'requete', banc.Banc.requete.__get__(b))
    moteur_initial = banc.moteur
    appels = []

    def moteur(args, **kw):
        if '/usr/bin/curl' in args:
            return subprocess.CompletedProcess(args, 0,
                '{"ok":false,"error":{"code":"peer_unavailable"}} 503\n', '')
        if b.etape != 'E3':
            return moteur_initial(args, **kw)
        assert not sessions[0].fermetures
        appels.append(args)
        # Une erreur et même une sortie sensible ne doivent pas arrêter les sondes.
        sortie = jeton if '/usr/bin/namei' in args else 'diagnostic simulé\x1b'
        return subprocess.CompletedProcess(args, 1, sortie, 'erreur simulée')

    monkeypatch.setattr(banc, 'moteur', moteur)
    with pytest.raises(banc.Echec, match='E3'):
        b.scenario()
    texte = (b.sortie / 'scenario.txt').read_text()
    assert len(appels) == 10
    assert 'E3 : statut HTTP 503, code de retour curl 0.' in texte
    assert texte.count('Code de retour : 1') == 10
    assert jeton not in texte and '\x1b' not in texte
    assert 'erreur simulée' in texte
    for args in appels:
        assert journal.verifier(banc.shlex.join(['docker', *args])) in texte
    for role, compte, chemin in (
        ('admin', 'paresia-romulus', '/run/paresia-tunnel/romulus/remus.sock'),
        ('admin', 'paresia-pollux', '/run/paresia-tunnel/pollux/castor.sock'),
        ('relais', 'tunnel', '/run/paresia-remus/remus.sock'),
        ('relais', 'tunnel', '/run/paresia-castor/castor.sock'),
    ):
        assert any(a[1] == banc.CONTENEURS[role] and a[2:7] ==
                   ['/usr/sbin/runuser', '-u', compte, '--', '/usr/bin/python3']
                   and a[-1] == chemin for a in appels)
    assert any('/usr/bin/namei' in a and '-l' in a for a in appels)
    assert sum('/usr/bin/getfacl' in a and '-p' in a for a in appels) == 2
    assert any('/usr/bin/ls' in a and '-ld' in a for a in appels)
    for role, unite in (('admin', 'paresia-tunnel'), ('relais', 'ssh')):
        assert ['exec', banc.CONTENEURS[role], '/usr/bin/journalctl', '-u', unite,
                '--no-pager', '-n', '30'] in appels
    journal.verifier(texte, [jeton])


def test_e5_attend_le_delai_de_fermeture(monkeypatch, tmp_path):
    b, _ = scenario_simule(monkeypatch, tmp_path)
    attentes = []
    monkeypatch.setattr(banc, 'DELAI_FERMETURE', 19)
    monkeypatch.setattr(banc.time, 'sleep', attentes.append)
    b.scenario()
    assert attentes == [19]


@pytest.mark.parametrize('etape', journal.ETAPES)
def test_scenario_echec_arrete_les_suivantes(monkeypatch, tmp_path, etape):
    b, sessions = scenario_simule(monkeypatch, tmp_path)
    attendre = b.attendre
    def refuser(courante, *args, **kw):
        if courante == etape:
            raise banc.Echec(etape)
        return attendre(courante, *args, **kw)
    monkeypatch.setattr(b, 'attendre', refuser)
    with pytest.raises(banc.Echec) as fin:
        b.scenario()
    assert fin.value.etape == etape
    texte = (b.sortie / 'scenario.txt').read_text()
    assert etape + ' : non observée' in texte
    for suivante in journal.ETAPES[journal.ETAPES.index(etape) + 1:]:
        assert suivante + ' : non exécutée' in texte
    assert all(s.fermetures for s in sessions if s.ouverte)


def test_attente_absente_bornee(monkeypatch, tmp_path):
    b, _ = preparer(monkeypatch, tmp_path)
    monkeypatch.setattr(b, 'lire', lambda *args: '')
    horloge = iter(range(100))
    monkeypatch.setattr(banc.time, 'monotonic', lambda: next(horloge))
    monkeypatch.setattr(banc.time, 'sleep', lambda _: None)
    with pytest.raises(banc.Echec) as fin:
        b.attendre('E3', 42, delai=2)
    assert fin.value.etape == 'E3'


def test_session_options_ssh(monkeypatch, tmp_path):
    b = banc.Banc(tmp_path)
    b.sauvegarder_etat({'dossier': str(tmp_path)})
    session = b.session()
    args = session.commande
    index = args.index('--')
    assert args[index - 2:index] == ['-o', 'StrictHostKeyChecking=yes']
    assert args[args.index('-p') + 1] == '2222'
    assert 'GlobalKnownHostsFile=/dev/null' in args
    assert 'UserKnownHostsFile=' + str(tmp_path / 'known_hosts') in args
    assert args[-1] == 'app@127.0.0.1'
    # L'environnement modifié par cette méthode est restauré par scenario en usage réel.
    monkeypatch.delenv('SSH_AUTH_SOCK', raising=False)


def test_secret_dans_relecture_finale(monkeypatch, tmp_path):
    b, _ = scenario_simule(monkeypatch, tmp_path)
    lire = b.lire
    lectures = [0]
    def contamine(role, unite=None):
        if b.etape == 'E6' and unite is None:
            lectures[0] += 1
            if lectures[0] > 2:
                return JETON
        return lire(role, unite)
    monkeypatch.setattr(b, 'lire', contamine)
    with pytest.raises(journal.SecretPresent):
        b.scenario()


@pytest.mark.parametrize('refuser_ajout', [False, True])
def test_cle_client_supprimee_apres_chargement(monkeypatch, tmp_path, refuser_ajout):
    dossier = tmp_path / 'temporaire'
    dossier.mkdir()
    b = banc.Banc(tmp_path / 'sortie')
    monkeypatch.setattr(banc.tempfile, 'mkdtemp', lambda **kw: str(dossier))
    monkeypatch.setattr(Path, 'is_socket', lambda _: True)
    appels = []
    class Agent:
        pid = 123456
        def __init__(self, args, **kw):
            appels.append(args)
    monkeypatch.setattr(banc.subprocess, 'Popen', Agent)
    def outil(args, **kw):
        appels.append(args)
        if args[0] == 'ssh-keygen':
            # Simulacre de fichier, aucun matériau cryptographique dans ce test.
            (dossier / 'client').touch()
            (dossier / 'client.pub').write_text('publique')
        if args[0] == 'ssh-add':
            assert (dossier / 'client').exists()
            assert kw['env']['SSH_AUTH_SOCK'] == str(dossier / 'agent')
            if refuser_ajout:
                raise banc.Echec('ssh-add')
    monkeypatch.setattr(banc, 'local', outil)
    if refuser_ajout:
        with pytest.raises(banc.Echec):
            b.creer_client()
    else:
        assert b.creer_client() == dossier
    assert not (dossier / 'client').exists()
    assert (dossier / 'client.pub').exists()
    assert dossier.stat().st_mode & 0o777 == 0o700
    assert appels[0] == ['ssh-agent', '-D', '-a', str(dossier / 'agent')]
    assert b.etat()['pid'] == Agent.pid


def test_enchainement_nettoie_apres_echec(monkeypatch, tmp_path):
    appels = []
    def construire(self):
        appels.append('construire')
        raise banc.Echec('construire')
    monkeypatch.setattr(banc.Banc, 'construire', construire)
    for nom in ('demarrer', 'scenario', 'journal', 'arreter'):
        monkeypatch.setattr(banc.Banc, nom, lambda self, n=nom: appels.append(n))
    assert banc.main(['--sortie', str(tmp_path), 'construire', 'demarrer', 'scenario', 'journal', 'arreter']) == 1
    assert appels == ['construire', 'journal', 'arreter']


def test_attente_systemd_relance_puis_echec(monkeypatch, tmp_path):
    reponses = iter([('', 'bus indisponible\n', 255), ('starting\n', '', 1), ('running\n', '', 0)])
    appels = []

    def moteur(args, **kw):
        appels.append(args)
        if 'is-system-running' in args:
            texte, erreur, code = next(reponses)
            return subprocess.CompletedProcess(args, code, texte, erreur)
        return subprocess.CompletedProcess(args, 0, '', '')
    monkeypatch.setattr(banc, 'moteur', moteur)
    monkeypatch.setattr(banc.time, 'sleep', lambda _: None)
    b = banc.Banc(tmp_path)
    b.attendre_systemd('relais')
    assert sum('is-system-running' in a for a in appels) == 3
    assert all('--wait' not in a for a in appels)
    assert 'code 255' in (tmp_path / 'scenario.txt').read_text()

    def vide(args, **kw):
        return subprocess.CompletedProcess(args, 1, '', 'Failed to connect to bus\n')
    monkeypatch.setattr(banc, 'moteur', vide)
    horloge = iter([0, 0, 100, 100])
    monkeypatch.setattr(banc.time, 'monotonic', lambda: next(horloge))
    with pytest.raises(banc.Echec) as fin:
        b.attendre_systemd('relais')
    assert fin.value.code == 1
    assert 'code 1' in fin.value.etape and 'Failed to connect to bus' in fin.value.etape
    assert 'Failed to connect to bus' in (tmp_path / 'scenario.txt').read_text()


def test_construire_sans_sortie_brute(monkeypatch, tmp_path):
    brut = '#5 writing image sha256:' + 'a1' * 32 + ' done\nSORTIE-BRUTE-UNIQUE\n'

    def moteur(args, **kw):
        return subprocess.CompletedProcess(args, 0, brut, '')
    monkeypatch.setattr(banc, 'moteur', moteur)
    b = banc.Banc(tmp_path)
    b.construire()
    texte = (tmp_path / 'scenario.txt').read_text()
    assert 'SORTIE-BRUTE-UNIQUE' not in texte and 'a1a1' not in texte
    assert 'code de retour 0' in texte
    journal.verifier('FROM debian@sha256:' + 'b2' * 32)

    def echec(args, **kw):
        return subprocess.CompletedProcess(args, 1, '', 'etape ' + 'c3' * 32 + ' fin\nERREUR-FINALE\n')
    monkeypatch.setattr(banc, 'moteur', echec)
    with pytest.raises(banc.Echec):
        b.construire()
    assert 'ERREUR-FINALE' in (tmp_path / 'scenario.txt').read_text()


def test_journal_moteur_absent_ecrit_scenario(monkeypatch, tmp_path):
    def absent(args, **kw):
        raise banc.Echec('Moteur Docker absent.', 69)
    monkeypatch.setattr(banc, 'moteur', absent)
    assert banc.main(['--sortie', str(tmp_path), 'journal']) == 1
    assert all((tmp_path / nom).exists() for nom in ('backend-admin.txt', 'backend-relais.txt', 'scenario.txt'))


@pytest.mark.parametrize('role', ('admin', 'relais'))
def test_image_installe_version(role):
    image = (RACINE / 'tests/banc' / (role + '.containerfile')).read_text()
    assert 'COPY --chmod=0644 VERSION /usr/local/lib/paresia/VERSION' in image.splitlines()


def cibles_code_image(texte):
    """Extrait les deux installations sans fixer leur destination attendue."""
    cibles = {}
    for ligne in texte.splitlines():
        if not ligne.startswith('COPY '):
            continue
        mots = shlex.split(ligne)
        if not mots or mots[0] != 'COPY':
            continue
        arguments = [m for m in mots[1:] if not m.startswith('--')]
        if len(arguments) == 2 and arguments[0] in ('server/', 'VERSION'):
            assert arguments[0] not in cibles
            cible = PurePosixPath(arguments[1])
            assert cible.is_absolute() and '..' not in cible.parts
            cibles[arguments[0]] = cible
    assert set(cibles) == {'server/', 'VERSION'}
    return cibles


def version_depuis_image(texte, dossier):
    """Exerce le vrai lecteur à l'emplacement déduit des directives COPY."""
    cibles = cibles_code_image(texte)
    source = RACINE / 'VERSION'
    assert source.is_file()  # Le contexte de construction du banc est RACINE.
    paquet = dossier.joinpath(*cibles['server/'].parts[1:])
    version = dossier.joinpath(*cibles['VERSION'].parts[1:])
    module = paquet / 'commun/version.py'
    module.parent.mkdir(parents=True)
    version.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(RACINE / 'server/commun/version.py', module)
    shutil.copyfile(source, version)
    specification = importlib.util.spec_from_file_location('version_installee', module)
    lecteur = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(lecteur)
    return lecteur.lire_version()


@pytest.mark.parametrize('role', ('admin', 'relais'))
def test_image_version_emplacement_effectif(role, tmp_path):
    texte = (RACINE / 'tests/banc' / (role + '.containerfile')).read_text()
    assert version_depuis_image(texte, tmp_path) == (RACINE / 'VERSION').read_text().strip()


@pytest.mark.parametrize('role', ('admin', 'relais'))
@pytest.mark.parametrize('source', ('server/', 'VERSION'))
def test_image_version_divergence_detectee(role, source, tmp_path):
    texte = (RACINE / 'tests/banc' / (role + '.containerfile')).read_text()
    cibles = cibles_code_image(texte)
    lignes = []
    for ligne in texte.splitlines():
        mots = shlex.split(ligne) if ligne.startswith('COPY ') else []
        if mots and mots[0] == 'COPY' and source in mots[1:-1]:
            cible = cibles[source]
            mots[-1] = str(cible.parent / 'decale' / cible.name)
            ligne = shlex.join(mots)
        lignes.append(ligne)
    # Mutation du texte seulement : aucun fichier du banc n'est modifié.
    with pytest.raises(RuntimeError, match='^version_unreadable$'):
        version_depuis_image('\n'.join(lignes), tmp_path)
