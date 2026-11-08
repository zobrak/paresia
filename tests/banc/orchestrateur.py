# SPDX-License-Identifier: AGPL-3.0-or-later
# Banc CI de présence ; dépendances : stdlib, Docker, OpenSSH, banc.client et banc.journal.
# Suivi des versions : 0.1.1 · 2026-11-07 · Deux conteneurs et scénario borné.
#   0.1.2 · 2026-11-07 · Contrôle des dossiers d'état des démons après démarrage (StateDirectory=).
#   0.1.1 · 2026-11-07 · Réinitialisation de SSH après création des clés ; délai de fermeture configuré.
#   0.1.1 · 2026-11-07 · Retrait de la réinitialisation SSH ; diagnostic des commandes en échec.
#   0.1.1 · 2026-11-07 · Diagnostic des accès aux sockets après échec du scénario.
#   0.1.1 · 2026-11-07 · Création des dossiers du tunnel par systemd-tmpfiles avant son démarrage.
"""Orchestration réservée au runner ; les imports et l'aide n'appellent aucun moteur."""
import argparse
import configparser
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from . import client, journal as controle

_MESSAGES = {
    'aide': 'Banc de présence à deux conteneurs Docker (CI uniquement).',
    'sortie': 'Dossier des journaux exportés.',
    'commandes': 'Sous-commandes à enchaîner : construire demarrer scenario journal arreter.',
    'usage': 'utilisation : ',
    'positionnels': 'arguments positionnels',
    'options': 'options',
    'version': 'Afficher la version et quitter.',
    'arguments': 'Arguments invalides ; consultez --aide.',
    'moteur': 'Moteur Docker absent.',
    'echec': 'Échec : {etape}.',
    'commande': 'Commande du moteur refusée.',
    'echec_commande': ('Commande en échec : {commande}\nCode de retour : {code}\n'
                       'Dernières lignes de stderr :\n{erreur}'),
    'systeme': 'Erreur système du banc.',
    'secret': 'Journal refusé : donnée sensible détectée ; contenu non exporté.',
    'verdict': '{etape} : {verdict}',
    'succes': 'observée',
    'absente': 'non observée',
    'ignoree': 'non exécutée',
    'etat': '{role} : état systemd {etat}',
    'absent': '{role} : conteneur absent ou arrêté.',
    'ecarts': ('Écarts : conteneurs neufs, sans sauvegarde de procédure ; serveur HTTP joué par '
               'www-data avec paresia-http ; ni nftables, ni sudoers de Remus ; connexions TCP '
               'sortantes du compte tunnel non essayées ; exécutable docker du relais : copie '
               'inerte de true ; client simulé avec agent SSH. Unités et configuration sans adaptation.'),
    'reglages': ('Moteur : privileged, cgroupns=private, container=docker, SIGRTMIN+3, '
                 'tmpfs /run, /run/lock, /tmp ; aucun montage hôte.'),
    'diagnostic': ('Unité {unite} en échec. Aucun contournement appliqué ; réglage du moteur '
                   'susceptible de lever le refus : non établi, à déterminer depuis le diagnostic.'),
    'build': 'Construction {role} : code de retour {code}.',
    'attente': '{role} : systemctl is-system-running, code {code}, état « {etat} », stderr « {erreur} »',
    'systemd': 'systemd {role} (code {code} : {erreur})',
    'socket': 'Sockets du tunnel : modes réels (StreamLocalBindMask livré : 0111).',
    'diagnostic_socket': 'Diagnostic : {commande}\nCode de retour : {code}\n{sortie}',
    'diagnostic_indisponible': 'Commande indisponible ou délai dépassé.',
    'connexion_ok': 'Connexion réussie',
    'connexion_erreur': 'Connexion refusée : errno={errno}, message={message}',
    'http': '{etape} : statut HTTP {statut}, code de retour curl {code}.',
}
# Extraits des interfaces officielles consultées ; les mesures restent celles du runner.
SOURCES = (
    'https://systemd.io/CONTAINER_INTERFACE/ : "send SIGRTMIN+3 to its init process" ; '
    '"Do not drop CAP_MKNOD" (PrivateDevices).',
    'https://docs.docker.com/reference/cli/docker/container/run/ : '
    '"Give extended privileges to this container" (--privileged) ; '
    '"Run the container in its own private cgroup namespace" (--cgroupns=private) ; '
    '"Mount a tmpfs directory" (--tmpfs) ; "Signal to stop the container" (--stop-signal) ; '
    '"Connect a container to a network" (--network) ; "IPv4 address" (--ip) ; '
    '"Publish a container’s port(s) to the host" (-p).',
    'https://docs.docker.com/reference/cli/docker/network/create/ : '
    '"Subnet in CIDR format that represents a network segment" (--subnet).',
    'https://docs.docker.com/reference/cli/docker/buildx/build/ : '
    '"Name of the Dockerfile" (-f) ; "docker build" (alias).',
    'https://docs.docker.com/reference/cli/docker/container/exec/ : '
    '"Keep STDIN open even if not attached" (-i).',
    'https://docs.docker.com/reference/cli/docker/container/rm/ : "Remove one or more containers".',
    'https://docs.docker.com/reference/cli/docker/network/rm/ : "Remove one or more networks".',
    'https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md : '
    '"Docker Client", "Docker Server" ; versions effectives relevées par le workflow.',
    'https://github.com/actions/upload-artifact/blob/main/README.md : '
    '"uses: actions/upload-artifact@v7" (exemple consulté).',
    'https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax : '
    '"timeout-minutes" ; "if: ${{ always() }}".',
)
RACINE = Path(__file__).resolve().parents[2]
PREFIXE = 'banc-paresia-'
RESEAU = PREFIXE + 'reseau'
CONTENEURS = {r: PREFIXE + 'backend-' + r for r in ('admin', 'relais')}
IMAGES = {r: PREFIXE + r for r in CONTENEURS}
MONTAGES_HOTE = ()
# Compte dont l'UID est uid_lighttpd ([romulus.http]) : seul pair HTTP accepté par Romulus.
UTILISATEUR_HTTP = 'www-data'
HEARTBEAT_S = 30
MARGIN_S = 5
VERIFICATION_S = 1
DELAI_SILENCE = HEARTBEAT_S + MARGIN_S + VERIFICATION_S + 10
_CONFIGURATION_RELAIS = configparser.ConfigParser()
_CONFIGURATION_RELAIS.read(RACINE / 'server/conf/paresia-relais.conf', encoding='utf-8')
CLOSED_S = _CONFIGURATION_RELAIS.getint('castor.lights', 'closed_s')
# Laisser expirer la réponse session_closed avant la seconde sonde de E5.
MARGE_FERMETURE_S = 2
DELAI_FERMETURE = CLOSED_S + MARGE_FERMETURE_S
# Dossier d'état créé par StateDirectory= : « propriétaire:groupe mode » attendu, par démon.
DOSSIERS_ETAT = {'admin': {'pollux': 'paresia-pollux', 'romulus': 'paresia-romulus'},
                 'relais': {'castor': 'paresia-castor', 'remus': 'chef'}}
