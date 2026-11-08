# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests de la copie du journal légal par Nisaba, des commandes externes et de l'absence de données réelles ;
# dépendances : pytest et bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha.41  2026-11-06  Création (T033, D87, C38, T012).
import os
from pathlib import Path
import re
import stat
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent / 'outils' / 'nisaba'))
from banc_journal import CLE, COMPTE, SOURCE, BancJournal  # noqa: E402
from nisaba_outils import registre  # noqa: E402
from server.nisaba import Nisaba  # noqa: E402
from server.nisaba.commandes import lancer  # noqa: E402

RACINE = Path(__file__).resolve().parents[1]
SPEC_FICHIER = f'u:{COMPTE}:r,g::r--,o::---'
SPEC_DOSSIER = f'u:{COMPTE}:rx,g::---,o::---,d:u::rwx,d:u:{COMPTE}:r,d:g::---,d:o::---'


@pytest.fixture
def banc(tmp_path):
    return BancJournal(tmp_path)


def mode(chemin):
    return stat.S_IMODE(os.stat(chemin).st_mode)


def executer(banc, nom='copie'):
    return banc.nisaba.planificateur.executer(nom)


def test_nisaba_copie(banc):
    banc.relais_ecrire('journal-2023-11-13.jsonl', '{"a":1}\n')
    banc.relais_ecrire('journal-2023-11-14.jsonl', '{"b":2}\n')
    banc.relais_ecrire('journal-x.jsonl', 'hors expression\n')          # copié par rsync, jamais retouché
    assert executer(banc) == {'tache': 'copie', 'resultat': 'ok', 'echecs': 0}
    d = banc.journal
    assert (d / 'journal-2023-11-13.jsonl').read_text() == '{"a":1}\n'
    for nom in ('journal-2023-11-13.jsonl', 'journal-2023-11-14.jsonl'):
        assert mode(d / nom) == 0o640 and banc.acl(d / nom) == SPEC_FICHIER
    assert mode(d) == 0o750 and banc.acl(d) == SPEC_DOSSIER      # avec une ACL, le groupe affiché est le masque (acl(5))
    assert banc.acl(d / 'journal-x.jsonl') is None
    # Même commande rsync que pull 1.2.1 : récursif, dates, ajout seul, filtres, jamais --delete.
    argv = banc.appels_de('rsync')[0]
    assert argv[:6] == ['--recursive', '--times', '--append', '--include=journal-*.jsonl', '--exclude=*',
                        '--timeout=50']
    assert '--delete' not in argv and argv[6] == '-e'
    assert argv[7] == (f'{banc.bin}/ssh -i {CLE} -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=20')
    assert argv[8:] == [SOURCE, f'{d}/']


def test_nisaba_copie_ajout_seul_et_immuable_ignore(banc):
    d = banc.journal
    banc.relais_ecrire('journal-2023-11-13.jsonl', 'ligne1\n')
    executer(banc)
    scelle = d / 'journal-2023-11-13.jsonl'
    banc.poser_attributs(scelle, 'i')
    banc.vider_appels()
    banc.relais_ecrire('journal-2023-11-13.jsonl', 'ligne1\nligne2\n')
    assert executer(banc)['resultat'] == 'ok'
    assert scelle.read_text() == 'ligne1\nligne2\n'                      # --append : seules les nouvelles lignes
    assert all(a[-1] != str(scelle) for a in banc.appels_de('setfacl'))   # immuable : ni mode ni ACL


def test_nisaba_copie_liens_ignores(banc):
    d = banc.journal
    cible = banc.base / 'ailleurs'
    cible.write_text('x')
    cible.chmod(0o600)
    (d / 'journal-2023-11-12.jsonl').symlink_to(cible)
    banc.relais_ecrire('journal-2023-11-13.jsonl', 'a\n')
    executer(banc)
    assert mode(cible) == 0o600 and banc.acl(cible) is None
    assert all(a[-1] != str(d / 'journal-2023-11-12.jsonl') for a in banc.appels_de('setfacl'))


def test_nisaba_copie_echec_filtre(banc):
    banc.relais_ecrire('journal-2023-11-13.jsonl', 'a\n')
    banc.echec('rsync', erreur=f'avis \x1b[31m rouge {CLE} inaccessible\n' + 'x' * 400)
    assert executer(banc) == {'tache': 'copie', 'resultat': 'echec', 'echecs': 1}
    ligne = banc.sortie_lignes()[0]
    assert ligne.startswith('<3>ECHEC_COPIE avis ') and '\x1b' not in ligne and CLE not in ligne
    assert '[cle]' in ligne and len(ligne) <= len('<3>ECHEC_COPIE ') + 200
    assert banc.appels_de('setfacl') == []                               # échec : pas de droits (comme pull)
    entree = banc.nisaba.anneau.entrees('copie')[0]
    assert entree['code'] == 'ECHEC_COPIE' and '\x1b' not in entree['texte']


def test_nisaba_copie_relais_injoignable(banc):
    banc.drapeau('injoignable')
    assert executer(banc)['resultat'] == 'echec'
    assert 'ECHEC_COPIE ssh: connexion impossible' in banc.sortie_lignes()[0]


