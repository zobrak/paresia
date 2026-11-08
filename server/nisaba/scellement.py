# SPDX-License-Identifier: AGPL-3.0-or-later
# Nisaba : scellement quotidien du journal légal (reprend seal_one_day et le rattrapage de journal-legal-seal.sh
# 1.3.0, D87, C38, T012) ; dépendances : bibliothèque standard, copie, droits, verification.
# Format du MANIFEST (inchangé, docs/journal-legal-format.md si fusionnée, sinon en-tête du script) :
#   <D> <sha256_fichier|ABSENT> <taille> <chaine_precedente> <chaine>
#   chaine = sha256("<chaine_precedente> <D> <sha256_fichier> <taille>"), première chaîne = 64 zéros.
# Suivi des versions
#   3.0.0-alpha.41  2026-11-06  Création (T033) : mêmes étapes et même contenu du MANIFEST que le script.
import datetime
import hashlib
import os
import re

from .copie import PLAFOND_PROCESSUS, commande_ssh, masquer, secondes
from .verification import GENESIS, MAX_MANIFEST, _LIGNE, _lire, ouvrir_ordinaire

_JOUR = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}')
_JOURNAL = re.compile(r'journal-([0-9]{4}-[0-9]{2}-[0-9]{2})\.jsonl')


class ErreurScellement(Exception):
    """Premier échec d'un scellement : arrêt, sans passer aux journées suivantes."""


def jour_valide(texte, aujourdhui):
    """Date AAAA-MM-JJ valide et terminée (strictement avant aujourd'hui, UTC) ; sinon None."""
    if not isinstance(texte, str) or _JOUR.fullmatch(texte) is None:
        return None
    try:
        jour = datetime.date.fromisoformat(texte)
    except ValueError:
        return None
    return jour if jour < aujourdhui else None


def empreinte_et_taille(chemin):
    """(SHA-256 hexadécimal, taille) d'un fichier ordinaire lu d'un seul passage, sans suivre de lien."""
    resume, taille = hashlib.sha256(), 0
    with ouvrir_ordinaire(chemin) as fichier:
        while True:
            bloc = fichier.read(1024 * 1024)
            if not bloc:
                return resume.hexdigest(), taille
            resume.update(bloc)
            taille += len(bloc)


