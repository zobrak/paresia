# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests du chargeur de fonctions.
# Suivi des versions
#   0.1.5  2026-11-07  Tests du chargeur, imports admis et erreurs typées aux frontières.
import ast
import os
from pathlib import Path

import pytest

from server.commun import plugins
from server.commun.jumeaux import PLAFOND_DELAI, PLAFOND_LIMITE
from server.commun.plugins import CLES_MANIFESTE, ErreurPlugin, charger

MOI = os.geteuid()
BASE = (
    'format = 1\ngreffon = "paresia-yin-exemple"\nnom = "{nom}"\naction = "exemple/objet/{nom}"\n'
    'delai_s = 5\n')
CONNUS = {'command_failed', 'not_available'}


@pytest.fixture
def arbre(tmp_path):
    for nom in ('livre', 'local'):
        (tmp_path / nom).mkdir(mode=0o755)
        os.chmod(tmp_path / nom, 0o755)
    os.chmod(tmp_path, 0o755)
    return tmp_path


def poser(dossier, nom, extra='', base=None, script=True, manifeste=True, mode=0o644):
    if script:
        (dossier / nom).write_text('contenu')
        os.chmod(dossier / nom, 0o755)
    if manifeste:
        texte = (BASE.format(nom=nom) if base is None else base.format(nom=nom)) + extra
        (dossier / (nom + '.toml')).write_text(texte)
        os.chmod(dossier / (nom + '.toml'), mode)


class Journal:
    def __init__(self):
        self.lignes = []

    def __call__(self, evenement, niveau, **champs):
        self.lignes.append((evenement, niveau, champs))


def lancer(arbre, cote='yin', rappel=None, **kw):
    return charger(cote, 'exemple', arbre / 'livre', arbre / 'local', codes_connus=CONNUS,
                   proprietaires={MOI}, racine_confiance=arbre, rappel=rappel, **kw)


def code(arbre, **kw):
    with pytest.raises(ErreurPlugin) as e:
        lancer(arbre, **kw)
    return e.value.code


def test_valide(arbre):
    poser(arbre / 'livre', 'lire', extra=(
        'privilege = "utilisateurs"\nsortie_max = 100\njournaliser = ["mode"]\n'
        'erreurs = ["not_available"]\n[[parametres]]\nnom = "mode"\ntype = "choix"\n'
        'valeurs = ["a", "b"]\n[[parametres]]\nnom = "n"\ntype = "entier"\nminimum = 0\n'
        'maximum = 9\nobligatoire = false\n'
        '[[commandes_privilegiees]]\noperation = "restart"\narguments = ["cible"]\n'))
    resultat = lancer(arbre)
    descripteur = resultat.catalogue.descripteur('exemple/objet/lire')
    assert descripteur.forme == 'ponctuel' and descripteur.privilege == 'utilisateurs'
    assert [p.nom for p in descripteur.parametres] == ['mode', 'n']
    assert descripteur.erreurs == ('not_available',)
    fonction = resultat.fonctions['exemple/objet/lire']
    assert fonction.sortie_max == 100 and fonction.journaliser == ('mode',)
    assert fonction.script == str(arbre / 'livre' / 'lire') and len(fonction.commandes) == 1
    donnees = resultat.catalogue.reponse('exemple/catalog/list', {})
    assert donnees['target'] == 'principale'
    assert {'action': 'exemple/objet/lire', 'plugin': 'paresia-yin-exemple'} in donnees['actions']
    assert 'script' not in repr(donnees)


def test_dossiers_absents(arbre):
    resultat = charger('yin', 'exemple', arbre / 'x', arbre / 'y' / 'z', codes_connus=CONNUS,
                       proprietaires={MOI}, racine_confiance=arbre)
    assert resultat.catalogue.actions == {'exemple/catalog/list', 'exemple/catalog/describe'}
    assert resultat.rejets == ()


def test_cible(arbre):
    assert lancer(arbre, cible='autre').catalogue.cible == 'autre'
    with pytest.raises(ValueError):
        lancer(arbre, cible='Mauvaise')
    for domaine in ('presence', 'castor'):
        with pytest.raises(ValueError):
            charger('yin', domaine, arbre / 'livre', arbre / 'local', codes_connus=CONNUS)


MAUVAIS = {
    'cle inconnue': ('x = 1\n', 'plugin_manifest_invalid'),
    'cle de langage': ('module = "m"\n', 'plugin_manifest_invalid'),
    'flux': ('flux = true\n', 'plugin_manifest_invalid'),
    'privilege inconnu': ('privilege = "autre"\n', 'plugin_manifest_invalid'),
    'erreurs hors connus': ('erreurs = ["inconnu"]\n', 'plugin_manifest_invalid'),
    'sortie_max nul': ('sortie_max = 0\n', 'plugin_manifest_invalid'),
    'forme': ('forme = "continu"\n', 'plugin_form_unsupported'),
    'forme non texte': ('forme = 3\n', 'plugin_manifest_invalid'),
    'journaliser inconnu': ('journaliser = ["z"]\n', 'plugin_manifest_invalid'),
    'borne manquante': ('[[parametres]]\nnom = "p"\ntype = "texte"\nmotif = "a"\n',
                        'plugin_manifest_invalid'),
    'type inconnu': ('[[parametres]]\nnom = "p"\ntype = "x"\n', 'plugin_manifest_invalid'),
    'liste_texte': ('[[parametres]]\nnom = "p"\ntype = "liste_texte"\nmotif = "a"\n'
                    'longueur_max = 3\nnombre_max = 3\n', 'plugin_manifest_invalid'),
    'doublon de parametre': ('[[parametres]]\nnom = "p"\ntype = "hexadecimal"\nlongueur = 4\n'
                             '[[parametres]]\nnom = "p"\ntype = "hexadecimal"\nlongueur = 4\n',
                             'plugin_manifest_invalid'),
    'trop de parametres': (''.join(
        f'[[parametres]]\nnom = "p{i}"\ntype = "hexadecimal"\nlongueur = 4\n'
        for i in range(17)), 'plugin_manifest_invalid'),
    'sudoers': ('[[sudo]]\nx = 1\n', 'plugin_manifest_invalid'),
    'codes_sortie': ('codes_sortie = [1]\n', 'plugin_manifest_invalid'),
    'bloc de privileges': ('[[commandes_privilegiees]]\noperation = "exec"\n'
                           'arguments = ["c", "p", "NOPASSWD"]\n', 'plugin_manifest_invalid'),
    'requiert relatif': ('[requiert]\nfichiers = ["relatif"]\n', 'plugin_manifest_invalid'),
    'requiert inconnu': ('[requiert]\nversion = ["/a"]\n', 'plugin_manifest_invalid'),
    'requiert trop': ('[requiert]\nfichiers = [' + ','.join(['"/a"'] * 9) + ']\n',
                      'plugin_manifest_invalid'),
    'toml invalide': ('=\n', 'plugin_manifest_invalid'),
    'doublon toml': ('delai_s = 6\n', 'plugin_manifest_invalid'),
}


