# SPDX-License-Identifier: AGPL-3.0-or-later
# Nisaba : horodatage OpenTimestamps des lignes du MANIFEST (reprend timestamp_manifest de journal-legal-seal.sh
# 1.3.0, D87, C38, T012) ; dépendances : bibliothèque standard, droits, verification. Le client `ots` est
# lancé par argv (N8) : `ots stamp FICHIER` crée FICHIER.ots ; `ots upgrade FICHIER.ots` complète la preuve et
# garde l'ancienne dans FICHIER.ots.bak (supprimée ici), comme le script. Seule l'empreinte part sur Internet.
# Suivi des versions
#   3.0.0-alpha.41  2026-11-06  Création (T033) : copie scellée de la ligne, soumission, mise à jour, ancrage.
import datetime
import os
import re
import stat

from .verification import MAX_MANIFEST, _lire

_JOUR = re.compile(r'([0-9]{4}-[0-9]{2}-[0-9]{2}) .*')


def _supprimer(chemin):
    try:
        os.unlink(chemin)
    except FileNotFoundError:
        pass


class Horodateur:
    def __init__(self, config_ots, dossier, droits, lancer, *, horloge, trace, echec_horodatage, echec_acl):
        self.ots = os.fspath(config_ots['ots'])
        self.attente = config_ots['attente_max_jours']
        self.delai = config_ots['delai_s']
        self.dossier = os.fspath(dossier).rstrip('/') or '/'
        self.manifest = os.path.join(self.dossier, 'MANIFEST')
        self.seals = os.path.join(self.dossier, 'seals')
        self.droits, self.lancer, self.horloge = droits, lancer, horloge
        self.trace, self.echec_horodatage, self.echec_acl = trace, echec_horodatage, echec_acl
        self._echecs = 0

    def _horodatage(self, texte):
        self._echecs += 1
        self.echec_horodatage(texte)

    def _acl(self, texte):
        if texte:
            self._echecs += 1
            self.echec_acl(texte)

    def _copie_scellee(self, chemin, ligne):
        """Copie exacte de la ligne du registre (sans saut de ligne), 0600 + ACL, puis chattr +i (échec sans effet)."""
        try:
            descripteur = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        except OSError:
            self._horodatage(f'seal_copy_failed: {os.path.basename(chemin)}')
            return False
        try:
            with os.fdopen(descripteur, 'wb') as fichier:
                fichier.write(ligne.encode())
        except OSError:
            self._horodatage(f'seal_copy_failed: {os.path.basename(chemin)}')
            return False
        self._acl(self.droits.poser(chemin, 'file600'))
        self.droits.fixer('+i', chemin)
        return True

    def horodater(self):
        """Renvoie le nombre d'échecs (ECHEC_HORODATAGE et ECHEC_ACL) ; ne lève rien pour un échec d'outil."""
        self._echecs = 0
        try:
            contenu = _lire(self.manifest, MAX_MANIFEST)
        except OSError:
            return 0                                       # registre absent ou illisible : rien à horodater
        if not contenu.strip() or len(contenu) > MAX_MANIFEST:
            return 0
        if not (os.path.isfile(self.ots) and os.access(self.ots, os.X_OK)):
            self._horodatage('ots_missing')
            return self._echecs
        try:
            etat = os.lstat(self.seals)
        except FileNotFoundError:
            try:
                os.mkdir(self.seals, 0o700)
            except OSError:
                self._horodatage('seals_create_failed')
                return self._echecs
            self._acl(self.droits.poser(self.seals, 'journal-dir'))
        except OSError:
            self._horodatage('seals_unreadable')
            return self._echecs
        else:
            if not stat.S_ISDIR(etat.st_mode):
                self._horodatage('seals_invalid')
                return self._echecs
        aujourdhui = datetime.datetime.fromtimestamp(self.horloge(), datetime.timezone.utc).date()
        limite = aujourdhui - datetime.timedelta(days=self.attente)
        lignes = contenu.decode('utf-8', 'replace').split('\n')
        for ligne in lignes:
            if not ligne:
                continue
            trouve = _JOUR.fullmatch(ligne)
            try:
                jour = datetime.date.fromisoformat(trouve.group(1)) if trouve else None
            except ValueError:
                jour = None
            if jour is None:
                self._horodatage('manifest_line_invalid')
                continue
            self._jour(jour, ligne, limite)
        return self._echecs

    def _jour(self, jour, ligne, limite):
        texte_jour = jour.isoformat()
        copie = os.path.join(self.seals, f'{texte_jour}.txt')
        preuve = copie + '.ots'
        if not os.path.lexists(copie) and not self._copie_scellee(copie, ligne):
            return
        if not os.path.isfile(copie) or os.path.islink(copie):
            return                                         # jamais d'opération sur autre chose qu'un fichier ordinaire
        if os.path.lexists(preuve) and not stat.S_ISREG(os.lstat(preuve).st_mode):
            self._horodatage(f'proof_invalid: {texte_jour}')
            return
        if not os.path.lexists(preuve):                    # première soumission
            if self.lancer([self.ots, 'stamp', copie], self.delai).code == 0:
                self._acl(self.droits.poser(preuve, 'file600'))
                self.trace('timestamp_submitted', jour=texte_jour)
            else:
                _supprimer(preuve)
                self._horodatage(f'submit_failed: {texte_jour}')
            return
        if self.droits.immuable(preuve) == 0:              # déjà ancrée
            return
        _supprimer(preuve + '.bak')                        # preuve en attente : tentative de complétion
        reussi = self.lancer([self.ots, 'upgrade', preuve], self.delai).code == 0
        _supprimer(preuve + '.bak')
        if reussi:                                         # upgrade réécrit le fichier : il peut perdre son ACL
            self._acl(self.droits.poser(preuve, 'file600'))
            self.droits.fixer('+i', preuve)
            self.trace('timestamp_anchored', jour=texte_jour)
        elif jour < limite:
            self._horodatage(f'proof_incomplete: {texte_jour} (after {self.attente} days)')
