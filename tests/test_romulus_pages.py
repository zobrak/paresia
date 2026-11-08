# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests de l'index des pages des greffons yang (server.romulus.pages) ; dépendances : pytest, bibliothèque standard et server.
# Suivi des versions
#   0.1.9  2026-11-08  Création : index, contrôle des fichiers, vérification, ligne de commande.
import io
import json
import os
from pathlib import Path
import re

import pytest

from server.commun import services
from server.romulus import pages

EUID = os.geteuid()
RACINE = Path(__file__).resolve().parents[1]


def declaration(nom, *scripts):
    court = nom.replace('-', '_')
    texte = (f'format = 1\ngreffon = "paresia-yang-{nom}"\ndomaine = "{court}"\n'
             'sans_destination = true\ncatalogue = "aucun"\n')
    for i, script in enumerate(scripts):
        texte += (f'[[pages]]\nid = "p{i}"\ntitre_cle = "ui_{court}_t{i}"\nscript = "{script}"\n')
    return texte


def ecrire(chemin, texte, mode=0o644):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(texte, encoding='utf-8')
    chemin.chmod(mode)


class Monde:
    """Arbre factice : déclarations livrées, dossier des pages, propriétaires injectés."""

    def __init__(self, racine):
        self.racine = racine
        self.livrees = racine / 'services'
        self.pages = racine / 'web' / 'greffons'
        for dossier in (self.livrees, self.pages):
            dossier.mkdir(parents=True)
        for chemin in (racine, racine / 'web', self.livrees, self.pages):
            chemin.chmod(0o755)

    def greffon(self, nom, scripts=('a.js',), catalogue=None, en=True):
        court = nom.replace('-', '_')
        ecrire(self.livrees / f'paresia-yang-{nom}.toml', declaration(nom, *scripts))
        base = self.pages / nom
        for script in scripts:
            ecrire(base / script, '// page\n')
        catalogue = catalogue if catalogue is not None else {f'ui_{court}_titre': 'Titre'}
        ecrire(base / 'i18n' / 'fr-FR.json', json.dumps(catalogue))
        if en:
            ecrire(base / 'i18n' / 'en-US.json', json.dumps(catalogue))
        for dossier in (base, base / 'i18n'):
            dossier.chmod(0o755)

    def declarations(self):
        return pages.charger_livrees(self.livrees, proprietaires=frozenset({EUID}),
                                     racine_confiance=self.racine)

    def options(self):
        return {'proprietaires': frozenset({EUID}), 'racine_confiance': self.racine}

    def index(self):
        return pages.construire_index(self.declarations(), self.pages, **self.options())

    def cli(self, *arguments):
        erreur, sortie = io.StringIO(), io.StringIO()
        code = pages.main(list(arguments), erreur=erreur, sortie=sortie, environ={},
                          dossier_livre=self.livrees, **self.options())
        return code, sortie.getvalue(), erreur.getvalue()


@pytest.fixture
def monde(tmp_path):
    return Monde(tmp_path)


def test_index_forme_exacte_tri_ascii(monde):
    monde.greffon('zeta', ('b.js', 'a.js'))
    monde.greffon('alpha')
    octets = monde.index()
    objet = json.loads(octets)
    assert octets.isascii() and len(octets) <= 65536
    assert list(objet) == ['format', 'greffons'] and objet['format'] == 1
    assert [g['nom'] for g in objet['greffons']] == ['alpha', 'zeta']
    assert all(list(g) == ['nom', 'pages'] for g in objet['greffons'])
    zeta = objet['greffons'][1]['pages']
    assert [p['id'] for p in zeta] == ['p0', 'p1']
    assert all(list(p) == ['id', 'titre_cle', 'script'] for p in zeta)
    assert zeta[0] == {'id': 'p0', 'titre_cle': 'ui_zeta_t0', 'script': 'b.js'}


def test_forme_conforme_au_contrat_du_client():
    """Les clés de l'index sont celles que lit le client des greffons (admin/web/greffons.js)."""
    source = (RACINE / 'admin/web/greffons.js')
    if not source.exists():
        pytest.skip('client des greffons absent de cette branche')
    texte = source.read_text(encoding='utf-8')
    for cle in ('format', 'greffons', 'nom', 'pages', 'titre_cle', 'script'):
        assert cle in texte


def test_index_vide_sans_greffon_a_pages(monde):
    assert json.loads(monde.index()) == {'format': 1, 'greffons': []}


