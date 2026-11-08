# SPDX-License-Identifier: AGPL-3.0-or-later
# Environnement factice des scripts d'installation : racine temporaire, comptes simulés, commandes
# factices en tête du PATH (voir faux_systeme.py). Les scripts n'ont aucun crochet de test.
# Dépendances : bibliothèque standard.
# Suivi des versions
#   0.1.0  2026-11-07  Création.
#   0.1.1  2026-11-07  Enveloppes lancées avec python3 -I -P -S (sans import de site).
#   0.1.3  2026-11-08  Copie de admin/web/ dans le modèle et dossier /usr/local/share du système simulé (étape web).
#   0.1.2  2026-11-07  Port d'essai propre à chaque instance, obtenu par une liaison sur le port 0.
import getpass
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

RACINE_DEPOT = Path(__file__).resolve().parents[2]
FAUX = Path(__file__).resolve().parent / 'faux_systeme.py'
COMMANDES = ('sudo', 'id', 'getent', 'ss', 'ssh-keyscan', 'systemctl', 'ssh-keygen', 'curl')
SENTINELLE = 'SENTINELLE-SECRETE-9f3a71c2'

OS_RELEASE = 'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nID=debian\nVERSION_ID="13"\n'
LOGIN_DEFS = 'SYS_UID_MIN 100\nSYS_UID_MAX 999\nSYS_GID_MIN 100\nSYS_GID_MAX 999\nUID_MIN 1000\nGID_MIN 1000\n'
ADDUSER_CONF = 'FIRST_SYSTEM_UID=100\nLAST_SYSTEM_UID=999\n'
SSHD_CONFIG = 'Include /etc/ssh/sshd_config.d/*.conf\nUsePAM yes\n'
SUDOERS = '@includedir /etc/sudoers.d\n'
EMPREINTE_HOTE_CORPS = 'AAAAC3NzaC1lZDI1NTE5AAAAIHoteRelaisDeTest0123456789abcdefghijklmnop'


def copier_modele(destination):
    """Copie minimale du dépôt (server/, deploy/, i18n/, admin/web/) servant de clone aux essais."""
    ignorer = shutil.ignore_patterns('__pycache__', '*.pyc', '.worktrees')
    shutil.copy(RACINE_DEPOT / 'VERSION', destination / 'VERSION')
    for nom in ('server', 'deploy', 'i18n'):
        shutil.copytree(RACINE_DEPOT / nom, destination / nom, ignore=ignorer, symlinks=True)
    shutil.copytree(RACINE_DEPOT / 'admin' / 'web', destination / 'admin' / 'web', ignore=ignorer, symlinks=True)