@pytest.mark.parametrize('cas', sorted(MAUVAIS))
def test_manifestes_refuses_livre_et_local(arbre, cas):
    extra, attendu = MAUVAIS[cas]
    poser(arbre / 'livre', 'lire', extra=extra)
    assert code(arbre) == attendu
    os.remove(arbre / 'livre' / 'lire.toml')
    os.remove(arbre / 'livre' / 'lire')
    poser(arbre / 'local', 'lire', extra=extra)
    poser(arbre / 'local', 'sain')
    journal = Journal()
    resultat = lancer(arbre, rappel=journal)
    assert [(r.code, r.scope, r.file) for r in resultat.rejets] == [(attendu, 'local', 'lire')]
    assert 'exemple/objet/sain' in resultat.catalogue.actions
    assert 'exemple/objet/lire' not in resultat.catalogue.actions
    rejets = [c for e, n, c in journal.lignes if e == 'plugin_rejected']
    assert rejets == [{'code': attendu, 'scope': 'local', 'file': 'lire'}]
    assert str(arbre) not in repr(journal.lignes)


@pytest.mark.parametrize('base,attendu', [
    ('greffon = "paresia-yin-exemple"\nnom = "{nom}"\naction = "exemple/o/{nom}"\ndelai_s = 5\n',
     'plugin_manifest_invalid'),
    ('format = 2\ngreffon = "paresia-yin-exemple"\nnom = "{nom}"\naction = "exemple/o/{nom}"\n'
     'delai_s = 5\nnouveau = 1\n', 'plugin_format_unsupported'),
    ('format = "1"\ngreffon = "paresia-yin-exemple"\nnom = "{nom}"\naction = "exemple/o/{nom}"\n'
     'delai_s = 5\n', 'plugin_manifest_invalid'),
    ('format = true\ngreffon = "paresia-yin-exemple"\nnom = "{nom}"\naction = "exemple/o/{nom}"\n'
     'delai_s = 5\n', 'plugin_manifest_invalid'),
    ('format = 1\ngreffon = "paresia-yin-exemple"\nnom = "autre"\naction = "exemple/o/{nom}"\n'
     'delai_s = 5\n', 'plugin_manifest_invalid'),
    ('format = 1\ngreffon = "paresia-yin-exemple"\nnom = "{nom}"\naction = "autre/o/{nom}"\n'
     'delai_s = 5\n', 'plugin_manifest_invalid'),
    ('format = 1\ngreffon = "paresia-yin-exemple"\nnom = "{nom}"\naction = "presence/o/{nom}"\n'
     'delai_s = 5\n', 'plugin_manifest_invalid'),
    ('format = 1\ngreffon = "paresia-yin-exemple"\nnom = "{nom}"\n'
     'action = "exemple/catalog/list"\ndelai_s = 5\n', 'plugin_manifest_invalid'),
    ('format = 1\ngreffon = "paresia-yin-exemple"\nnom = "{nom}"\n'
     'action = "exemple/catalog/describe"\ndelai_s = 5\n', 'plugin_manifest_invalid'),
    ('format = 1\ngreffon = "paresia-yin-exemple"\nnom = "{nom}"\naction = "exemple/o/{nom}"\n'
     'delai_s = 0\n', 'plugin_manifest_invalid'),
    ('format = 1\ngreffon = "paresia-yin-exemple"\nnom = "{nom}"\naction = "exemple/o/{nom}"\n'
     'delai_s = 99999\n', 'plugin_manifest_invalid'),
    ('format = 1\ngreffon = "paresia-yin-exemple"\nnom = "{nom}"\naction = "exemple/o/{nom}"\n'
     'delai_s = nan\n', 'plugin_manifest_invalid'),
])
def test_champs_obligatoires(arbre, base, attendu):
    poser(arbre / 'livre', 'lire', base=base)
    assert code(arbre) == attendu


def test_manifeste_trop_gros(arbre):
    poser(arbre / 'livre', 'lire', extra='# ' + 'x' * 65536 + '\n')
    assert code(arbre) == 'plugin_manifest_invalid'


def test_forme_explicite_et_defaut(arbre):
    poser(arbre / 'livre', 'lire', extra='forme = "ponctuel"\n')
    poser(arbre / 'livre', 'autre')
    resultat = lancer(arbre)
    assert {resultat.catalogue.descripteur(a).forme
            for a in ('exemple/objet/lire', 'exemple/objet/autre')} == {'ponctuel'}


def test_forme_non_prise_en_charge_sans_valeur(arbre):
    poser(arbre / 'local', 'lire', extra='forme = "valeur-secrete"\n')
    journal = Journal()
    resultat = lancer(arbre, rappel=journal)
    assert resultat.rejets[0].code == 'plugin_form_unsupported'
    assert 'valeur-secrete' not in repr((resultat.rejets, journal.lignes))


def test_cles_manifeste_exactes():
    assert CLES_MANIFESTE == {'format', 'forme', 'greffon', 'nom', 'action', 'privilege',
                              'delai_s', 'sortie_max', 'flux', 'journaliser', 'erreurs',
                              'parametres', 'commandes_privilegiees', 'requiert', 'produit',
                              'compatible_yang'}
    assert not {'yin', 'yang'} & CLES_MANIFESTE


def test_nommage_des_cotes(arbre):
    poser(arbre / 'livre', 'lire')
    assert lancer(arbre).catalogue.descripteur('exemple/objet/lire')
    assert code(arbre, cote='yang') == 'plugin_manifest_invalid'
    os.remove(arbre / 'livre' / 'lire.toml')
    for nom in ('paresia-yang-exemple', 'exemple', 'paresia-exemple', 'paresia-yan-x',
                'paresia-yin-Exemple', 'paresia-yin-' + 'a' * 33, 'paresia-yin-'):
        poser(arbre / 'livre', 'lire', manifeste=True, script=False, base=BASE.replace(
            'paresia-yin-exemple', nom))
        assert code(arbre) == 'plugin_manifest_invalid', nom
    poser(arbre / 'livre', 'lire', script=False,
          base=BASE.replace('yin', 'yang'))
    assert lancer(arbre, cote='yang').catalogue.descripteur('exemple/objet/lire')
    with pytest.raises(ValueError):
        lancer(arbre, cote='autre')


