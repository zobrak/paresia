# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests des gabarits de l'exécuteur de Remus (T022) ; pytest et bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha  2026-11-05  Gabarits (T022, exigences 4 et 5).
#   3.0.0-alpha  2026-11-05  Cycle 1 : tiret initial, espace, immutabilité.
import pytest

from server.remus.executeur import (Choix, Entier, ErreurGabarit, Hexadecimal, ListeEntiers, Texte)


def refuse(gabarit, *valeurs):
    for valeur in valeurs:
        with pytest.raises(ErreurGabarit) as erreur:
            gabarit.valider(valeur)
        assert 'x' * 3 not in str(erreur.value)


def test_gabarit_entier():
    g = Entier(0, 100)
    assert g.valider(0) == '0' and g.valider(100) == '100'
    refuse(g, -1, 101, True, False, 1.0, '5', None, [])
    with pytest.raises(ValueError):
        Entier(-1, 5)
    with pytest.raises(ValueError):
        Entier(5, 4)


def test_gabarit_hexadecimal():
    g = Hexadecimal(4)
    assert g.valider('ab09') == 'ab09'
    refuse(g, 'AB09', 'ab0', 'ab090', '', 'zzzz', 1234, None, 'ab0\n')


def test_gabarit_choix():
    g = Choix('a', 'b')
    assert g.valider('a') == 'a'
    refuse(g, 'A', 'c', '', 1, None, 'a ')
    for invalide in ('-x', '', 'a\x00'):
        with pytest.raises(ValueError):
            Choix(invalide)


def test_gabarit_texte():
    g = Texte('[a-z0-9._]+', 10)
    assert g.valider('abc.1') == 'abc.1'
    refuse(g, '', 'a b', 'a' * 11, 'é', 'a\nb', 'a\x00b', 'A', 12, None, '-')
    # Un motif trop large ne laisse pas passer ce que les règles communes interdisent.
    large = Texte('.+', 10)
    refuse(large, 'é', 'a\tb', 'a\x7f', ' a b', 'a b')
    assert large.valider('ab') == 'ab'


def test_texte_refuse_tiret_initial():
    refuse(Texte('.+', 10), '-x', '-', '--help')
    refuse(Texte('[a-z-]+', 10), '-a', '-')
    assert Texte('[a-z-]+', 10).valider('a-b') == 'a-b'


def test_texte_espace_explicite():
    g = Texte('.+', 10, espace=True)
    assert g.valider('a b') == 'a b'
    refuse(g, '-a b')
    with pytest.raises(ValueError):
        Texte('.+', 10, espace='oui')


def test_choix_tiret_et_espace():
    g = Choix('a', 'b-c')
    refuse(g, '-a', '-b-c', '-')
    with pytest.raises(ValueError):
        Choix('a b')
    avec = Choix('a b', 'c', espace=True)
    assert avec.valider('a b') == 'a b'
    refuse(avec, 'a  b', ' a b')


def test_gabarits_immuables():
    for g, champ in ((Entier(0, 9), 'maximum'), (Hexadecimal(4), 'longueur'), (Choix('a'), 'valeurs'),
                     (Texte('a', 5), 'motif'), (Texte('a', 5), '_regex'), (ListeEntiers(0, 9, 3), 'nombre_max')):
        with pytest.raises(AttributeError):
            setattr(g, champ, None)
        with pytest.raises(AttributeError):
            delattr(g, champ)
    g = Entier(0, 9)
    with pytest.raises(AttributeError):
        g.maximum = 10**9
    assert g.valider(9) == '9'
    refuse(g, 10)


def test_gabarit_liste_entiers():
    g = ListeEntiers(1, 50, 3)
    assert g.valider([1, 50, 7]) == '1,50,7'
    refuse(g, [], [0], [51], [1, 2, 3, 4], [True], ['1'], (1, 2), '1,2', None, [1.0])
