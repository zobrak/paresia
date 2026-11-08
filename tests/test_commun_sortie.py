# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests du contrat de sortie.
# Suivi des versions
#   0.1.5  2026-11-07  Import unique ; enveloppe de test avec borne explicite conservée.
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.commun import sortie
from server.commun.jumeaux import PLAFOND_LIMITE


def interpreter_sortie(octets, code, descripteur, sortie_max=65536):
    return sortie.interpreter_sortie(octets, code, descripteur, sortie_max=sortie_max)


D = SimpleNamespace(erreurs=('command_failed', 'busy_now'))


def ok(data):
    return json.dumps({'ok': True, 'data': data}).encode()


def ko(code):
    return json.dumps({'ok': False, 'error': {'code': code}}).encode()


ECHEC = ('erreur', 'command_failed')


def test_succes_filtre():
    assert interpreter_sortie(ok({'a': [1, 'x']}), 0, D) == ('ok', {'a': [1, 'x']})
    assert interpreter_sortie(ok({'a': 1}) + b'\n', 0, D).contrat == 'ok'


def test_erreurs_declarees():
    assert interpreter_sortie(ko('busy_now'), 1, D) == ('erreur', 'busy_now')
    assert interpreter_sortie(ko('autre'), 1, D) == ECHEC
    assert interpreter_sortie(ko('autre'), 1, D).contrat == 'violated'
    assert interpreter_sortie(ko('not_available'), 2, D) == ('erreur', 'not_available')
    assert interpreter_sortie(ko('busy_now'), 2, D) == ECHEC


@pytest.mark.parametrize('octets,code', [
    (ko('command_failed'), 0), (ok({}), 1), (ok({}), 2), (ok({}), 3), (ok({}), 137),
    (ok({}), -9), (ok({}), None), (b'', 0), (b'pas du json', 0), (b'[]', 0),
    (b'{"ok":true,"data":{},"ok":true}', 0), (b'{"ok":true,"data":{"a":NaN}}', 0),
    (b'{"ok":true,"data":{"a":1e999}}', 0),
    (b'{"ok":true,"data":{},"x":1}', 0), (b'{"ok":true,"data":[]}', 0),
    (b'{"ok":false,"error":{"code":"command_failed","message":"m"}}', 1),
    (b'{"ok":false,"error":"x"}', 1), (b'{"ok":1,"data":{}}', 0), ('texte', 0),
    (ok({'a': '\x07'}), 0), (ok({'\x07': 1}), 0), (ok({'a': '\ud800'}), 0),
    (ok({'a': {'b': {'c': {'d': {'e': {'f': {'g': {'h': 1}}}}}}}}), 0),
])
def test_violations(octets, code):
    assert interpreter_sortie(octets, code, D) == ECHEC


def test_profondeur_limite_acceptee():
    data = {'a': {'b': {'c': {'d': {'e': {'f': {'g': 1}}}}}}}  # huit niveaux avec la racine
    assert interpreter_sortie(ok(data), 0, D)[0] == 'ok'


def test_taille_max():
    octets = ok({'a': 'x' * 100})
    assert interpreter_sortie(octets, 0, D, sortie_max=len(octets))[0] == 'ok'
    assert interpreter_sortie(octets, 0, D, sortie_max=len(octets) - 1) == ECHEC


def test_aucun_message_retourne():
    resultat = interpreter_sortie(b'{"ok":false,"error":{"code":"x","message":"secret"}}', 1, D)
    assert 'secret' not in repr(resultat)


def test_sans_processus():
    arbre = ast.parse(Path(sortie.__file__).read_text())
    importes = {n.names[0].name for n in ast.walk(arbre) if isinstance(n, ast.Import)}
    importes |= {n.module for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom)}
    assert not importes & {'subprocess', 'os', 'importlib'}


def test_sortie_max_obligatoire():
    with pytest.raises(TypeError):
        sortie.interpreter_sortie(ok({}), 0, D)


@pytest.mark.parametrize('valeur', [True, 0, -1, PLAFOND_LIMITE + 1, None, 1.5, '10'])
def test_sortie_max_invalide_est_une_violation(valeur):
    resultat = sortie.interpreter_sortie(ok({}), 0, D, sortie_max=valeur)
    assert resultat == ECHEC and resultat.contrat == 'violated'


def test_sortie_max_plafond_et_taille_exacte():
    assert sortie.interpreter_sortie(ok({}), 0, D, sortie_max=PLAFOND_LIMITE)[0] == 'ok'
    octets = ok({})
    assert sortie.interpreter_sortie(octets, 0, D, sortie_max=len(octets))[0] == 'ok'
    assert sortie.interpreter_sortie(octets, 0, D, sortie_max=len(octets) - 1) == ECHEC
