# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests de acl check et acl apply de Nisaba (modes, ACL, attributs ; tableau A de T012) ;
# dépendances : pytest et bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha.41  2026-11-06  Création (T033, D87, C38, T012).
import io
import os
from pathlib import Path
import stat
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent / 'outils' / 'nisaba'))
from banc_journal import COMPTE, BancJournal  # noqa: E402
from nisaba_outils import requete  # noqa: E402
import server.nisaba.ctl as ctl  # noqa: E402
from server.nisaba import LIGNES_MAX, Nisaba  # noqa: E402

CONTENU = '{"event":"a"}\n'
JOURS = ('2023-11-10', '2023-11-11')


@pytest.fixture
def banc(tmp_path):
    b = BancJournal(tmp_path)
    for jour in JOURS:
        b.relais_ecrire(f'journal-{jour}.jsonl', CONTENU)
    b.nisaba.planificateur.executer('copie')
    for jour in JOURS:
        b.nisaba.planificateur.executer('scellement', jour=jour)
    b.vider_appels()
    b.sortie.truncate(0)
    b.sortie.seek(0)
    return b


def mode(chemin):
    return stat.S_IMODE(os.stat(chemin).st_mode)


def verifier(banc):
    rep = banc.nisaba._traiter(requete('nisaba/acl/check'), True)
    assert rep['ok'] is True
    return rep['data']


def appliquer(banc):
    return banc.nisaba._traiter(requete('nisaba/acl/apply'), True)


def conformer(banc):
    """État conforme : racine posée par apply, le reste vient de la copie et du scellement."""
    rep = appliquer(banc)
    assert rep['ok'] and rep['data']['code'] == 0, rep
    banc.vider_appels()
    assert verifier(banc)['code'] == 0
    banc.vider_appels()


def outils_appeles(banc):
    return {nom for nom, _ in banc.appels() if nom != 'ENV'}


# -- check ----------------------------------------------------------------------------------------
def test_nisaba_acl_check_conforme_sans_ecriture(banc):
    appliquer(banc)
    banc.vider_appels()
    donnees = verifier(banc)
    assert donnees['code'] == 0 and donnees['lignes'][-1] == 'RÉSULTAT : conforme'
    assert all(not ligne.startswith('ERREUR') for ligne in donnees['lignes'])
    assert outils_appeles(banc) <= {'ENV', 'getfacl', 'lsattr'}           # lecture seule ; pas de runuser (N9)
    assert 'runuser' not in (banc.etat_outils / 'appels.log').read_text()


def test_nisaba_acl_check_cas_du_tableau(banc):
    d = banc.journal
    # Racine jamais posée : entrées manquantes.
    donnees = verifier(banc)
    assert donnees['code'] == 1
    assert any(f'ERREUR entrée ACL manquante « user:{COMPTE}:--x » : {banc.racine}' == l for l in donnees['lignes'])
    conformer(banc)
    journal = d / 'journal-2023-11-10.jsonl'
    # Entrée en trop, famille file640.
    banc.poser_acl(journal, banc.acl(journal) + ',u:autre:r')
    assert f'ERREUR entrée ACL non prévue « user:autre:r-- » : {journal}' in verifier(banc)['lignes']
    banc.poser_acl(journal, banc.acl(journal).replace(',u:autre:r', '').replace('g::r--', 'g::---'))
    assert f'ERREUR entrée ACL manquante « group::r-- » : {journal}' in verifier(banc)['lignes']
    banc.poser_acl(journal, f'u:{COMPTE}:r,g::r--,o::---')
    assert verifier(banc)['code'] == 0
    # Propriétaire.
    banc.nisaba.droits.uid_attendu = os.getuid() + 1
    assert any('ERREUR propriétaire' in l for l in verifier(banc)['lignes'])
    banc.nisaba.droits.uid_attendu = os.getuid()
    # ACL illisible.
    banc.echec('getfacl', 'MANIFEST')
    assert f'ERREUR ACL illisible : {d / "MANIFEST"}' in verifier(banc)['lignes']
    (banc.etat_outils / 'echec-getfacl').unlink()
    # Attributs : MANIFEST a, journal inscrit i, seals/*.txt i.
    for chemin, lettre in ((d / 'MANIFEST', 'a'), (journal, 'i'), (d / 'seals' / '2023-11-11.txt', 'i')):
        banc.poser_attributs(chemin, '')
        assert f'ERREUR attribut {lettre} absent : {chemin}' in verifier(banc)['lignes']
        banc.poser_attributs(chemin, lettre)
    assert verifier(banc)['code'] == 0
    # Journal inscrit absent, attributs illisibles, famille manquante.
    journal.unlink()
    assert f'ERREUR journal inscrit au registre absent : {journal}' in verifier(banc)['lignes']
    journal.write_text(CONTENU)
    banc.echec('lsattr', 'MANIFEST')
    assert f'ERREUR attributs illisibles : {d / "MANIFEST"}' in verifier(banc)['lignes']


