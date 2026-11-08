# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests de l'horodatage OpenTimestamps du journal légal par Nisaba ; dépendances : pytest et bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha.41  2026-11-06  Création (T033, D87, C38, T012).
import os
from pathlib import Path
import stat
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent / 'outils' / 'nisaba'))
from banc_journal import COMPTE, BancJournal  # noqa: E402
from nisaba_outils import GENESIS, sha  # noqa: E402

SPEC_PRIVE = f'u:{COMPTE}:r,g::---,o::---'


@pytest.fixture
def banc(tmp_path):
    return BancJournal(tmp_path)


def inscrire(banc, *jours):
    """MANIFEST cohérent sans passer par le scellement ; renvoie les lignes."""
    precedent, lignes = GENESIS, []
    for jour in jours:
        chaine = sha(f'{precedent} {jour} ABSENT 0')
        lignes.append(f'{jour} ABSENT 0 {precedent} {chaine}')
        precedent = chaine
    (banc.journal / 'MANIFEST').write_text('\n'.join(lignes) + '\n')
    return lignes


def horodater(banc):
    return banc.nisaba.planificateur.executer('horodatage')


def mode(chemin):
    return stat.S_IMODE(os.stat(chemin).st_mode)


def test_nisaba_horodatage_soumission(banc):
    ligne, = inscrire(banc, '2023-11-12')
    assert horodater(banc) == {'tache': 'horodatage', 'resultat': 'ok', 'echecs': 0}
    seals = banc.journal / 'seals'
    assert mode(seals) == 0o750 and banc.acl(seals) == (
        f'u:{COMPTE}:rx,g::---,o::---,d:u::rwx,d:u:{COMPTE}:r,d:g::---,d:o::---')
    copie = seals / '2023-11-12.txt'
    assert copie.read_text() == ligne                                    # copie exacte, sans saut de ligne
    assert mode(copie) == 0o640 and banc.acl(copie) == SPEC_PRIVE and 'i' in banc.attributs(copie)
    preuve = seals / '2023-11-12.txt.ots'
    assert preuve.exists() and mode(preuve) == 0o640 and banc.acl(preuve) == SPEC_PRIVE
    assert banc.appels_de('ots') == [['stamp', str(copie)]]
    assert 'i' not in banc.attributs(preuve)                             # en attente
    assert any(e['event'] == 'timestamp_submitted' for e in banc.evenements())


def test_nisaba_horodatage_mise_a_jour_et_ancrage(banc):
    inscrire(banc, '2023-11-13')
    horodater(banc)
    preuve = banc.journal / 'seals' / '2023-11-13.txt.ots'
    (banc.journal / 'seals' / '2023-11-13.txt.ots.bak').write_text('ancienne')
    banc.vider_appels()
    # Preuve encore en attente (récente) : essai de mise à jour, aucun échec, aucun .bak conservé.
    assert horodater(banc)['resultat'] == 'ok'
    assert banc.appels_de('ots') == [['upgrade', str(preuve)]]
    assert not preuve.with_name(preuve.name + '.bak').exists() and 'i' not in banc.attributs(preuve)
    # Ancrage : preuve réécrite, mode 0600 + ACL, puis immuable.
    banc.drapeau('ancrage')
    preuve.chmod(0o644)
    assert horodater(banc)['resultat'] == 'ok'
    assert preuve.read_text() == 'ANCREE\n' and mode(preuve) == 0o640 and banc.acl(preuve) == SPEC_PRIVE
    assert 'i' in banc.attributs(preuve) and not preuve.with_name(preuve.name + '.bak').exists()
    assert any(e['event'] == 'timestamp_anchored' for e in banc.evenements())
    # Ancrée : plus rien à faire.
    banc.vider_appels()
    horodater(banc)
    assert banc.appels_de('ots') == []


