# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests du catalogue : descripteurs, répertoire, introspection, traduction Varlink.
import pytest

from server.commun import catalogue as cat
from server.commun.catalogue import (Catalogue, ErreurCatalogue, Parametre, Repertoire,
                                     creer_descripteur, nom_varlink)
from server.commun.jumeaux import ACTIONS, PROTO


def texte(nom='x'):
    return Parametre(nom, 'texte', {'motif': '[a-z]+', 'longueur_max': 8})


def desc(action, **kw):
    return creer_descripteur(action, plugin='paresia-yin-exemple', delai_s=5, **kw)


def test_motif_action_couvre_actions():
    assert all(cat.MOTIF_ACTION.match(a) for a in ACTIONS)


def test_nom_varlink():
    assert nom_varlink('exemple/identity/add') == 'IdentityAdd'
    assert nom_varlink('exemple/relay-key/sign-mute-list') == 'RelayKeySignMuteList'
    assert nom_varlink('exemple/a_b') == 'AB'
    for mauvais in ('exemple/a--b', 'exemple/a-', 'exemple', 'Exemple/a', 'exemple/1a'):
        with pytest.raises(ValueError):
            nom_varlink(mauvais)
    assert cat.nom_erreur_varlink('exemple', 'command_failed') == 'exemple.CommandFailed'


def test_noms_varlink_uniques():
    with pytest.raises(ValueError):
        Catalogue('principale', 'exemple', [desc('exemple/a-b'), desc('exemple/a_b')])


def test_table_de_correspondance_complete():
    assert set(cat.TYPES_VARLINK) == set(cat.TYPES)
    assert set(cat.BORNES_VARLINK) == cat.VOCABULAIRE_BORNES
    tous = set().union(*cat.BORNES_REQUISES.values(), *cat.BORNES_FACULTATIVES.values())
    assert tous == cat.VOCABULAIRE_BORNES


@pytest.mark.parametrize('type_,bornes', [
    ('texte', {'motif': 'a'}), ('texte', {'motif': '(', 'longueur_max': 3}),
    ('entier', {'minimum': 3, 'maximum': 1}), ('entier', {'minimum': 0}),
    ('choix', {'valeurs': []}), ('choix', {'valeurs': ['a', 'a']}),
    ('hexadecimal', {}), ('hexadecimal', {'longueur': 0}),
    ('liste_entiers', {'minimum': 0, 'maximum': 9}),
    ('entier', {'minimum': 0, 'maximum': 1, 'motif': 'a'}),
    ('entier', {'minimum': True, 'maximum': 1}),
])
def test_bornes_invalides(type_, bornes):
    with pytest.raises(ValueError):
        Parametre('p', type_, bornes)


def test_types_inconnus_et_noms():
    with pytest.raises(ValueError):
        Parametre('p', 'inconnu', {})
    with pytest.raises(ValueError):
        Parametre('P', 'hexadecimal', {'longueur': 4})
    with pytest.raises(ValueError):
        desc('exemple/a', parametres=[texte('x'), texte('x')])


def test_codes_erreur_contre_codes_connus():
    with pytest.raises(ValueError):
        desc('exemple/a', erreurs=['inconnu'], codes_connus={'command_failed'})
    assert desc('exemple/a', erreurs=['command_failed'], codes_connus={'command_failed'})


def test_list_sans_fonction():
    catalogue = Catalogue('principale', 'exemple')
    donnees = catalogue.reponse('exemple/catalog/list', {})
    assert donnees == {'proto': PROTO, 'target': 'principale', 'domain': 'exemple', 'format': 1,
                       'actions': [{'action': 'exemple/catalog/describe', 'plugin': None},
                                   {'action': 'exemple/catalog/list', 'plugin': None}]}
    with pytest.raises(ErreurCatalogue) as e:
        catalogue.reponse('exemple/catalog/list', {'x': 1})
    assert e.value.code == 'bad_request'


