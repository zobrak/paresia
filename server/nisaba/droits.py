# SPDX-License-Identifier: AGPL-3.0-or-later
# Nisaba : modes, ACL et attributs du journal légal (reprend journal-legal-acl.sh 1.1.0 et set_mode_acl des scripts
# pull 1.2.1 et seal 1.3.0, D22, D24, D87, C38, T012) ; dépendances : bibliothèque standard, commandes, verification.
# Programmes lancés par argv (N8) : setfacl, getfacl, chattr, lsattr. Le mode est posé par os.chmod, jamais
# après setfacl sur un même chemin. L'essai de lecture par runuser du script n'existe plus (N9) : Romulus le
# fait sous son propre compte (T009, legal/journal/status).
# Suivi des versions
#   3.0.0-alpha.41  2026-11-06  Création (T033, D87, C38, T012) : familles, contrôle, application, rétablissement garanti.
import os
import pwd
import re
import stat

from server.commun.texte import filtrer
from .commandes import lancer
from .verification import MAX_MANIFEST, _lire

_JOURNAL = re.compile(r'journal-[0-9]{4}-[0-9]{2}-[0-9]{2}\.jsonl')
_SCELLE = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}\.txt(?:\.ots)?')
_JOUR = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}')
_COMMENTAIRE = re.compile(r'[ \t\r\f\v]*#.*$')
MODES = {'root-dir': 0o700, 'journal-dir': 0o700, 'file640': 0o640, 'file600': 0o600}


def spec_acl(famille, compte):
    """Spécification de setfacl -m d'une famille (tableau A de T012)."""
    if famille == 'root-dir':
        return f'u:{compte}:x,g::---,o::---'
    if famille == 'journal-dir':
        return f'u:{compte}:rx,g::---,o::---,d:u::rwx,d:u:{compte}:r,d:g::---,d:o::---'
    if famille == 'file640':
        return f'u:{compte}:r,g::r--,o::---'
    return f'u:{compte}:r,g::---,o::---'


def entrees_attendues(famille, compte):
    """Lignes attendues de getfacl pour une famille."""
    if famille == 'root-dir':
        return ['user::rwx', f'user:{compte}:--x', 'group::---', 'mask::--x', 'other::---']
    if famille == 'journal-dir':
        return ['user::rwx', f'user:{compte}:r-x', 'group::---', 'mask::r-x', 'other::---',
                'default:user::rwx', f'default:user:{compte}:r--', 'default:group::---', 'default:other::---']
    if famille == 'file640':
        return ['user::rw-', f'user:{compte}:r--', 'group::r--', 'mask::r--', 'other::---']
    return ['user::rw-', f'user:{compte}:r--', 'group::---', 'mask::r--', 'other::---']


def _nom_utilisateur(uid):
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def _ordinaire(chemin):
    """Fichier ordinaire, jamais un lien."""
    try:
        return stat.S_ISREG(os.lstat(chemin).st_mode)
    except OSError:
        return False


def _dossier(chemin):
    try:
        return stat.S_ISDIR(os.lstat(chemin).st_mode)
    except OSError:
        return False