# --- fichiers -----------------------------------------------------------------------------

def defauts_fichiers(arbre):
    """Fabrique chaque défaut de fichier dans le dossier livre, puis dans le dossier local."""
    cas = {}

    def fonction(d):
        poser(d, 'lire')
    cas['manifeste sans script'] = (lambda d: poser(d, 'lire', script=False), 'plugin_incomplete')
    cas['script sans manifeste'] = (lambda d: poser(d, 'lire', manifeste=False),
                                    'plugin_incomplete')
    cas['autre fichier'] = (lambda d: ((d / 'note').write_text('x'), os.chmod(d / 'note', 0o644)),
                            'plugin_incomplete')
    cas['nom hors forme'] = (lambda d: (d / 'Mauvais.txt').write_text('x'),
                             'plugin_unexpected_entry')
    cas['sous-dossier'] = (lambda d: (d / 'sous').mkdir(), 'plugin_incomplete')
    cas['groupe inscriptible'] = (lambda d: (poser(d, 'lire'), os.chmod(d / 'lire', 0o775)),
                                  'plugin_unsafe_permissions')
    cas['manifeste inscriptible'] = (lambda d: poser(d, 'lire', mode=0o666),
                                     'plugin_unsafe_permissions')
    cas['setuid'] = (lambda d: (poser(d, 'lire'), os.chmod(d / 'lire', 0o4755)),
                     'plugin_unsafe_permissions')
    cas['setgid manifeste'] = (lambda d: poser(d, 'lire', mode=0o2644),
                               'plugin_unsafe_permissions')
    cas['non executable'] = (lambda d: (poser(d, 'lire'), os.chmod(d / 'lire', 0o644)),
                             'plugin_unsafe_permissions')
    cas['lien symbolique'] = (lambda d: (poser(d, 'cible'), os.symlink(d / 'cible', d / 'lire'),
                                         os.symlink(d / 'cible.toml', d / 'lire.toml')),
                              'plugin_unsafe_permissions')
    return cas


CAS_FICHIERS = sorted(defauts_fichiers(None))


@pytest.mark.parametrize('cas', CAS_FICHIERS)
def test_defauts_de_fichiers_livre_fatal(arbre, cas):
    creer, attendu = defauts_fichiers(arbre)[cas]
    creer(arbre / 'livre')
    erreur = pytest.raises(ErreurPlugin, lancer, arbre)
    assert erreur.value.code in {attendu, 'plugin_unexpected_entry'}
    assert str(arbre) not in str(erreur.value)


@pytest.mark.parametrize('cas', CAS_FICHIERS)
def test_defauts_de_fichiers_local_ignore(arbre, cas):
    creer, _ = defauts_fichiers(arbre)[cas]
    creer(arbre / 'local')
    poser(arbre / 'local', 'sain')
    journal = Journal()
    resultat = lancer(arbre, rappel=journal)
    assert resultat.rejets
    assert 'exemple/objet/sain' in resultat.catalogue.actions
    assert 'exemple/objet/lire' not in resultat.catalogue.actions
    assert str(arbre) not in repr((resultat.rejets, journal.lignes))


def test_proprietaire_etranger(arbre):
    poser(arbre / 'livre', 'lire')
    with pytest.raises(ErreurPlugin) as erreur:
        charger('yin', 'exemple', arbre / 'livre', arbre / 'local', codes_connus=CONNUS,
                proprietaires={MOI + 1}, racine_confiance=arbre)
    assert erreur.value.code == 'plugin_unsafe_permissions'


def test_dossier_ancetre_ou_dossier_non_sur(arbre):
    poser(arbre / 'livre', 'lire')
    os.chmod(arbre / 'livre', 0o775)
    assert code(arbre) == 'plugin_unsafe_permissions'
    os.chmod(arbre / 'livre', 0o755)
    os.chmod(arbre, 0o1777)  # « sticky » inscriptible : refusé
    assert code(arbre) == 'plugin_unsafe_permissions'
    os.chmod(arbre, 0o755)
    os.remove(arbre / 'livre' / 'lire.toml')
    os.remove(arbre / 'livre' / 'lire')
    poser(arbre / 'local', 'lire')
    os.chmod(arbre / 'local', 0o777)
    resultat = lancer(arbre)
    assert [r.code for r in resultat.rejets] == ['plugin_unsafe_permissions']
    assert resultat.catalogue.descripteur('exemple/objet/lire') is None


def test_dossier_lien_symbolique(arbre):
    (arbre / 'reel').mkdir(mode=0o755)
    os.rmdir(arbre / 'livre')
    os.symlink(arbre / 'reel', arbre / 'livre')
    assert code(arbre) == 'plugin_unsafe_permissions'


def test_hors_racine_de_confiance(arbre):
    with pytest.raises(ErreurPlugin):
        charger('yin', 'exemple', arbre.parent, arbre / 'local', codes_connus=CONNUS,
                proprietaires={MOI}, racine_confiance=arbre)


def test_trop_de_fonctions(arbre):
    for i in range(257):
        (arbre / 'livre' / f'f{i}').write_text('')
    assert code(arbre) == 'plugin_too_many'


# --- doublons -----------------------------------------------------------------------------

def test_doublons(arbre):
    poser(arbre / 'livre', 'lire')
    poser(arbre / 'local', 'lire')
    poser(arbre / 'livre', 'autre', base=BASE.replace('{nom}', '{nom}').replace(
        'objet/{nom}', 'objet/lire'))
    assert code(arbre) == 'plugin_duplicate'
    os.remove(arbre / 'livre' / 'autre')
    os.remove(arbre / 'livre' / 'autre.toml')
    resultat = lancer(arbre)
    assert [r.code for r in resultat.rejets] == ['plugin_duplicate']
    assert resultat.fonctions['exemple/objet/lire'].script.startswith(str(arbre / 'livre'))


def test_conflit_entre_locaux_ordre_alphabetique(arbre):
    commun = BASE.replace('objet/{nom}', 'objet/commun')
    poser(arbre / 'local', 'zebre', base=commun)
    poser(arbre / 'local', 'abeille', base=commun)
    resultat = lancer(arbre)
    assert resultat.fonctions['exemple/objet/commun'].nom == 'abeille'
    assert [(r.code, r.file) for r in resultat.rejets] == [('plugin_duplicate', 'zebre')]


