# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests de la CLI et des métriques de Nisaba ; dépendances : pytest et bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha.40  2026-11-06  Création (T031, C34, C35).
import io
import json
from pathlib import Path
import re
import sys
import tempfile

import pytest

sys.path.insert(0, str(Path(__file__).parent / 'outils' / 'nisaba'))
from nisaba_outils import monter, registre  # noqa: E402
import server.nisaba.ctl as ctl  # noqa: E402
from server.nisaba.metriques import rendre  # noqa: E402

RACINE = Path(__file__).resolve().parents[1]


@pytest.fixture
def dossier_socket():
    with tempfile.TemporaryDirectory(prefix='nisaba-') as dossier:
        yield Path(dossier)


@pytest.fixture
def banc(tmp_path, dossier_socket, monkeypatch):
    n, journal, *_ = monter(tmp_path, dossier_socket)
    monkeypatch.setattr(ctl, 'configuration', lambda argv=None, **_: n.config)
    return n, journal


def lancer(*argv):
    sortie, erreur = io.StringIO(), io.StringIO()
    code = ctl.main(list(argv), sortie=sortie, erreur=erreur)
    return code, sortie.getvalue(), erreur.getvalue()


def test_nisaba_cli(banc):
    n, journal = banc
    registre(journal, ['2023-11-12', '2023-11-13'])
    n.echec('purge', 'ECHEC_PURGE', 'texte\x1b[31m dangereux')
    with n:
        code, sortie, erreur = lancer('status')
        assert code == 0 and erreur == ''
        assert 'Nisaba démarré le 2023-11-14T22:13:20Z (UTC).' in sortie
        assert 'Tâche purge : dernière exécution jamais' in sortie and 'ECHEC_PURGE' in sortie
        assert '2 journée(s) au registre, dernière journée 2023-11-13' in sortie
        assert '\x1b' not in sortie
        code, sortie, _ = lancer('verify')
        assert code == 0 and sortie.splitlines()[-1] == 'RÉSULTAT : registre intègre (2 journées)'
        (journal / 'journal-2023-11-12.jsonl').write_text('altéré\n')
        code, sortie, _ = lancer('verify')
        assert code == 1 and 'fichier modifié depuis le scellement' in sortie
        code, sortie, _ = lancer('run', 'purge')
        assert code == 0 and sortie == 'Tâche purge : réussie.\n'
        code, _, erreur = lancer('run', 'copie')                     # non enregistrée avant T033
        assert code == 1 and 'Opération indisponible' in erreur
        code, _, erreur = lancer('acl', 'check')
        assert code == 1
        n.planificateur._taches['purge'].fonction = lambda: 2
        code, sortie, _ = lancer('run', 'purge')
        assert code == 1 and sortie == 'Tâche purge : 2 échec(s).\n'


@pytest.mark.parametrize('argv', [[], ['inconnue'], ['status', 'x'], ['run'], ['run', 'autre'], ['run', 'purge', 'x'],
                                  ['acl'], ['acl', 'autre'], ['--config'], ['--config', '', 'status'],
                                  ['--config', 'a', '--config', 'b', 'status'], ['metrics', '--verbose']])
def test_nisaba_cli_usage(banc, argv):
    code, sortie, erreur = lancer(*argv)
    assert code == 2 and sortie == '' and erreur.startswith('Usage : ')


def test_nisaba_cli_injoignable_et_configuration(banc, monkeypatch):
    code, sortie, erreur = lancer('status')              # démon non démarré
    assert code == 3 and sortie == '' and 'injoignable' in erreur
    from server.commun.config import ErreurConfiguration

    def echec(argv=None, **_):
        raise ErreurConfiguration('config_missing', 'ctl', 'socket')

    monkeypatch.setattr(ctl, 'configuration', echec)
    code, _, erreur = lancer('status')
    assert code == 2 and 'config_missing' in erreur


def test_nisaba_cli_transmet_config_seule(monkeypatch):
    recu = []
    monkeypatch.setattr(ctl, 'configuration', lambda argv=None, **_: recu.append(argv) or (_ for _ in ()).throw(
        __import__('server.commun.config', fromlist=['x']).ErreurConfiguration('config_unreadable')))
    lancer('--config', '/chemin/test.conf', 'status')
    lancer('status')
    assert recu == [['--config', '/chemin/test.conf'], []]


