# SPDX-License-Identifier: AGPL-3.0-or-later
# Journal d'activité de Romulus : qui fait quoi, borné et circulaire ; dépendances : bibliothèque standard, server.commun.
# Suivi des versions
#   0.1.15  2026-11-08  Première version : trois niveaux, regroupement des refus sans session, rotation, lecture bornée.
"""Journal d'activité de Romulus (JSON par ligne), distinct du journal d'exploitation.

Une entrée est une ligne JSON ASCII d'au plus 2048 octets, écrite par un seul appel d'écriture
en mode ajout. Le volume total est borné par `taille_max` : le fichier courant est renommé en
`activite.jsonl.1` quand il atteindrait la moitié de `taille_max`, les plus anciennes entrées
disparaissant d'abord. Seuls des champs validés sont écrits : ni `params`, ni `data`, ni jeton,
ni texte reçu (un chemin ou une action inconnus ne sont jamais recopiés). À la lecture, toute
ligne tronquée, trop longue ou aux champs hors forme est ignorée.
"""
import datetime
import ipaddress
import json
import os
import re
import stat
import threading
import time

from server.commun.plugins import (ErreurPlugin, ouvrir_dossier_confiance,
                                   ouvrir_fichier_controle)
from server.commun.texte import filtrer

NOM_FICHIER = 'activite.jsonl'
NOM_ANCIEN = 'activite.jsonl.1'
LIGNE_MAX = 2048
LECTURE_MAX = 1024 * 1024
TAILLE_MAX_DEFAUT = 1048576
NIVEAUX = (1, 2, 3)
ACTION_LISTE = 'kernel/activity/list'
ARGS_TEXTE_MAX = 128
ARGS_MAX = 8
DELAI_SIGNAL_S = 60

EVENEMENTS = ('action', 'refusal', 'session_open', 'session_close', 'protocol')
_TS = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z\Z')
_ADMIN = re.compile(r'[A-Za-z0-9._@-]{1,64}\Z')
_DOMAINE = re.compile(r'[a-z][a-z0-9_]{0,31}\Z')
_ACTION = re.compile(r'[a-z][a-z0-9_-]{0,31}(/[a-z][a-z0-9_-]{0,63}){2,3}\Z')
_CODE = re.compile(r'[a-z][a-z0-9_]{0,47}\Z')
_JUMEAU = re.compile(r'[a-z][a-z0-9_-]{0,31}\Z')
_IDENTIFIANT = re.compile(r'[0-9a-f]{16}\Z')
_CLE_ARG = re.compile(r'[a-z][a-z0-9_]{0,31}\Z')


class ActiviteInutilisable(Exception):
    """Dossier ou fichier non conforme ; `code` est stable."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _entier(valeur, minimum=0, maximum=2**53):
    return type(valeur) is int and minimum <= valeur <= maximum


def _texte(motif):
    return lambda v: isinstance(v, str) and motif.match(v) is not None


def _adresse(valeur):
    if not isinstance(valeur, str) or len(valeur) > 64 or '%' in valeur:
        return False
    try:
        return str(ipaddress.ip_address(valeur)) == valeur
    except ValueError:
        return False


def _args(valeur):
    if not isinstance(valeur, dict) or len(valeur) > ARGS_MAX:
        return False
    for cle, contenu in valeur.items():
        if not isinstance(cle, str) or not _CLE_ARG.match(cle):
            return False
        if isinstance(contenu, str):
            if len(contenu) > ARGS_TEXTE_MAX or filtrer(contenu) != contenu:
                return False
        elif type(contenu) is not int and type(contenu) is not bool:
            return False
        elif type(contenu) is int and not _entier(contenu, -2**53):
            return False
    return True


def _ou_nul(controle):
    return lambda v: v is None or controle(v)


CHAMPS = {
    'ts': _texte(_TS),
    'level': lambda v: _entier(v, 1, 3),
    'event': lambda v: v in EVENEMENTS,
    'admin': _ou_nul(_texte(_ADMIN)),
    'session': lambda v: _entier(v),
    'source': _ou_nul(_adresse),
    'domain': _ou_nul(_texte(_DOMAINE)),
    'action': _ou_nul(_texte(_ACTION)),
    'result': _texte(_CODE),
    'duration_ms': lambda v: _entier(v),
    'twin': _ou_nul(_texte(_JUMEAU)),
    'count': lambda v: _entier(v, 1, 10**6),
    'args': _args,
    'request_id': _texte(_IDENTIFIANT),
    'step': lambda v: v in ('sent', 'received'),
    'ok': lambda v: type(v) is bool,
    'code': _texte(_CODE),
    'bytes': lambda v: _entier(v),
    'http_status': lambda v: _entier(v, 100, 599),
    'peer_uid': lambda v: _entier(v, 0, 2**32 - 2),
}
OBLIGATOIRES = frozenset({'ts', 'level', 'event'})


def valider(entree):
    """L'entrée si tous ses champs sont connus et de la bonne forme, sinon None."""
    if not isinstance(entree, dict) or not OBLIGATOIRES <= entree.keys():
        return None
    for cle, valeur in entree.items():
        controle = CHAMPS.get(cle)
        if controle is None or not controle(valeur):
            return None
    return entree


