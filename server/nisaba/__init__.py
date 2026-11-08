# SPDX-License-Identifier: AGPL-3.0-or-later
# Nisaba : processus annexe du journal légal sur backend-admin (D87, C38) ; socle : configuration,
# planificateur, anneau des échecs, sockets Unix, état. Dépendances : bibliothèque standard et server.commun.
# Suivi des versions
#   0.1.1  2026-11-07  Sections journal et métriques transmises au chargeur (options de configuration()).
#   3.0.0-alpha.40  2026-11-06  Création (T031) : socle, purge, vérification, état, échecs ECHEC_* ; copie
#                      et scellement s'enregistrent par T033 (planificateur interne, N2 ; D87).
#   3.0.0-alpha.41  2026-11-06  T033 (D87, C38, T012) : tâches copie, scellement, horodatage ; acl check|apply ;
#                      sections [nisaba.source], [nisaba.ots], [nisaba.droits] ; tâches enchaînées (apres),
#                      tâches à la demande, options d'exécution (jour) ; verrou unique pour acl apply (N10).
#   3.0.0-alpha.41  2026-11-06  Refus des comptes ACL divergents dès la validation (D111).
import datetime
import json
import os
import re
import sys
import threading
import time

from server.commun.config import ErreurConfiguration, Option, lire
from server.commun.journal import Journal
from server.commun.jumeaux import MAX_LINE, reponse
from server.commun.serveur import Serveur
from server.commun.texte import filtrer
from . import copie as modcopie
from . import etat as releves
from . import purge as modpurge
from .commandes import lancer as lancer_externe
from .droits import Droits
from .horodatage import Horodateur
from .metriques import Metriques
from .scellement import Scelleur, jour_valide
from .verification import executer_externe, verifier

SCHEMA = {
    ('socket', 'socket'): Option('chemin'),
    ('socket', 'uid_romulus'): Option('uid'),
    ('socket', 'gid'): Option('uid'),
    ('socket', 'delai_s'): Option('duree', 30),
    ('socket', 'max_line'): Option('limite', 65536),
    ('ctl', 'socket'): Option('chemin'),
    ('ctl', 'uid'): Option('uid'),
    ('journal', 'dossier'): Option('chemin'),
    ('journal', 'compte_acl'): Option('compte'),
    ('journal', 'lsattr'): Option('chemin'),
    ('journal', 'chattr'): Option('chemin'),
    ('horaire', 'copie_s'): Option('duree', 60),
    ('horaire', 'scellement'): Option('texte'),
    ('horaire', 'purge'): Option('texte'),
    ('horaire', 'conservation_jours'): Option('limite', 365),
    ('horaire', 'arret_s'): Option('duree', 30),
    ('etat', 'dossier'): Option('chemin'),
    ('etat', 'historique'): Option('limite', 20),
    ('source', 'source'): Option('texte'),
    ('source', 'cle_ssh'): Option('chemin'),
    ('source', 'rsync'): Option('chemin'),
    ('source', 'ssh'): Option('chemin'),
    ('source', 'connexion_s'): Option('duree', 20),
    ('source', 'rsync_s'): Option('duree', 50),
    ('ots', 'ots'): Option('chemin'),
    ('ots', 'attente_max_jours'): Option('limite', 3),
    ('ots', 'delai_s'): Option('duree', 120),
    ('droits', 'chattr'): Option('chemin'),
    ('droits', 'setfacl'): Option('chemin'),
    ('droits', 'getfacl'): Option('chemin'),
    ('droits', 'compte'): Option('compte'),
}
SCHEMA_NISABA = SCHEMA

TACHES = ('copie', 'scellement', 'horodatage', 'purge')
CODES_TACHE = {'copie': 'ECHEC_COPIE', 'scellement': 'ECHEC_SCELLEMENT',
               'horodatage': 'ECHEC_HORODATAGE', 'purge': 'ECHEC_PURGE'}