def test_noms_varlink_en_conflit(arbre):
    poser(arbre / 'local', 'a', base=BASE.replace('objet/{nom}', 'objet/a-b'))
    poser(arbre / 'local', 'b', base=BASE.replace('objet/{nom}', 'objet/a_b'))
    resultat = lancer(arbre)
    assert [r.file for r in resultat.rejets] == ['b']


# --- condition de chargement --------------------------------------------------------------

def test_condition(arbre, tmp_path_factory):
    dehors = tmp_path_factory.mktemp('dehors')
    present = dehors / 'present'
    present.write_text('x')
    binaire = dehors / 'binaire'
    trace = dehors / 'trace'
    binaire.write_text(f'#!/bin/sh\necho x > {trace}\n')
    os.chmod(binaire, 0o755)
    inexec = dehors / 'inexec'
    inexec.write_text('x')
    os.chmod(inexec, 0o644)
    cas = {
        'ok': f'[requiert]\nfichiers = ["{present}"]\nbinaires = ["{binaire}"]\n',
        'fichier absent': f'[requiert]\nfichiers = ["{dehors}/non"]\n',
        'binaire absent': f'[requiert]\nbinaires = ["{dehors}/non"]\n',
        'binaire non executable': f'[requiert]\nbinaires = ["{inexec}"]\n',
    }
    for nom, extra in cas.items():
        for dossier in ('livre', 'local'):
            for autre in ('livre', 'local'):
                for f in (arbre / autre).iterdir():
                    f.unlink()
            poser(arbre / dossier, 'lire', extra=extra)
            journal = Journal()
            resultat = lancer(arbre, rappel=journal)
            assert resultat.rejets == ()
            charge = 'exemple/objet/lire' in resultat.catalogue.actions
            assert charge == (nom == 'ok'), (nom, dossier)
            if not charge:
                assert [(e, n) for e, n, _ in journal.lignes] == [('plugin_skipped', 'warning')]
                champs = journal.lignes[0][2]
                assert champs['code'] == 'plugin_requirement_unmet' and champs['file'] == 'lire'
                assert champs['scope'] == dossier and 'requirement' in champs
                assert str(dehors) not in repr(journal.lignes)
                assert 'exemple/objet/lire' not in repr(
                    resultat.catalogue.reponse('exemple/catalog/list', {}))
    assert not trace.exists()


def test_condition_ecartee_compte_pour_doublons(arbre):
    poser(arbre / 'livre', 'lire', extra='[requiert]\nfichiers = ["/inexistant/x"]\n')
    poser(arbre / 'local', 'lire')
    resultat = lancer(arbre)
    assert [r.code for r in resultat.rejets] == ['plugin_duplicate']
    assert 'exemple/objet/lire' not in resultat.catalogue.actions


def test_manifeste_defectueux_malgre_condition(arbre):
    poser(arbre / 'livre', 'lire', extra='x = 1\n[requiert]\nfichiers = ["/inexistant/x"]\n')
    assert code(arbre) == 'plugin_manifest_invalid'


# --- privilèges ---------------------------------------------------------------------------

PRIV = '[[commandes_privilegiees]]\noperation = "restart"\narguments = ["cible"]\n'


def test_verifier_privileges(arbre):
    recu = []

    def accepte(description):
        recu.append(description)
        return True

    poser(arbre / 'livre', 'lire', extra=PRIV)
    lancer(arbre, verifier_privileges=accepte)
    assert recu == [[{'verbe': 'restart', 'elements': ['cible']}]]

    def refuse(_):
        raise ValueError('inexprimable')

    assert code(arbre, verifier_privileges=refuse) == 'plugin_privileges_rejected'
    os.remove(arbre / 'livre' / 'lire.toml')
    os.remove(arbre / 'livre' / 'lire')
    poser(arbre / 'local', 'lire', extra=PRIV)
    resultat = lancer(arbre, verifier_privileges=lambda _: False)
    assert [r.code for r in resultat.rejets] == ['plugin_privileges_rejected']


def test_verifier_privileges_fail_closed(arbre):
    poser(arbre / 'livre', 'lire', extra=PRIV)

    def leve(_):
        raise RuntimeError('boum')

    for retour in (None, False, 1, 'oui', [True], 0):
        assert code(arbre, verifier_privileges=lambda _, r=retour: r) == (
            'plugin_privileges_rejected')
    assert code(arbre, verifier_privileges=leve) == 'plugin_privileges_rejected'
    os.remove(arbre / 'livre' / 'lire.toml')
    os.remove(arbre / 'livre' / 'lire')
    poser(arbre / 'local', 'lire', extra=PRIV)
    for retour in (None, False, 1, 'oui'):
        resultat = lancer(arbre, verifier_privileges=lambda _, r=retour: r)
        assert [r.code for r in resultat.rejets] == ['plugin_privileges_rejected']
    assert [r.code for r in lancer(arbre, verifier_privileges=leve).rejets] == [
        'plugin_privileges_rejected']
    resultat = lancer(arbre, verifier_privileges=lambda _: True)
    assert not resultat.rejets and 'exemple/objet/lire' in resultat.catalogue.actions


# --- bornes et valeurs fautives -----------------------------------------------------------

def base_delai(valeur):
    return BASE.replace('delai_s = 5', f'delai_s = {valeur}')


def test_bornes_sortie_max(arbre):
    poser(arbre / 'livre', 'lire')
    assert lancer(arbre).fonctions['exemple/objet/lire'].sortie_max == 65536
    os.remove(arbre / 'livre' / 'lire.toml')
    for valeur, accepte in ((PLAFOND_LIMITE, True), (PLAFOND_LIMITE + 1, False), ('true', False),
                            (0, False), (1, True)):
        poser(arbre / 'livre', 'lire', extra=f'sortie_max = {valeur}\n')
        if accepte:
            assert lancer(arbre).fonctions['exemple/objet/lire'].sortie_max == valeur
        else:
            assert code(arbre) == 'plugin_manifest_invalid'
        os.remove(arbre / 'livre' / 'lire.toml')


def test_bornes_delai(arbre):
    for valeur, accepte in ((0, False), (PLAFOND_DELAI, True), (PLAFOND_DELAI + 1, False)):
        poser(arbre / 'livre', 'lire', base=base_delai(valeur))
        if accepte:
            assert lancer(arbre).catalogue.descripteur('exemple/objet/lire').delai_s == valeur
        else:
            assert code(arbre) == 'plugin_manifest_invalid'
        os.remove(arbre / 'livre' / 'lire.toml')