class Droits:
    """Pose, contrôle et rétablit modes, ACL et attributs ; un chemin à la fois, rien n'est élargi en repli."""

    def __init__(self, *, dossier, compte, setfacl, getfacl, chattr, lsattr, lancer=lancer, uid_attendu=None,
                 delai=10):
        self.dossier = os.fspath(dossier).rstrip('/') or '/'
        self.racine = os.path.dirname(self.dossier)           # LOG_ROOT du script : parent du dossier du journal
        self.seals = os.path.join(self.dossier, 'seals')
        self.manifest = os.path.join(self.dossier, 'MANIFEST')
        self.compte = compte
        self.setfacl, self.getfacl, self.chattr, self.lsattr = setfacl, getfacl, chattr, lsattr
        self.lancer = lancer
        self.uid_attendu = os.geteuid() if uid_attendu is None else uid_attendu
        self.delai = delai

    # -- attributs ------------------------------------------------------------------
    def attributs(self, chemin):
        """Lettres d'attributs de lsattr -d, ou None si illisibles."""
        code, sortie, _ = self.lancer([self.lsattr, '-d', '--', chemin], self.delai)
        if code != 0:
            return None
        return sortie.split('\n', 1)[0].split(' ', 1)[0]

    def immuable(self, chemin):
        """0 = immuable posé, 1 = non posé, 2 = attributs illisibles."""
        lettres = self.attributs(chemin)
        if lettres is None:
            return 2
        return 0 if 'i' in lettres else 1

    def fixer(self, signe_lettre, chemin):
        """chattr +i|-i|+a|-a ; vrai si réussi."""
        return self.lancer([self.chattr, signe_lettre, '--', chemin], self.delai).code == 0

    # -- pose -----------------------------------------------------------------------
    def poser(self, chemin, famille):
        """chmod PUIS setfacl -m (jamais l'inverse) ; None si réussi, sinon texte d'échec (ECHEC_ACL)."""
        mode = MODES[famille]
        try:
            os.chmod(chemin, mode)
        except OSError:
            return f'chmod_failed: {oct(mode)[2:].zfill(4)} {chemin}'
        if self.lancer([self.setfacl, '-m', spec_acl(famille, self.compte), '--', chemin], self.delai).code != 0:
            return f'setfacl_failed: {chemin}'
        return None

    # -- cibles ---------------------------------------------------------------------
    def cibles(self):
        """[(famille, chemin)] : racine, dossier, journaux à nom strict, MANIFEST, seals/ et son contenu."""
        cibles = [('root-dir', self.racine), ('journal-dir', self.dossier)]
        try:
            noms = sorted(os.listdir(self.dossier))
        except OSError:
            noms = []
        for nom in noms:
            chemin = os.path.join(self.dossier, nom)
            if _JOURNAL.fullmatch(nom) and _ordinaire(chemin):
                cibles.append(('file640', chemin))
        if _ordinaire(self.manifest):
            cibles.append(('file600', self.manifest))
        if _dossier(self.seals):
            cibles.append(('journal-dir', self.seals))
            try:
                noms = sorted(os.listdir(self.seals))
            except OSError:
                noms = []
            for nom in noms:
                chemin = os.path.join(self.seals, nom)
                if _SCELLE.fullmatch(nom) and _ordinaire(chemin):
                    cibles.append(('file600', chemin))
        return cibles

    # -- contrôle -------------------------------------------------------------------
    def _acl(self, chemin):
        code, sortie, _ = self.lancer([self.getfacl, '--absolute-names', '--omit-header', '--', chemin], self.delai)
        lignes = [_COMMENTAIRE.sub('', ligne).rstrip() for ligne in sortie.split('\n')] if code == 0 else []
        return [ligne for ligne in lignes if ligne]

    def controler_cible(self, famille, chemin):
        """Liste des défauts d'un élément (vide : conforme)."""
        try:
            attributs = os.stat(chemin)
        except OSError:
            return [f'ERREUR absent : {chemin}']
        erreurs = []
        if attributs.st_uid != self.uid_attendu:
            erreurs.append(f'ERREUR propriétaire {_nom_utilisateur(attributs.st_uid)} au lieu de '
                           f'{_nom_utilisateur(self.uid_attendu)} : {chemin}')
        acl = self._acl(chemin)
        if not acl:
            return erreurs + [f'ERREUR ACL illisible : {chemin}']
        attendues = entrees_attendues(famille, self.compte)
        for voulue in attendues:
            if voulue not in acl:
                erreurs.append(f'ERREUR entrée ACL manquante « {voulue} » : {chemin}')
        for trouvee in acl:
            if trouvee.startswith(('mask::', 'default:mask::', 'user::', 'group::', 'other::')):
                continue                                  # masque recalculé par setfacl ; le reste est dans attendues
            if trouvee not in attendues:
                erreurs.append(f'ERREUR entrée ACL non prévue « {trouvee} » : {chemin}')
        return erreurs

    def _controler_attribut(self, chemin, lettre):
        lettres = self.attributs(chemin)
        if lettres is None:
            return f'ERREUR attributs illisibles : {chemin}'
        if lettre not in lettres:
            return f'ERREUR attribut {lettre} absent : {chemin}'
        return None

    def controler_attributs(self):
        """Attributs attendus : MANIFEST a ; journaux inscrits au MANIFEST et seals/*.txt i. [(erreurs, éléments)]."""
        erreurs, elements = [], 0
        if _ordinaire(self.manifest):
            elements += 1
            defaut = self._controler_attribut(self.manifest, 'a')
            if defaut:
                erreurs.append(defaut)
            try:
                contenu = _lire(self.manifest, MAX_MANIFEST)
            except OSError:
                contenu = b''
                erreurs.append(f'ERREUR lecture impossible : {self.manifest}')
            for ligne in contenu.decode('utf-8', 'replace').split('\n'):
                champs = ligne.split(' ')
                if not champs[0]:
                    continue
                if len(champs) > 1 and champs[1] == 'ABSENT':
                    continue
                if not _JOUR.fullmatch(champs[0]):
                    erreurs.append(f'ERREUR ligne de registre invalide : {self.manifest}')
                    continue
                journal = os.path.join(self.dossier, f'journal-{champs[0]}.jsonl')
                if _ordinaire(journal):
                    elements += 1
                    defaut = self._controler_attribut(journal, 'i')
                    if defaut:
                        erreurs.append(defaut)
                else:
                    erreurs.append(f'ERREUR journal inscrit au registre absent : {journal}')
        if _dossier(self.seals):
            try:
                noms = sorted(os.listdir(self.seals))
            except OSError:
                noms = []
            for nom in noms:
                chemin = os.path.join(self.seals, nom)
                if re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}\.txt', nom) and _ordinaire(chemin):
                    elements += 1
                    defaut = self._controler_attribut(chemin, 'i')
                    if defaut:
                        erreurs.append(defaut)
        return erreurs, elements

    def controler(self):
        """acl check : propriétaire, entrées ACL et attributs, sans essai de lecture (N9). Lecture seule."""
        lignes, erreurs, elements = [], 0, 0
        for famille, chemin in self.cibles():
            elements += 1
            defauts = self.controler_cible(famille, chemin)
            lignes.extend(defauts)
            erreurs += 1 if defauts else 0
        if not os.path.lexists(self.manifest):
            lignes.append(f'OK      MANIFEST absent (pas encore créé) : {self.manifest}')
        if not os.path.lexists(self.seals):
            lignes.append(f'OK      seals/ absent (pas encore créé) : {self.seals}')
        defauts, supplement = self.controler_attributs()
        lignes.extend(defauts)
        erreurs += len(defauts)
        lignes.append('RÉSULTAT : conforme' if erreurs == 0 else f'RÉSULTAT : {erreurs} erreur(s)')
        return {'code': 0 if erreurs == 0 else 1, 'lignes': [filtrer(ligne) for ligne in lignes],
                'elements': elements + supplement}

    # -- application ----------------------------------------------------------------
    def _retablir(self, chemin, immuable, ajout):
        """Rétablit +i puis +a ; vrai si tout est rétabli (sinon ECHEC_ACL de l'appelant)."""
        ok = True
        for pose, lettre in ((immuable, '+i'), (ajout, '+a')):
            if pose and not self.fixer(lettre, chemin):
                ok = False
        return ok

    def appliquer_cible(self, famille, chemin, trace, echec):
        """Traite un élément ; (réussi, rétablissement_ok). Un élément conforme n'est pas touché."""
        if not self.controler_cible(famille, chemin):
            trace(f'INCHANGE {chemin} (déjà conforme)')
            return True, True
        lettres = self.attributs(chemin)
        if lettres is None:
            echec(f'attrs_unreadable: {chemin}')
            return False, True
        immuable, ajout = 'i' in lettres, 'a' in lettres
        reussi, retabli = False, True
        try:                                              # ce qu'il faudra rétablir est noté AVANT tout retrait
            texte = None
            if immuable and not self.fixer('-i', chemin):
                texte = f'unseal_failed: {chemin}'
            if texte is None and ajout and not self.fixer('-a', chemin):
                texte = f'unappend_failed: {chemin}'
            if texte is None:
                try:
                    os.chmod(chemin, MODES[famille])
                except OSError:
                    texte = f'chmod_failed: {chemin}'
            if texte is None:
                if (self.lancer([self.setfacl, '-b', '--', chemin], self.delai).code != 0
                        or self.lancer([self.setfacl, '-m', spec_acl(famille, self.compte), '--', chemin],
                                       self.delai).code != 0):
                    texte = f'setfacl_failed: {chemin}'
            if texte is not None:
                echec(texte)
            else:
                reussi = True
        finally:
            retabli = self._retablir(chemin, immuable, ajout)
            if not retabli:
                echec(f'restore_failed: {chemin}')
        if reussi and retabli:
            trace(f'TRAITE {chemin}')
        return reussi and retabli, retabli

    def appliquer(self, trace, echec, interrompu=lambda: False):
        """acl apply : un élément à la fois ; arrêt si un rétablissement échoue ou sur interruption demandée."""
        echecs = 0
        lignes = []

        def _trace(texte):
            if not texte.startswith('INCHANGE'):          # les éléments conformes ne sont que tracés (taille de la réponse)
                lignes.append(filtrer(texte))
            trace(texte)

        def _echec(texte):
            lignes.append(filtrer('ECHEC_ACL ' + texte))
            echec(texte)

        for famille, chemin in self.cibles():
            if interrompu():
                _trace('ARRÊT : interruption demandée ; aucun autre fichier n\'est traité')
                return {'code': 1, 'lignes': lignes}
            reussi, retabli = self.appliquer_cible(famille, chemin, _trace, _echec)
            echecs += 0 if reussi else 1
            if not retabli:
                _trace(f'ARRÊT : rétablissement d\'attribut impossible sur {chemin} ; '
                       'aucun autre fichier n\'est traité')
                return {'code': 1, 'lignes': lignes}
        _trace('RÉSULTAT : modes et ACL appliqués' if echecs == 0 else f'RÉSULTAT : {echecs} élément(s) en échec')
        return {'code': 0 if echecs == 0 else 1, 'lignes': lignes}
