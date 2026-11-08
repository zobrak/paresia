# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests du socle client ; dépendances : bibliothèque standard, server.commun et pytest.
# Suivi des versions
#   0.1.19  2026-11-08  Refus du caractère pour cent dans l’adresse HTTPS.
#   0.1.14  2026-11-08  Fenêtre et point d'entrée seuls autorisés à importer PyQt6.
#   0.1.12  2026-11-08  Option ssh_keygen dans l'exemple complet.
#   3.0.0-alpha.40  2026-11-06  Couches, validations, catalogues et affichage sûr.
#   3.0.0-alpha.40  2026-11-06  Clés non textuelles et contrôle des langues dans admin.
import ast
import configparser
import json
import os
from pathlib import Path

import pytest

from admin.app.config import SCHEMA, configuration
from admin.app.textes import afficher, charger, diagnostic
from server.commun.config import ErreurConfiguration
from server.commun.jumeaux import CODES_ERREUR


RACINE = Path(__file__).resolve().parents[1]
EXEMPLE = RACINE / 'admin/app/conf/paresia-admin.conf'


@pytest.fixture
def couches(tmp_path):
    systeme = tmp_path / 'systeme'
    utilisateur = tmp_path / 'utilisateur'
    systeme.mkdir(mode=0o700)
    (systeme / 'conf.d').mkdir(mode=0o700)
    (utilisateur / 'paresia').mkdir(mode=0o700, parents=True)
    (systeme / 'paresia.conf').write_bytes(EXEMPLE.read_bytes())
    return systeme, utilisateur


def lire_couches(couches, environ=None):
    systeme, utilisateur = couches
    return configuration([], environ={} if environ is None else environ,
                         racine_systeme=systeme, repertoire_utilisateur=utilisateur)


def test_exemple_complet(couches):
    fichier = configparser.ConfigParser()
    fichier.read(EXEMPLE, encoding='utf-8')
    assert {(section.removeprefix('admin.'), cle)
            for section in fichier.sections() for cle in fichier[section]} == SCHEMA.keys()
    assert lire_couches(couches) == {
        'connexion': {'url': 'https://bunker.example.org',
                      'hote_ssh': 'backend-admin.example.org', 'compte_ssh': 'app',
                      'ssh': '/usr/bin/ssh'},
        'cle': {'cle_publique': '/etc/paresia/admin.pub',
                'commande_forcee': '/usr/local/bin/pollux-session',
                'ssh_keygen': '/usr/bin/ssh-keygen'},
        'presence': {'ouverture_s': 90},
        'interface': {'langue': 'fr-FR', 'dossier_i18n': '/usr/local/share/paresia/i18n'},
    }


def test_priorite_des_quatre_couches(couches):
    systeme, utilisateur = couches
    assert lire_couches(couches)['presence']['ouverture_s'] == 90
    (systeme / 'conf.d/20-presence.conf').write_text('[admin.presence]\nouverture_s = 120\n')
    (systeme / 'conf.d/10-presence.conf').write_text('[admin.presence]\nouverture_s = 100\n')
    assert lire_couches(couches)['presence']['ouverture_s'] == 120
    (utilisateur / 'paresia/client.conf').write_text('[admin.presence]\nouverture_s = 150\n')
    assert lire_couches(couches)['presence']['ouverture_s'] == 150
    assert lire_couches(couches, {'PARESIA_ADMIN_PRESENCE_OUVERTURE_S': '180'})[
        'presence']['ouverture_s'] == 180
    assert configuration([], environ={'XDG_CONFIG_HOME': str(utilisateur)},
                         racine_systeme=systeme)['presence']['ouverture_s'] == 150


def test_defaut_et_option_obligatoire(couches):
    chemin = couches[0] / 'paresia.conf'
    contenu = chemin.read_text().replace('ouverture_s = 90', '')
    chemin.write_text(contenu)
    assert lire_couches(couches)['presence']['ouverture_s'] == 90
    chemin.write_text(contenu.replace('compte_ssh = app', ''))
    with pytest.raises(ErreurConfiguration, match='^config_missing:connexion:compte_ssh$'):
        lire_couches(couches)