def serialiser(entree):
    """Ligne (octets, LF compris) d'au plus LIGNE_MAX octets ; les champs optionnels sont
    retirés plutôt que la ligne refusée. None si l'entrée est invalide."""
    if valider(entree) is None:
        return None
    entree = dict(entree)
    for retire in ('args', 'twin', 'source', None):
        ligne = (json.dumps(entree, ensure_ascii=True, allow_nan=False,
                            separators=(',', ':')) + '\n').encode('ascii')
        if len(ligne) <= LIGNE_MAX:
            return ligne
        if retire is None:
            return None
        entree.pop(retire, None)
    return None


def valeur_args(valeur):
    """Valeur typée et bornée d'un paramètre marqué non secret ; None si le type n'est pas admis."""
    if type(valeur) is bool or type(valeur) is int:
        return valeur if type(valeur) is bool or _entier(valeur, -2**53) else None
    if isinstance(valeur, str):
        return filtrer(valeur)[:ARGS_TEXTE_MAX]
    return None


def dossier_activite(options, environ):
    """Dossier du journal d'activité : option `dossier`, sinon `activite` sous STATE_DIRECTORY."""
    dossier = options.get('dossier')
    if dossier is None:
        base = environ.get('STATE_DIRECTORY', '').split(':')[0]
        dossier = os.path.join(base, 'activite') if base else None
    if not dossier or not os.path.isabs(dossier) or '\0' in dossier:
        return None
    return dossier


