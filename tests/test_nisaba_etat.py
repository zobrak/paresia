# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests de l'état de Nisaba et de l'anneau des échecs ; dépendances : pytest et bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha.40  2026-11-06  Création (T031) : nisaba/state/status, anneau persistant de 20 échecs.
import json
import os
from pathlib import Path
import stat
import sys

sys.path.insert(0, str(Path(__file__).parent / 'outils' / 'nisaba'))
from nisaba_outils import LSATTR, Horloge, journal_capture, monter, registre  # noqa: E402
from server.nisaba import Anneau  # noqa: E402


def test_nisaba_etat(tmp_path):
    n, journal, etat, horloge, sortie, _ = monter(tmp_path)
    registre(journal, ['2023-11-10', '2023-11-11', '2023-11-12', '2023-11-13'])
    (journal / 'journal-2023-11-14.jsonl').write_text('{"a":1}\n{"a":2}\n{"a":3}\n')
    (journal / 'seals' / '2023-11-10.txt.ots').write_bytes(b'x')
    (journal / 'seals' / '2023-11-10.txt.ots').chmod(0o444)        # simulacre lsattr : immuable
    (journal / 'seals' / '2023-11-11.txt.ots').write_bytes(b'x')
    n.echec('purge', 'ECHEC_PURGE', 'mauvais\x1b[31m texte\n')
    donnees = n.etat()
    assert set(donnees) == {'demarrage', 'taches', 'journal', 'metriques'}
    assert donnees['demarrage'] == '2023-11-14T22:13:20Z'
    purge = donnees['taches']['purge']
    assert purge['derniere'] is None and purge['resultat'] is None
    assert purge['prochaine'] == '2023-11-15T03:23:00Z'
    assert len(purge['echecs']) == 1 and purge['echecs'][0]['code'] == 'ECHEC_PURGE'
    assert '\x1b' not in purge['echecs'][0]['texte'] and '\n' not in purge['echecs'][0]['texte']
    assert purge['echecs'][0]['heure'] == '2023-11-14T22:13:20Z'
    assert donnees['journal'] == {
        'publications_jour': 3, 'journees': 4, 'derniere_journee': '2023-11-13',
        'age_plus_ancien_s': 4 * 86400 + 22 * 3600 + 13 * 60 + 20,
        'preuves': {'ancrees': 1, 'en_attente': 1, 'non_soumises': 2}}
    assert donnees['metriques']['journees'] == 4
    json.dumps(donnees)
    n.planificateur.executer('purge')
    apres = n.etat()['taches']['purge']
    assert apres['derniere'] == '2023-11-14T22:13:20Z' and apres['resultat'] == 'ok'


def test_nisaba_etat_journal_absent(tmp_path):
    n, journal, *_ = monter(tmp_path)
    donnees = n.etat()['journal']
    assert donnees['publications_jour'] is None and donnees['journees'] == 0
    assert donnees['derniere_journee'] is None and donnees['age_plus_ancien_s'] is None
    assert donnees['preuves'] == {'ancrees': 0, 'en_attente': 0, 'non_soumises': 0}


def anneau(dossier, historique=20, horloge=None):
    capture, flux = journal_capture()
    return Anneau(dossier, historique, journal=capture, horloge=horloge or Horloge()), flux


def test_nisaba_anneau(tmp_path):
    a, flux = anneau(tmp_path)
    a.charger()
    assert 'failure_ring_empty' in flux.getvalue() and a.entrees('purge') == []
    for i in range(25):
        a.ajouter('purge', 'ECHEC_PURGE', f'echec {i}')
    a.ajouter('copie', 'ECHEC_ACL', 'acl')
    entrees = a.entrees('purge')
    assert len(entrees) == 20 and entrees[0]['texte'] == 'echec 5' and entrees[-1]['texte'] == 'echec 24'
    fichier = tmp_path / 'echecs.json'
    assert stat.S_IMODE(fichier.stat().st_mode) == 0o600 and not (tmp_path / 'echecs.json.tmp').exists()
    # Persistant : un nouvel anneau relit le fichier.
    b, _ = anneau(tmp_path)
    b.charger()
    assert b.entrees('purge') == entrees and b.entrees('copie')[0]['code'] == 'ECHEC_ACL'
    # Historique configuré plus petit : seules les plus récentes sont gardées.
    c, _ = anneau(tmp_path, historique=3)
    c.charger()
    assert [e['texte'] for e in c.entrees('purge')] == ['echec 22', 'echec 23', 'echec 24']