def test_ecriture_atomique_mode_et_contenu(monde):
    monde.greffon('alpha')
    pages.ecrire(monde.declarations(), monde.pages, **monde.options())
    chemin = monde.pages / 'index.json'
    assert chemin.read_bytes() == monde.index()
    assert (chemin.stat().st_mode & 0o7777) == 0o644
    assert [p.name for p in monde.pages.iterdir() if p.name.startswith('.')] == []
    pages.verifier(monde.declarations(), monde.pages, **monde.options())


def test_taille_maximale_de_l_index(monde):
    for i in range(60):
        monde.greffon(f'g{i:02d}-' + 'x' * 20, tuple(f'{"s" * 50}{j}.js' for j in range(16)))
    with pytest.raises(pages.ErreurPages) as e:
        monde.index()
    assert e.value.code == 'pages_too_large'


def defauts(monde, preparation, code):
    monde.greffon('alpha')
    monde.greffon('beta')
    preparation(monde.pages / 'beta')
    with pytest.raises(pages.ErreurPages) as e:
        monde.index()
    assert (e.value.code, e.value.greffon) == (code, 'beta')
    cible = monde.pages / 'index.json'
    statut, sortie, erreur = monde.cli('--ecrire', str(monde.pages))
    assert statut != 0 and not cible.exists() and sortie == ''
    assert code in erreur and 'beta' in erreur and str(monde.racine) not in erreur
    assert re.fullmatch(r'<3>\w+ beta\n', erreur)


def test_script_absent(monde):
    defauts(monde, lambda d: (d / 'a.js').unlink(), 'pages_invalid')


def test_catalogue_francais_absent(monde):
    defauts(monde, lambda d: (d / 'i18n' / 'fr-FR.json').unlink(), 'pages_invalid')


def test_catalogue_anglais_facultatif(monde):
    monde.greffon('alpha', en=False)
    assert json.loads(monde.index())['greffons'][0]['nom'] == 'alpha'


def test_lien_symbolique(monde):
    def lier(d):
        (d / 'a.js').unlink()
        (d / 'a.js').symlink_to(monde.pages / 'alpha' / 'a.js')
    defauts(monde, lier, 'pages_unsafe_permissions')


def test_ecriture_groupe_ou_autres(monde):
    defauts(monde, lambda d: (d / 'a.js').chmod(0o664), 'pages_unsafe_permissions')
    monde.greffon('gamma')
    (monde.pages / 'gamma' / 'i18n' / 'en-US.json').chmod(0o646)
    (monde.pages / 'beta' / 'a.js').chmod(0o644)
    with pytest.raises(pages.ErreurPages) as e:
        monde.index()
    assert e.value.code == 'pages_unsafe_permissions'


def test_dossier_modifiable(monde):
    defauts(monde, lambda d: (d / 'i18n').chmod(0o777), 'pages_unsafe_permissions')


def test_proprietaire_etranger(monde):
    monde.greffon('alpha')
    with pytest.raises(pages.ErreurPages) as e:
        pages.construire_index(monde.declarations(), monde.pages,
                               proprietaires=frozenset({EUID + 1}), racine_confiance=monde.racine)
    assert e.value.code == 'pages_unsafe_permissions'


def test_fichier_trop_grand(monde):
    def gros(d):
        (d / 'a.js').write_bytes(b'x' * (1048576 + 1))
    defauts(monde, gros, 'pages_too_large')


def test_fichier_a_la_limite_admis(monde):
    monde.greffon('alpha')
    (monde.pages / 'alpha' / 'a.js').write_bytes(b'x' * 1048576)
    monde.index()


@pytest.mark.parametrize('contenu', ['[]', '"x"', '{"ui_beta_a": 1}', 'pas du json',
                                     '{"ui_alpha_a": "x"}', '{"autre": "x"}', '{"ui_beta_a": "x", "b": "y"}'])
def test_catalogue_invalide_ou_hors_prefixe(monde, contenu):
    defauts(monde, lambda d: ecrire(d / 'i18n' / 'fr-FR.json', contenu), 'pages_catalog_invalid')


def test_verifier_detecte_les_alterations(monde):
    monde.greffon('alpha')
    pages.ecrire(monde.declarations(), monde.pages, **monde.options())
    index = monde.pages / 'index.json'
    assert monde.cli('--verifier', str(monde.pages))[0] == 0
    # index modifié à la main
    index.write_text(index.read_text().replace('alpha', 'omega'))
    assert monde.cli('--verifier', str(monde.pages))[0] != 0
    pages.ecrire(monde.declarations(), monde.pages, **monde.options())
    # index devenu modifiable
    index.chmod(0o666)
    assert monde.cli('--verifier', str(monde.pages))[0] == pages.EX_CONFIG
    index.chmod(0o644)
    # fichier devenu modifiable puis manquant
    (monde.pages / 'alpha' / 'a.js').chmod(0o666)
    assert monde.cli('--verifier', str(monde.pages))[0] == pages.EX_CONFIG
    (monde.pages / 'alpha' / 'a.js').unlink()
    assert monde.cli('--verifier', str(monde.pages))[0] == pages.EX_DATAERR
    # index absent
    index.unlink()
    assert monde.cli('--verifier', str(monde.pages))[0] != 0