class Activite:
    """Écriture, regroupement et lecture du journal d'activité.

    options : detail (1 à 3), taille_max, regroupement_max, regroupements_simultanes.
    confiance : proprietaires (uid admis, par défaut root et l'uid effectif), racine_confiance
    (par défaut « / »), horloge (secondes depuis l'époque) et monotone, injectables en test.
    """

    def __init__(self, dossier, options, journal, *, proprietaires=None, racine_confiance='/',
                 horloge=time.time, monotone=time.monotonic):
        self.dossier = dossier
        self.detail = options.get('detail', 1)
        self.taille_max = options.get('taille_max', TAILLE_MAX_DEFAUT)
        self.regroupement_max = options.get('regroupement_max', 100000)
        self.regroupements_simultanes = options.get('regroupements_simultanes', 64)
        if self.detail not in NIVEAUX or not 65536 <= self.taille_max <= 16 * 1024 * 1024:
            raise ValueError('invalid_activity_options')
        self.journal = journal
        self.proprietaires = frozenset(
            {0, os.geteuid()} if proprietaires is None else proprietaires)
        self.racine_confiance = racine_confiance
        self.horloge, self.monotone = horloge, monotone
        # Renseignés par Romulus : jumeau de chaque action, paramètres marqués non secrets.
        self.jumeaux = {}
        self.marques = {}
        self.compteur_echecs = None
        self._verrou = threading.RLock()
        self._dossier_fd = None
        self._fichier_fd = None
        self._taille = 0
        self._groupes = {}
        self._signaux = {}
        self._essai = 0.0

    # -- horodatage -------------------------------------------------------------------

    def _ts(self, instant=None):
        instant = self.horloge() if instant is None else instant
        texte = datetime.datetime.fromtimestamp(instant, datetime.timezone.utc).isoformat(
            timespec='milliseconds')
        return texte.replace('+00:00', 'Z')

    # -- signalement au journal habituel (au plus une fois par minute et par événement) ----

    def _signaler(self, evenement, code):
        maintenant = self.monotone()
        dernier = self._signaux.get(evenement)
        if dernier is not None and maintenant - dernier < DELAI_SIGNAL_S:
            return
        self._signaux[evenement] = maintenant
        try:
            self.journal.ecrire('error', evenement, code=code)
        except Exception:
            pass

    # -- dossier et fichier -----------------------------------------------------------------

    def _ouvrir_dossier(self, creer):
        """Descripteur du dossier contrôlé, ou None s'il est absent (et non créé)."""
        try:
            fd = ouvrir_dossier_confiance(self.dossier, self.racine_confiance, self.proprietaires)
            if fd is None and creer:
                parent = ouvrir_dossier_confiance(os.path.dirname(self.dossier),
                                                  self.racine_confiance, self.proprietaires)
                if parent is None:
                    raise ActiviteInutilisable('activity_dir_missing')
                try:
                    try:
                        os.mkdir(os.path.basename(self.dossier), 0o700, dir_fd=parent)
                    except FileExistsError:
                        pass
                finally:
                    os.close(parent)
                fd = ouvrir_dossier_confiance(self.dossier, self.racine_confiance,
                                              self.proprietaires)
        except ErreurPlugin:
            raise ActiviteInutilisable('activity_unsafe') from None
        except OSError:
            raise ActiviteInutilisable('activity_io_error') from None
        if fd is None and creer:
            raise ActiviteInutilisable('activity_dir_missing')
        return fd

    def _controler_fichier(self, fd):
        attributs = os.fstat(fd)
        if (not stat.S_ISREG(attributs.st_mode) or attributs.st_uid not in self.proprietaires
                or attributs.st_mode & 0o077):
            raise ActiviteInutilisable('activity_unsafe')
        return attributs

    def _ouvrir_ecriture(self):
        if self._dossier_fd is None:
            self._dossier_fd = self._ouvrir_dossier(True)
        try:
            fd = os.open(NOM_FICHIER, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW
                         | os.O_CLOEXEC, 0o600, dir_fd=self._dossier_fd)
        except OSError:
            raise ActiviteInutilisable('activity_unsafe') from None
        try:
            attributs = self._controler_fichier(fd)
        except BaseException:
            os.close(fd)
            raise
        self._fichier_fd, self._taille = fd, attributs.st_size

    def _fermer_fichiers(self):
        for nom in ('_fichier_fd', '_dossier_fd'):
            descripteur = getattr(self, nom)
            setattr(self, nom, None)
            if descripteur is not None:
                try:
                    os.close(descripteur)
                except OSError:
                    pass

    def preparer(self):
        """Crée le dossier et le fichier ; signale un état inutilisable sans lever d'exception."""
        with self._verrou:
            try:
                if self._fichier_fd is None:
                    self._ouvrir_ecriture()
                return True
            except ActiviteInutilisable as erreur:
                self._fermer_fichiers()
                self._signaler('activity_unusable', erreur.code)
            except OSError:
                self._fermer_fichiers()
                self._signaler('activity_write_failed', 'activity_io_error')
            return False

    def _tourner(self):
        os.close(self._fichier_fd)
        self._fichier_fd = None
        os.rename(NOM_FICHIER, NOM_ANCIEN, src_dir_fd=self._dossier_fd,
                  dst_dir_fd=self._dossier_fd)
        self._ouvrir_ecriture()

    def _ecrire_ligne(self, ligne):
        """Un seul appel d'écriture ; un échec n'atteint jamais l'action d'administration."""
        with self._verrou:
            try:
                if self._fichier_fd is None:
                    if self.monotone() < self._essai:
                        return
                    self._ouvrir_ecriture()
                if self._taille and self._taille + len(ligne) > self.taille_max // 2:
                    self._tourner()
                if os.write(self._fichier_fd, ligne) != len(ligne):
                    raise OSError('activity_short_write')
                self._taille += len(ligne)
            except ActiviteInutilisable as erreur:
                self._fermer_fichiers()
                self._essai = self.monotone() + 5
                self._signaler('activity_unusable', erreur.code)
            except OSError:
                self._fermer_fichiers()
                self._essai = self.monotone() + 5
                self._signaler('activity_write_failed', 'activity_io_error')
                if self.compteur_echecs is not None:
                    try:
                        self.compteur_echecs.incrementer()
                    except Exception:
                        pass

    def fermer(self):
        with self._verrou:
            self._vider_groupes(force=True)
            self._fermer_fichiers()

    # -- enregistrement -----------------------------------------------------------------------

    def _ecrire(self, entree):
        ligne = serialiser(entree)
        if ligne is not None:
            self._ecrire_ligne(ligne)

    def _entree(self, niveau, evenement, **champs):
        entree = {'ts': self._ts(), 'level': niveau, 'event': evenement}
        entree.update({cle: valeur for cle, valeur in champs.items() if valeur is not Ellipsis})
        return entree

    def requete(self, evenement, action, resultat, *, session=None, admin=None, source=None,
                duree_ms=None, args=None):
        """Une requête d'administration traitée ou refusée (niveaux 1 et 2).

        action : action connue du routeur ou None ; le domaine en est tiré, jamais d'un chemin
        reçu. session None : requête sans session (refus regroupés).
        """
        # Seuls les appels réussis de la liste d'activité relèvent du niveau 2 ; les refus
        # (jeton, origine, requête mal formée) restent enregistrés dès le niveau 1.
        niveau = 2 if (action == ACTION_LISTE and evenement == 'action'
                       and resultat == 'ok') else 1
        if niveau > self.detail:
            return
        with self._verrou:
            self._vider_groupes()
            if session is None and evenement == 'refusal':
                self._regrouper(resultat, source)
                return
            domaine = action.split('/')[0] if action else None
            champs = {'admin': admin, 'session': session or 0, 'domain': domaine,
                      'action': action, 'result': resultat}
            if self.detail >= 2:
                if session:
                    champs['source'] = source
                champs['duration_ms'] = max(0, int(duree_ms or 0))
                champs['twin'] = self.jumeaux.get(action) if action else None
            elif session is None:
                champs['source'] = source
            if self.detail >= 3 and args:
                champs['args'] = args
            self._ecrire(self._entree(niveau, evenement, **champs))

    def session(self, evenement, numero, admin, source):
        """Ouverture ou fermeture d'une session de présence (`session_open`, `session_close`)."""
        with self._verrou:
            self._vider_groupes()
            champs = {'admin': admin, 'session': numero, 'result': 'ok'}
            if self.detail >= 2:
                champs['source'] = source
            self._ecrire(self._entree(1, evenement, **champs))

    def protocole(self, **champs):
        """Entrée `protocol` du niveau 3 ; seuls les champs de forme connue sont écrits."""
        if self.detail < 3:
            return
        with self._verrou:
            self._ecrire(self._entree(
                3, 'protocol', **{c: v for c, v in champs.items() if v is not None}))

    def args_pour(self, action, params):
        """Paramètres marqués non secrets de l'action, typés et bornés ; {} sinon."""
        marques = self.marques.get(action, ())
        if not marques or not isinstance(params, dict):
            return {}
        resultat = {}
        for nom in sorted(marques):
            if nom in params:
                valeur = valeur_args(params[nom])
                if valeur is not None:
                    resultat[nom] = valeur
        return resultat

    # -- regroupement des refus sans session --------------------------------------------------

    def _regrouper(self, resultat, source):
        cle = (resultat, source)
        if cle not in self._groupes and len(self._groupes) >= self.regroupements_simultanes:
            cle = (resultat, None)
        groupe = self._groupes.get(cle)
        if groupe is None:
            groupe = self._groupes[cle] = {'debut': self.monotone(), 'ts': self._ts(),
                                           'count': 0}
        groupe['count'] += 1
        if groupe['count'] >= self.regroupement_max:
            self._ecrire_groupe(cle, self._groupes.pop(cle))

    def _ecrire_groupe(self, cle, groupe):
        resultat, source = cle
        self._ecrire({'ts': groupe['ts'], 'level': 1, 'event': 'refusal', 'admin': None,
                      'session': 0, 'domain': None, 'action': None, 'result': resultat,
                      'source': source, 'count': groupe['count']})

    def _vider_groupes(self, force=False):
        maintenant = self.monotone()
        for cle in [c for c, g in self._groupes.items()
                    if force or maintenant - g['debut'] >= 60]:
            self._ecrire_groupe(cle, self._groupes.pop(cle))

    # -- lecture ------------------------------------------------------------------------------

    def _lire_fichier(self, dossier_fd, nom, budget):
        """(lignes de la fin vers le début, octets lus, fichier incomplet) ; absent : vide."""
        try:
            fd = ouvrir_fichier_controle(nom, dossier_fd, self.proprietaires)
        except ErreurPlugin as erreur:
            if erreur.code == 'plugin_incomplete':
                return [], 0, False
            raise ActiviteInutilisable('activity_unsafe') from None
        try:
            attributs = self._controler_fichier(fd)
            debut = max(0, attributs.st_size - budget)
            donnees = b''
            while len(donnees) < attributs.st_size - debut:
                bloc = os.pread(fd, attributs.st_size - debut - len(donnees),
                                debut + len(donnees))
                if not bloc:
                    break
                donnees += bloc
        except OSError:
            raise ActiviteInutilisable('activity_io_error') from None
        finally:
            os.close(fd)
        lignes = donnees.split(b'\n')
        if debut > 0:
            lignes = lignes[1:]    # première ligne probablement coupée
        return list(reversed(lignes)), len(donnees), debut > 0

    def lire(self, limite, niveau, domaine):
        """(entrées, tronqué) les plus récentes d'abord ; ActiviteInutilisable si non conforme."""
        with self._verrou:
            self._vider_groupes(force=True)
        dossier_fd = self._ouvrir_dossier(False)
        if dossier_fd is None:
            return [], False
        resultat, correspondances, incomplet, budget = [], 0, False, LECTURE_MAX
        try:
            for nom in (NOM_FICHIER, NOM_ANCIEN):
                if budget <= 0:
                    incomplet = True
                    break
                lignes, lus, partiel = self._lire_fichier(dossier_fd, nom, budget)
                budget -= lus
                incomplet = incomplet or partiel
                for ligne in lignes:
                    entree = self._analyser(ligne)
                    if (entree is None or entree['level'] > niveau
                            or (domaine is not None and entree.get('domain') != domaine)):
                        continue
                    correspondances += 1
                    if correspondances > limite:
                        return resultat, True
                    resultat.append(entree)
        finally:
            os.close(dossier_fd)
        return resultat, incomplet

    @staticmethod
    def _analyser(ligne):
        if not ligne or len(ligne) + 1 > LIGNE_MAX:
            return None
        try:
            return valider(json.loads(ligne.decode('ascii')))
        except (ValueError, UnicodeError, RecursionError):
            return None