def choix(*valeurs):
    liste = ', '.join(f'"{v}"' for v in valeurs)
    return f'[[parametres]]\nnom = "m"\ntype = "choix"\nvaleurs = [{liste}]\n'


@pytest.mark.parametrize('valeurs', [('-a',), ('a', '-b'), ('a', 'b', '--c')])
def test_valeur_de_choix_avec_tiret_initial_refusee(arbre, valeurs):
    poser(arbre / 'livre', 'lire', extra=choix(*valeurs))
    assert code(arbre) == 'plugin_manifest_invalid'
    os.remove(arbre / 'livre' / 'lire.toml')
    os.remove(arbre / 'livre' / 'lire')
    poser(arbre / 'local', 'lire', extra=choix(*valeurs))
    resultat = lancer(arbre)
    assert [r.code for r in resultat.rejets] == ['plugin_manifest_invalid']
    assert not any(v in repr(resultat.rejets) for v in valeurs if v.startswith('-'))


def test_valeur_de_choix_interieure_acceptee(arbre):
    poser(arbre / 'livre', 'lire', extra=choix('a-b', 'c'))
    assert lancer(arbre).catalogue.descripteur('exemple/objet/lire') is not None


def test_valeur_fautive_jamais_publiee(arbre):
    fautives = {
        'privilege = "secret-privilege"\n': 'secret-privilege',
        choix('-valeur-choix'): 'valeur-choix',
        'forme = "forme-secrete"\n': 'forme-secrete',
    }
    for extra in fautives:
        poser(arbre / 'local', 'lire', extra=extra)
        journal = Journal()
        resultat = lancer(arbre, rappel=journal)
        assert len(resultat.rejets) == 1
        publie = repr((resultat.rejets, journal.lignes))
        assert fautives[extra] not in publie and str(arbre) not in publie
        os.remove(arbre / 'local' / 'lire.toml')
    poser(arbre / 'local', 'lire', base=BASE.replace(
        'exemple/objet/{nom}', 'exemple/action-secrete/x/y/z'))
    journal = Journal()
    resultat = lancer(arbre, rappel=journal)
    assert resultat.rejets and 'action-secrete' not in repr((resultat.rejets, journal.lignes))


def test_nom_de_fichier_avec_controle_jamais_brut(arbre):
    (arbre / 'local' / 'a\x07b').write_text('x')
    (arbre / 'local' / 'c\x1bd.toml').write_text('x')
    journal = Journal()
    resultat = lancer(arbre, rappel=journal)
    assert resultat.rejets
    for rejet in resultat.rejets:
        assert rejet.file == 'invalid_name'
    for _, _, champs in journal.lignes:
        assert champs.get('file', 'invalid_name') == 'invalid_name'
    assert '\x07' not in repr((resultat.rejets, journal.lignes))
    assert '\x1b' not in repr((resultat.rejets, journal.lignes))


def test_introspection_de_bout_en_bout_sans_fuite(arbre):
    poser(arbre / 'livre', 'lire', extra=(
        'privilege = "utilisateurs"\nsortie_max = 4242\njournaliser = ["mode"]\n'
        + choix('a', 'b').replace('"m"', '"mode"')
        + '[[commandes_privilegiees]]\noperation = "exec"\n'
        'arguments = ["conteneur", "prog-fixe", {parametre = "mode"}]\n'
        '[requiert]\nfichiers = ["/chemin-condition-absent"]\n'))
    assert not lancer(arbre).catalogue.descripteur('exemple/objet/lire')
    os.remove(arbre / 'livre' / 'lire.toml')
    poser(arbre / 'livre', 'lire', extra=(
        'privilege = "utilisateurs"\nsortie_max = 4242\njournaliser = ["mode"]\n'
        + choix('a', 'b').replace('"m"', '"mode"')
        + '[[commandes_privilegiees]]\noperation = "exec"\n'
        'arguments = ["conteneur", "prog-fixe", {parametre = "mode"}]\n'
        f'[requiert]\nfichiers = ["{arbre}"]\n'))
    resultat = lancer(arbre)
    liste = resultat.catalogue.reponse('exemple/catalog/list', {})
    decrit = resultat.catalogue.reponse('exemple/catalog/describe',
                                        {'action': 'exemple/objet/lire'})
    assert set(liste) == {'proto', 'target', 'domain', 'format', 'actions'}
    assert set(decrit) == {'action', 'plugin', 'privilege', 'delay_s', 'parameters', 'errors'}
    assert set(decrit['parameters'][0]) == {'name', 'type', 'required', 'bounds'}
    publie = repr((liste, decrit))
    for interne in (str(arbre), 'prog-fixe', 'conteneur', 'journaliser', '4242', 'sortie_max',
                    'requiert', 'commandes', 'script'):
        assert interne not in publie


# --- aucune exécution ---------------------------------------------------------------------

# Les clés des imports relatifs incluent le niveau ; les alias sont explicites.
IMPORTS_ADMIS = {
    'catalogue': {
        'math', 're', (0, 'dataclasses', 'dataclass', None), (0, 'dataclasses', 'field', None),
        (0, 'types', 'MappingProxyType', None), (1, 'texte', 'filtrer', None)},
    'privileges': {'re', (0, 'dataclasses', 'dataclass', None)},
    'sortie': {
        'math', (1, 'jumeaux', 'PLAFOND_LIMITE', None),
        (1, 'jumeaux', 'charger_json_strict', None), (1, 'texte', 'filtrer', None)},
    'plugins': {
        'math', 'os', 're', 'stat', 'tomllib', (0, 'dataclasses', 'dataclass', None), (0, 'dataclasses', 'field', None),
        (0, 'types', 'MappingProxyType', None), (1, '', 'catalogue', 'cat'),
        (1, 'catalogue', 'Catalogue', None), (1, 'catalogue', 'Parametre', None),
        (1, 'catalogue', 'creer_descripteur', None), (1, 'catalogue', 'nom_varlink', None),
        (1, 'jumeaux', 'PLAFOND_DELAI', None), (1, 'jumeaux', 'PLAFOND_LIMITE', None),
        (1, 'privileges', 'valeurs_choix_valides', None),
        (1, 'privileges', 'valider_commandes', None), (1, 'privileges', 'vers_sudo', None),
        (1, 'sortie', 'SORTIE_MAX_DEFAUT', None), (1, 'texte', 'filtrer', None)},
}
ATTRIBUTS_ADMIS = {
    'os': {'open', 'O_NOFOLLOW', 'O_CLOEXEC', 'O_RDONLY', 'O_DIRECTORY', 'O_NONBLOCK',
           'fstat', 'stat', 'close', 'read', 'listdir', 'fspath', 'path'},
    'os.path': {'abspath', 'basename', 'join'},
    'stat': {'S_ISDIR', 'S_ISREG', 'S_ISLNK'},
    'tomllib': {'loads', 'TOMLDecodeError'},
}