def test_nisaba_acl_check_elements_absents(tmp_path):
    banc = BancJournal(tmp_path)
    banc.nisaba.planificateur.executer('copie')
    lignes = verifier(banc)['lignes']
    assert f'OK      MANIFEST absent (pas encore créé) : {banc.journal / "MANIFEST"}' in lignes
    assert f'OK      seals/ absent (pas encore créé) : {banc.journal / "seals"}' in lignes


def test_nisaba_acl_noms_stricts_et_liens(banc):
    d = banc.journal
    ailleurs = banc.base / 'ailleurs'
    ailleurs.write_text('x')
    (d / 'journal-2023-11-09.jsonl').symlink_to(ailleurs)
    (d / 'journal-autre.jsonl').write_text('x')
    (d / 'seals' / 'divers.txt').write_text('x')
    cibles = [chemin for _, chemin in banc.nisaba.droits.cibles()]
    assert str(d / 'journal-2023-11-09.jsonl') not in cibles and str(d / 'journal-autre.jsonl') not in cibles
    assert str(d / 'seals' / 'divers.txt') not in cibles and str(banc.racine) == cibles[0]
    appliquer(banc)
    assert banc.acl(ailleurs) is None and banc.acl(d / 'journal-autre.jsonl') is None


# -- apply ------------------------------------------------------------------------------------
def test_nisaba_acl_apply_et_idempotence(banc):
    d = banc.journal
    journal, manifest = d / 'journal-2023-11-10.jsonl', d / 'MANIFEST'
    journal.chmod(0o644)
    banc.poser_acl(journal, f'u:{COMPTE}:rw,g::rw-,o::r--')
    manifest.chmod(0o666)
    banc.vider_appels()
    rep = appliquer(banc)
    assert rep['data']['code'] == 0 and rep['data']['lignes'][-1] == 'RÉSULTAT : modes et ACL appliqués'
    assert mode(journal) == 0o640 and banc.acl(journal) == f'u:{COMPTE}:r,g::r--,o::---'
    assert mode(manifest) == 0o640 and 'a' in banc.attributs(manifest) and 'i' in banc.attributs(journal)
    assert mode(banc.racine) == 0o710 and banc.acl(banc.racine) == f'u:{COMPTE}:x,g::---,o::---'
    assert f'TRAITE {journal}' in rep['data']['lignes']
    # Un fichier à la fois : -i, (mode), setfacl, +i sans autre chemin entre les deux.
    ouvert = None
    for nom, args in banc.appels():
        if nom == 'chattr' and args[0] in ('-i', '-a'):
            assert ouvert in (None, args[-1])
            ouvert = args[-1]
        elif nom == 'chattr' and args[0] in ('+i', '+a'):
            assert ouvert == args[-1]
            ouvert = None
        elif nom == 'setfacl' and ouvert is not None:
            assert args[-1] == ouvert
    assert ouvert is None
    assert verifier(banc)['code'] == 0
    # Idempotent : un élément conforme n'est pas touché (ni attribut, ni setfacl).
    banc.vider_appels()
    rep = appliquer(banc)
    assert rep['data']['code'] == 0 and 'chattr' not in outils_appeles(banc) and 'setfacl' not in outils_appeles(banc)
    assert not any(l.startswith('TRAITE') for l in rep['data']['lignes'])
    traces = [e['texte'] for e in banc.evenements() if e['event'] == 'acl_apply']
    cibles = banc.nisaba.droits.cibles()
    assert all(t.startswith('INCHANGE') for t in traces[-len(cibles) - 1:-1])        # chaque élément est tracé


def test_nisaba_acl_retablissement_meme_si_setfacl_echoue(banc):
    d = banc.journal
    journal = d / 'journal-2023-11-10.jsonl'
    journal.chmod(0o644)
    banc.echec('setfacl', str(journal))
    rep = appliquer(banc)
    assert rep['data']['code'] == 1 and 'i' in banc.attributs(journal)    # +i rétabli malgré l'échec
    assert any(l.startswith('ECHEC_ACL setfacl_failed: ') for l in rep['data']['lignes'])
    assert any(l.startswith('<3>ECHEC_ACL setfacl_failed: ') for l in banc.sortie_lignes())
    assert rep['data']['lignes'][-1] == 'RÉSULTAT : 1 élément(s) en échec'
    echecs = banc.nisaba.metriques.instantane(banc.nisaba.releve())['echecs']
    assert {'tache': 'acl', 'code': 'ECHEC_ACL', 'n': 1} in echecs
    # Les autres éléments sont traités.
    assert banc.acl(banc.racine) is not None
    # Aucun droit élargi en repli : le mode n'a pas été relâché au-delà de la cible.
    assert mode(journal) == 0o640