def test_nisaba_echec_acl(banc):
    d = banc.journal
    banc.relais_ecrire('journal-2023-11-13.jsonl', 'a\n')
    banc.relais_ecrire('journal-2023-11-14.jsonl', 'b\n')
    banc.echec('setfacl', 'journal-2023-11-13')
    resultat = executer(banc)
    assert resultat['resultat'] == 'echec' and resultat['echecs'] == 1   # la tâche se termine
    lignes = banc.sortie_lignes()
    assert len(lignes) == 1 and lignes[0].startswith('<3>ECHEC_ACL setfacl_failed: ')
    assert banc.acl(d / 'journal-2023-11-14.jsonl') == SPEC_FICHIER       # la copie des droits continue
    assert banc.acl(d / 'journal-2023-11-13.jsonl') is None
    assert mode(d / 'journal-2023-11-13.jsonl') == 0o640                  # aucun droit élargi : jamais 0644
    assert banc.nisaba.anneau.entrees('copie')[0]['code'] == 'ECHEC_ACL'


def test_nisaba_ordre_droits(banc, monkeypatch):
    """Sur chaque chemin : chmod, puis setfacl, puis (scellement) chattr ; jamais l'inverse."""
    vrai = os.chmod

    def chmod(chemin, mode_, *a, **k):
        banc.etat_outils.joinpath('appels.log').open('a').write(f'chmod\t{chemin}\n')
        return vrai(chemin, mode_, *a, **k)

    monkeypatch.setattr('server.nisaba.droits.os.chmod', chmod)
    banc.relais_ecrire('journal-2023-11-13.jsonl', 'a\n')
    executer(banc, 'copie')
    executer(banc, 'scellement')
    suites = {}
    for nom, args in banc.appels():
        if nom in ('chmod', 'setfacl', 'chattr'):
            chemin = args[-1]
            operation = nom if nom != 'chattr' else 'chattr' + args[0]
            suites.setdefault(chemin, []).append(operation)
    assert str(banc.journal) in suites and len(suites) >= 4   # dossier, journal, MANIFEST, seals/ et ses fichiers
    for chemin, operations in suites.items():
        for i, operation in enumerate(operations):
            if operation == 'chmod':                     # un chmod est toujours suivi de son setfacl
                assert operations[i + 1:i + 2] == ['setfacl'], (chemin, operations)
            if operation.startswith('chattr'):           # plus aucune modification de mode ni d'ACL ensuite
                assert not {'chmod', 'setfacl'} & set(operations[i + 1:]), (chemin, operations)
    manifest = suites[str(banc.journal / 'MANIFEST')]
    assert manifest == ['chmod', 'setfacl', 'chattr+a']
    assert suites[str(banc.journal / 'journal-2023-11-13.jsonl')][-3:] == ['chmod', 'setfacl', 'chattr+i']


def test_nisaba_commandes(banc, tmp_path):
    """Environnement vide hors PATH, argv sans shell, sorties bornées et filtrées, délai."""
    banc.relais_ecrire('journal-2023-11-13.jsonl', 'a\n')
    executer(banc)
    envs = [m for m in (l.split('\t') for l in (banc.etat_outils / 'appels.log').read_text().splitlines())
            if m[0] == 'ENV']
    assert envs and all(set(m[1].split(',')) <= {'PATH', 'LC_CTYPE'} and 'PATH' in m[1] for m in envs)
    # LC_CTYPE est ajouté par l'interpréteur du simulacre (PEP 538), jamais par Nisaba.
    # Programme introuvable ou délai dépassé : code 127.
    assert lancer([str(tmp_path / 'absent')]) == (127, '', '')
    assert lancer(['/bin/sleep', '5'], 0.2).code == 127
    # Aucun shell : un argument est transmis tel quel.
    assert lancer(['/bin/echo', '$HOME; ls']).sortie == '$HOME; ls\n'
    # Erreur standard sur une ligne, 300 caractères, contrôles filtrés.
    r = lancer(['/bin/sh', '-c', "printf 'a\\033[1mb\\n%0400d' 0 >&2"])
    assert '\x1b' not in r.erreur and '\n' not in r.erreur and len(r.erreur) == 300
    for source in (RACINE / 'server' / 'nisaba').glob('*.py'):
        texte = source.read_text(encoding='utf-8')
        assert 'shell=True' not in texte and 'os.system' not in texte and 'os.popen' not in texte


def test_nisaba_sans_donnees_reelles():
    motif_ip = re.compile(r'\b(\d{1,3})\.(\d{1,3})\.\d{1,3}\.\d{1,3}\b')
    fichiers = [*(RACINE / 'server' / 'nisaba').glob('*.py'), *(RACINE / 'tests' / 'outils' / 'nisaba').glob('*'),
                RACINE / 'tests' / 'test_nisaba_copie.py', RACINE / 'tests' / 'test_nisaba_scellement.py',
                RACINE / 'tests' / 'test_nisaba_horodatage.py', RACINE / 'tests' / 'test_nisaba_acl.py']
    sections = re.search(r'^\[nisaba\.source\].*?^# Échecs', (RACINE / 'server/conf/paresia.conf').read_text(),
                         re.M | re.S)
    textes = [(f.name, f.read_text(encoding='utf-8')) for f in fichiers if f.is_file()]
    textes.append(('paresia.conf', sections.group(0)))
    for nom, texte in textes:
        for trouve in motif_ip.finditer(texte):
            if trouve.group(0) in ('127.0.0.1',) or nom == 'nisaba_outils.py':
                continue
            assert trouve.group(0).startswith(('192.0.2.', '198.51.100.', '203.0.113.')), (nom, trouve.group(0))
        assert not re.search('(?i)' + '|'.join(['lap' + '2', 'log' + 'serv', 'opn' + 'sense', 'lap' + 'top',
                                                 'home' + 'lab', 'zo' + 'brak', r'claude\.ai/']), texte), nom
        assert not re.search(r'[A-Za-z0-9]@[A-Za-z0-9.-]+\.(?:com|net|fr|org)\b(?<!example\.org)', texte), nom