def test_configuration_explicite(couches):
    assert configuration(['--config', str(EXEMPLE)], environ={},
                         racine_systeme=couches[0], repertoire_utilisateur=couches[1])[
        'interface']['langue'] == 'fr-FR'


def test_permissions_utilisateur(couches):
    fichier = couches[1] / 'paresia/client.conf'
    fichier.write_text('[admin.interface]\nlangue = en-US\n')
    fichier.chmod(0o666)
    with pytest.raises(ErreurConfiguration, match='^config_unsafe_permissions$'):
        lire_couches(couches)


@pytest.mark.parametrize('domaine,cle,valeur', [
    ('connexion', 'url', valeur) for valeur in (
        'https://[2001:db8::1%25zone]:8443',
        'http://bunker.example.org', 'https://', 'https://bunker.example.org/',
        'https://bunker.example.org/api', 'https://app@bunker.example.org',
        'https://bunker.example.org?x=1', 'https://bunker.example.org?',
        'https://bunker.example.org#fragment', 'https://bunker.example.org#',
        'https://bunker.example.org:99999', 'https://bunker.example.org:',
        'https://bunker.example.org:0', 'https://[2001:db8::1]suffix',
        'https://bun\u202eker.example.org', 'https://bunker.example.org\\suffix',
    )
] + [
    ('connexion', 'hote_ssh', valeur) for valeur in (
        '-option', 'backend admin.example.org', 'backend\tadmin.example.org',
        'backend\u202eadmin.example.org', 'app@backend-admin.example.org',
        'backend/admin', 'backend..example.org', '2001:db8::1%zone/chemin',
    )
] + [
    ('interface', 'langue', valeur) for valeur in ('../x', 'fr', 'FR-fr', 'fr-FR\n', 'fr-FR-extra')
])
def test_configuration_invalide(couches, domaine, cle, valeur):
    with pytest.raises(ErreurConfiguration) as erreur:
        lire_couches(couches, {f'PARESIA_ADMIN_{domaine.upper()}_{cle.upper()}': valeur})
    assert str(erreur.value) == f'config_invalid:{domaine}:{cle}'


@pytest.mark.parametrize('url,hote', [
    ('https://bunker.example.org:8443', 'backend-admin.example.org'),
    ('https://192.0.2.1', '192.0.2.1'),
    ('https://[2001:db8::1]:8443', '2001:db8::1'),
])
def test_adresses_valides(couches, url, hote):
    connexion = lire_couches(couches, {'PARESIA_ADMIN_CONNEXION_URL': url,
                                      'PARESIA_ADMIN_CONNEXION_HOTE_SSH': hote})['connexion']
    assert connexion['url'] == url
    assert connexion['hote_ssh'] == hote


def test_catalogues_et_codes():
    catalogues = [json.loads((RACINE / 'i18n' / (langue + '.json')).read_text())
                 for langue in ('fr-FR', 'en-US')]
    assert catalogues[0].keys() == catalogues[1].keys()
    for langue, attendu in zip(('fr-FR', 'en-US'), catalogues):
        catalogue = charger(langue, RACINE / 'i18n')
        for cle in ('ui_app_titre', 'ui_config_invalide'):
            assert attendu[cle] and catalogue.erreur(cle) == attendu[cle]
        for code in CODES_ERREUR:
            assert catalogue.erreur(code) == attendu[code]
        assert catalogue.libelle('cle_absente') == 'cle_absente'
        for code in ('code_inconnu', 'state_running', 'ui_inconnu', None, {}, []):
            assert catalogue.erreur(code) == attendu['internal_error']
    assert charger('zz-ZZ', RACINE / 'i18n').libelle('internal_error') == catalogues[0]['internal_error']


@pytest.mark.parametrize('cle', [None, 42, b'ui_app_titre', {}, []])
def test_libelle_cle_non_textuelle(cle):
    assert charger('fr-FR', RACINE / 'i18n').libelle(cle) == ''


@pytest.mark.parametrize('langue', ['../x', '', 'fr', 'fr/fr', 'fr-FR\n', None, []])
def test_langue_refusee_avant_chemin(langue):
    class DossierInterdit:
        def __fspath__(self):
            pytest.fail('Le chemin ne doit pas être construit pour une langue invalide')

    with pytest.raises(ValueError, match='^catalogue_invalid_language$'):
        charger(langue, DossierInterdit())


