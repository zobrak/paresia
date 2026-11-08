# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests du bloc de privilèges neutre.
from pathlib import Path

import pytest

from server.commun import privileges
from server.commun.catalogue import Parametre
from server.commun.privileges import valider_commandes, vers_sudo

P = [Parametre('mode', 'choix', {'valeurs': ['a', 'b']}),
     Parametre('cle', 'hexadecimal', {'longueur': 8}),
     Parametre('n', 'entier', {'minimum': 0, 'maximum': 99}),
     Parametre('t', 'texte', {'motif': 'a', 'longueur_max': 4})]


def bloc(*arguments, operation='exec'):
    return [{'operation': operation, 'arguments': list(arguments)}]


def test_vers_sudo():
    commandes = valider_commandes(
        bloc('conteneur', '/usr/bin/prog', {'parametre': 'mode'}, {'parametre': 'cle'},
             {'parametre': 'n'}) + bloc('conteneur', operation='restart'), P)
    assert vers_sudo(commandes) == [
        {'verbe': 'exec', 'elements': [
            'conteneur', '/usr/bin/prog',
            {'nom': 'mode', 'type': 'choix', 'bornes': {'valeurs': ('a', 'b')}},
            {'nom': 'cle', 'type': 'hexadecimal', 'bornes': {'longueur': 8}},
            {'nom': 'n', 'type': 'entier', 'bornes': {'minimum': 0, 'maximum': 99}}]},
        {'verbe': 'restart', 'elements': ['conteneur']}]


@pytest.mark.parametrize('mauvais', [
    bloc('c', 'p', 'NOPASSWD'), bloc('c', 'p', 'ALL'), bloc('c', 'p', '^a$'), bloc('c', 'p', 'a b'),
    bloc('c', 'p', '(a|b)'), bloc('c', 'p', {'parametre': 'inconnu'}),
    bloc('c', 'p', {'parametre': 't'}), bloc('c', 'p', {'parametre': 'n', 'x': 1}),
    bloc('c', 'p', 1), bloc('c', operation='reboot'), bloc('c', operation='restart')[0:0] + [1],
    bloc('c', {'parametre': 'mode'}), bloc('c', 'p', {'parametre': 'mode'}, operation='restart'),
    bloc('-c', 'p'), bloc('c', '-p'), bloc('c', 'p', '-x'), bloc('c', 'p', '--force'),
    bloc('c', 'p', 'a', '-b', 'd'), bloc('-c', operation='restart'), bloc(), bloc(*['a'] * 17),
    [{'operation': 'exec', 'arguments': ['c', 'p'], 'sudo': 'x'}],
    [{'operation': 'exec'}], 'texte', bloc('c', 'p') * 17,
])
def test_blocs_refuses(mauvais):
    with pytest.raises(ValueError, match='plugin_manifest_invalid'):
        valider_commandes(mauvais, P)


def test_variable_hors_generateur_refusee():
    large = [Parametre('h', 'hexadecimal', {'longueur': 200}),
             Parametre('n', 'entier', {'minimum': -1, 'maximum': 5})]
    for nom in ('h', 'n'):
        with pytest.raises(ValueError):
            valider_commandes(bloc('c', 'p', {'parametre': nom}), large)


def test_aucune_dependance_vers_le_demon():
    source = Path(privileges.__file__).read_text()
    assert 'remus' not in source and 'subprocess' not in source


def test_verbes_acceptes_et_refuses():
    assert valider_commandes(bloc('c', 'p'), P)[0].operation == 'exec'
    assert valider_commandes(bloc('c', operation='restart'), P)[0].operation == 'restart'
    for verbe in ('run', 'stop', 'EXEC', 'sudo', ''):
        with pytest.raises(ValueError):
            valider_commandes(bloc('c', 'p', operation=verbe), P)


def test_caracteres_interdits_dans_un_element_fixe():
    for mauvais in ('a b', 'a;b', 'a$b', 'a\nb', 'a*b', "a'b", 'é', ''):
        with pytest.raises(ValueError):
            valider_commandes(bloc('c', 'p', mauvais), P)


def test_tiret_interieur_accepte():
    assert valider_commandes(bloc('c-d', 'p', 'a-b'), P)


def test_valeur_de_choix_avec_tiret_initial_refusee():
    for valeurs in (['-a'], ['a', '-b']):
        mauvais = [Parametre('mode', 'choix', {'valeurs': valeurs})]
        with pytest.raises(ValueError):
            valider_commandes(bloc('c', 'p', {'parametre': 'mode'}), mauvais)
        assert not privileges.valeurs_choix_valides(mauvais)
    assert privileges.valeurs_choix_valides(P)
