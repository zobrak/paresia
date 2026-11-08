# SPDX-License-Identifier: AGPL-3.0-or-later
# Nisaba : purge de la copie du journal légal (reprend journal-legal-purge.sh 1.1.0, D87, C38) ;
# dépendances : bibliothèque standard et verification.
# Suivi des versions
#   3.0.0-alpha.40  2026-11-06  Création (T031) : mêmes noms et même seuil que le script ; ECHEC_PURGE nouveau.
import datetime
import os
import re
import stat

from .verification import executer_externe

_NOM = re.compile(r'journal-(\d{4}-\d{2}-\d{2})\.jsonl')


def purger(dossier, conservation_jours, chattr, aujourdhui, *, supprime, echec, executer=executer_externe):
    """Supprime les journal-AAAA-MM-JJ.jsonl antérieurs de plus de conservation_jours jours à aujourdhui (UTC).

    Un fichier du jour D disparaît donc à D + conservation_jours + 1. Nom strict, fichier ordinaire,
    jamais un lien. L'immutabilité de ce seul fichier est retirée avant la suppression (chattr -i,
    argv). MANIFEST et seals/ ne sont jamais touchés. supprime(nom) et echec(texte) sont des rappels ;
    un échec n'arrête pas les autres fichiers. Renvoie le nombre de fichiers supprimés.
    """
    limite = aujourdhui - datetime.timedelta(days=conservation_jours)
    dossier = os.fspath(dossier)
    supprimes = 0
    try:
        noms = sorted(os.listdir(dossier))
    except OSError:
        echec('list_failed')
        return 0
    for nom in noms:
        trouve = _NOM.fullmatch(nom)
        if trouve is None:
            continue
        try:
            jour = datetime.date.fromisoformat(trouve.group(1))
        except ValueError:
            continue
        chemin = os.path.join(dossier, nom)
        try:
            attributs = os.lstat(chemin)
        except OSError:
            continue
        if not stat.S_ISREG(attributs.st_mode):       # lstat : un lien n'est jamais un fichier ordinaire
            continue
        if jour >= limite:
            continue
        if attributs.st_nlink != 1:                  # lien physique : le fichier n'est ni modifié ni supprimé
            echec(f'nlink_ignored: {nom}')
            continue
        executer([chattr, '-i', '--', chemin])      # l'échec est sans effet : le fichier n'est peut-être pas immuable
        try:
            os.unlink(chemin)
        except FileNotFoundError:
            continue
        except OSError:
            echec(f'unlink_failed: {nom}')
            continue
        supprimes += 1
        supprime(nom)
    return supprimes