def test_nisaba_anneau_corrompu_ou_forge(tmp_path):
    fichier = tmp_path / 'echecs.json'
    for contenu in (b'pas du json', b'[]', b'{"version":2,"taches":{}}', b'{"version":1,"taches":[]}',
                    b'x' * (Anneau.TAILLE_MAX + 1), b'\xff\xfe'):
        fichier.write_bytes(contenu)
        a, flux = anneau(tmp_path)
        a.charger()
        assert all(a.entrees(t) == [] for t in ('copie', 'purge')), contenu[:20]
        assert 'failure_ring_empty' in flux.getvalue() and 'corrupt' in flux.getvalue()
    bon = {'code': 'ECHEC_PURGE', 'texte': 'ok\x1b[0m', 'heure': '2026-01-01T00:00:00Z'}
    forges = [{'code': 'AUTRE', 'texte': 't', 'heure': '2026-01-01T00:00:00Z'},
              {'code': 'ECHEC_PURGE', 'texte': 't', 'heure': 'hier'},
              {'code': 'ECHEC_PURGE', 'texte': 5, 'heure': '2026-01-01T00:00:00Z'},
              {'code': 'ECHEC_PURGE', 'texte': 't', 'heure': '2026-01-01T00:00:00Z', 'extra': 1},
              'texte', None]
    fichier.write_text(json.dumps({'version': 1, 'taches': {'purge': [*forges, bon], 'inconnue': [bon],
                                                            'copie': 'x'}}))
    a, _ = anneau(tmp_path)
    a.charger()
    assert len(a.entrees('purge')) == 1 and '\x1b' not in a.entrees('purge')[0]['texte']
    assert a.entrees('copie') == []


def test_nisaba_anneau_lien_refuse_et_ecriture_echouee(tmp_path):
    cible = tmp_path / 'cible.json'
    cible.write_text('{"version":1,"taches":{}}')
    os.symlink(cible, tmp_path / 'echecs.json')
    a, flux = anneau(tmp_path)
    a.charger()
    assert 'corrupt' in flux.getvalue()
    b, flux = anneau(tmp_path / 'inexistant')
    b.ajouter('purge', 'ECHEC_PURGE', 'texte')          # l'écriture échoue sans lever
    assert 'failure_ring_write_failed' in flux.getvalue() and len(b.entrees('purge')) == 1


def test_nisaba_anneau_taille_bornee(tmp_path):
    a, _ = anneau(tmp_path, historique=40)
    for tache, code in (('copie', 'ECHEC_COPIE'), ('scellement', 'ECHEC_SCELLEMENT'),
                        ('horodatage', 'ECHEC_HORODATAGE'), ('purge', 'ECHEC_PURGE')):
        for _ in range(40):
            a.ajouter(tache, code, '€' * 300)
    assert (tmp_path / 'echecs.json').stat().st_size <= Anneau.TAILLE_MAX


def test_nisaba_preuves_appels_lsattr_bornes(tmp_path):
    from server.nisaba.etat import preuves
    from server.nisaba.verification import executer_externe
    seals = tmp_path / 'seals'
    seals.mkdir()
    for i in range(300):
        jour = f'2022-{1 + i // 28:02d}-{1 + i % 28:02d}'
        (seals / f'{jour}.txt').write_text('x')
        if i % 3:
            ots = seals / f'{jour}.txt.ots'
            ots.write_bytes(b'x')
            ots.chmod(0o444 if i % 3 == 1 else 0o644)       # simulacre lsattr : 444 = immuable
    appels = []

    def executer(argv):
        appels.append(argv)
        assert argv[:3] == [LSATTR, '-d', '--']
        return executer_externe(argv)

    compte = preuves(tmp_path, LSATTR, executer)
    assert compte == {'ancrees': 100, 'en_attente': 100, 'non_soumises': 100}
    assert 1 <= len(appels) <= 20                                    # 200 fichiers .ots, jamais un appel par fichier
    assert sum(len(argv) - 3 for argv in appels) == 200 and all(len(argv) - 3 <= 64 for argv in appels)


def test_nisaba_fichiers_non_ordinaires_sans_blocage(tmp_path):
    from server.nisaba.etat import publications, registre as lire_registre
    from server.nisaba.verification import verifier
    registre(tmp_path, ['2023-11-13'])
    os.unlink(tmp_path / 'MANIFEST')
    os.mkfifo(tmp_path / 'MANIFEST')
    assert lire_registre(tmp_path) == (0, None)
    r = verifier(tmp_path, LSATTR)
    assert not r['ok'] and 'lecture impossible' in r['lignes'][0]
    os.mkfifo(tmp_path / 'journal-2023-11-14.jsonl')
    assert publications(tmp_path, '2023-11-14') is None
    os.unlink(tmp_path / 'MANIFEST')
    registre(tmp_path, ['2023-11-13'])                              # MANIFEST ordinaire de nouveau
    os.unlink(tmp_path / 'journal-2023-11-13.jsonl')
    os.mkfifo(tmp_path / 'journal-2023-11-13.jsonl')
    r = verifier(tmp_path, LSATTR)
    assert not r['ok'] and any('lecture impossible de' in ligne for ligne in r['lignes'])
