# SPDX-License-Identifier: AGPL-3.0-or-later
# Nisaba : relevés du journal légal pour l'état et les métriques (lecture seule) ;
# dépendances : bibliothèque standard et verification.
# Suivi des versions
#   3.0.0-alpha.40  2026-11-06  Création (T031) : publications du jour, registre, âge, preuves (seal 1.3.0).
import datetime
import os
import re

from .verification import MAX_MANIFEST, _LIGNE, _lire, etats_immuables, executer_externe, ouvrir_ordinaire

_JOURNAL = re.compile(r'journal-(\d{4}-\d{2}-\d{2})\.jsonl')
_PREUVE = re.compile(r'(\d{4}-\d{2}-\d{2})\.txt')


def publications(dossier, jour):
    """Nombre de lignes du journal du jour (UTC), ou None si le fichier est illisible ou absent."""
    chemin = os.path.join(os.fspath(dossier), f'journal-{jour}.jsonl')
    try:
        fichier = ouvrir_ordinaire(chemin)
    except OSError:
        return None
    total, dernier = 0, b'\n'
    with fichier:
        while True:
            bloc = fichier.read(1024 * 1024)
            if not bloc:
                break
            total += bloc.count(b'\n')
            dernier = bloc[-1:]
    return total + (0 if dernier == b'\n' else 1)


def registre(dossier):
    """(nombre de journées, dernière journée) du MANIFEST ; (0, None) si absent ou illisible."""
    try:
        contenu = _lire(os.path.join(os.fspath(dossier), 'MANIFEST'), MAX_MANIFEST)
    except OSError:
        return 0, None
    if len(contenu) > MAX_MANIFEST:
        return 0, None
    journees, derniere = 0, None
    for ligne in contenu.decode('utf-8', 'replace').split('\n'):
        trouve = _LIGNE.fullmatch(ligne)
        if trouve is not None:
            journees += 1
            derniere = trouve.group(1)
    return journees, derniere


def age_plus_ancien(dossier, maintenant):
    """Âge en secondes du plus ancien journal conservé (date du nom, minuit UTC), ou None."""
    try:
        noms = os.listdir(os.fspath(dossier))
    except OSError:
        return None
    jours = []
    for nom in noms:
        trouve = _JOURNAL.fullmatch(nom)
        if trouve is not None:
            try:
                jours.append(datetime.date.fromisoformat(trouve.group(1)))
            except ValueError:
                pass
    if not jours:
        return None
    debut = datetime.datetime.combine(min(jours), datetime.time(), datetime.timezone.utc).timestamp()
    return max(0, int(maintenant - debut))


def preuves(dossier, lsattr, executer=executer_externe):
    """Preuves OpenTimestamps : ancrées (.ots immuable), en attente (.ots non immuable), non soumises."""
    seals = os.path.join(os.fspath(dossier), 'seals')
    compte = {'ancrees': 0, 'en_attente': 0, 'non_soumises': 0}
    try:
        noms = sorted(os.listdir(seals))
    except OSError:
        return compte
    presentes = []
    for nom in noms:
        if _PREUVE.fullmatch(nom) is None:
            continue
        chemin = os.path.join(seals, nom + '.ots')
        if os.path.exists(chemin):
            presentes.append(chemin)
        else:
            compte['non_soumises'] += 1
    for chemin, etat in etats_immuables(presentes, lsattr, executer).items():
        compte['ancrees' if etat == 0 else 'en_attente'] += 1
    return compte


def collecter(dossier, lsattr, maintenant, executer=executer_externe):
    """Relevé du journal à l'instant maintenant (secondes depuis l'époque)."""
    jour = datetime.datetime.fromtimestamp(maintenant, datetime.timezone.utc).strftime('%Y-%m-%d')
    journees, derniere = registre(dossier)
    return {'publications_jour': publications(dossier, jour), 'journees': journees,
            'derniere_journee': derniere, 'age_plus_ancien_s': age_plus_ancien(dossier, maintenant),
            'preuves': preuves(dossier, lsattr, executer)}
