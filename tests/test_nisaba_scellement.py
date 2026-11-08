# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests du scellement du journal légal par Nisaba (rattrapage, chaînage, immuabilité, échecs, CLI) ;
# dépendances : pytest et bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha.41  2026-11-06  Création (T033, D87, C38, T012).
import hashlib
import os
from pathlib import Path
import stat
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent / 'outils' / 'nisaba'))
sys.path.insert(0, str(Path(__file__).parent))
from banc_journal import CLE, COMPTE, BancJournal  # noqa: E402
from nisaba_outils import requete  # noqa: E402
import server.nisaba.ctl as ctl  # noqa: E402
from server.nisaba.verification import GENESIS, verifier  # noqa: E402
import test_journal_legal_scripts as scripts  # noqa: E402

CONTENU = '{"event":"a"}\n'
SPEC_REGISTRE = f'u:{COMPTE}:r,g::---,o::---'
SPEC_FICHIER = f'u:{COMPTE}:r,g::r--,o::---'


@pytest.fixture
def banc(tmp_path):
    return BancJournal(tmp_path)


def sha(texte):
    return hashlib.sha256(texte.encode()).hexdigest()


def attendu(jours):
    """Calcul indépendant du MANIFEST : jours = [(jour, contenu | None)]."""
    precedent, texte = GENESIS, ''
    for jour, contenu in jours:
        empreinte, taille = ('ABSENT', 0) if contenu is None else (sha(contenu), len(contenu.encode()))
        chaine = sha(f'{precedent} {jour} {empreinte} {taille}')
        texte += f'{jour} {empreinte} {taille} {precedent} {chaine}\n'
        precedent = chaine
    return texte


def sceller(banc, **options):
    return banc.nisaba.planificateur.executer('scellement', **options)


def test_nisaba_scellement_manifest_identique(banc, tmp_path):
    jours = [('2023-11-10', CONTENU), ('2023-11-11', None), ('2023-11-12', '{"event":"b"}\n{"event":"c"}\n')]
    for jour, contenu in jours:
        if contenu is not None:
            banc.relais_ecrire(f'journal-{jour}.jsonl', contenu)
        assert sceller(banc, jour=jour)['resultat'] == 'ok'
    manifest = (banc.journal / 'MANIFEST').read_text()
    assert manifest == attendu(jours)                                     # calcul indépendant
    # Même journal, mêmes octets que journal-legal-seal.sh 1.3.0 (simulacres des scripts).
    (tmp_path / 'scripts').mkdir()
    ancien = scripts.Banc(tmp_path / 'scripts')
    for jour, contenu in jours:
        if contenu is not None:
            (ancien.remote / f'journal-{jour}.jsonl').write_text(contenu)
        res = ancien.lancer('journal-legal-seal.sh', jour)
        assert res.returncode == 0, res.stderr
    assert (ancien.journal / 'MANIFEST').read_bytes() == (banc.journal / 'MANIFEST').read_bytes()
    for jour, _ in jours:
        assert verifier(banc.journal, banc.config['journal']['lsattr'])['erreurs'] == 0
    # Droits : MANIFEST 0600 en ajout seul, journal scellé 0640 + ACL + immuable.
    assert stat.S_IMODE(os.stat(banc.journal / 'MANIFEST').st_mode) == 0o640     # 0600 + ACL : groupe = masque
    assert banc.acl(banc.journal / 'MANIFEST') == SPEC_REGISTRE and 'a' in banc.attributs(banc.journal / 'MANIFEST')
    scelle = banc.journal / 'journal-2023-11-10.jsonl'
    assert stat.S_IMODE(os.stat(scelle).st_mode) == 0o640 and banc.acl(scelle) == SPEC_FICHIER
    assert 'i' in banc.attributs(scelle)
    assert not (banc.journal / 'journal-2023-11-11.jsonl').exists()


def test_nisaba_scellement_deja_scelle(banc):
    banc.relais_ecrire('journal-2023-11-10.jsonl', CONTENU)
    sceller(banc, jour='2023-11-10')
    avant = (banc.journal / 'MANIFEST').read_bytes()
    assert sceller(banc, jour='2023-11-10')['resultat'] == 'ok'
    assert (banc.journal / 'MANIFEST').read_bytes() == avant
    assert any(e['event'] == 'already_sealed' for e in banc.evenements())


def test_nisaba_scellement_rattrapage_sans_trou(banc):
    # Horloge : 2023-11-14 22:13 UTC ; la veille est le 13. Registre vide : départ au plus ancien journal local.
    contenus = {'2023-11-10': CONTENU, '2023-11-12': '{"x":2}\n'}
    for jour, texte in contenus.items():
        banc.relais_ecrire(f'journal-{jour}.jsonl', texte)
    banc.nisaba.planificateur.executer('copie')
    assert sceller(banc) == {'tache': 'scellement', 'resultat': 'ok', 'echecs': 0}
    jours = [('2023-11-10', CONTENU), ('2023-11-11', None), ('2023-11-12', '{"x":2}\n'), ('2023-11-13', None)]
    assert (banc.journal / 'MANIFEST').read_text() == attendu(jours)
    # Registre à jour jusqu'à la veille : rien à faire, puis la journée suivante au passage suivant.
    avant = (banc.journal / 'MANIFEST').read_bytes()
    sceller(banc)
    assert (banc.journal / 'MANIFEST').read_bytes() == avant
    assert any(e['event'] == 'nothing_to_seal' for e in banc.evenements())
    banc.horloge.t += 86400
    sceller(banc)
    assert (banc.journal / 'MANIFEST').read_text() == attendu(jours + [('2023-11-14', None)])


