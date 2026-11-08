# SPDX-License-Identifier: AGPL-3.0-or-later
# Outils communs aux tests de Nisaba ; dépendances : bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha.40  2026-11-06  Banc de test de Nisaba (T031).
import hashlib
import io
import os
from pathlib import Path
import secrets
import tempfile

from server.commun.client import appeler as appeler_client
from server.commun.journal import Journal
from server.nisaba import Nisaba

GENESIS = '0' * 64
LSATTR = str(Path(__file__).resolve().parent / 'lsattr')
BASE = 1_700_000_000.0          # 2023-11-14 22:13:20 UTC


class Horloge:
    def __init__(self, t=BASE):
        self.t = t

    def __call__(self):
        return self.t


def configuration(dossier, journal, etat, **horaire):
    dossier = Path(dossier)
    return {
        'socket': {'socket': str(dossier / 'n.sock'), 'uid_romulus': os.getuid(), 'gid': os.getgid(),
                   'delai_s': 5, 'max_line': 65536},
        'ctl': {'socket': str(dossier / 'c.sock'), 'uid': os.getuid()},
        'journal': {'dossier': str(journal), 'compte_acl': 'compte-test', 'lsattr': LSATTR,
                    'chattr': '/chattr-factice'},
        'horaire': {'copie_s': 60, 'scellement': '00:20', 'purge': '03:23', 'conservation_jours': 365,
                    'arret_s': 5, **horaire},
        'etat': {'dossier': str(etat), 'historique': 20},
    }


def journal_capture():
    flux = io.StringIO()
    return Journal('nisaba', flux=flux), flux


def requete(action, **params):
    return {'proto': 'jumeaux/1', 'id': secrets.token_hex(8), 'session': 0, 'action': action, 'params': params}


def appeler(chemin, action, **params):
    return appeler_client(chemin, requete(action, **params), 5)


def dossier_court():
    return tempfile.TemporaryDirectory(prefix='nisaba-')


def sha(texte):
    return hashlib.sha256(texte.encode()).hexdigest()


def registre(dossier, jours, contenus=None):
    """Écrit MANIFEST, journaux et seals/ cohérents ; renvoie la liste des lignes du MANIFEST."""
    dossier = Path(dossier)
    (dossier / 'seals').mkdir(parents=True, exist_ok=True)
    precedent, lignes = GENESIS, []
    for jour in jours:
        texte = (contenus or {}).get(jour, f'{{"jour":"{jour}"}}\n')
        if texte is None:
            empreinte, taille = 'ABSENT', 0
        else:
            (dossier / f'journal-{jour}.jsonl').write_text(texte)
            empreinte, taille = hashlib.sha256(texte.encode()).hexdigest(), len(texte.encode())
        chaine = sha(f'{precedent} {jour} {empreinte} {taille}')
        ligne = f'{jour} {empreinte} {taille} {precedent} {chaine}'
        (dossier / 'seals' / f'{jour}.txt').write_text(ligne + '\n')
        lignes.append(ligne)
        precedent = chaine
    (dossier / 'MANIFEST').write_text('\n'.join(lignes) + '\n')
    return lignes


def monter(tmp_path, dossier_socket=None, **horaire):
    """Nisaba non démarré, horloge fictive, sortie et journal capturés."""
    journal, etat = Path(tmp_path) / 'journal', Path(tmp_path) / 'etat'
    journal.mkdir(exist_ok=True)
    etat.mkdir(exist_ok=True)
    capture, flux = journal_capture()
    sortie = io.StringIO()
    horloge = Horloge()
    n = Nisaba(configuration(dossier_socket or tmp_path, journal, etat, **horaire),
               horloge=horloge, journal=capture, sortie=sortie)
    return n, journal, etat, horloge, sortie, flux