UNITES = {'admin': ('ssh', 'pollux', 'romulus', 'paresia-tunnel'),
          'relais': ('ssh', 'castor', 'remus')}
SONDE = ("import json,secrets,socket,sys; s=socket.socket(socket.AF_UNIX); s.settimeout(3); "
         "s.connect('/run/paresia-castor/castor-state.sock'); "
         "s.sendall(json.dumps({'proto':'jumeaux/1','id':secrets.token_hex(8),"
         "'session':int(sys.argv[1]),'action':'castor/light/state','params':{}}).encode()+b'\\n'); "
         "print(s.makefile('rb').readline().decode().strip())")


class Echec(Exception):
    def __init__(self, etape, code=1):
        self.etape, self.code = etape, code


def moteur(arguments, *, input=None, timeout=60):
    """Point unique d'appel de Docker, remplaçable sans moteur ni réseau."""
    try:
        return subprocess.run(['docker', *arguments], input=input, capture_output=True,
                              text=True, timeout=timeout, check=False)
    except FileNotFoundError:
        raise Echec(_MESSAGES['moteur'], 69) from None
    except subprocess.TimeoutExpired:
        raise Echec(_MESSAGES['commande']) from None


def local(arguments, *, env=None, timeout=15):
    """Ne jamais propager une exception subprocess contenant les arguments ou stdin."""
    try:
        resultat = subprocess.run(arguments, env=env, capture_output=True, text=True,
                                   timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise Echec(_MESSAGES['systeme']) from None
    if resultat.returncode:
        raise Echec(_MESSAGES['systeme'])
    return resultat


class Banc:
    def __init__(self, sortie):
        self.sortie = Path(sortie)
        self.jetons = []
        self.agent = None
        self.etape = 'demarrer'

    def appel(self, arguments, *, input=None, timeout=60, verifier=True):
        resultat = moteur(arguments, input=input, timeout=timeout)
        if verifier and resultat.returncode:
            # Ni stdin ni stdout : seules les dernières lignes d'erreur sont exportées.
            # Un outil peut répéter une donnée sensible reçue sur stdin dans son erreur.
            erreur = '\n'.join(resultat.stderr.splitlines()[-20:])
            try:
                erreur = controle.verifier(erreur, self.jetons)
            except controle.SecretPresent:
                erreur = _MESSAGES['secret']
            self.noter(_MESSAGES['echec_commande'].format(
                commande=shlex.join(['docker', *arguments]), code=resultat.returncode, erreur=erreur))
            raise Echec(self.etape)
        return resultat

    def executer(self, role, *arguments, input=None, timeout=30, verifier=True):
        return self.appel(['exec', *(['-i'] if input is not None else []),
                           CONTENEURS[role], *arguments], input=input,
                          timeout=timeout, verifier=verifier)

    def noter(self, texte):
        propre = controle.verifier(texte, self.jetons)
        self.sortie.mkdir(parents=True, exist_ok=True)
        with (self.sortie / 'scenario.txt').open('a', encoding='utf-8') as flux:
            flux.write(propre + '\n')

    def verdict(self, etape, verdict):
        texte = _MESSAGES['verdict'].format(etape=etape, verdict=_MESSAGES[verdict])
        self.noter(texte)
        print(controle.filtrer(texte), flush=True)

    def construire(self):
        self.etape = 'construire'
        for role in CONTENEURS:
            resultat = self.appel(['build', '-f', str(RACINE / 'tests/banc' / (role + '.containerfile')),
                                   '-t', IMAGES[role], str(RACINE)], timeout=900, verifier=False)
            # Seuls le code de retour et, en cas d'échec, la fin de la sortie sont consignés.
            self.noter(_MESSAGES['build'].format(role=role, code=resultat.returncode))
            if resultat.returncode:
                lignes = (resultat.stdout + resultat.stderr).splitlines()[-20:]
                self.noter(controle.masquer_empreintes('\n'.join(lignes)))
                raise Echec(self.etape)

    def etat(self):
        return json.loads((self.sortie / '.etat.json').read_text(encoding='utf-8'))

    def sauvegarder_etat(self, etat):
        self.sortie.mkdir(parents=True, exist_ok=True)
        chemin = self.sortie / '.etat.json'
        chemin.touch(mode=0o600, exist_ok=True)
        chemin.write_text(json.dumps(etat), encoding='utf-8')

    def creer_client(self):
        dossier = Path(tempfile.mkdtemp(prefix='banc-p-', dir='/tmp'))
        dossier.chmod(0o700)
        sock = str(dossier / 'agent')
        self.sauvegarder_etat({'dossier': str(dossier)})
        try:
            self.agent = subprocess.Popen(['ssh-agent', '-D', '-a', sock],
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            raise Echec(_MESSAGES['systeme']) from None
        self.sauvegarder_etat({'dossier': str(dossier), 'pid': self.agent.pid})
        fin = time.monotonic() + 10
        while not Path(sock).is_socket():
            if self.agent.poll() is not None or time.monotonic() >= fin:
                raise Echec('ssh-agent')
            time.sleep(0.1)
        env = dict(os.environ, SSH_AUTH_SOCK=sock)
        cle = dossier / 'client'
        try:
            local(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(cle)])
            local(['ssh-add', str(cle)], env=env)
        finally:
            cle.unlink(missing_ok=True)
        return dossier

    def poser(self, role, chemin, contenu):
        # tee n'est jamais affiché : seulement des clés publiques ou known_hosts.
        self.executer(role, '/usr/bin/tee', chemin, input=contenu)
        self.executer(role, '/usr/bin/chown', 'root:root', chemin)
        self.executer(role, '/usr/bin/chmod', '0644', chemin)

    def diagnostics(self, role, unite):
        for commande in (('/usr/bin/systemctl', 'status', unite, '--no-pager', '--full'),
                         ('/usr/bin/journalctl', '-u', unite, '-n', '30', '--no-pager', '-o', 'short-iso')):
            r = self.executer(role, *commande, verifier=False)
            self.noter(r.stdout + r.stderr)
        self.noter(_MESSAGES['diagnostic'].format(unite=unite))

    def demarrer_unite(self, role, unite):
        try:
            resultat = self.executer(role, '/usr/bin/systemctl', 'start', unite, verifier=False)
            fin = time.monotonic() + 15
            while not resultat.returncode:
                etat = self.executer(role, '/usr/bin/systemctl', 'is-active', unite, verifier=False)
                if etat.stdout.strip() == 'active':
                    return
                if time.monotonic() >= fin or etat.stdout.strip() in ('failed', 'inactive'):
                    break
                time.sleep(0.25)
        except Echec as erreur:
            if erreur.code == 69:
                raise
        self.diagnostics(role, unite)
        raise Echec(unite)

    def attendre_systemd(self, role, delai=90):
        """Interroge is-system-running sans --wait : sans lui, starting et initializing
        sont rapportés (systemctl(1)) ; running et degraded terminent l'attente."""
        fin = time.monotonic() + delai
        while True:
            r = self.executer(role, '/usr/bin/systemctl', 'is-system-running',
                              timeout=15, verifier=False)
            etat = r.stdout.strip()
            if etat in ('running', 'degraded'):
                self.noter(_MESSAGES['etat'].format(role=role, etat=etat))
                if etat == 'degraded':
                    echecs = self.executer(role, '/usr/bin/systemctl', '--failed', '--no-pager',
                                           verifier=False)
                    self.noter(echecs.stdout + echecs.stderr)
                return
            erreur = ' '.join(controle.filtrer(r.stderr).split())
            if etat not in ('starting', 'initializing'):
                self.noter(_MESSAGES['attente'].format(role=role, code=r.returncode,
                                                       etat=controle.filtrer(etat), erreur=erreur))
            if time.monotonic() >= fin:
                raise Echec(_MESSAGES['systemd'].format(role=role, code=r.returncode, erreur=erreur))
            time.sleep(1)

    def demarrer(self):
        self.etape = 'demarrer'
        self.noter(_MESSAGES['ecarts'])
        self.noter(_MESSAGES['reglages'])
        self.noter('\n'.join(SOURCES))
        self.appel(['network', 'create', '--subnet', '192.0.2.0/24', RESEAU])
        for role, adresse in (('relais', '192.0.2.200'), ('admin', '192.0.2.10')):
            commande = ['run', '-d', '--name', CONTENEURS[role], '--privileged',
                        '--cgroupns=private', '--env', 'container=docker',
                        '--stop-signal', 'SIGRTMIN+3', '--tmpfs', '/run',
                        '--tmpfs', '/run/lock', '--tmpfs', '/tmp',
                        '--network', RESEAU, '--ip', adresse]
            for montage in MONTAGES_HOTE:
                commande += ['--mount', montage]
            if role == 'admin':
                commande += ['-p', '127.0.0.1:2222:22']
            self.appel([*commande, IMAGES[role], '/sbin/init'])
            self.attendre_systemd(role)
            for outils in (('/usr/bin/systemctl', '--version'), ('/usr/bin/ssh', '-V')):
                r = self.executer(role, *outils)
                self.noter(role + '\n' + r.stdout + r.stderr)
            self.executer(role, '/usr/bin/ssh-keygen', '-A')
            self.executer(role, '/usr/bin/install', '-d', '-o', 'root', '-g', 'root',
                          '-m', '0755', '/run/sshd', '/run/sudo')
        dossier = self.creer_client()
        champs = (dossier / 'client.pub').read_text(encoding='ascii').split()
        if len(champs) < 2 or champs[0] != 'ssh-ed25519':
            raise Echec('authorized_keys')
        publique = ' '.join(champs[:2])
        self.poser('admin', '/var/lib/paresia-app/.ssh/authorized_keys',
                   'restrict,command="/usr/local/bin/pollux-session" ' + publique + ' banc\n')
        self.executer('admin', '/usr/bin/ssh-keygen', '-q', '-t', 'ed25519', '-N', '',
                      '-f', '/etc/paresia/tunnel/id_ed25519')
        self.executer('admin', '/usr/bin/chown', 'paresia-tunnel:paresia-tunnel',
                      '/etc/paresia/tunnel/id_ed25519')
        self.executer('admin', '/usr/bin/chmod', '0400', '/etc/paresia/tunnel/id_ed25519')
        publique = self.executer('admin', '/usr/bin/cat', '/etc/paresia/tunnel/id_ed25519.pub').stdout.strip()
        self.executer('admin', '/usr/bin/chown', 'root:root', '/etc/paresia/tunnel/id_ed25519.pub')
        self.executer('admin', '/usr/bin/chmod', '0644', '/etc/paresia/tunnel/id_ed25519.pub')
        self.poser('relais', '/var/lib/paresia-tunnel/.ssh/authorized_keys',
                   'restrict,port-forwarding,from="192.0.2.10",command="/bin/false" ' + publique + '\n')
        for role, hote in (('admin', '[127.0.0.1]:2222'), ('relais', '192.0.2.200')):
            publique = self.executer(role, '/usr/bin/cat', '/etc/ssh/ssh_host_ed25519_key.pub').stdout
            champs = publique.split()
            if len(champs) < 2 or champs[0] != 'ssh-ed25519':
                raise Echec('known_hosts')
            ligne = hote + ' ' + ' '.join(champs[:2]) + '\n'
            if role == 'admin':
                (dossier / 'known_hosts').write_text(ligne, encoding='ascii')
            else:
                self.poser('admin', '/etc/paresia/tunnel/known_hosts', ligne)
        for role, unites in (('relais', ('ssh', 'castor', 'remus')),
                             ('admin', ('ssh', 'romulus', 'pollux', 'paresia-tunnel'))):
            self.executer(role, '/usr/sbin/sshd', '-t')
            for unite in unites:
                if unite == 'paresia-tunnel':
                    # systemd-tmpfiles(8), --create : crée les dossiers déclarés par tmpfiles.d(5).
                    self.executer(role, '/usr/bin/systemd-tmpfiles', '--create',
                                  '/etc/tmpfiles.d/paresia-tunnel.conf')
                self.demarrer_unite(role, unite + '.service')
            self.controler_dossiers_etat(role)

    def controler_dossiers_etat(self, role):
        """systemd.exec(5), StateDirectory= : dossier créé au démarrage, propriété de User= et Group=,
        mode StateDirectoryMode= ; aucune écriture refusée par ProtectSystem=strict. Métriques inactives."""
        for demon, compte in DOSSIERS_ETAT[role].items():
            r = self.executer(role, '/usr/bin/stat', '-c', '%U:%G %a', '/var/lib/paresia-' + demon)
            self.exiger(r.stdout.strip() == compte + ':' + compte + ' 711')
        journal = self.executer(role, '/usr/bin/journalctl', '--no-pager', '-o', 'cat', verifier=False)
        self.exiger('read-only file system' not in (journal.stdout + journal.stderr).lower())

    def lire(self, role, unite=None):
        commande = ['/usr/bin/journalctl', '--no-pager', '-o', 'short-iso']
        for nom in ((unite,) if unite else UNITES[role]):
            commande += ['-u', nom + '.service']
        return self.executer(role, *commande).stdout

    def attendre(self, etape, numero=None, *, delai=15):
        fin = time.monotonic() + delai
        while True:
            texte = self.lire('admin') + '\n' + self.lire('relais')
            controle.verifier(texte, self.jetons)
            try:
                preuves = controle.observer(etape, texte, numero)
            except ValueError:
                if time.monotonic() >= fin:
                    raise Echec(etape) from None
                time.sleep(0.25)
            else:
                self.noter('\n'.join(preuves))
                return

    def session(self):
        dossier = Path(self.etat()['dossier'])
        os.environ['SSH_AUTH_SOCK'] = str(dossier / 'agent')
        session = client.Session(hote='127.0.0.1', compte='app', cle_publique=dossier / 'client.pub', admin='banc')
        index = session.commande.index('--')
        session.commande[index:index] = ['-p', '2222', '-o', 'UserKnownHostsFile=' + str(dossier / 'known_hosts'),
                                        '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'StrictHostKeyChecking=yes']
        return session

    def requete(self, jeton):
        r = self.executer('admin', '/usr/sbin/runuser', '-u', UTILISATEUR_HTTP, '-g', 'paresia-http', '--',
                          '/usr/bin/curl', '--max-time', '15', '-sS', '-w', ' %{http_code}\n',
                          '--unix-socket', '/run/paresia-romulus/romulus-http.sock',
                          '-X', 'POST', '-d', '', '-H', '@-',
                          'http://localhost/api/admin/relay/state/status',
                          input='X-Admin-Token: ' + jeton + '\nOrigin: http://localhost\n',
                          verifier=False)
        statut_brut = r.stdout.strip().rsplit(' ', 1)[-1]
        self.noter(_MESSAGES['http'].format(
            etape=self.etape, statut=statut_brut if re.fullmatch('[0-9]{3}', statut_brut) else '?',
            code=r.returncode))
        self.noter(r.stdout + r.stderr)
        try:
            corps, statut = r.stdout.strip().rsplit(' ', 1)
            return json.loads(corps), int(statut)
        except (ValueError, TypeError):
            raise Echec(self.etape) from None

    def sonde(self, numero):
        r = self.executer('relais', '/usr/sbin/runuser', '-u', 'chef', '-g', 'chef', '-G', 'paresia-castor-etat', '--',
                          '/usr/bin/python3', '-c', SONDE, str(numero))
        self.noter(r.stdout)
        try:
            return json.loads(r.stdout)
        except ValueError:
            raise Echec(self.etape) from None

    def sonde_fermee(self, numero, delai=4):
        # La fermeture gagne Castor par le tunnel ; closed_s (10 s) borne la fenêtre d'observation.
        fin = time.monotonic() + delai
        while True:
            if self.sonde(numero).get('error', {}).get('code') == 'session_closed':
                return True
            if time.monotonic() >= fin:
                return False
            time.sleep(0.25)

    def sans_ping(self, session):
        # Le client simulé pingue seul (heartbeat_s < green_s) : le feu ne s'éteindrait jamais.
        # Le fil est arrêté sans fermer la session, qui reste ouverte (timeout_s de Pollux).
        session._arret.set()
        if session._fil is not None:
            session._fil.join(timeout=session.delai_s + 1)

    def exiger(self, condition):
        if not condition:
            raise Echec(self.etape)

    def diagnostic_tunnel(self):
        """Sondes sans données applicatives ; une commande refusée n'arrête pas les suivantes."""
        locales = ('/run/paresia-tunnel/romulus/remus.sock',
                   '/run/paresia-tunnel/pollux/castor.sock')
        distantes = ('/run/paresia-remus/remus.sock', '/run/paresia-castor/castor.sock')
        dossiers = ('/run/paresia-remus', '/run/paresia-castor')
        commandes = [
            ('admin', ('/usr/bin/namei', '-l', *locales)),
            ('admin', ('/usr/bin/getfacl', '-p', '/run/paresia-tunnel',
                       '/run/paresia-tunnel/romulus', '/run/paresia-tunnel/pollux', *locales)),
            ('relais', ('/usr/bin/ls', '-ld', *dossiers, *distantes)),
            ('relais', ('/usr/bin/getfacl', '-p', *dossiers, *distantes)),
        ]
        programme = (
            'import socket,sys\n'
            'with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:\n'
            ' s.settimeout(3)\n'
            ' try:\n'
            '  s.connect(sys.argv[1])\n'
            f'  print({_MESSAGES["connexion_ok"]!r})\n'
            ' except OSError as e:\n'
            f'  print({_MESSAGES["connexion_erreur"]!r}.format(errno=e.errno, message=str(e)))\n'
        )
        for role, comptes, sockets in (
                ('admin', ('paresia-romulus', 'paresia-pollux'), locales),
                ('relais', ('tunnel', 'tunnel'), distantes)):
            for compte, chemin in zip(comptes, sockets):
                commandes.append((role, ('/usr/sbin/runuser', '-u', compte, '--',
                                         '/usr/bin/python3', '-c', programme, chemin)))
        commandes.extend((role, ('/usr/bin/journalctl', '-u', unite, '--no-pager', '-n', '30'))
                         for role, unite in (('admin', 'paresia-tunnel'), ('relais', 'ssh')))
        for role, arguments in commandes:
            try:
                resultat = self.executer(role, *arguments, verifier=False)
                code, sortie = resultat.returncode, resultat.stdout + resultat.stderr
            except (Echec, OSError, subprocess.TimeoutExpired) as erreur:
                code = erreur.code if isinstance(erreur, Echec) else 1
                sortie = _MESSAGES['diagnostic_indisponible']
            try:
                sortie = controle.verifier(sortie, self.jetons)
            except controle.SecretPresent:
                sortie = _MESSAGES['secret']
            self.noter(_MESSAGES['diagnostic_socket'].format(
                commande=shlex.join(['docker', 'exec', CONTENEURS[role], *arguments]),
                code=code, sortie=sortie))

    def scenario(self):
        sessions = []
        terminees = set()
        ancien_env = os.environ.get('SSH_AUTH_SOCK')
        try:
            for etape in controle.ETAPES:
                self.etape = etape
                if etape == 'E0':
                    self.exiger(self.executer('admin', '/usr/bin/systemctl', 'is-active',
                                             'paresia-tunnel.service').stdout.strip() == 'active')
                    fin = time.monotonic() + 15
                    while True:
                        r = self.executer('admin', '/usr/bin/stat', '-c', '%a %U:%G %n',
                                          '/run/paresia-tunnel/pollux/castor.sock',
                                          '/run/paresia-tunnel/romulus/remus.sock', verifier=False)
                        if r.returncode == 0:
                            break
                        if time.monotonic() >= fin:
                            raise Echec(etape)
                        time.sleep(0.25)
                    self.noter(_MESSAGES['socket'] + '\n' + r.stdout)
                    self.executer('admin', '/usr/bin/python3', '-c',
                                  "import pathlib,stat; assert all(stat.S_ISSOCK(p.stat().st_mode) for p in "
                                  "map(pathlib.Path, ['/run/paresia-tunnel/pollux/castor.sock',"
                                  "'/run/paresia-tunnel/romulus/remus.sock']))")
                    self.attendre(etape)
                elif etape == 'E1':
                    session = self.session()
                    sessions.append(session)
                    session.ouvrir()
                    self.jetons.append(session.jeton())
                    numero = session.numero
                    self.attendre(etape, numero)
                    self.exiger('Accepted publickey for app' in self.lire('admin', 'ssh'))
                elif etape == 'E2':
                    jeton = session.jeton()
                    self.jetons.append(jeton)
                    self.exiger(re.fullmatch('[0-9a-f]{64}', jeton) is not None)
                    self.attendre(etape, numero)
                elif etape == 'E3':
                    corps, statut = self.requete(jeton)
                    self.exiger(statut == 501 and corps.get('error', {}).get('code') == 'not_available')
                    self.attendre(etape, numero)
                elif etape == 'E4':
                    self.attendre(etape, numero)
                    self.exiger(self.sonde(numero).get('data', {}).get('state') == 'green')
                    self.exiger('peer_unavailable' not in self.lire('admin', 'pollux') + self.lire('admin', 'romulus'))
                elif etape == 'E5':
                    session.fermer()
                    # La sonde immédiate précède les sondages journald pour ne pas perdre closed_s.
                    self.exiger(self.sonde_fermee(numero))
                    self.attendre(etape, numero, delai=5)
                    time.sleep(DELAI_FERMETURE)
                    self.exiger(self.sonde(numero).get('data', {}).get('state') == 'red')
                elif etape == 'E5 bis':
                    seconde = self.session()
                    sessions.append(seconde)
                    seconde.ouvrir()
                    self.sans_ping(seconde)
                    second_jeton = seconde.jeton()
                    self.jetons.append(second_jeton)
                    corps, statut = self.requete(second_jeton)
                    self.exiger(statut == 501 and corps.get('error', {}).get('code') == 'not_available')
                    self.attendre(etape, seconde.numero, delai=DELAI_SILENCE)
                    self.exiger(self.sonde(seconde.numero).get('data', {}).get('state') == 'red')
                    seconde.verifier()
                    self.exiger(not any(o.get('event') == 'session_closed' and o.get('session') == seconde.numero
                                        for _, o in controle.evenements(self.lire('admin', 'pollux'))))
                elif etape == 'E6':
                    avant = [l for l, o in controle.evenements(self.lire('admin', 'romulus'))
                             if o['event'] == 'action_routed']
                    corps, statut = self.requete(jeton)
                    self.exiger(statut == 403 and corps.get('error', {}).get('code') == 'token_unknown')
                    self.attendre(etape, numero)
                    apres = [l for l, o in controle.evenements(self.lire('admin', 'romulus'))
                             if o['event'] == 'action_routed']
                    self.exiger(avant == apres)
                terminees.add(etape)
                self.verdict(etape, 'succes')
        except (Echec, client.ErreurClient, OSError, ValueError, subprocess.TimeoutExpired):
            if self.etape in ('E3', 'E4', 'E5', 'E5 bis', 'E6'):
                self.diagnostic_tunnel()
            self.verdict(self.etape, 'absente')
            raise Echec(self.etape) from None
        finally:
            try:
                for session in sessions:
                    try:
                        session.fermer()
                    except (client.ErreurClient, OSError, subprocess.TimeoutExpired):
                        pass
                for etape in controle.ETAPES:
                    if etape not in terminees and etape != self.etape:
                        self.verdict(etape, 'ignoree')
                # Dernier contrôle avec les deux secrets encore en mémoire, avant export.
                for role in CONTENEURS:
                    controle.verifier(self.lire(role), self.jetons)
            finally:
                if ancien_env is None:
                    os.environ.pop('SSH_AUTH_SOCK', None)
                else:
                    os.environ['SSH_AUTH_SOCK'] = ancien_env

    def journal(self):
        erreur = False
        for role, unites in UNITES.items():
            parties = []
            for unite in unites:
                for commande in (('/usr/bin/journalctl', '-u', unite + '.service', '--no-pager', '-o', 'short-iso'),
                                 ('/usr/bin/systemctl', 'status', unite + '.service', '--no-pager', '--full')):
                    try:
                        r = self.executer(role, *commande, verifier=False)
                    except Echec:
                        erreur = True
                        continue
                    if r.returncode and commande[0].endswith('journalctl'):
                        erreur = True
                    parties.append(r.stdout + r.stderr)
            try:
                present = self.executer(role, '/usr/bin/true', verifier=False).returncode == 0
            except Echec:
                present = False
            if not present:
                erreur = True
                parties.append(_MESSAGES['absent'].format(role=role))
            texte = controle.verifier('\n'.join(parties), self.jetons)
            self.sortie.mkdir(parents=True, exist_ok=True)
            (self.sortie / ('backend-' + role + '.txt')).write_text(texte, encoding='utf-8')
        chemin = self.sortie / 'scenario.txt'
        precedent = chemin.read_text(encoding='utf-8') if chemin.exists() else ''
        for etape in controle.ETAPES:
            if not any(ligne.startswith(etape + ' : ') for ligne in precedent.splitlines()):
                self.verdict(etape, 'ignoree')
        controle.verifier(chemin.read_text(encoding='utf-8'), self.jetons)
        if erreur:
            raise Echec(_MESSAGES['absent'].format(role='journal'))

    def arreter(self):
        # Noms fermés, jamais de sélection globale ni d'objet fourni par un état relu.
        erreur = False
        try:
            for role in CONTENEURS:
                r = self.appel(['rm', '-f', CONTENEURS[role]], verifier=False)
                erreur |= bool(r.returncode and 'No such container' not in r.stderr)
            r = self.appel(['network', 'rm', RESEAU], verifier=False)
            erreur |= bool(r.returncode and 'not found' not in r.stderr)
            for image in IMAGES.values():
                r = self.appel(['image', 'rm', '-f', image], verifier=False)
                erreur |= bool(r.returncode and 'No such image' not in r.stderr)
        finally:
            chemin = self.sortie / '.etat.json'
            if chemin.exists():
                etat = self.etat()
                dossier = Path(etat['dossier'])
                # État public validé avant suppression et signal ; aucun chemin arbitraire.
                if (dossier.parent != Path('/tmp') or not dossier.name.startswith('banc-p-')
                        or dossier.is_symlink()):
                    raise Echec('arreter')
                pid = etat.get('pid')
                if type(pid) is int and pid > 1:
                    try:
                        args = Path('/proc') / str(pid) / 'cmdline'
                        attendu = ['ssh-agent', '-D', '-a', str(dossier / 'agent')]
                        if args.read_bytes().split(b'\0')[:-1] == [a.encode() for a in attendu]:
                            os.kill(pid, signal.SIGTERM)
                            if self.agent is not None:
                                self.agent.wait(timeout=5)
                    except (FileNotFoundError, ProcessLookupError):
                        pass
                if dossier.exists():
                    shutil.rmtree(dossier, ignore_errors=False)
                chemin.unlink()
        if erreur:
            raise Echec('arreter')


class Arguments(argparse.ArgumentParser):
    def format_usage(self):
        return super().format_usage().replace('usage: ', _MESSAGES['usage'], 1)

    def format_help(self):
        return super().format_help().replace('usage: ', _MESSAGES['usage'], 1)

    def error(self, message):
        raise Echec(_MESSAGES['arguments'], 2)


def main(argv=None):
    parseur = Arguments(description=_MESSAGES['aide'], add_help=False)
    parseur._positionals.title = _MESSAGES['positionnels']
    parseur._optionals.title = _MESSAGES['options']
    parseur.add_argument('--aide', action='help', help=_MESSAGES['aide'])
    parseur.add_argument('--version', action='version', version=(RACINE / 'VERSION').read_text().strip(),
                         help=_MESSAGES['version'])
    parseur.add_argument('--sortie', default='banc-journal', help=_MESSAGES['sortie'])
    parseur.add_argument('commandes', nargs='+', choices=('construire', 'demarrer', 'scenario', 'journal', 'arreter'),
                         help=_MESSAGES['commandes'])
    banc = None
    try:
        args = parseur.parse_args(argv)
        banc = Banc(args.sortie)
        code = 0
        for commande in args.commandes:
            if code and commande not in ('journal', 'arreter'):
                continue
            try:
                banc.etape = commande
                getattr(banc, commande)()
            except controle.SecretPresent:
                # Aucune donnée suspecte ne doit survivre dans un artefact de ce banc.
                for nom in ('scenario.txt', 'backend-admin.txt', 'backend-relais.txt'):
                    (banc.sortie / nom).unlink(missing_ok=True)
                banc.noter(_MESSAGES['secret'])
                print(_MESSAGES['secret'], file=sys.stderr)
                code = code or 1
            except Echec as erreur:
                print(controle.filtrer(_MESSAGES['echec'].format(etape=erreur.etape)), file=sys.stderr)
                code = code or erreur.code
            except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
                print(controle.filtrer(_MESSAGES['echec'].format(etape=commande)), file=sys.stderr)
                code = code or 1
        return code
    except Echec as erreur:
        print(controle.filtrer(_MESSAGES['echec'].format(etape=erreur.etape)), file=sys.stderr)
        return erreur.code
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        print(_MESSAGES['systeme'], file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
