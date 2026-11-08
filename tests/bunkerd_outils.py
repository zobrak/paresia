# Banc d'essai de bunkerd 2.0.0 ; dépendances : pytest et bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha  2026-11-05  Première version (T005) : nak simulé, setfacl simulé, profils fabriqués.
#   3.0.0-alpha  2026-11-05  Cycle 1 : autre_compte() ne renvoie plus root (uid 0 refusé par bunkerd).
import contextlib
import io
import json
import os
from pathlib import Path
import pwd
import random
import secrets
import shutil
import sys
import tempfile
import textwrap

from server.bunkerd import configuration
from server.bunkerd.admin import demarrer_administration
from server.bunkerd.depot import Depot
from server.bunkerd.operations import Operations
from server.bunkerd.superviseur import Superviseur
from server.commun.client import Connexion
from server.commun.journal import Journal



def faux_ncryptsec():
    """Valeur de test générée à l'exécution (forme valide, aucune clé réelle)."""
    return 'ncryptsec1' + ''.join(random.SystemRandom().choice('02345678acdefghjklmnpqrstuvwxyz')
                                  for _ in range(120))


def compte_courant():
    return pwd.getpwuid(os.getuid()).pw_name


def autre_compte():
    return 'nobody'      # jamais un compte d'uid 0 : bunkerd le refuse (admin_disabled, invalid_account)


def ecrire_executable(chemin, texte):
    Path(chemin).write_text(texte)
    os.chmod(chemin, 0o700)


def nak_simule(chemin, phrase):
    """Faux nak : demande « password », accepte une phrase, annonce une adresse puis attend."""
    ecrire_executable(chemin, textwrap.dedent(f'''\
        #!{sys.executable}
        import sys, time
        sys.stdout.write("enter password: ")
        sys.stdout.flush()
        ligne = sys.stdin.readline().strip()
        if ligne != {phrase!r}:
            sys.stdout.write("[2/3] enter password: ")
            sys.stdout.flush()
            time.sleep(30)
        else:
            sys.stdout.write("bunker://" + "ab" * 32 + "?relay=wss%3A%2F%2Fr.example&secret=abc\\n")
            sys.stdout.write("pubkey: " + "cd" * 32 + "\\n")
            sys.stdout.flush()
            time.sleep(60)
        '''))


def setfacl_simule(chemin, reussite=True):
    """Faux setfacl : consigne ses arguments dans <chemin>.appels."""
    ecrire_executable(chemin, f'#!/bin/sh\necho "$@" >> "{chemin}.appels"\nexit {0 if reussite else 1}\n')


class Banc:
    """Bunkerd sans démon : dossier d'état temporaire, journal en mémoire, nak et setfacl simulés."""

    def __init__(self, racine, **env):
        self.racine = Path(racine)
        self.socks = Path(tempfile.mkdtemp(prefix='bd-'))        # chemins courts (limite des sockets)
        self.home = self.racine / 'home'
        self.home.mkdir()
        self.phrase = secrets.token_hex(8)
        self.nak = self.racine / 'nak'
        nak_simule(self.nak, self.phrase)
        self.setfacl = self.racine / 'setfacl'
        setfacl_simule(self.setfacl)
        self.flux = io.StringIO()
        self.journal = Journal('bunkerd', flux=self.flux)
        valeurs = {
            'GENERAL_RELAY_IDENTITY': '(none)', 'ETAT_HOME': str(self.home),
            'OUTILS_NAK': str(self.nak), 'OUTILS_SETFACL': str(self.setfacl),
            'CONTROLE_SOCKET': str(self.socks / 'ctl.sock'), 'WEB_SOCKET': '(none)',
            'WEB_USER': compte_courant(), 'ADMIN_SOCKET': str(self.socks / 'admin.sock'),
            'ADMIN_ROMULUS_USER': compte_courant(), 'ADMIN_DELAI_S': '5',
        }
        valeurs.update(env)
        environ = {f'PARESIA_BUNKERD_{cle}': valeur for cle, valeur in valeurs.items()}
        self.config = configuration(['--config', 'server/conf/paresia.conf'], environ)
        self.depot = Depot(self.home)
        self.sup = Superviseur(self.depot, self.config['outils']['nak'], self.journal, unlock_wait=10)
        self.ops = Operations(self.sup, self.journal, self.config['general']['relay_identity'])
        self.serveur = None

    def profil(self, identite, clients=None, relais=('wss://relais.example',), timeout=None):
        """Profil nak fabriqué (valeur de test, jamais un fichier de l'utilisateur)."""
        self.ncryptsec = faux_ncryptsec()
        self.depot.write_profile(identite, {'clients': list(clients or []), 'sec': self.ncryptsec,
                                            'relays': list(relais)})
        if timeout is not None:
            etat = self.depot.load_state()
            etat.setdefault(identite, {})['timeout'] = timeout
            self.depot.save_state(etat)
        return self.ncryptsec

    def demarrer_admin(self):
        self.serveur = demarrer_administration(self.config, self.ops, self.journal,
                                               self.config['outils']['setfacl'])
        return self.serveur

    def appeler(self, action, params=None, session=1):
        requete = {'proto': 'jumeaux/1', 'id': secrets.token_hex(8), 'session': session,
                   'action': 'bunker/' + action, 'params': params or {}}
        with Connexion(self.config['admin']['socket'], 5) as connexion:
            return connexion.appeler(requete)

    def lignes_journal(self):
        return [json.loads(ligne) for ligne in self.flux.getvalue().splitlines()]

    def fermer(self):
        self.sup.tout_verrouiller('shutdown')
        if self.serveur is not None:
            self.serveur.arreter()
        shutil.rmtree(self.socks, ignore_errors=True)


@contextlib.contextmanager
def banc(racine, **env):
    b = Banc(racine, **env)
    try:
        yield b
    finally:
        b.fermer()