def test_nisaba_scellement_registre_vide_sans_journal(banc):
    assert sceller(banc)['resultat'] == 'ok'                              # départ à la veille
    assert (banc.journal / 'MANIFEST').read_text() == attendu([('2023-11-13', None)])


def test_nisaba_scellement_arret_au_premier_echec(banc):
    banc.relais_ecrire('journal-2023-11-11.jsonl', CONTENU)
    banc.relais_ecrire('journal-2023-11-12.jsonl', CONTENU)
    assert sceller(banc, jour='2023-11-10')['resultat'] == 'ok'           # le 10 : ABSENT, sans comparaison
    banc.echec('rsync', '--dry-run')                                      # la comparaison échoue dès le 11
    banc.vider_appels()
    assert sceller(banc) == {'tache': 'scellement', 'resultat': 'echec', 'echecs': 1}
    assert (banc.journal / 'MANIFEST').read_text() == attendu([('2023-11-10', None)])    # le 11 n'est pas inscrit
    assert not (banc.journal / 'journal-2023-11-12.jsonl').exists()       # le 12 n'est même pas tenté
    assert 'ECHEC_SCELLEMENT compare_failed: journal-2023-11-11.jsonl' in banc.sortie_lignes()[0]
    banc.echec('rsync', 'rien-ne-correspond')                             # relais redevenu sain : reprise
    assert sceller(banc)['resultat'] == 'ok'
    texte = (banc.journal / 'MANIFEST').read_text()
    assert [ligne.split()[0] for ligne in texte.splitlines()] == [
        '2023-11-10', '2023-11-11', '2023-11-12', '2023-11-13']


def test_nisaba_scellement_divergence(banc):
    banc.relais_ecrire('journal-2023-11-10.jsonl', 'original\n')
    banc.journal_ecrire('2023-11-10', 'altéré!!\n')                       # copie locale divergente (autre contenu)
    resultat = sceller(banc, jour='2023-11-10')
    assert resultat['resultat'] == 'echec'
    assert not (banc.journal / 'MANIFEST').exists()                       # rien n'est scellé
    assert (banc.journal / 'journal-2023-11-10.jsonl').read_text() == 'altéré!!\n'       # rien n'est écrasé
    assert 'ECHEC_SCELLEMENT differs: journal-2023-11-10.jsonl: >fc.t...... journal-2023-11-10.jsonl' \
        in banc.sortie_lignes()[0]
    assert banc.appels_de('chattr') == []


def test_nisaba_scellement_relais_injoignable_et_fichier_perdu(banc):
    banc.drapeau('injoignable')
    assert sceller(banc, jour='2023-11-10')['resultat'] == 'echec'
    assert 'ECHEC_SCELLEMENT relay_unreachable: 2023-11-10' in banc.sortie_lignes()[0]
    assert not (banc.journal / 'MANIFEST').exists()
    banc.drapeau('injoignable', False)
    banc.journal_ecrire('2023-11-10', CONTENU)                            # existe ici, plus sur le relais
    assert sceller(banc, jour='2023-11-10')['resultat'] == 'echec'
    assert 'local_only: journal-2023-11-10.jsonl' in banc.sortie_lignes()[1]
    assert not (banc.journal / 'MANIFEST').exists()


def test_nisaba_scellement_echec_chattr_et_acl(banc):
    banc.relais_ecrire('journal-2023-11-10.jsonl', CONTENU)
    banc.echec('chattr', '+i')
    resultat = sceller(banc, jour='2023-11-10')
    assert resultat['resultat'] == 'echec'
    assert 'ECHEC_SCELLEMENT chattr_failed: journal-2023-11-10.jsonl (seal recorded in manifest)' \
        in banc.sortie_lignes()[0]
    assert (banc.journal / 'MANIFEST').read_text() == attendu([('2023-11-10', CONTENU)])
    banc.echec('chattr')                                                  # chattr +a en échec : sans effet (script)
    banc.relais_ecrire('journal-2023-11-11.jsonl', CONTENU)
    banc.echec('setfacl')
    resultat = sceller(banc, jour='2023-11-11')
    assert resultat['echecs'] >= 1                                        # ECHEC_ACL, scellement tout de même fait
    assert 'ECHEC_ACL' in ''.join(banc.sortie_lignes())


