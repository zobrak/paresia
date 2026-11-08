# SPDX-License-Identifier: AGPL-3.0-or-later
# Nisaba : vérification du MANIFEST du journal légal (reprend verify_manifest de journal-legal-seal.sh 1.3.0,
# D87, C38) ; lecture seule ; dépendances : bibliothèque standard et server.commun.texte.
# Suivi des versions
#   3.0.0-alpha.40  2026-11-06  Création (T031) : mêmes contrôles et mêmes libellés que le script.
import errno
import hashlib
import os
import re
import stat
import subprocess

from server.commun.texte import filtrer

GENESIS = '0' * 64
PATH_OUTILS = '/usr/sbin:/usr/bin:/sbin:/bin'
MAX_MANIFEST = 16 * 1024 * 1024
MAX_COPIE = 65536
MAX_SORTIE = 4096
PAQUET_LSATTR = 64          # chemins par appel de lsattr
MARGE_LIGNE = 32            # attributs, espace et fin de ligne d'une ligne de lsattr
_LIGNE = re.compile(r'(\d{4}-\d{2}-\d{2}) ([0-9a-f]{64}|ABSENT) ([0-9]{1,15}) ([0-9a-f]{64}) ([0-9a-f]{64})')


def executer_externe(argv, delai=10):
    """Lance un outil par argv (jamais par un interpréteur de commandes) ; (code, sortie filtrée et bornée).

    Environnement vide hors PATH ; 127 si l'outil est introuvable ou dépasse le délai.
    """
    try:
        processus = subprocess.run(list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, env={'PATH': PATH_OUTILS},
                                   timeout=delai, check=False)
    except (OSError, subprocess.SubprocessError, ValueError):
        return 127, ''
    sortie = processus.stdout[:MAX_SORTIE].decode('utf-8', 'replace')
    return processus.returncode, '\n'.join(filtrer(ligne) for ligne in sortie.split('\n'))   # lignes conservées


