# SPDX-License-Identifier: AGPL-3.0-or-later
# Neutralité du noyau : aucun nom de greffon dans le code des jumeaux ; dépendances : pytest, ast.
# Suivi des versions
#   0.1.17  2026-11-08  Test de neutralité du noyau, garde de chargement de code, nommage des greffons.
import ast
from pathlib import Path
import re
import tomllib

RACINE = Path(__file__).resolve().parents[1]
NOYAU = ('server/commun', 'server/romulus', 'server/remus', 'server/pollux', 'server/castor')
SANS_RELAY = ('server/commun', 'server/romulus', 'server/remus')
HORS_NOYAU = ('server/bunkerd', 'server/nisaba')
NOMS_DE_GREFFONS = ('strfry', 'bunker', 'nisaba', 'legal')
CHARGEURS = frozenset({'importlib', '__import__', 'entry_points', 'pluggy', 'stevedore', 'yapsy'})
DECLARATIONS = (RACINE / 'deploy/backend-admin/usr/local/lib/paresia/romulus/services')

# Exceptions : (fichier relatif, texte) ; l'ensemble exact est comparé, une exception devenue
# inutile fait échouer le test. Aucune aujourd'hui : l'action du noyau `presence/relay/ping`
# (« relais » désigne la machine du côté Remus) n'est ni égale à `relay` ni préfixée par
# `relay/`, et les codes d'erreur de greffons (`relay_light_red`, ...) ne contiennent aucun
# nom de greffon ; toute nouvelle exception se justifie ici, une ligne par entrée.
EXCEPTIONS = set()


def fichiers(dossiers):
    for dossier in dossiers:
        for chemin in sorted((RACINE / dossier).rglob('*.py')):
            if 'exemples' in chemin.relative_to(RACINE / dossier).parts:
                continue
            yield chemin


def _docstrings(arbre):
    ids = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            corps = noeud.body
            if (corps and isinstance(corps[0], ast.Expr) and isinstance(corps[0].value, ast.Constant)
                    and isinstance(corps[0].value.value, str)):
                ids.add(id(corps[0].value))
    return ids


def termes(source):
    """Identifiants et chaînes hors docstrings d'un source Python (aucun commentaire)."""
    arbre = ast.parse(source)
    docstrings = _docstrings(arbre)
    trouves = []
    for n in ast.walk(arbre):
        if isinstance(n, ast.Name):
            trouves.append(n.id)
        elif isinstance(n, ast.Attribute):
            trouves.append(n.attr)
        elif isinstance(n, ast.arg):
            trouves.append(n.arg)
        elif isinstance(n, ast.keyword) and n.arg:
            trouves.append(n.arg)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            trouves.append(n.name)
        elif isinstance(n, ast.alias):
            trouves.extend(n.name.split('.'))
            if n.asname:
                trouves.append(n.asname)
        elif isinstance(n, ast.ImportFrom) and n.module:
            trouves.extend(n.module.split('.'))
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings:
            trouves.append(n.value)
    return trouves


def interdits(terme, sans_relay):
    bas = terme.lower()
    return (any(nom in bas for nom in NOMS_DE_GREFFONS) or terme.startswith('relay/')
            or (sans_relay and terme == 'relay'))


def relever(source, dossier_sans_relay):
    return {t for t in termes(source) if interdits(t, dossier_sans_relay)}


def violations(dossiers):
    trouvees = set()
    for chemin in fichiers(dossiers):
        relatif = chemin.relative_to(RACINE).as_posix()
        sans_relay = relatif.startswith(tuple(d + '/' for d in SANS_RELAY))
        for terme in relever(chemin.read_text(encoding='utf-8'), sans_relay):
            trouvees.add((relatif, terme))
    return trouvees


def test_noyau_neutre_aux_exceptions_exactes_pres():
    assert violations(NOYAU) == EXCEPTIONS


def test_le_test_detecte_un_nom_de_greffon(tmp_path):
    fictif = tmp_path / 'module.py'
    fictif.write_text("def f():\n    return 'bunker'\n", encoding='utf-8')
    assert relever(fictif.read_text(encoding='utf-8'), True) == {'bunker'}
    fictif.write_text("relay = 1\nx = 'relay/state/status'\n", encoding='utf-8')
    assert relever(fictif.read_text(encoding='utf-8'), True) == {'relay', 'relay/state/status'}
    # Docstrings et commentaires ne comptent pas.
    fictif.write_text('"""strfry"""\n# nisaba\nx = 1\n', encoding='utf-8')
    assert relever(fictif.read_text(encoding='utf-8'), True) == set()


def test_les_modules_de_greffons_sont_detectes():
    assert violations(HORS_NOYAU), 'le test doit reconnaître les modules hors noyau'


def test_aucun_chargement_de_code_de_greffon():
    trouves = set()
    for chemin in fichiers(NOYAU):
        for terme in set(termes(chemin.read_text(encoding='utf-8'))) & CHARGEURS:
            trouves.add((chemin.relative_to(RACINE).as_posix(), terme))
    assert trouves == set()


def test_declarations_livrees_nommees_yang():
    motif = re.compile(r'paresia-(yin|yang)-[a-z][a-z0-9-]{0,31}\Z')
    declarations = sorted(DECLARATIONS.glob('*.toml'))
    assert declarations
    for chemin in declarations:
        nom = tomllib.loads(chemin.read_text(encoding='utf-8'))['greffon']
        assert motif.match(nom) and nom.startswith('paresia-yang-'), chemin.name
        assert chemin.name == nom + '.toml'
    assert (DECLARATIONS / 'paresia-yang-strfry.toml').exists()
    assert (DECLARATIONS / 'paresia-yang-journal-legal.toml').exists()
    document = (RACINE / 'docs/plugins/strfry.md').read_text(encoding='utf-8')
    assert 'paresia-yin-strfry' in document and 'paresia-yang-strfry' in document