CODES_ECHEC = frozenset(CODES_TACHE.values()) | {'ECHEC_ACL'}
ACTIONS_ROMULUS = frozenset({'nisaba/state/status', 'nisaba/state/verify'})
ACTIONS_CTL = ACTIONS_ROMULUS | {'nisaba/job/run', 'nisaba/acl/check', 'nisaba/acl/apply'}
TEXTE_MAX = 200
LIGNES_MAX = 200        # lignes d'un compte rendu acl check|apply renvoyées par la socket
MAX_CONSERVATION_JOURS = 36500
_HORAIRE = re.compile(r'([01][0-9]|2[0-3]):([0-5][0-9])')
_HEURE = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z')
_SOURCE = re.compile(r'[A-Za-z_][A-Za-z0-9_.-]*@(?:[A-Za-z0-9][A-Za-z0-9.-]*|\[[0-9A-Fa-f:.]+\]):/(?:[A-Za-z0-9._-]+/)*')
_SANS_ESPACE = re.compile(r'[A-Za-z0-9_./+@%:=,-]+')     # composé dans l'argument -e de rsync (rsync(1))


def configuration(*, argv=None, environ=None, **options):
    """Lit la configuration en couches puis valide les horaires HH:MM (UTC), la conservation, ctl.uid (0) et les sockets."""
    resultat = lire('nisaba', SCHEMA, argv=argv, environ=environ, **{'journal': True, 'metriques': True, **options})
    if resultat['ctl']['uid'] != 0:         # nisaba-ctl.sock : uid 0 seul (N5)
        raise ErreurConfiguration('config_invalid', 'ctl', 'uid')
    valider_configuration(resultat)
    return resultat


def valider_configuration(config):
    if 'droits' in config and config['droits']['compte'] != config['journal']['compte_acl']:
        raise ErreurConfiguration('config_invalid', 'droits', 'compte')
    for cle in ('scellement', 'purge'):
        if not isinstance(config['horaire'][cle], str) or not _HORAIRE.fullmatch(config['horaire'][cle]):
            raise ErreurConfiguration('config_invalid', 'horaire', cle)
    if not 1 <= config['horaire']['conservation_jours'] <= MAX_CONSERVATION_JOURS:
        raise ErreurConfiguration('config_invalid', 'horaire', 'conservation_jours')
    if os.fspath(config['socket']['socket']) == os.fspath(config['ctl']['socket']):
        raise ErreurConfiguration('config_invalid', 'ctl', 'socket')
    if 'source' in config:
        source = config['source']
        if not _SOURCE.fullmatch(source['source']):
            raise ErreurConfiguration('config_invalid', 'source', 'source')
        for cle in ('cle_ssh', 'ssh'):
            if not _SANS_ESPACE.fullmatch(os.fspath(source[cle])):
                raise ErreurConfiguration('config_invalid', 'source', cle)
        if not 1 <= config['ots']['attente_max_jours'] <= MAX_CONSERVATION_JOURS:
            raise ErreurConfiguration('config_invalid', 'ots', 'attente_max_jours')


