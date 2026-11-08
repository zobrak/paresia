# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests de la vérification du MANIFEST par Nisaba ; dépendances : pytest et bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha.40  2026-11-06  Création (T031) : mêmes libellés que journal-legal-seal.sh 1.3.0.
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent / 'outils' / 'nisaba'))
from nisaba_outils import LSATTR, registre  # noqa: E402
from server.nisaba.verification import verifier  # noqa: E402

JOURS = ['2026-01-01', '2026-01-02', '2026-01-03']
ROOT = pytest.mark.skipif(os.geteuid() == 0, reason='les droits de lecture ne s’appliquent pas à root')


def lancer(dossier):
    return verifier(dossier, LSATTR)


def test_nisaba_verification_integre(tmp_path):
    registre(tmp_path, JOURS, {'2026-01-02': None})
    r = lancer(tmp_path)
    assert r == {'ok': True, 'erreurs': 0, 'journees': 3, 'lignes': [
        'OK      2026-01-01  fichier et chaîne intègres',
        'OK      2026-01-02  aucune publication ce jour-là',
        'OK      2026-01-03  fichier et chaîne intègres',
        'RÉSULTAT : registre intègre (3 journées)']}


def test_nisaba_verification_registre_vide_ou_absent(tmp_path):
    r = lancer(tmp_path)
    assert r['ok'] and r['journees'] == 0 and r['lignes'] == [f'registre vide ou absent : {tmp_path}/MANIFEST']


def test_nisaba_verification_chaine_rompue(tmp_path):
    lignes = registre(tmp_path, JOURS)
    (tmp_path / 'MANIFEST').write_text('\n'.join([lignes[0], lignes[2]]) + '\n')
    r = lancer(tmp_path)
    assert not r['ok'] and any('chaîne rompue' in ligne for ligne in r['lignes'])
    assert r['lignes'][-1] == f'RÉSULTAT : {r["erreurs"]} erreur(s)'


def test_nisaba_verification_ligne_modifiee(tmp_path):
    lignes = registre(tmp_path, JOURS)
    champs = lignes[1].split(' ')
    champs[2] = '999'
    (tmp_path / 'MANIFEST').write_text('\n'.join([lignes[0], ' '.join(champs), lignes[2]]) + '\n')
    r = lancer(tmp_path)
    assert not r['ok']
    assert any('ligne 2 (2026-01-02) : ligne du registre modifiée' in ligne for ligne in r['lignes'])
    assert any('la copie horodatée seals/2026-01-02.txt ne correspond pas' in ligne for ligne in r['lignes'])


def test_nisaba_verification_fichier_modifie(tmp_path):
    registre(tmp_path, JOURS)
    (tmp_path / 'journal-2026-01-01.jsonl').write_text('altéré\n')
    r = lancer(tmp_path)
    assert r['erreurs'] == 1
    assert 'ERREUR ligne 1 (2026-01-01) : fichier modifié depuis le scellement' in r['lignes']


def test_nisaba_verification_fichier_purge(tmp_path):
    registre(tmp_path, JOURS)
    (tmp_path / 'journal-2026-01-01.jsonl').unlink()
    r = lancer(tmp_path)
    assert r['ok'] and 'OK      2026-01-01  chaîne intègre (fichier purgé)' in r['lignes']


@ROOT
def test_nisaba_verification_fichier_illisible(tmp_path):
    registre(tmp_path, JOURS)
    fichier = tmp_path / 'journal-2026-01-03.jsonl'
    fichier.chmod(0)
    r = lancer(tmp_path)
    fichier.chmod(0o600)
    assert not r['ok'] and r['erreurs'] == 1
    assert any('lecture impossible de' in ligne and 'droits ou ACL manquants' in ligne for ligne in r['lignes'])
    assert not any('modifié' in ligne for ligne in r['lignes'])


@ROOT
def test_nisaba_verification_manifest_illisible(tmp_path):
    registre(tmp_path, JOURS)
    (tmp_path / 'MANIFEST').chmod(0)
    r = lancer(tmp_path)
    (tmp_path / 'MANIFEST').chmod(0o600)
    assert r['lignes'] == [f'ERREUR lecture impossible : {tmp_path}/MANIFEST (droits ou ACL manquants)',
                           'RÉSULTAT : 1 erreur(s)'] and not r['ok']