def test_nisaba_scellement_manifest_invalide(banc):
    (banc.journal / 'MANIFEST').write_text('pas une ligne\n')
    banc.relais_ecrire('journal-2023-11-10.jsonl', CONTENU)
    assert sceller(banc, jour='2023-11-10')['resultat'] == 'echec'
    assert (banc.journal / 'MANIFEST').read_text() == 'pas une ligne\n'


def test_nisaba_scellement_secret_non_affiche(banc):
    banc.relais_ecrire('journal-2023-11-10.jsonl', CONTENU)
    banc.echec('rsync', erreur=f'Identity file {CLE} not accessible')
    sceller(banc, jour='2023-11-10')
    sortie = banc.sortie.getvalue() + banc.flux.getvalue()
    assert CLE not in sortie
    for appel in banc.appels_de('rsync'):
        assert all(isinstance(a, str) for a in appel)


@pytest.mark.parametrize('params', [
    {'task': 'scellement', 'day': '2023-11-14'},        # pas encore terminée (UTC)
    {'task': 'scellement', 'day': '2023-11-15'},
    {'task': 'scellement', 'day': '2023-13-01'},
    {'task': 'scellement', 'day': '2023-11-1'},
    {'task': 'scellement', 'day': 20231110},
    {'task': 'scellement', 'day': '2023-11-10', 'x': 1},
    {'task': 'copie', 'day': '2023-11-10'},
    {'day': '2023-11-10'}])
def test_nisaba_scellement_requete_invalide(banc, params):
    q = requete('nisaba/job/run', **params)
    reponse = banc.nisaba._traiter(q, True)
    assert reponse['ok'] is False and reponse['error']['code'] == 'bad_request'
    assert not (banc.journal / 'MANIFEST').exists() and banc.appels() == []


def test_nisaba_scellement_requete_valide(banc):
    banc.relais_ecrire('journal-2023-11-10.jsonl', CONTENU)
    reponse = banc.nisaba._traiter(requete('nisaba/job/run', task='scellement', day='2023-11-10'), True)
    assert reponse['ok'] is True and reponse['data']['resultat'] == 'ok'
    assert (banc.journal / 'MANIFEST').read_text() == attendu([('2023-11-10', CONTENU)])
    # L'horodatage suit le scellement (chaîné) : la copie de la ligne est faite.
    assert (banc.journal / 'seals' / '2023-11-10.txt').read_text() == attendu([('2023-11-10', CONTENU)]).strip()


def test_nisaba_scellement_cli(banc, monkeypatch):
    monkeypatch.setattr(ctl, 'configuration', lambda argv=None, **_: banc.config)
    assert ctl._analyser(['run', 'scellement', '2023-11-10']) == ('run', ['scellement', '2023-11-10'], None)
    for invalide in (['run', 'copie', '2023-11-10'], ['run', 'scellement', 'hier'], ['run', 'scellement', '1', '2']):
        assert ctl._analyser(invalide) is None


def test_nisaba_scellement_rattrapage_identique_aux_scripts(banc, tmp_path):
    # Rattrapage sans argument, jours ABSENT intercalés : MANIFEST identique, octet pour octet, aux scripts.
    contenus = {'2023-11-10': CONTENU, '2023-11-12': '{"x":2}\n'}
    for jour, texte in contenus.items():
        banc.relais_ecrire(f'journal-{jour}.jsonl', texte)
    banc.nisaba.planificateur.executer('copie')
    assert sceller(banc)['resultat'] == 'ok'
    (tmp_path / 'scripts').mkdir()
    ancien = scripts.Banc(tmp_path / 'scripts')
    for jour in ('2023-11-10', '2023-11-11', '2023-11-12', '2023-11-13'):
        if jour in contenus:
            (ancien.remote / f'journal-{jour}.jsonl').write_text(contenus[jour])
        res = ancien.lancer('journal-legal-seal.sh', jour)
        assert res.returncode == 0, res.stderr
    manifest = (banc.journal / 'MANIFEST').read_bytes()
    assert manifest == (ancien.journal / 'MANIFEST').read_bytes()
    assert manifest.count(b' ABSENT 0 ') == 2


def test_nisaba_scellement_reprise_apres_inscription_sans_immuabilite(banc):
    # Interruption entre l'ajout au MANIFEST et chattr +i : le passage suivant ne réécrit pas le MANIFEST
    # (comme journal-legal-seal.sh : « déjà scellée »). L'immuabilité manquante reste détectée par acl check.
    banc.relais_ecrire('journal-2023-11-10.jsonl', CONTENU)
    banc.echec('chattr', '+i')
    assert sceller(banc, jour='2023-11-10')['resultat'] == 'echec'
    journal = banc.journal / 'journal-2023-11-10.jsonl'
    assert 'i' not in banc.attributs(journal)
    avant = (banc.journal / 'MANIFEST').read_bytes()
    (banc.etat_outils / 'echec-chattr').unlink()                          # panne levée
    assert sceller(banc, jour='2023-11-10')['resultat'] == 'ok'
    assert (banc.journal / 'MANIFEST').read_bytes() == avant == attendu([('2023-11-10', CONTENU)]).encode()
    assert any(e['event'] == 'already_sealed' for e in banc.evenements())