class Faux:
    def __init__(self, base, modele, machine, uid=None):
        self.base = Path(base).resolve()
        self.machine = machine
        self.racine = self.base / 'racine'
        self.etat = self.base / 'etat'
        self.bin = self.base / 'bin'
        self.travail = self.base / 'travail'      # dossier d'exécution : défaut du journal (0700, au compte de l'essai)
        self.clone = self.base / 'clone'
        for d in (self.racine, self.etat, self.bin, self.travail):
            d.mkdir(parents=True)
        self.travail.chmod(0o700)
        shutil.copytree(modele, self.clone, symlinks=True)
        self.script = self.clone / 'deploy' / f'backend-{machine}' / f'installer-backend-{machine}.sh'
        os.chmod(self.script, 0o755)
        for nom in COMMANDES:
            f = self.bin / nom
            f.write_text(f'#!/bin/sh\nexec python3 -I -P -S {FAUX} {nom} "$@"\n')
            f.chmod(0o755)
        self.uid = 0 if machine == 'admin' else 1000
        if uid is not None:
            self.uid = uid
        (self.etat / 'uid').write_text(str(self.uid))
        (self.etat / 'hostkey').write_text(EMPREINTE_HOTE_CORPS + '\n')
        (self.etat / 'sentinelle').write_text(SENTINELLE)
        (self.etat / 'passwd').write_text('root:x:0:0:root:/root:/bin/bash\nnobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin\n'
                                          'www-data:x:33:33:www-data:/var/www:/usr/sbin/nologin\n')
        (self.etat / 'group').write_text('root:x:0:\nnogroup:x:65534:\nwww-data:x:33:\n')
        self.ecrire('/etc/os-release', OS_RELEASE)
        self.ecrire('/etc/login.defs', LOGIN_DEFS)
        self.ecrire('/etc/adduser.conf', ADDUSER_CONF)
        self.ecrire('/etc/ssh/sshd_config', SSHD_CONFIG)
        self.ecrire('/etc/sudoers', SUDOERS)
        self.ecrire('/etc/ssh/ssh_host_ed25519_key.pub', 'ssh-ed25519 %s root@hote\n' % EMPREINTE_HOTE_CORPS)
        (self.racine / 'etc/sudoers.d').mkdir()
        (self.racine / 'run/sudo').mkdir(parents=True)
        for d in ('usr/local/bin', 'usr/local/lib', 'usr/local/share', 'etc/ssh/sshd_config.d', 'etc/systemd/system', 'var/lib', 'var/log'):
            (self.racine / d).mkdir(parents=True, exist_ok=True)
        for chemin in ('usr/sbin/sshd', 'usr/sbin/nft', 'usr/sbin/visudo', 'usr/sbin/runuser', 'usr/bin/sudo',
                       'usr/bin/curl', 'usr/bin/ssh-keygen', 'usr/bin/ssh-keyscan'):
            self.ecrire('/' + chemin, '')
            (self.racine / chemin).chmod(0o755)
        # Port libre propre à cette instance (deux installations d'un même test ne partagent pas de port).
        with socket.socket() as libre:
            libre.bind(('127.0.0.1', 0))
            self.port = libre.getsockname()[1]

    # -- utilitaires ------------------------------------------------------------------------
    def chemin(self, absolu):
        return Path(str(self.racine) + absolu)

    def ecrire(self, absolu, texte):
        p = self.chemin(absolu)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(texte)

    def lire(self, absolu):
        return self.chemin(absolu).read_text()

    def existe(self, absolu):
        return self.chemin(absolu).exists()

    def regler(self, **valeurs):
        f = self.etat / 'knobs.json'
        donnees = json.loads(f.read_text()) if f.exists() else {}
        donnees.update(valeurs)
        f.write_text(json.dumps(donnees))

    def comptes(self):
        return (self.etat / 'passwd').read_text(), (self.etat / 'group').read_text()

    def appels(self):
        f = self.etat / 'appels.log'
        return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []

    def arbre(self, exclure=('run/paresia-installation', 'var/backups')):
        """{chemin relatif: (type, mode)} de la racine, hors sauvegardes, copie de travail et journal."""
        resultat = {}
        for p in sorted(self.racine.rglob('*')):
            rel = str(p.relative_to(self.racine))
            if any(rel == e or rel.startswith(e + '/') for e in exclure):
                continue
            resultat[rel] = ('d' if p.is_dir() else 'f', oct(p.stat().st_mode & 0o7777),
                             p.read_bytes() if p.is_file() else None)
        return resultat

    def jeux(self):
        dossier = self.racine / 'var/backups/paresia' / self.machine
        return sorted(p.name for p in dossier.iterdir()) if dossier.exists() else []

    def instantane(self, nom):
        """Copie de la racine et de l'état simulé ; restaurés en place (mêmes chemins, donc manifestes valides)."""
        cible = self.base / f'instantane-{nom}'
        shutil.rmtree(cible, ignore_errors=True)
        shutil.copytree(self.racine, cible / 'racine', symlinks=True)
        shutil.copytree(self.etat, cible / 'etat', symlinks=True)

    def restaurer(self, nom):
        source = self.base / f'instantane-{nom}'
        shutil.rmtree(self.racine)
        shutil.rmtree(self.etat)
        shutil.copytree(source / 'racine', self.racine, symlinks=True)
        shutil.copytree(source / 'etat', self.etat, symlinks=True)

    def environnement(self, extra=None):
        env = {'PATH': f'{self.bin}:/usr/bin:/bin', 'FAUX_ETAT': str(self.etat), 'FAUX_RACINE': str(self.racine),
               'FAUX_DEPOT': str(self.clone), 'USER_REEL': getpass.getuser(), 'HOME': str(self.base),
               'LANG': 'fr' + '_FR.UTF-8', 'LANGUE_TEST': '1', 'SECRET_TEST': SENTINELLE}
        env.update(extra or {})
        return env

    def lancer(self, *args, env=None, timeout=180, entree=None):
        return subprocess.run(['/bin/bash', str(self.script), *args], env=self.environnement(env), text=True,
                              capture_output=True, timeout=timeout, input=entree, cwd=self.travail)

    # -- paramètres d'une installation complète ---------------------------------------------
    def installation(self, *args, env=None, **autres):
        if self.machine == 'admin':
            base = ['--session-secours', 'oui']
        else:
            base = ['--session-secours', 'oui', '--port-essai', str(self.port)]
        return self.lancer(*base, *args, env=env, **autres)