def iso(instant):
    return datetime.datetime.fromtimestamp(instant, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class Occupe(Exception):
    """Une tâche est déjà en cours (command_busy)."""


class Anneau:
    """Derniers échecs par tâche, en mémoire et dans etat.dossier (StateDirectory=, C33)."""
    NOM = 'echecs.json'
    TAILLE_MAX = 64 * 1024
    PLAFOND = 40         # 4 tâches x 40 entrées tiennent sous TAILLE_MAX ; l'écriture ajuste de toute façon

    def __init__(self, dossier, historique, *, journal, horloge=time.time):
        self.dossier = os.fspath(dossier)
        self.maximum = min(historique, self.PLAFOND)
        self.journal = journal
        self.horloge = horloge
        self._verrou = threading.Lock()
        self._entrees = {tache: [] for tache in TACHES}

    def charger(self):
        chemin = os.path.join(self.dossier, self.NOM)
        try:
            descripteur = os.open(chemin, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
            with os.fdopen(descripteur, 'rb') as fichier:
                contenu = fichier.read(self.TAILLE_MAX + 1)
            if len(contenu) > self.TAILLE_MAX:
                raise ValueError('too_large')
            donnees = json.loads(contenu.decode('utf-8'))
            taches = donnees['taches']
            if donnees['version'] != 1 or not isinstance(taches, dict):
                raise ValueError('format')
        except FileNotFoundError:
            self.journal.ecrire('warning', 'failure_ring_empty', reason='absent')
            return
        except (OSError, ValueError, KeyError, TypeError, RecursionError):
            self.journal.ecrire('warning', 'failure_ring_empty', reason='corrupt')
            return
        with self._verrou:
            for tache in TACHES:
                liste = taches.get(tache, [])
                if not isinstance(liste, list):
                    continue
                valides = []
                for entree in liste:
                    if (isinstance(entree, dict) and set(entree) == {'code', 'texte', 'heure'}
                            and entree['code'] in CODES_ECHEC and isinstance(entree['texte'], str)
                            and isinstance(entree['heure'], str) and _HEURE.fullmatch(entree['heure'])):
                        valides.append({'code': entree['code'],
                                        'texte': filtrer(entree['texte'])[:TEXTE_MAX],
                                        'heure': entree['heure']})
                self._entrees[tache] = valides[-self.maximum:]

    def ajouter(self, tache, code, texte):
        if tache not in TACHES or code not in CODES_ECHEC:
            raise ValueError('invalid_failure')
        entree = {'code': code, 'texte': filtrer(str(texte))[:TEXTE_MAX], 'heure': iso(self.horloge())}
        with self._verrou:
            liste = self._entrees[tache]
            liste.append(entree)
            del liste[:-self.maximum]
            try:
                self._ecrire()
            except OSError:
                self.journal.ecrire('warning', 'failure_ring_write_failed')

    def entrees(self, tache):
        with self._verrou:
            return [dict(entree) for entree in self._entrees[tache]]

    def _ecrire(self):
        """Fichier temporaire 0600 puis rename, sous le verrou ; excès écarté (plus anciennes d'abord)."""
        while True:
            contenu = json.dumps({'version': 1, 'taches': self._entrees}, ensure_ascii=True,
                                 separators=(',', ':')).encode()
            if len(contenu) <= self.TAILLE_MAX:
                break
            total = sum(len(liste) for liste in self._entrees.values())
            for _ in range(max(1, total * (len(contenu) - self.TAILLE_MAX) // len(contenu) + 1)):
                plus_longue = max(TACHES, key=lambda t: len(self._entrees[t]))
                if self._entrees[plus_longue]:
                    del self._entrees[plus_longue][0]
        chemin = os.path.join(self.dossier, self.NOM)
        temporaire = chemin + '.tmp'
        try:
            os.unlink(temporaire)
        except FileNotFoundError:
            pass
        descripteur = os.open(temporaire, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            with os.fdopen(descripteur, 'wb') as fichier:
                fichier.write(contenu)
            os.rename(temporaire, chemin)
        except BaseException:
            try:
                os.unlink(temporaire)
            except OSError:
                pass
            raise


class _Tache:
    def __init__(self, nom, fonction, code, periode, quotidien, rattrapage, apres=None):
        self.nom, self.fonction, self.code = nom, fonction, code
        self.periode, self.quotidien, self.rattrapage = periode, quotidien, rattrapage
        self.apres = apres
        self.derniere = None
        self.resultat = None
        self.prochaine = None


class Planificateur:
    """Un fil, échéances UTC par horloge injectable, jamais deux tâches en même temps (N2)."""

    def __init__(self, *, horloge=time.time, journal=None, echec, metriques=None, arret_s=30):
        self.horloge = horloge
        self.journal = journal if journal is not None else Journal('nisaba')
        self.echec = echec
        self.metriques = metriques
        self.arret_s = arret_s
        self._taches = {}
        self._verrou = threading.Lock()
        self._occupe = threading.Lock()
        self._arret = threading.Event()
        self._fil = None

    def enregistrer(self, nom, fonction, *, periode=None, quotidien=None, rattrapage=False, apres=None):
        """Enregistre une tâche connue (copie, scellement, horodatage, purge) ; un nom inconnu est refusé.

        Une tâche a une période, un horaire quotidien, ou bien `apres` : elle suit alors la tâche
        nommée (déjà enregistrée), sous le même verrou, après chacune de ses exécutions ; elle reste
        lançable seule à la demande. Son horaire est alors inconnu (prochaine = None).
        """
        if nom not in TACHES:
            raise ValueError('unknown_task')
        if apres is not None:
            if nom in self._taches or periode is not None or quotidien is not None or apres not in self._taches:
                raise ValueError('invalid_task')
        elif nom in self._taches or (periode is None) == (quotidien is None):
            raise ValueError('invalid_task')
        if quotidien is not None and not _HORAIRE.fullmatch(quotidien):
            raise ValueError('invalid_schedule')
        tache = _Tache(nom, fonction, CODES_TACHE[nom], periode, quotidien, rattrapage, apres)
        tache.prochaine = self._initiale(tache)
        with self._verrou:
            self._taches[nom] = tache

    def noms(self):
        with self._verrou:
            return sorted(self._taches)

    def _suivante(self, tache, maintenant):
        if tache.apres is not None:
            return None
        if tache.periode is not None:
            return maintenant + tache.periode
        heure, minute = (int(x) for x in tache.quotidien.split(':'))
        base = datetime.datetime.fromtimestamp(maintenant, datetime.timezone.utc)
        prochaine = base.replace(hour=heure, minute=minute, second=0, microsecond=0)
        if prochaine <= base:
            prochaine += datetime.timedelta(days=1)
        return prochaine.timestamp()

    def _initiale(self, tache):
        maintenant = self.horloge()
        return maintenant if tache.rattrapage and tache.apres is None else self._suivante(tache, maintenant)

    def etat(self):
        with self._verrou:
            return {nom: {'derniere': t.derniere, 'resultat': t.resultat, 'prochaine': t.prochaine}
                    for nom, t in sorted(self._taches.items())}

    def _lancer(self, tache, options):
        debut = self.horloge()
        try:
            echecs = int(tache.fonction(**options) or 0)
        except Exception:
            self.echec(tache.nom, tache.code, 'task_exception')
            echecs = 1
        fin = self.horloge()
        with self._verrou:
            tache.derniere = debut
            tache.resultat = 'ok' if echecs == 0 else 'echec'
            tache.prochaine = self._suivante(tache, fin)
        if echecs == 0 and self.metriques is not None:
            self.metriques.succes(tache.nom, fin)
        return {'tache': tache.nom, 'resultat': 'ok' if echecs == 0 else 'echec', 'echecs': echecs}

    def executer(self, nom, **options):
        """Exécute la tâche maintenant (puis celles qui la suivent) ; Occupe si une tâche est en cours.

        Le résultat renvoyé est celui de la tâche demandée ; options est transmis à sa fonction.
        """
        with self._verrou:
            tache = self._taches.get(nom)
        if tache is None:
            raise ValueError('unknown_task')
        if not self._occupe.acquire(blocking=False):
            raise Occupe()
        try:
            resultat = self._lancer(tache, options)
            with self._verrou:
                suites = [t for _, t in sorted(self._taches.items()) if t.apres == nom]
            for suite in suites:
                self._lancer(suite, {})
            return resultat
        finally:
            self._occupe.release()

    def exclusif(self, fonction):
        """Exécute fonction() sous le verrou des tâches (N10) ; Occupe si une tâche est en cours."""
        if not self._occupe.acquire(blocking=False):
            raise Occupe()
        try:
            return fonction()
        finally:
            self._occupe.release()

    def arret_demande(self):
        return self._arret.is_set()

    def pas(self):
        """Exécute les tâches échues (ordre du nom) ; faux si une tâche en cours a empêché un départ."""
        maintenant = self.horloge()
        with self._verrou:
            echues = [nom for nom, t in sorted(self._taches.items())
                      if t.prochaine is not None and t.prochaine <= maintenant]
        for nom in echues:
            if self._arret.is_set():
                break
            try:
                self.executer(nom)
            except Occupe:
                return False
        return True

    def _boucle(self):
        while not self._arret.is_set():
            try:
                self.pas()
            except Exception:
                self.journal.ecrire('error', 'scheduler_failed')
            self._arret.wait(1.0)

    def demarrer(self):
        with self._verrou:
            for tache in self._taches.values():
                tache.prochaine = self._initiale(tache)
        self._arret.clear()
        self._fil = threading.Thread(target=self._boucle, daemon=True)
        self._fil.start()

    def arreter(self):
        """Attend la tâche en cours (planifiée ou manuelle) au plus arret_s ; ne l'interrompt jamais."""
        self._arret.set()
        limite = time.monotonic() + self.arret_s
        if self._fil is not None:
            self._fil.join(timeout=self.arret_s)
            self._fil = None
        if self._occupe.acquire(timeout=max(0.0, limite - time.monotonic())):
            self._occupe.release()
        else:
            self.journal.ecrire('warning', 'shutdown_task_timeout')


class Nisaba:
    """Socle de Nisaba ; les tâches de copie et de scellement s'enregistrent par planificateur (T033)."""

    def __init__(self, config, *, horloge=time.time, journal=None, sortie=None, executer=executer_externe,
                 lancer=lancer_externe, uid_attendu=None):
        valider_configuration(config)
        self.config = config
        self.horloge = horloge
        self.executer = executer
        self.lancer = lancer
        self.droits = None
        self.journal = journal if journal is not None else Journal('nisaba')
        self.sortie = sortie if sortie is not None else sys.stdout
        self._sortie_verrou = threading.Lock()
        self._verrou_releve = threading.Lock()      # un seul relevé d'état à la fois
        self._verrou_verification = threading.Lock()  # une seule vérification à la fois (command_busy)
        self.demarrage = horloge()
        self.metriques = Metriques()
        etat = config['etat']
        self.anneau = Anneau(etat['dossier'], etat['historique'], journal=self.journal, horloge=horloge)
        self.anneau.charger()
        self.planificateur = Planificateur(horloge=horloge, journal=self.journal, echec=self.echec,
                                           metriques=self.metriques, arret_s=config['horaire']['arret_s'])
        self.planificateur.enregistrer('purge', self._purger, quotidien=config['horaire']['purge'])
        self.gestionnaires_ctl = {}     # action -> rappel(requete) : acl/check et acl/apply (T033)
        if 'source' in config:           # copie, scellement, horodatage et droits (T033) : sections obligatoires
            self._installer_journal_legal(uid_attendu)
        self._demarre = False
        sock, ctl = config['socket'], config['ctl']
        self.serveurs = [
            Serveur(sock['socket'], {sock['uid_romulus']}, ACTIONS_ROMULUS, self._traiter_romulus,
                    gid=sock['gid'], max_line=sock['max_line'], delai=sock['delai_s'], journal=self.journal),
            Serveur(ctl['socket'], {ctl['uid']}, ACTIONS_CTL, self._traiter_ctl, gid=os.getegid(),
                    max_line=sock['max_line'], delai=sock['delai_s'], journal=self.journal, mode=0o600),
        ]

    # -- échecs (N6) ----------------------------------------------------------------
    def echec(self, tache, code, texte):
        """ECHEC_* sur la sortie standard (journald), code en tête ; mémorisé dans l'anneau."""
        if code not in CODES_ECHEC or tache not in TACHES:
            raise ValueError('invalid_failure')
        texte = filtrer(str(texte))[:TEXTE_MAX]
        priorite = '<4>' if code == 'ECHEC_HORODATAGE' else '<3>'      # sd-daemon(3) : SD_WARNING, SD_ERR
        with self._sortie_verrou:
            print(f'{priorite}{code} {texte}', file=self.sortie, flush=True)
        self.metriques.echec(tache, code)
        self.anneau.ajouter(tache, code, texte)

    def echec_acl_manuel(self, texte):
        """ECHEC_ACL d'un acl apply (hors tâche : rien dans l'anneau) ; sortie standard et métriques."""
        texte = filtrer(str(texte))[:TEXTE_MAX]
        with self._sortie_verrou:
            print(f'<3>ECHEC_ACL {texte}', file=self.sortie, flush=True)
        self.metriques.echec('acl', 'ECHEC_ACL')

    # -- tâches ---------------------------------------------------------------------
    def _installer_journal_legal(self, uid_attendu):
        config = self.config
        source, ots, droits = config['source'], config['ots'], config['droits']
        dossier = config['journal']['dossier']
        self.droits = Droits(dossier=dossier, compte=droits['compte'], setfacl=droits['setfacl'],
                             getfacl=droits['getfacl'], chattr=droits['chattr'],
                             lsattr=config['journal']['lsattr'], lancer=self.lancer, uid_attendu=uid_attendu)

        def trace(evenement, **champs):
            self.journal.ecrire('info', evenement, **champs)

        def echec(tache, code):
            return lambda texte: self.echec(tache, code, texte)

        self.scelleur = Scelleur(source, dossier, self.droits, self.lancer, horloge=self.horloge, trace=trace,
                                 echec_scellement=echec('scellement', 'ECHEC_SCELLEMENT'),
                                 echec_acl=echec('scellement', 'ECHEC_ACL'))
        self.horodateur = Horodateur(ots, dossier, self.droits, self.lancer, horloge=self.horloge, trace=trace,
                                     echec_horodatage=echec('horodatage', 'ECHEC_HORODATAGE'),
                                     echec_acl=echec('horodatage', 'ECHEC_ACL'))
        horaire = config['horaire']
        self.planificateur.enregistrer('copie', self._copier, periode=horaire['copie_s'])
        self.planificateur.enregistrer('scellement', self.scelleur.sceller, quotidien=horaire['scellement'],
                                       rattrapage=True)
        self.planificateur.enregistrer('horodatage', self.horodateur.horodater, apres='scellement')
        self.gestionnaires_ctl['nisaba/acl/check'] = self._acl_check
        self.gestionnaires_ctl['nisaba/acl/apply'] = self._acl_apply

    def _copier(self):
        config = self.config
        return modcopie.copier(config['source'], config['journal']['dossier'], self.droits, self.lancer,
                               lambda texte: self.echec('copie', 'ECHEC_COPIE', texte),
                               lambda texte: self.echec('copie', 'ECHEC_ACL', texte))

    def _lsattr(self):
        return self.config['journal']['lsattr']

    def _purger(self):
        horaire, journal = self.config['horaire'], self.config['journal']
        aujourdhui = datetime.datetime.fromtimestamp(self.horloge(), datetime.timezone.utc).date()
        echecs = []

        def echec(texte):
            echecs.append(texte)
            self.echec('purge', 'ECHEC_PURGE', texte)

        modpurge.purger(journal['dossier'], horaire['conservation_jours'], journal['chattr'], aujourdhui,
                        supprime=lambda nom: self.journal.ecrire('info', 'journal_purged', fichier=nom),
                        echec=echec, executer=self.executer)
        return len(echecs)

    # -- état et vérification -------------------------------------------------------
    def releve(self):
        with self._verrou_releve:
            return releves.collecter(self.config['journal']['dossier'], self._lsattr(), self.horloge(),
                                     self.executer)

    def etat(self):
        releve = self.releve()
        taches = {}
        for nom, valeurs in self.planificateur.etat().items():
            taches[nom] = {
                'derniere': None if valeurs['derniere'] is None else iso(valeurs['derniere']),
                'resultat': valeurs['resultat'],
                'prochaine': None if valeurs['prochaine'] is None else iso(valeurs['prochaine']),
                'echecs': self.anneau.entrees(nom)}
        return {'demarrage': iso(self.demarrage), 'taches': taches, 'journal': releve,
                'metriques': self.metriques.instantane(releve)}

    def verification(self):
        """Vérification du registre ; Occupe si une autre est déjà en cours."""
        if not self._verrou_verification.acquire(blocking=False):
            raise Occupe()
        try:
            resultat = verifier(self.config['journal']['dossier'], self._lsattr(), executer=self.executer)
        finally:
            self._verrou_verification.release()
        return {'code': 0 if resultat['ok'] else 1, 'lignes': resultat['lignes']}

    # -- droits : acl check|apply ---------------------------------------------------
    @staticmethod
    def _borner_lignes(resultat):
        lignes = resultat['lignes']
        if len(lignes) > LIGNES_MAX:
            lignes = lignes[:LIGNES_MAX - 2] + [f'… {len(lignes) - LIGNES_MAX + 1} ligne(s) omise(s)'] + lignes[-1:]
        return {'code': resultat['code'], 'lignes': lignes}

    def _acl_check(self, q):
        if q['params']:
            return reponse(q['id'], code='bad_request')
        return reponse(q['id'], self._borner_lignes(self.droits.controler()))

    def _acl_apply(self, q):
        if q['params']:
            return reponse(q['id'], code='bad_request')

        def appliquer():
            return self.droits.appliquer(
                lambda texte: self.journal.ecrire('info', 'acl_apply', texte=texte), self.echec_acl_manuel,
                self.planificateur.arret_demande)

        try:
            resultat = self.planificateur.exclusif(appliquer)
        except Occupe:
            return reponse(q['id'], code='command_busy')
        return reponse(q['id'], self._borner_lignes(resultat))

    # -- sockets (N4, N5) -----------------------------------------------------------
    def _traiter_romulus(self, q, _):
        return self._traiter(q, False)

    def _traiter_ctl(self, q, _):
        return self._traiter(q, True)

    def _traiter(self, q, ctl):
        action, params, identifiant = q['action'], q['params'], q['id']
        if action in ('nisaba/state/status', 'nisaba/state/verify'):
            if params:
                return reponse(identifiant, code='bad_request')
            try:
                return reponse(identifiant, self.etat() if action.endswith('status') else self.verification())
            except Occupe:
                return reponse(identifiant, code='command_busy')
        if not ctl:
            return reponse(identifiant, code='unknown_action')
        if action == 'nisaba/job/run':
            nom = params.get('task') if set(params) in ({'task'}, {'task', 'day'}) else None
            if not isinstance(nom, str) or nom not in TACHES:
                return reponse(identifiant, code='bad_request')
            options = {}
            if 'day' in params:          # run scellement AAAA-MM-JJ : journée valide et terminée (UTC)
                aujourdhui = datetime.datetime.fromtimestamp(self.horloge(), datetime.timezone.utc).date()
                if nom != 'scellement' or jour_valide(params['day'], aujourdhui) is None:
                    return reponse(identifiant, code='bad_request')
                options['jour'] = params['day']
            if nom not in self.planificateur.noms():
                return reponse(identifiant, code='not_available')
            try:
                return reponse(identifiant, self.planificateur.executer(nom, **options))
            except Occupe:
                return reponse(identifiant, code='command_busy')
        gestionnaire = self.gestionnaires_ctl.get(action)
        if gestionnaire is None:
            return reponse(identifiant, code='not_available')
        return gestionnaire(q)

    # -- cycle de vie ---------------------------------------------------------------
    def demarrer(self):
        try:
            for serveur in self.serveurs:
                ancien = os.umask(0o177)
                try:
                    serveur.demarrer()
                finally:
                    os.umask(ancien)
            self.planificateur.demarrer()
            self._demarre = True
        except BaseException:
            self.arreter()
            raise
        self.journal.ecrire('info', 'startup')
        return self

    def arreter(self):
        self.planificateur.arreter()
        for serveur in self.serveurs:
            serveur.arreter()
        if self._demarre:
            self._demarre = False
            self.journal.ecrire('info', 'shutdown')

    def __enter__(self):
        return self.demarrer()

    def __exit__(self, *_):
        self.arreter()