@pytest.mark.parametrize('contenu', [b'[]', b'{"x": 1}', b'{"x": null}', b'{', b'\xff',
                                     b' ' * (1024 * 1024 + 1)])
def test_catalogue_invalide_sans_repli(tmp_path, contenu):
    (tmp_path / 'fr-FR.json').write_text('{"x": "repli"}')
    (tmp_path / 'en-US.json').write_bytes(contenu)
    with pytest.raises(ValueError, match='^catalogue_invalid$'):
        charger('en-US', tmp_path)


def test_catalogue_taille_limite(tmp_path):
    contenu = b'{"x":"valeur"}'
    (tmp_path / 'fr-FR.json').write_bytes(contenu + b' ' * (1024 * 1024 - len(contenu)))
    assert charger('fr-FR', tmp_path).libelle('x') == 'valeur'


@pytest.mark.parametrize('genre', ['dossier', 'fifo', 'lien'])
def test_catalogue_non_regulier(tmp_path, genre):
    chemin = tmp_path / 'fr-FR.json'
    if genre == 'dossier':
        chemin.mkdir()
    elif genre == 'fifo':
        os.mkfifo(chemin)
    else:
        cible = tmp_path / 'cible.json'
        cible.write_text('{}')
        chemin.symlink_to(cible)
    with pytest.raises(ValueError, match='^catalogue_(invalid|unreadable)$'):
        charger('fr-FR', tmp_path)


def test_catalogue_par_defaut_absent(tmp_path):
    with pytest.raises(ValueError, match='^catalogue_unreadable$'):
        charger('zz-ZZ', tmp_path)


def test_filtrage_et_diagnostic(tmp_path):
    dangereux = '\x1b\u202e\u2028\ud800\ue000'
    assert afficher(dangereux) == '\ufffd' * 5
    assert afficher('Étiquette sûre') == 'Étiquette sûre'
    assert diagnostic(dangereux + 'x' * 300) == '\ufffd' * 5 + 'x' * 195
    for valeur in (None, 42, b'texte', {}, []):
        assert afficher(valeur) == diagnostic(valeur) == ''
    (tmp_path / 'fr-FR.json').write_text(json.dumps({'ui_test': dangereux,
                                                    'internal_error': dangereux,
                                                    'autre': 'non autorisé'}))
    catalogue = charger('fr-FR', tmp_path)
    assert catalogue.libelle('ui_test') == catalogue.erreur('ui_test') == '\ufffd' * 5
    assert catalogue.libelle(dangereux) == '\ufffd' * 5
    assert catalogue.erreur('autre') == '\ufffd' * 5


def test_aucun_import_graphique():
    autorises = {'fenetre.py', '__main__.py'}
    for fichier in (RACINE / 'admin/app').glob('*.py'):
        if fichier.name in autorises:
            continue
        arbre = ast.parse(fichier.read_text())
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                assert all(nom.name.split('.')[0] != 'PyQt6' for nom in noeud.names)
            elif isinstance(noeud, ast.ImportFrom):
                assert (noeud.module or '').split('.')[0] != 'PyQt6'
    for nom in ('controleur', 'presence', 'cles', 'config', 'textes', 'signature'):
        assert (RACINE / 'admin/app' / (nom + '.py')).is_file()


def test_admin_aucun_nom_posix_residuel():
    anciens = [a + '_' + b for a, b in [('fr', 'FR'), ('en', 'US')]]
    for fichier in (RACINE / 'admin').rglob('*'):
        if (not fichier.is_file() or '__pycache__' in fichier.parts
                or 'secrets' in fichier.parts or fichier.suffix in ('.key', '.pyc')
                or fichier.name == '.env'):
            continue
        contenu = fichier.read_bytes()
        if b'\x00' in contenu:
            continue
        try:
            texte = contenu.decode('utf-8')
        except UnicodeDecodeError:
            continue
        assert not any(nom in texte for nom in anciens), fichier.relative_to(RACINE)