def verifier_imports_admis(source, admis):
    """Contrôle statique par refus par défaut, sans importer ni exécuter la source."""
    interdits = {'exec', 'eval', 'compile', '__import__', 'importlib', 'getattr', 'entry_points'}
    arbre = ast.parse(source)
    re_importe = any(
        isinstance(n, ast.Import) and any(a.name == 're' and a.asname is None for a in n.names)
        for n in ast.walk(arbre))
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            for alias in noeud.names:
                assert alias.asname is None and alias.name in admis
        elif isinstance(noeud, ast.ImportFrom):
            for alias in noeud.names:
                assert alias.name != '*'
                assert (noeud.level, noeud.module or '', alias.name, alias.asname) in admis
        elif isinstance(noeud, ast.Name):
            assert noeud.id not in interdits
            if noeud.id in ATTRIBUTS_ADMIS:
                assert noeud.id in admis
        elif isinstance(noeud, ast.Attribute):
            if noeud.attr == 'compile':
                assert (isinstance(noeud.value, ast.Name) and noeud.value.id == 're'
                        and re_importe and 're' in admis)
            else:
                assert noeud.attr not in interdits and not noeud.attr.startswith('exec')
            assert noeud.attr not in {'system', 'popen', 'spawn', 'import_module'}
            parent = noeud.value
            if isinstance(parent, ast.Name) and parent.id in ATTRIBUTS_ADMIS:
                assert noeud.attr in ATTRIBUTS_ADMIS[parent.id]
            elif (isinstance(parent, ast.Attribute) and isinstance(parent.value, ast.Name)
                  and parent.value.id == 'os' and parent.attr == 'path'):
                assert noeud.attr in ATTRIBUTS_ADMIS['os.path']


def test_modules_sans_execution_ni_import_dynamique():
    racine = Path(plugins.__file__).parent
    for nom, admis in IMPORTS_ADMIS.items():
        verifier_imports_admis((racine / f'{nom}.py').read_text(), admis)


@pytest.mark.parametrize('module', ['catalogue', 'plugins', 'privileges'])
def test_analyse_admet_re_compile(module):
    verifier_imports_admis("import re\nre.compile('x')", IMPORTS_ADMIS[module])


def test_listes_imports_admis_fermees():
    interdits = {'subprocess', 'ctypes', 'multiprocessing', 'socket', 'pty', 'shlex',
                 'importlib', 'runpy', 'pkgutil', '*'}
    for nom, admis in IMPORTS_ADMIS.items():
        for entree in admis:
            mots = {entree} if isinstance(entree, str) else set(entree)
            assert not mots & interdits
        assert (admis & {'os', 'stat', 'tomllib'}) == (
            {'os', 'stat', 'tomllib'} if nom == 'plugins' else set())


@pytest.mark.parametrize('module', IMPORTS_ADMIS)
@pytest.mark.parametrize('source', [
    forme.format(module=module)
    for module in ('ctypes', 'multiprocessing', 'socket', 'pty', 'shlex')
    for forme in ('import {module}', 'import {module}.sous_module as alias',
                  'from {module} import objet', 'from {module}.sous_module import objet')
] + [
    f'os.{nom}' for nom in ('fork', 'forkpty', 'posix_spawn', 'posix_spawnp',
                           'exec', 'execl', 'execle', 'execlp', 'execlpe',
                           'execv', 'execve', 'execvp', 'execvpe', 'exec_inconnu')
 ] + [
    forme.format(nom=nom)
    for nom in ('fork', 'forkpty', 'posix_spawn', 'posix_spawnp', 'execv', 'exec_inconnu')
    for forme in ('from os import {nom}', 'from os import {nom} as alias',
                  'import os as o; o.{nom}()')
 ] + ['objet.execute', 'objet.execution()', 'from os import *; fork()',
     'getattr(os, "fork")()', 'os.spawnv(...)', 'import subprocess', 'import importlib',
     '__import__("x")', 'exec(...)', 'eval(...)', 'compile(...)', 'import json',
     'builtins.compile(...)', 'os.compile(...)', 'o.compile(...)', 'x.y.compile(...)',
     're.compile("x")', 'import re as r; r.compile("x")',
     'def cache():\n    import subprocess', 'if True:\n    import socket',
     'try:\n    import pty\nexcept Exception:\n    pass', 'import runpy', 'import pkgutil',
     'os.path.inconnu', 'stat.inconnu', 'tomllib.inconnu', 'from math import *',
     'from texte import filtrer', 'from ..texte import filtrer', 'import math as m',
     'from .texte import filtrer as f', 'objet.entry_points', 'objet.import_module',
     'objet.system()', 'objet.popen()', 'objet.spawn()'])
def test_analyse_refuse_modules_forges(tmp_path, source, module):
    chemin = tmp_path / 'module_forge.py'
    chemin.write_text(source)
    with pytest.raises(AssertionError):
        verifier_imports_admis(chemin.read_text(), IMPORTS_ADMIS[module])


@pytest.mark.parametrize('nom', ['a\nb', '\n'])
def test_nom_erreur_fatale_filtre(arbre, nom):
    (arbre / 'livre' / nom).write_text('x')
    with pytest.raises(ErreurPlugin) as erreur:
        lancer(arbre)
    assert erreur.value.code == 'plugin_unexpected_entry'
    assert erreur.value.fichier == 'invalid_name'


@pytest.mark.parametrize('defaut', ['dossier', 'ancetre'])
def test_defaut_dossier_local_ecarte_toutes_ses_fonctions(arbre, defaut):
    poser(arbre / 'livre', 'livree')
    parent = arbre / 'extensions'
    parent.mkdir(mode=0o755)
    local = parent / 'local'
    local.mkdir(mode=0o755)
    for nom in ('premiere', 'seconde'):
        poser(local, nom)
    os.chmod(local if defaut == 'dossier' else parent, 0o777)
    resultat = charger('yin', 'exemple', arbre / 'livre', local, codes_connus=CONNUS,
                       proprietaires={MOI}, racine_confiance=arbre)
    assert set(resultat.fonctions) == {'exemple/objet/livree'}
    assert resultat.catalogue.actions == {
        'exemple/objet/livree', 'exemple/catalog/list', 'exemple/catalog/describe'}
    assert [(r.code, r.file) for r in resultat.rejets] == [
        ('plugin_unsafe_permissions', 'local')]