def test_nisaba_verification_ancrage_lsattr_simule(tmp_path):
    registre(tmp_path, JOURS)
    (tmp_path / 'seals' / '2026-01-01.txt.ots').write_bytes(b'ots')
    (tmp_path / 'seals' / '2026-01-01.txt.ots').chmod(0o444)       # simulacre : immuable
    (tmp_path / 'seals' / '2026-01-02.txt.ots').write_bytes(b'ots')
    r = lancer(tmp_path)
    assert r['ok']
    assert 'OK      2026-01-01  fichier et chaîne intègres ; horodatage ancré' in r['lignes']
    assert 'OK      2026-01-02  fichier et chaîne intègres ; horodatage en attente' in r['lignes']
    assert 'OK      2026-01-03  fichier et chaîne intègres' in r['lignes']


def test_nisaba_verification_attributs_illisibles(tmp_path):
    registre(tmp_path, JOURS[:1])
    (tmp_path / 'seals' / '2026-01-01.txt.ots').write_bytes(b'ots')
    r = verifier(tmp_path, LSATTR, executer=lambda argv: (1, ''))
    assert not r['ok']
    assert any('attributs illisibles pour seals/2026-01-01.txt.ots' in ligne for ligne in r['lignes'])


def test_nisaba_verification_argv_sans_shell(tmp_path):
    registre(tmp_path, JOURS[:1])
    (tmp_path / 'seals' / '2026-01-01.txt.ots').write_bytes(b'ots')
    appels = []
    verifier(tmp_path, '/outil/lsattr', executer=lambda argv: appels.append(argv) or (0, '--------------e--- x'))
    assert appels == [['/outil/lsattr', '-d', '--', str(tmp_path / 'seals' / '2026-01-01.txt.ots')]]


def test_nisaba_verification_ligne_illisible_et_lien(tmp_path):
    registre(tmp_path, JOURS[:1])
    with open(tmp_path / 'MANIFEST', 'a') as f:
        f.write('n importe quoi\x1b[31m\n')
    r = lancer(tmp_path)
    assert not r['ok'] and 'ERREUR ligne 2 : ligne du registre illisible' in r['lignes']
    assert all('\x1b' not in ligne for ligne in r['lignes'])
    # Un lien à la place du journal n'est jamais suivi : lecture impossible, pas d'empreinte.
    (tmp_path / 'journal-2026-01-01.jsonl').unlink()
    (tmp_path / 'autre').write_text('{"jour":"2026-01-01"}\n')
    os.symlink(tmp_path / 'autre', tmp_path / 'journal-2026-01-01.jsonl')
    assert any('lecture impossible de' in ligne for ligne in lancer(tmp_path)['lignes'])


def test_nisaba_verification_libelles_script(tmp_path):
    """Les libellés restent ceux de journal-legal-seal.sh 1.3.0 (relevé dans le script livré)."""
    racine = Path(__file__).resolve().parents[1]
    script = (racine / 'deploy/backend-admin/usr/local/sbin/journal-legal-seal.sh').read_text()
    for libelle in ('chaîne rompue (précédent attendu', 'ligne du registre modifiée (empreinte de chaîne incorrecte)',
                    'fichier modifié depuis le scellement', 'chaîne intègre (fichier purgé)',
                    'horodatage ancré', 'horodatage en attente', 'registre vide ou absent',
                    'aucune publication ce jour-là', 'fichier et chaîne intègres', 'registre intègre (',
                    'la copie horodatée seals/', 'attributs illisibles pour seals/'):
        assert libelle in script, libelle
    registre(tmp_path, JOURS)
    source = (racine / 'server/nisaba/verification.py').read_text()
    for libelle in ('chaîne rompue (précédent attendu', 'fichier modifié depuis le scellement',
                    'registre intègre (', 'RÉSULTAT :'):
        assert libelle in source