# -- métriques ---------------------------------------------------------------------------------
HELP = re.compile(r'# HELP [a-zA-Z_:][a-zA-Z0-9_:]* .*')
TYPE = re.compile(r'# TYPE ([a-zA-Z_:][a-zA-Z0-9_:]*) (counter|gauge)')
ECHANTILLON = re.compile(r'([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[a-z_]+="(?:[^"\\\n]|\\.)*"(?:,[a-z_]+="(?:[^"\\\n]|\\.)*")*\})? '
                         r'-?[0-9]+(?:\.[0-9]+)?(?:e[+-]?[0-9]+)?')


def verifier_format(texte):
    assert texte.endswith('\n') and '\n\n' not in texte
    declares = set()
    for ligne in texte.splitlines():
        if ligne.startswith('# HELP'):
            assert HELP.fullmatch(ligne), ligne
        elif ligne.startswith('# TYPE'):
            trouve = TYPE.fullmatch(ligne)
            assert trouve and trouve.group(1) not in declares, ligne
            declares.add(trouve.group(1))
        else:
            trouve = ECHANTILLON.fullmatch(ligne)
            assert trouve and trouve.group(1) in declares, ligne
    return declares


def test_nisaba_metriques(banc):
    n, journal = banc
    registre(journal, ['2023-11-13'])
    (journal / 'seals' / '2023-11-13.txt.ots').write_bytes(b'x')
    n.echec('purge', 'ECHEC_PURGE', 'x')
    n.echec('purge', 'ECHEC_PURGE', 'y')
    n.planificateur.executer('purge')
    with n:
        code, sortie, erreur = lancer('metrics')
    assert code == 0 and erreur == ''
    assert verifier_format(sortie) == {
        'nisaba_last_success_timestamp_seconds', 'nisaba_failures_total', 'nisaba_manifest_days',
        'nisaba_proofs', 'nisaba_oldest_journal_age_seconds'}
    assert 'nisaba_last_success_timestamp_seconds{tache="purge"} 1700000000.0' in sortie
    assert 'nisaba_failures_total{tache="purge",code="ECHEC_PURGE"} 2' in sortie
    assert 'nisaba_manifest_days 1' in sortie
    assert 'nisaba_proofs{etat="en_attente"} 1' in sortie and 'nisaba_proofs{etat="non_soumises"} 0' in sortie
    assert f'nisaba_oldest_journal_age_seconds {86400 + 22 * 3600 + 13 * 60 + 20}' in sortie


def test_nisaba_metriques_echappement():
    donnees = {'derniere_reussite': {'a"b\\c\nd': 1.5}, 'echecs': [], 'journees': 0,
               'preuves': {'ancrees': 0, 'en_attente': 0, 'non_soumises': 0}, 'age_plus_ancien_s': None}
    texte = rendre(donnees, {'nisaba_manifest_days': 'ligne\\1\nligne2'})
    verifier_format(texte)
    assert 'nisaba_last_success_timestamp_seconds{tache="a\\"b\\\\c\\nd"} 1.5' in texte
    assert '# HELP nisaba_manifest_days ligne\\\\1\\nligne2' in texte
    assert not re.search(r'^nisaba_oldest_journal_age_seconds ', texte, re.M)     # série sans échantillon : en-têtes seuls


def test_nisaba_cli_catalogues():
    fr = json.loads((RACINE / 'i18n/fr-FR.json').read_text(encoding='utf-8'))
    en = json.loads((RACINE / 'i18n/en-US.json').read_text(encoding='utf-8'))
    cles = {c for c in fr if c.startswith('nisaba_')}
    assert cles == {c for c in en if c.startswith('nisaba_')}
    source = (RACINE / 'server/nisaba/ctl.py').read_text(encoding='utf-8')
    utilisees = set(re.findall(r"dire\('(nisaba_[a-z_]+)'", source)) | {'nisaba_result_ok', 'nisaba_result_echec',
                                                                         'nisaba_never', 'nisaba_unknown'}
    assert utilisees <= cles and all(cle in cles for cle in ctl.AIDE_METRIQUES.values())