def ouvrir_ordinaire(chemin):
    """Ouvre un fichier ordinaire en lecture, sans suivre de lien et sans bloquer (FIFO, périphérique).

    Lève OSError (FileNotFoundError si absent) ; un fichier non ordinaire est refusé (OSError EINVAL).
    """
    descripteur = os.open(chemin, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        if not stat.S_ISREG(os.fstat(descripteur).st_mode):
            raise OSError(errno.EINVAL, 'not_regular_file')
        return os.fdopen(descripteur, 'rb')
    except BaseException:
        os.close(descripteur)
        raise


def _lire(chemin, maximum):
    """Contenu d'un fichier ordinaire (sans suivre de lien) ; lève FileNotFoundError ou OSError."""
    with ouvrir_ordinaire(chemin) as fichier:
        return fichier.read(maximum + 1)[:maximum + 1]


def empreinte_fichier(chemin):
    """SHA-256 d'un fichier en flux ; lève FileNotFoundError ou OSError (jamais de suivi de lien)."""
    resume = hashlib.sha256()
    with ouvrir_ordinaire(chemin) as fichier:
        while True:
            bloc = fichier.read(1024 * 1024)
            if not bloc:
                return resume.hexdigest()
            resume.update(bloc)


def etat_immuable(chemin, lsattr, executer=executer_externe):
    """0 = attribut immuable posé, 1 = non posé, 2 = attributs illisibles (lecture par lsattr, D22)."""
    code, sortie = executer([lsattr, '-d', '--', chemin])
    if code != 0:
        return 2
    attributs = sortie.split(' ', 1)[0]
    return 0 if 'i' in attributs else 1


def etats_immuables(chemins, lsattr, executer=executer_externe):
    """{chemin: 0 immuable, 1 non posé, 2 illisible} ; lsattr -d -- par paquets bornés (jamais un appel par fichier)."""
    chemins = list(chemins)
    resultat = {}
    debut = 0
    while debut < len(chemins):
        fin, taille = debut, 0
        while fin < len(chemins) and fin - debut < PAQUET_LSATTR and (
                fin == debut or taille + len(chemins[fin]) + MARGE_LIGNE <= MAX_SORTIE):
            taille += len(chemins[fin]) + MARGE_LIGNE
            fin += 1
        paquet = chemins[debut:fin]
        debut = fin
        _, sortie = executer([lsattr, '-d', '--', *paquet])
        lues = {}
        for ligne in sortie.split('\n'):
            attributs, _, chemin = ligne.partition(' ')
            if chemin:
                lues[chemin] = attributs
        for chemin in paquet:
            attributs = lues.get(chemin)
            resultat[chemin] = 2 if attributs is None else (0 if 'i' in attributs else 1)
    return resultat


def _resultat(lignes, erreurs, journees):
    return {'ok': erreurs == 0, 'erreurs': erreurs, 'journees': journees,
            'lignes': [filtrer(ligne) for ligne in lignes]}


def verifier(dossier, lsattr, *, executer=executer_externe):
    """Vérifie tout le registre ; renvoie {'ok', 'erreurs', 'journees', 'lignes'} (lecture seule)."""
    dossier = os.fspath(dossier)
    manifest = os.path.join(dossier, 'MANIFEST')
    seals = os.path.join(dossier, 'seals')
    illisible = ([f'ERREUR lecture impossible : {manifest} (droits ou ACL manquants)',
                  'RÉSULTAT : 1 erreur(s)'])
    if not os.access(dossier, os.X_OK):
        return _resultat(illisible, 1, 0)
    try:
        contenu = _lire(manifest, MAX_MANIFEST)
    except FileNotFoundError:
        contenu = b''
    except OSError:
        return _resultat(illisible, 1, 0)
    if len(contenu) > MAX_MANIFEST:
        return _resultat([f'ERREUR registre trop volumineux : {manifest}', 'RÉSULTAT : 1 erreur(s)'], 1, 0)
    if not contenu:
        return _resultat([f'registre vide ou absent : {manifest}'], 0, 0)
    entrees = contenu.decode('utf-8', 'replace').split('\n')
    if entrees and entrees[-1] == '':
        entrees.pop()
    lignes, attendu, erreurs = [], GENESIS, 0
    for numero, brute in enumerate(entrees, 1):
        trouve = _LIGNE.fullmatch(brute)
        if trouve is None:
            lignes.append(f'ERREUR ligne {numero} : ligne du registre illisible')
            erreurs += 1
            continue
        jour, empreinte, taille, precedent, chaine = trouve.groups()
        erreurs_ligne = 0

        def signaler(texte):
            nonlocal erreurs_ligne
            lignes.append(f'ERREUR ligne {numero} ({jour}) : {texte}')
            erreurs_ligne += 1

        if precedent != attendu:
            signaler(f'chaîne rompue (précédent attendu {attendu})')
        recalcule = hashlib.sha256(f'{precedent} {jour} {empreinte} {taille}'.encode()).hexdigest()
        if recalcule != chaine:
            signaler('ligne du registre modifiée (empreinte de chaîne incorrecte)')
        statut = 'aucune publication ce jour-là'
        if empreinte != 'ABSENT':
            fichier = os.path.join(dossier, f'journal-{jour}.jsonl')
            try:
                reel = empreinte_fichier(fichier)
            except FileNotFoundError:
                statut = 'chaîne intègre (fichier purgé)'
            except OSError:
                signaler(f'lecture impossible de {fichier} (droits ou ACL manquants)')
                statut = 'fichier illisible'
            else:
                if reel != empreinte:
                    signaler('fichier modifié depuis le scellement')
                statut = 'fichier et chaîne intègres'
        copie = os.path.join(seals, f'{jour}.txt')
        try:
            texte = _lire(copie, MAX_COPIE).decode('utf-8', 'replace').rstrip('\n')
        except FileNotFoundError:
            pass
        except OSError:
            signaler(f'lecture impossible de seals/{jour}.txt (droits ou ACL manquants)')
        else:
            if texte != f'{jour} {empreinte} {taille} {precedent} {chaine}':
                signaler(f'la copie horodatée seals/{jour}.txt ne correspond pas au registre')
        if os.path.exists(copie + '.ots'):
            etat = etat_immuable(copie + '.ots', lsattr, executer)
            if etat == 0:
                statut += ' ; horodatage ancré'
            elif etat == 1:
                statut += ' ; horodatage en attente'
            else:
                signaler(f'attributs illisibles pour seals/{jour}.txt.ots (droits ou ACL manquants)')
        if erreurs_ligne == 0:
            lignes.append(f'OK      {jour}  {statut}')
        erreurs += erreurs_ligne
        attendu = chaine
    lignes.append(f'RÉSULTAT : registre intègre ({len(entrees)} journées)' if erreurs == 0
                  else f'RÉSULTAT : {erreurs} erreur(s)')
    return _resultat(lignes, erreurs, len(entrees))