@pytest.mark.parametrize('operation', ['lecture', 'ouverture', 'stat'])
@pytest.mark.parametrize('scope', ['local', 'livre'])
def test_erreur_es_fonction_isolee(arbre, monkeypatch, operation, scope):
    poser(arbre / 'livre', 'livree')
    for nom in ('aaa', 'bbb', 'ccc'):
        poser(arbre / scope, nom)
    journal = Journal()
    if operation == 'lecture':
        originale = plugins._lire_manifeste
        compteur = 0

        def lire(fd):
            nonlocal compteur
            compteur += 1
            if compteur == (3 if scope == 'local' else 2):
                raise OSError()
            return originale(fd)

        monkeypatch.setattr(plugins, '_lire_manifeste', lire)
    else:
        nom_operation = 'ouvrir_fichier_controle' if operation == 'ouverture' else '_verifier_type'
        originale = getattr(plugins, nom_operation)

        def echouer(nom, *args, **kwargs):
            if nom == 'bbb':
                raise OSError()
            return originale(nom, *args, **kwargs)

        monkeypatch.setattr(plugins, nom_operation, echouer)
    if scope == 'livre':
        with pytest.raises(ErreurPlugin) as erreur:
            lancer(arbre, rappel=journal)
        assert (erreur.value.code, erreur.value.fichier) == ('plugin_unreadable', 'bbb')
        return
    resultat = lancer(arbre, rappel=journal)
    assert set(resultat.fonctions) == {
        'exemple/objet/livree', 'exemple/objet/aaa', 'exemple/objet/ccc'}
    assert 'exemple/objet/bbb' not in resultat.catalogue.actions
    assert [(r.code, r.scope, r.file) for r in resultat.rejets] == [
        ('plugin_unreadable', 'local', 'bbb')]
    assert [champs for evenement, _, champs in journal.lignes
            if evenement == 'plugin_rejected'] == [
        {'code': 'plugin_unreadable', 'scope': 'local', 'file': 'bbb'}]


@pytest.mark.parametrize('operation', ['ouverture', 'enumeration', 'enumeration_tardive'])
def test_erreur_es_dossier_local_atomique(arbre, monkeypatch, operation):
    poser(arbre / 'livre', 'livree')
    for nom in ('aaa', 'bbb', 'ccc'):
        poser(arbre / 'local', nom)
    journal = Journal()
    chargees = []
    charger_une = plugins._charger_une

    def observer(*args, **kwargs):
        charger_une(*args, **kwargs)
        chargees.append(args[0])

    monkeypatch.setattr(plugins, '_charger_une', observer)
    if operation == 'ouverture':
        ouvrir = plugins.ouvrir_dossier_confiance

        def ouvrir_local(dossier, *args):
            if dossier == arbre / 'local':
                raise OSError()
            return ouvrir(dossier, *args)

        monkeypatch.setattr(plugins, 'ouvrir_dossier_confiance', ouvrir_local)
    else:
        entrees = plugins._entrees

        class EnumerationDefaillante(dict):
            def __getitem__(self, nom):
                if nom == 'bbb':
                    assert 'aaa' in chargees
                    raise OSError()
                return super().__getitem__(nom)

        def enumerer(fd):
            groupes, inattendues = entrees(fd)
            if 'aaa' in groupes:
                if operation == 'enumeration':
                    raise OSError()
                return EnumerationDefaillante(groupes), inattendues
            return groupes, inattendues

        monkeypatch.setattr(plugins, '_entrees', enumerer)
    resultat = lancer(arbre, rappel=journal)
    assert set(resultat.fonctions) == {'exemple/objet/livree'}
    assert resultat.catalogue.actions == {
        'exemple/objet/livree', 'exemple/catalog/list', 'exemple/catalog/describe'}
    assert [(r.code, r.scope, r.file) for r in resultat.rejets] == [
        ('plugin_unreadable', 'local', 'local')]
    assert [(evenement, niveau, champs) for evenement, niveau, champs in journal.lignes
            if champs['scope'] == 'local'] == [
        ('plugin_rejected', 'error',
         {'code': 'plugin_unreadable', 'scope': 'local', 'file': 'local'})]


@pytest.mark.parametrize('valeur', ['[[1]]', '[1]', '["inconnu"]', '"texte"', '["m", "m"]'])
@pytest.mark.parametrize('scope', ['local', 'livre'])
def test_journaliser_invalide_type(arbre, scope, valeur):
    for nom in ('aaa', 'ccc'):
        poser(arbre / scope, nom)
    poser(arbre / scope, 'bbb', extra=f'journaliser = {valeur}\n' + choix('a'))
    journal = Journal()
    if scope == 'livre':
        with pytest.raises(ErreurPlugin) as erreur:
            lancer(arbre, rappel=journal)
        assert (erreur.value.code, erreur.value.fichier) == ('plugin_manifest_invalid', 'bbb')
        assert str(erreur.value) == 'plugin_manifest_invalid'
    else:
        resultat = lancer(arbre, rappel=journal)
        assert set(resultat.fonctions) == {'exemple/objet/aaa', 'exemple/objet/ccc'}
        assert [(r.code, r.scope, r.file) for r in resultat.rejets] == [
            ('plugin_manifest_invalid', 'local', 'bbb')]
        assert [champs for evenement, _, champs in journal.lignes
                if evenement == 'plugin_rejected'] == [
            {'code': 'plugin_manifest_invalid', 'scope': 'local', 'file': 'bbb'}]
    assert valeur not in repr(journal.lignes)


EXCEPTIONS_INJECTEES = [RuntimeError, TypeError, ValueError, KeyError, RecursionError,
                       UnicodeDecodeError, OSError]


def lever_defaut(type_erreur):
    if type_erreur is UnicodeDecodeError:
        raise type_erreur('utf-8', b'\xff', 0, 1, 'diagnostic_interne')
    raise type_erreur('diagnostic_interne')