def test_nisaba_horodatage_preuve_en_retard(banc):
    inscrire(banc, '2023-11-10', '2023-11-11')       # aujourd'hui 2023-11-14 ; limite = 2023-11-11 (3 jours)
    horodater(banc)
    assert horodater(banc) == {'tache': 'horodatage', 'resultat': 'echec', 'echecs': 1}
    lignes = banc.sortie_lignes()
    assert lignes == ['<4>ECHEC_HORODATAGE proof_incomplete: 2023-11-10 (after 3 days)']
    assert banc.nisaba.anneau.entrees('horodatage')[0]['code'] == 'ECHEC_HORODATAGE'


def test_nisaba_horodatage_echec_soumission(banc):
    inscrire(banc, '2023-11-13')
    banc.echec('ots', 'stamp')
    assert horodater(banc)['resultat'] == 'echec'
    assert banc.sortie_lignes() == ['<4>ECHEC_HORODATAGE submit_failed: 2023-11-13']
    assert not (banc.journal / 'seals' / '2023-11-13.txt.ots').exists()
    banc.echec('ots', 'rien')
    assert horodater(banc)['resultat'] == 'ok'                          # nouvel essai au passage suivant
    assert (banc.journal / 'seals' / '2023-11-13.txt.ots').exists()


def test_nisaba_horodatage_echec_n_empeche_pas_le_scellement(banc):
    banc.relais_ecrire('journal-2023-11-10.jsonl', '{"a":1}\n')
    banc.echec('ots')
    resultat = banc.nisaba.planificateur.executer('scellement', jour='2023-11-10')
    assert resultat == {'tache': 'scellement', 'resultat': 'ok', 'echecs': 0}
    assert (banc.journal / 'MANIFEST').read_text().startswith('2023-11-10 ')
    etat = banc.nisaba.planificateur.etat()
    assert etat['scellement']['resultat'] == 'ok' and etat['horodatage']['resultat'] == 'echec'
    assert etat['horodatage']['prochaine'] is None                       # tâche enchaînée, sans horaire propre
    assert [e['code'] for e in banc.nisaba.anneau.entrees('horodatage')] == ['ECHEC_HORODATAGE']
    assert banc.nisaba.anneau.entrees('scellement') == []


def test_nisaba_horodatage_client_absent(banc, tmp_path):
    inscrire(banc, '2023-11-13')
    (banc.bin / 'ots').unlink()
    assert horodater(banc)['resultat'] == 'echec'
    assert banc.sortie_lignes() == ['<4>ECHEC_HORODATAGE ots_missing']
    assert not (banc.journal / 'seals').exists()


def test_nisaba_horodatage_registre_vide_ou_absent(banc):
    assert horodater(banc)['resultat'] == 'ok'
    (banc.journal / 'MANIFEST').write_text('')
    assert horodater(banc)['resultat'] == 'ok'
    assert banc.appels() == [] and not (banc.journal / 'seals').exists()


def test_nisaba_horodatage_echec_acl_apres_ancrage(banc):
    inscrire(banc, '2023-11-13')
    horodater(banc)
    banc.drapeau('ancrage')
    banc.echec('setfacl', '.ots')
    assert horodater(banc) == {'tache': 'horodatage', 'resultat': 'echec', 'echecs': 1}
    assert banc.sortie_lignes()[0].startswith('<3>ECHEC_ACL setfacl_failed: ')
    assert 'i' in banc.attributs(banc.journal / 'seals' / '2023-11-13.txt.ots')     # ancrée malgré tout


def test_nisaba_horodatage_ligne_invalide_et_liens(banc):
    ligne, = inscrire(banc, '2023-11-13')
    with open(banc.journal / 'MANIFEST', 'a') as f:
        f.write('2023-13-45 ABSENT 0 x y\nn-importe-quoi\n')
    seals = banc.journal / 'seals'
    seals.mkdir()
    ailleurs = banc.base / 'ailleurs'
    ailleurs.write_text('x')
    (seals / '2023-11-13.txt').symlink_to(ailleurs)                      # lien : jamais suivi ni modifié
    assert horodater(banc)['echecs'] == 2                                # deux lignes invalides
    assert ailleurs.read_text() == 'x' and banc.acl(ailleurs) is None
    assert banc.appels_de('ots') == []