def test_describe():
    catalogue = Catalogue('principale', 'exemple', [desc(
        'exemple/objet/lire', privilege='utilisateurs', parametres=[
            texte('x'), Parametre('c', 'choix', {'valeurs': ['a', 'b']}, False)],
        erreurs=['not_available'])])
    donnees = catalogue.reponse('exemple/catalog/describe', {'action': 'exemple/objet/lire'})
    assert donnees == {
        'action': 'exemple/objet/lire', 'plugin': 'paresia-yin-exemple',
        'privilege': 'utilisateurs', 'delay_s': 5,
        'parameters': [
            {'name': 'x', 'type': 'texte', 'required': True,
             'bounds': {'motif': '[a-z]+', 'longueur_max': 8}},
            {'name': 'c', 'type': 'choix', 'required': False, 'bounds': {'valeurs': ['a', 'b']}}],
        'errors': ['not_available']}
    zero = catalogue.reponse('exemple/catalog/describe', {'action': 'exemple/catalog/list'})
    assert zero['parameters'] == [] and zero['errors'] == [] and zero['plugin'] is None
    assert catalogue.reponse('exemple/catalog/describe',
                             {'action': 'exemple/catalog/describe'})['parameters'][0]['name'] == 'action'
    for params, code in (({}, 'bad_request'), ({'action': 'x', 'y': 1}, 'bad_request'),
                         ({'action': 'Mauvais'}, 'bad_request'),
                         ({'action': 'exemple/absente/x'}, 'unknown_action')):
        with pytest.raises(ErreurCatalogue) as e:
            catalogue.reponse('exemple/catalog/describe', params)
        assert e.value.code == code
    with pytest.raises(ErreurCatalogue):
        catalogue.reponse('exemple/objet/lire', {})


def test_aucune_fuite_et_aucune_contrepartie():
    catalogue = Catalogue('principale', 'exemple', [desc('exemple/a', parametres=[texte()])])
    publie = [catalogue.reponse('exemple/catalog/list', {}),
              catalogue.reponse('exemple/catalog/describe', {'action': 'exemple/a'})]
    texte_publie = repr(publie).lower()
    for mot in ('yin"', "'yin'", 'yang', 'counterpart', 'contrepartie', 'script', 'journaliser',
                'commandes', 'requiert', 'exit'):
        assert mot not in texte_publie.replace('paresia-yin-exemple', '')
    assert set(publie[0]) == {'proto', 'target', 'domain', 'format', 'actions'}
    assert set(publie[1]) == {'action', 'plugin', 'privilege', 'delay_s', 'parameters', 'errors'}


def test_action_hors_domaine_ou_double_refusee():
    with pytest.raises(ValueError):
        Catalogue('principale', 'exemple', [desc('autre/a')])
    with pytest.raises(ValueError):
        Catalogue('principale', 'exemple', [desc('exemple/a'), desc('exemple/a')])
    with pytest.raises(ValueError):
        Catalogue('Principale', 'exemple')


def test_repertoire_deux_cibles_deux_domaines():
    cles = [('c1', 'd1'), ('c1', 'd2'), ('c2', 'd1'), ('c2', 'd2')]
    repertoire = Repertoire(Catalogue(c, d, [desc(f'{d}/a')]) for c, d in cles)
    assert repertoire.cles() == cles
    for cible, domaine in cles:
        donnees = repertoire.reponse(cible, domaine, f'{domaine}/catalog/list', {})
        assert (donnees['target'], donnees['domain']) == (cible, domaine)
        assert f'{domaine}/a' in repertoire.actions(cible, domaine)
    assert repertoire.obtenir('c3', 'd1') is None
    with pytest.raises(ErreurCatalogue) as e:
        repertoire.reponse('c3', 'd1', 'd1/catalog/list', {})
    assert e.value.code == 'unknown_action'
    with pytest.raises(ErreurCatalogue) as e:
        repertoire.reponse('c1', 'd3', 'd3/catalog/list', {})
    assert e.value.code == 'unknown_action'
    with pytest.raises(ValueError):
        Repertoire([Catalogue('c1', 'd1'), Catalogue('c1', 'd1')])


def test_modules_sans_constante_de_greffon():
    import re
    from pathlib import Path
    racine = Path(cat.__file__).parent
    for nom in ('catalogue', 'plugins', 'sortie', 'privileges'):
        source = (racine / f'{nom}.py').read_text()
        assert not re.search(r'strfry|bunker|nisaba|legal|relay/', source), nom


LISTE_TEXTE = {'motif': '[a-z]+', 'longueur_max': 8, 'nombre_max': 4}


def test_liste_texte_bornes_obligatoires():
    assert Parametre('l', 'liste_texte', LISTE_TEXTE)
    assert Parametre('l', 'liste_texte', dict(LISTE_TEXTE, nombre_min=1))
    for manquante in LISTE_TEXTE:
        bornes = {k: v for k, v in LISTE_TEXTE.items() if k != manquante}
        with pytest.raises(ValueError):
            Parametre('l', 'liste_texte', bornes)
    with pytest.raises(ValueError):
        Parametre('l', 'liste_texte', dict(LISTE_TEXTE, nombre_min=5))