@pytest.mark.parametrize('type_erreur', EXCEPTIONS_INJECTEES)
@pytest.mark.parametrize('scope', ['local', 'livre'])
@pytest.mark.parametrize('frontiere', ['fonction', 'condition', 'dossier', 'fusion'])
def test_seule_erreur_plugin_sort(arbre, monkeypatch, type_erreur, scope, frontiere):
    if scope == 'local':
        poser(arbre / 'livre', 'livree')
    for nom in ('aaa', 'bbb', 'ccc'):
        extra = '[requiert]\nfichiers = ["/condition"]\n' if nom == 'bbb' else ''
        poser(arbre / scope, nom, extra=extra)
    if frontiere == 'fonction':
        originale = plugins._manifeste

        def manifeste(table, nom, *args):
            if nom == 'bbb':
                lever_defaut(type_erreur)
            return originale(table, nom, *args)

        monkeypatch.setattr(plugins, '_manifeste', manifeste)
    elif frontiere == 'condition':
        def condition(*args):
            lever_defaut(type_erreur)

        monkeypatch.setattr(plugins, '_condition_remplie', condition)
    elif frontiere == 'dossier':
        originale = plugins._entrees

        class Groupes(dict):
            def __getitem__(self, nom):
                if nom == 'bbb':
                    lever_defaut(type_erreur)
                return super().__getitem__(nom)

        def entrees(fd):
            groupes, inattendues = originale(fd)
            return Groupes(groupes), inattendues

        monkeypatch.setattr(plugins, '_entrees', entrees)
    else:
        originale = plugins.Catalogue

        def catalogue(cible, domaine, descripteurs):
            if any(d.action == 'exemple/objet/aaa' for d in descripteurs):
                lever_defaut(type_erreur)
            return originale(cible, domaine, descripteurs)

        monkeypatch.setattr(plugins, 'Catalogue', catalogue)
    par_fonction = frontiere in {'fonction', 'condition'}
    attendu = ('plugin_manifest_invalid' if par_fonction and type_erreur is not OSError
               else 'plugin_unreadable')
    fichier = 'bbb' if par_fonction else scope
    journal = Journal()
    if scope == 'livre':
        with pytest.raises(ErreurPlugin) as erreur:
            lancer(arbre, rappel=journal)
        assert (erreur.value.code, erreur.value.fichier) == (attendu, fichier)
        assert 'diagnostic_interne' not in str(erreur.value)
    else:
        resultat = lancer(arbre, rappel=journal)
        gardees = {'exemple/objet/livree'}
        if par_fonction:
            gardees |= {'exemple/objet/aaa', 'exemple/objet/ccc'}
        assert set(resultat.fonctions) == gardees
        assert resultat.catalogue.actions == gardees | {
            'exemple/catalog/list', 'exemple/catalog/describe'}
        assert [(r.code, r.scope, r.file) for r in resultat.rejets] == [
            (attendu, 'local', fichier)]
        assert [champs for evenement, _, champs in journal.lignes
                if evenement == 'plugin_rejected'] == [
            {'code': attendu, 'scope': 'local', 'file': fichier}]
        if not par_fonction:
            assert not any(e == 'plugin_loaded' and c['scope'] == 'local'
                           for e, _, c in journal.lignes)
    assert 'diagnostic_interne' not in repr(journal.lignes)


PRODUIT = '[produit]\nnom = "outil"\nsource = "https://example.org/outil"\nversion = "{v}"\n'


def test_produit_et_compatibles_exposes(arbre):
    extra = 'compatible_yang = ["paresia-yang-outil"]\n' + PRODUIT.format(v='>=1.1.3,<2')
    poser(arbre / 'livre', 'lire', extra=extra)
    poser(arbre / 'livre', 'ecrire', extra=extra)
    resultat = lancer(arbre)
    donnees = resultat.greffons['paresia-yin-exemple']
    assert donnees['produit']['nom'] == 'outil' and donnees['produit']['empreinte'] is None
    assert donnees['compatible_yang'] == ('paresia-yang-outil',)
    assert 'example.org' not in repr(resultat.fonctions['exemple/objet/lire'])
    assert 'example.org' not in repr(resultat.catalogue.reponse('exemple/catalog/list', {}))


def test_sans_produit_comme_avant(arbre):
    poser(arbre / 'livre', 'lire')
    r = lancer(arbre)
    assert r.fonctions['exemple/objet/lire'].produit is None
    assert r.greffons['paresia-yin-exemple']['compatible_yang'] == ()


@pytest.mark.parametrize('extra', [
    'compatible_yang = "paresia-yang-x"\n',
    'compatible_yang = ["paresia-yin-x"]\n',
    'compatible_yang = ["paresia-yang-x", "paresia-yang-x"]\n',
    'compatible_yang = [%s]\n' % ', '.join('"paresia-yang-n%d"' % i for i in range(17)),
    PRODUIT.format(v='') ,
    PRODUIT.format(v='>=1,'),
    PRODUIT.format(v='~1'),
    PRODUIT.format(v='>=1,<2,<3,<4,<5'),
    PRODUIT.format(v='1 2'),
    '[produit]\nnom = "o"\nsource = "x"\n',
    PRODUIT.format(v='1') + 'inconnue = 1\n',
    PRODUIT.format(v='1') + 'empreinte = "sha256:abc"\n',
    PRODUIT.format(v='1') + 'empreinte = "sha256:' + 'A' * 64 + '"\n',
    '[produit]\nnom = "O"\nsource = "x"\nversion = "1"\n',
    '[produit]\nnom = "o"\nsource = "a b"\nversion = "1"\n',
    '[produit]\nnom = "o"\nsource = "' + 'a' * 257 + '"\nversion = "1"\n',
])
def test_produit_invalide(arbre, extra):
    poser(arbre / 'livre', 'lire', extra=extra)
    assert code(arbre) == 'plugin_manifest_invalid'


def test_empreinte_valide(arbre):
    poser(arbre / 'livre', 'lire', extra=PRODUIT.format(v='4cd3cf6') + 'empreinte = "sha256:' + 'a' * 64 + '"\n')
    assert lancer(arbre).greffons['paresia-yin-exemple']['produit']['empreinte'] == 'sha256:' + 'a' * 64


def test_incoherence_entre_fonctions(arbre):
    poser(arbre / 'livre', 'lire', extra=PRODUIT.format(v='1'))
    poser(arbre / 'livre', 'ecrire', extra=PRODUIT.format(v='2'))
    assert code(arbre) == 'plugin_manifest_invalid'
    poser(arbre / 'livre', 'ecrire', extra='')
    assert code(arbre) == 'plugin_manifest_invalid'


def test_incoherence_dossier_local_ignore(arbre):
    poser(arbre / 'local', 'lire', extra=PRODUIT.format(v='1'))
    poser(arbre / 'local', 'ecrire', extra=PRODUIT.format(v='2'))
    r = lancer(arbre)
    assert not r.fonctions and r.rejets[0].code == 'plugin_manifest_invalid'