def test_nisaba_acl_chmod_echoue_attributs_retablis(banc, monkeypatch):
    d = banc.journal
    journal = d / 'journal-2023-11-10.jsonl'
    journal.chmod(0o644)
    vrai = os.chmod

    def chmod(chemin, *a, **k):
        if str(chemin) == str(journal):
            raise PermissionError
        return vrai(chemin, *a, **k)

    monkeypatch.setattr('server.nisaba.droits.os.chmod', chmod)
    rep = appliquer(banc)
    assert rep['data']['code'] == 1 and 'i' in banc.attributs(journal)
    assert f'ECHEC_ACL chmod_failed: {journal}' in rep['data']['lignes']
    assert mode(journal) == 0o644                                         # rien n'est modifié ni élargi


def test_nisaba_acl_arret_si_retablissement_echoue(banc):
    d = banc.journal
    journal = d / 'journal-2023-11-10.jsonl'
    journal.chmod(0o644)
    banc.echec('chattr', '+i')                                            # -i passe, +i échoue
    manifest = d / 'MANIFEST'
    manifest.chmod(0o666)
    rep = appliquer(banc)
    assert rep['data']['code'] == 1
    lignes = rep['data']['lignes']
    assert any(l.startswith('ECHEC_ACL restore_failed: ') for l in lignes)
    assert lignes[-1].startswith('ARRÊT : rétablissement d\'attribut impossible sur ')
    assert mode(manifest) == 0o666                                        # aucun autre fichier n'est traité
    assert not any(l.startswith('RÉSULTAT') for l in lignes)


def test_nisaba_acl_exception_retablit_les_attributs(banc):
    d = banc.journal
    journal = d / 'journal-2023-11-10.jsonl'
    journal.chmod(0o644)
    reel = banc.nisaba.droits.lancer

    def lancer(argv, delai=10):
        if argv[1:2] == ['-b']:
            raise KeyboardInterrupt
        return reel(argv, delai)

    banc.nisaba.droits.lancer = lancer
    with pytest.raises(KeyboardInterrupt):
        appliquer(banc)
    assert 'i' in banc.attributs(journal)                                 # try/finally : +i rétabli
    # Le verrou des tâches est libéré : une tâche peut repartir.
    assert banc.nisaba.planificateur.executer('copie')['resultat'] == 'ok'


def test_nisaba_acl_refus_pendant_une_tache(banc):
    journal = banc.journal / 'journal-2023-11-10.jsonl'
    journal.chmod(0o644)
    assert banc.nisaba.planificateur._occupe.acquire(blocking=False)      # une tâche est en cours
    try:
        rep = appliquer(banc)
    finally:
        banc.nisaba.planificateur._occupe.release()
    assert rep['ok'] is False and rep['error']['code'] == 'command_busy'
    assert banc.appels() == [] and mode(journal) == 0o644


def test_nisaba_acl_interruption_demandee(banc):
    journal = banc.journal / 'journal-2023-11-10.jsonl'
    journal.chmod(0o644)
    banc.nisaba.planificateur._arret.set()
    rep = appliquer(banc)
    assert rep['data']['code'] == 1 and rep['data']['lignes'][0].startswith('ARRÊT : interruption')
    assert mode(journal) == 0o644 and banc.appels() == []


def test_nisaba_acl_parametres_refuses(banc):
    for action in ('nisaba/acl/check', 'nisaba/acl/apply'):
        rep = banc.nisaba._traiter(requete(action, x=1), True)
        assert rep['ok'] is False and rep['error']['code'] == 'bad_request'
    # Socle seul (sans sections T033) : action indisponible.
    rep = banc.nisaba._traiter(requete('nisaba/acl/check'), False)
    assert rep['error']['code'] == 'unknown_action'


def test_nisaba_acl_reponse_bornee(banc):
    lignes = [f'ERREUR n{i}' for i in range(500)] + ['RÉSULTAT : 500 erreur(s)']
    borne = Nisaba._borner_lignes({'code': 1, 'lignes': lignes})
    assert len(borne['lignes']) == LIGNES_MAX and borne['lignes'][-1] == 'RÉSULTAT : 500 erreur(s)'
    assert borne['lignes'][-2].startswith('… ')


# -- CLI ------------------------------------------------------------------------------------
@pytest.mark.parametrize('code,sortie', [(0, 0), (1, 1)])
def test_nisaba_acl_cli(banc, monkeypatch, code, sortie):
    appels = []

    def appeler(chemin, requete_, delai, *, actions=None):
        appels.append(requete_['action'])
        return {'ok': True, 'data': {'code': code, 'lignes': ['ERREUR x\x1b[31m', 'RÉSULTAT : fin']}}

    monkeypatch.setattr(ctl, 'configuration', lambda argv=None, **_: banc.config)
    monkeypatch.setattr(ctl, 'appeler', appeler)
    for operation in ('check', 'apply'):
        out, err = io.StringIO(), io.StringIO()
        assert ctl.main(['acl', operation], sortie=out, erreur=err) == sortie
        assert 'RÉSULTAT : fin' in out.getvalue() and '\x1b' not in out.getvalue()
        assert ('Opération ACL' in out.getvalue()) == (code == 0)
    assert appels == ['nisaba/acl/check', 'nisaba/acl/apply']