def test_declarations_locales_hors_de_l_index(monde, tmp_path):
    monde.greffon('alpha')
    local = tmp_path / 'services.d'
    ecrire(local / 'paresia-yang-local.toml', declaration('local', 'a.js'))
    local.chmod(0o755)
    declarations = services.charger(monde.livrees, local, proprietaires=frozenset({EUID}),
                                    racine_confiance=monde.racine)
    assert any(s.greffon == 'paresia-yang-local' for s in declarations.services)
    noms = [g['nom'] for g in json.loads(monde.index())['greffons']]
    assert noms == ['alpha']


def test_declaration_livree_defectueuse_fatale(monde):
    ecrire(monde.livrees / 'paresia-yang-mauvais.toml', 'format = 1\n')
    statut, _, erreur = monde.cli('--ecrire', str(monde.pages))
    assert statut != 0 and 'pages_invalid' in erreur and not (monde.pages / 'index.json').exists()


def test_usage_aide_version(monde):
    assert monde.cli()[0] == pages.EX_USAGE
    assert monde.cli('--ecrire')[0] == pages.EX_USAGE
    assert monde.cli('--inconnue', 'x')[0] == pages.EX_USAGE
    code, sortie, erreur = monde.cli('--help')
    assert code == 0 and sortie.strip() and not erreur
    code, sortie, _ = monde.cli('--version')
    assert code == 0 and 'romulus.pages' in sortie


def test_silence_en_succes(monde):
    monde.greffon('alpha')
    assert monde.cli('--ecrire', str(monde.pages)) == (0, '', '')
    assert monde.cli('--verifier', str(monde.pages)) == (0, '', '')


def test_dossier_des_pages_absent(monde):
    monde.greffon('alpha')
    statut, _, erreur = monde.cli('--ecrire', str(monde.racine / 'inconnu'))
    assert statut == pages.EX_DATAERR and 'pages_invalid' in erreur


def _motif_client(nom):
    source = (RACINE / 'admin/web/greffons.js')
    if not source.exists():
        pytest.skip('client des greffons absent de cette branche')
    trouve = re.search(r'const ' + nom + r' = /(.*)/;', source.read_text(encoding='utf-8'))
    return re.compile(trouve.group(1))


@pytest.mark.parametrize('script', ['.p.js', '_p.js', '-p.js', 'a..b.js', 'a/b.js', 'p.JS', 'p.js ',
                                    'a' * 65 + '.js', '.js'])
def test_script_refuse_comme_par_le_client(script):
    client = _motif_client('SCRIPT')
    serveur_accepte = bool(services.MOTIF_SCRIPT.match(script)) and '..' not in script
    client_accepte = bool(client.match(script)) and '..' not in script
    assert not serveur_accepte or client_accepte
    assert not serveur_accepte


def test_script_accepte_identique_au_client():
    client = _motif_client('SCRIPT')
    for script in ('page.js', '0.js', 'a-b_c.v1.js', 'a' * 64 + '.js'):
        assert services.MOTIF_SCRIPT.match(script) and client.match(script)
    assert not services.MOTIF_SCRIPT.match('a' * 65 + '.js')


def test_titre_cle_meme_borne_que_le_client():
    client = _motif_client('CLE_TITRE')
    for longueur in (1, 100, 101):
        cle = 'ui_' + 'a' * longueur
        assert bool(services.MOTIF_TITRE_CLE.match(cle)) == bool(client.match(cle))
    assert services.MOTIF_TITRE_CLE.match('ui_' + 'a' * 100)
    assert not services.MOTIF_TITRE_CLE.match('ui_' + 'a' * 101)


def test_declaration_script_a_point_initial_refusee(monde):
    monde.greffon('alpha')
    texte = declaration('beta', '.cache.js')
    ecrire(monde.livrees / 'paresia-yang-beta.toml', texte)
    statut, _, erreur = monde.cli('--ecrire', str(monde.pages))
    assert statut == pages.EX_DATAERR and 'pages_invalid' in erreur


def test_aide_decrit_les_options_reelles(monde):
    _, sortie, _ = monde.cli('--help')
    for option in ('--ecrire', '--verifier', '--help', '--version'):
        assert option in sortie
    for option in ('--check', '--debug', '--config'):
        assert option not in sortie