class Scelleur:
    def __init__(self, config_source, dossier, droits, lancer, *, horloge, trace, echec_scellement, echec_acl):
        self.source = config_source
        self.dossier = os.fspath(dossier).rstrip('/') or '/'
        self.manifest = os.path.join(self.dossier, 'MANIFEST')
        self.droits, self.lancer, self.horloge = droits, lancer, horloge
        self.trace, self.echec_scellement, self.echec_acl = trace, echec_scellement, echec_acl
        self._echecs_acl = 0

    # -- utilitaires ----------------------------------------------------------------
    def aujourdhui(self):
        return datetime.datetime.fromtimestamp(self.horloge(), datetime.timezone.utc).date()

    def _acl(self, texte):
        if texte:
            self._echecs_acl += 1
            self.echec_acl(texte)

    def _lignes(self):
        """Lignes du MANIFEST, chacune au format strict ; ErreurScellement sinon."""
        try:
            contenu = _lire(self.manifest, MAX_MANIFEST)
        except FileNotFoundError:
            return []
        except OSError:
            raise ErreurScellement('manifest_unreadable') from None
        if len(contenu) > MAX_MANIFEST:
            raise ErreurScellement('manifest_too_large')
        lignes = contenu.decode('utf-8', 'replace').split('\n')
        if lignes and lignes[-1] == '':
            lignes.pop()
        for ligne in lignes:
            if _LIGNE.fullmatch(ligne) is None:
                raise ErreurScellement('manifest_invalid')
        return lignes

    def _rsync(self, *arguments):
        argv = [os.fspath(self.source['rsync']), *arguments]
        resultat = self.lancer(argv, PLAFOND_PROCESSUS)
        return resultat.code, masquer(resultat.sortie, self.source), masquer(resultat.erreur, self.source)

    def _base(self):
        return [f"--timeout={secondes(self.source['rsync_s'])}", '-e', commande_ssh(self.source)]

    # -- une journée ----------------------------------------------------------------
    def sceller_journee(self, jour):
        nom = f'journal-{jour}.jsonl'
        journal = os.path.join(self.dossier, nom)
        lignes = self._lignes()
        if any(ligne.startswith(jour + ' ') for ligne in lignes):
            self.trace('already_sealed', jour=jour)
            return
        base = self._base()
        distant = self.source['source'] + nom
        # 1. Existence sur backend-relais : « pas de fichier » se distingue de « relais injoignable ».
        if self._rsync('--list-only', *base, distant)[0] == 0:
            existe = True
        else:
            if self._rsync('--list-only', *base, self.source['source'])[0] != 0:
                raise ErreurScellement(f'relay_unreachable: {jour}')
            existe = False
        if existe:
            # 2. Dernière copie, puis contrôle d'identité par sommes de contrôle ; rien n'est écrasé.
            destination = self.dossier + '/'
            if self._rsync('--times', '--append', *base, distant, destination)[0] != 0:
                raise ErreurScellement(f'last_copy_failed: {nom}')
            code, sortie, _ = self._rsync('--dry-run', '--checksum', '--itemize-changes', *base, distant,
                                          destination)
            if code != 0:
                raise ErreurScellement(f'compare_failed: {nom}')
            if sortie.strip('\n'):
                raise ErreurScellement(f'differs: {nom}: {" ".join(sortie.split())}')
            try:
                empreinte, taille = empreinte_et_taille(journal)
            except OSError:
                raise ErreurScellement(f'journal_unreadable: {nom}') from None
        else:
            if os.path.lexists(journal):
                raise ErreurScellement(f'local_only: {nom}')
            empreinte, taille = 'ABSENT', 0
        # 3. Chaînage et inscription au registre.
        precedente = lignes[-1].split(' ')[4] if lignes else GENESIS
        chaine = hashlib.sha256(f'{precedente} {jour} {empreinte} {taille}'.encode()).hexdigest()
        if not os.path.lexists(self.manifest):
            try:
                os.close(os.open(self.manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                                 | os.O_CLOEXEC, 0o600))
            except OSError:
                raise ErreurScellement('manifest_create_failed') from None
            self._acl(self.droits.poser(self.manifest, 'file600'))
        # setfacl AVANT chattr +a : un fichier en ajout seul n'accepte plus de changement d'ACL.
        self.droits.fixer('+a', self.manifest)             # registre en ajout seul, idempotent ; échec sans effet
        ligne = f'{jour} {empreinte} {taille} {precedente} {chaine}\n'.encode()
        try:
            descripteur = os.open(self.manifest, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                if os.write(descripteur, ligne) != len(ligne):
                    raise OSError('short_write')
                os.fsync(descripteur)
            finally:
                os.close(descripteur)
        except OSError:
            raise ErreurScellement('manifest_append_failed') from None
        # 4. Immuabilité du fichier scellé : mode 0640 et ACL, puis chattr +i.
        if empreinte != 'ABSENT':
            self._acl(self.droits.poser(journal, 'file640'))
            if not self.droits.fixer('+i', journal):
                raise ErreurScellement(f'chattr_failed: {nom} (seal recorded in manifest)')
        self.trace('sealed', jour=jour, fichier=empreinte, taille=taille, chaine=chaine)

    # -- tâche ----------------------------------------------------------------------
    def _a_sceller(self, hier):
        lignes = self._lignes()
        if lignes:
            return datetime.date.fromisoformat(lignes[-1].split(' ')[0]) + datetime.timedelta(days=1)
        try:
            noms = sorted(os.listdir(self.dossier))
        except OSError:
            noms = []
        jours = []
        for nom in noms:
            trouve = _JOURNAL.fullmatch(nom)
            if trouve is None or not os.path.isfile(os.path.join(self.dossier, nom)) \
                    or os.path.islink(os.path.join(self.dossier, nom)):
                continue
            try:
                jours.append(datetime.date.fromisoformat(trouve.group(1)))
            except ValueError:
                pass
        return min(jours) if jours else hier

    def sceller(self, jour=None):
        """Scelle la journée indiquée, ou rattrape de la suivante du registre jusqu'à la veille (UTC).

        Renvoie le nombre d'échecs (premier échec de scellement : arrêt ; échecs d'ACL : sans arrêt).
        """
        self._echecs_acl = 0
        aujourdhui = self.aujourdhui()
        echecs = 0
        try:
            if jour is not None:
                termine = jour_valide(jour, aujourdhui)
                if termine is None:
                    raise ValueError('invalid_day')
                self.sceller_journee(jour)
            else:
                hier = aujourdhui - datetime.timedelta(days=1)
                courant = self._a_sceller(hier)
                if courant > hier:
                    self.trace('nothing_to_seal', jusqua=hier.isoformat())
                while courant <= hier:
                    self.sceller_journee(courant.isoformat())     # le premier échec arrête tout (pas de trou)
                    courant += datetime.timedelta(days=1)
        except ErreurScellement as erreur:
            echecs = 1
            self.echec_scellement(str(erreur))
        return echecs + self._echecs_acl
