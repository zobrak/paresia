# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests de la découverte des pages de greffons (admin/web/greffons.js) ; dépendances : pytest, node.
# Suivi des versions
#   0.1.15  2026-11-08  Première version ; délais de lecture et durée totale bornée.
import importlib.util
import json
from pathlib import Path
import re
import shutil

import pytest

RACINE = Path(__file__).resolve().parents[1]
WEB = RACINE / 'admin' / 'web'
_spec = importlib.util.spec_from_file_location('hote_js', RACINE / 'tests' / 'outils' / 'hote_js.py')
hote_js = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hote_js)

avec_node = pytest.mark.skipif(shutil.which('node') is None, reason='node absent')

# Préambule commun : serveur factice d'index, de catalogues et de scripts.
PREAMBULE = """
const D = donnees;
if (D.index_remplissage) {
  D.index_brut = '{"format":1,"greffons":[],"x":"' + (D.remplissage || '\u00e9').repeat(D.index_remplissage) + '"}';
}
const JSON_T = 'application/json';
hote.api = async (url) => {
  if (url === '/admin/greffons/index.json') {
    if (D.index_statut !== undefined && D.index_statut !== 200) return hote.reponse(D.index_statut, JSON_T, '');
    return hote.reponse(200, D.index_type || JSON_T, D.index_brut !== undefined ? D.index_brut : D.index);
  }
  const m = /^\\/admin\\/greffons\\/([^/]+)\\/i18n\\/(fr-FR|en-US)\\.json$/.exec(url);
  if (m && D.catalogues && D.catalogues[m[1]] !== undefined) {
    return hote.reponse(200, JSON_T, D.catalogues[m[1]]);
  }
  return hote.reponse(404, 'text/plain', '');
};
function page(id, titre_cle, script) { return {id, titre_cle, script}; }
function inscrire(id, titre_cle, extra) {
  return () => { Paresia.enregistrer({id, titre_cle, afficher: (c) => { c.textContent = Paresia.t(titre_cle); }}); };
}
const diag = () => hote.document.getElementById('diagnostic-texte').textContent;
const menu = () => hote.document.getElementById('menu').children.map((b) => b.getAttribute('data-page'));
"""


def lancer(scenario, donnees):
    return hote_js.executer(PREAMBULE + scenario, donnees=donnees, scripts=hote_js.SCRIPTS_GREFFONS)


def gref(nom, pages):
    return {'nom': nom, 'pages': pages}


def pg(ident, cle, script='p.js'):
    return {'id': ident, 'titre_cle': cle, 'script': script}


def lire(nom):
    return (WEB / nom).read_text(encoding='utf-8')


@avec_node
def test_greffons_valides_menu_et_catalogues():
    donnees = {
        'index': {'format': 1, 'greffons': [
            gref('zeta', [pg('z-un', 'ui_zeta_titre')]),
            gref('alpha-b', [pg('b-page', 'ui_alpha_b_titre'), pg('a-page', 'ui_alpha_b_autre', 'a.js')]),
        ]},
        'catalogues': {
            'zeta': {'ui_zeta_titre': 'Zêta'},
            'alpha-b': {'ui_alpha_b_titre': 'Bravo', 'ui_alpha_b_autre': 'Alfa'},
        },
    }
    sortie = lancer("""
      hote.scripts['/admin/greffons/zeta/p.js'] = inscrire('z-un', 'ui_zeta_titre');
      hote.scripts['/admin/greffons/alpha-b/p.js'] = inscrire('b-page', 'ui_alpha_b_titre');
      hote.scripts['/admin/greffons/alpha-b/a.js'] = inscrire('a-page', 'ui_alpha_b_autre');
      Paresia.enregistrer({id: 'noyau', titre_cle: 'ui_web_menu', afficher: () => {}});
      await Paresia.demarrer();
      const avant = Paresia.t('ui_web_menu');
      return {menu: menu(), t: Paresia.t('ui_zeta_titre'), t2: Paresia.t('ui_alpha_b_autre'),
              noyau: avant, a_cle: Paresia.a_cle('ui_zeta_titre'), diag: diag(),
              urls: hote.appels.map((a) => a.url), creds: hote.appels.filter((a) => a.url.startsWith('/admin/')).map((a) => a.init.credentials)};
    """, donnees)
    assert sortie['menu'] == ['noyau', 'a-page', 'b-page', 'z-un']
    assert sortie['t'] == 'Zêta' and sortie['t2'] == 'Alfa' and sortie['a_cle'] is True
    assert sortie['noyau'] == 'Navigation' and sortie['diag'] == ''
    assert set(sortie['creds']) == {'same-origin'}
    assert '/admin/greffons/index.json' in sortie['urls']


@avec_node
def test_page_de_greffon_dans_son_conteneur():
    donnees = {'index': {'format': 1, 'greffons': [gref('g', [pg('p', 'ui_g_titre')])]},
               'catalogues': {'g': {'ui_g_titre': 'Titre'}}}
    sortie = lancer("""
      hote.scripts['/admin/greffons/g/p.js'] = () => {
        Paresia.enregistrer({id: 'p', titre_cle: 'ui_g_titre', afficher: (c) => { c.textContent = 'ok'; }});
      };
      await Paresia.demarrer();
      return {contenu: hote.document.getElementById('contenu').textContent,
              conteneurs: hote.document.getElementById('contenu').children.length};
    """, donnees)
    assert sortie == {'contenu': 'ok', 'conteneurs': 1}


GREFFONS_INVALIDES = [
    ('cle_inconnue', {'nom': 'mauvais', 'pages': [], 'extra': 1}),
    ('page_cle_inconnue', {'nom': 'mauvais', 'pages': [{'id': 'p', 'titre_cle': 'ui_mauvais_t', 'script': 'p.js', 'x': 1}]}),
    ('id_hors_forme', gref('mauvais', [pg('Page', 'ui_mauvais_t')])),
    ('script_point_point', gref('mauvais', [pg('p', 'ui_mauvais_t', 'a..js')])),
    ('script_avec_barre', gref('mauvais', [pg('p', 'ui_mauvais_t', 'sub/p.js')])),
    ('script_autre_extension', gref('mauvais', [pg('p', 'ui_mauvais_t', 'p.html')])),
    ('dix_sept_pages', gref('mauvais', [pg('p%d' % i if False else 'p-' + 'abcdefghijklmnopq'[i], 'ui_mauvais_t') for i in range(17)])),
    ('nom_hors_forme', gref('Mauvais', [])),
    ('nom_avec_barre', gref('a/b', [])),
    ('id_double', gref('mauvais', [pg('p', 'ui_mauvais_t'), pg('p', 'ui_mauvais_t', 'q.js')])),
    ('pas_un_objet', 'texte'),
]


@avec_node
@pytest.mark.parametrize('nom,invalide', GREFFONS_INVALIDES, ids=[x[0] for x in GREFFONS_INVALIDES])
def test_greffon_invalide_ignore_en_entier(nom, invalide):
    donnees = {'index': {'format': 1, 'greffons': [invalide, gref('bon', [pg('bon-p', 'ui_bon_t')])]},
               'catalogues': {'bon': {'ui_bon_t': 'Bon'}, 'mauvais': {'ui_mauvais_t': 'X'}, 'a/b': {}}}
    sortie = lancer("""
      hote.scripts['/admin/greffons/bon/p.js'] = inscrire('bon-p', 'ui_bon_t');
      hote.scripts['/admin/greffons/mauvais/p.js'] = inscrire('p', 'ui_mauvais_t');
      await Paresia.demarrer();
      return {menu: menu(), mauvais: Paresia.a_cle('ui_mauvais_t'), diag: diag(), bon: Paresia.t('ui_bon_t'),
              urls: hote.appels.map((a) => a.url)};
    """, donnees)
    assert sortie['menu'] == ['bon-p'] and sortie['bon'] == 'Bon'
    assert sortie['mauvais'] is False
    assert 'Greffon refusé' in sortie['diag'] and 'Mauvais' not in sortie['diag']
    assert not [u for u in sortie['urls'] if 'mauvais' in u or 'a/b' in u]


@avec_node
def test_noms_en_double_ecartes():
    donnees = {'index': {'format': 1, 'greffons': [gref('dup', []), gref('dup', [pg('p', 'ui_dup_t')]),
                                                    gref('bon', [pg('bon-p', 'ui_bon_t')])]},
               'catalogues': {'dup': {'ui_dup_t': 'D'}, 'bon': {'ui_bon_t': 'Bon'}}}
    sortie = lancer("""
      hote.scripts['/admin/greffons/bon/p.js'] = inscrire('bon-p', 'ui_bon_t');
      await Paresia.demarrer();
      return {menu: menu(), diag: diag()};
    """, donnees)
    assert sortie['menu'] == ['bon-p'] and 'nom_en_double' in sortie['diag']


COLLISIONS = [
    ('hors_prefixe', {'ui_bon_t': 'Bon', 'ui_ailleurs': 'x'}, 'cle_hors_prefixe'),
    ('cle_du_noyau', {'ui_web_menu': 'pirate'}, 'cle_hors_prefixe'),
    ('valeur_non_chaine', {'ui_bon_t': 3}, 'catalogue_invalide'),
]


@avec_node
@pytest.mark.parametrize('nom,catalogue,code', COLLISIONS, ids=[x[0] for x in COLLISIONS])
def test_collision_de_cles_refuse_le_greffon(nom, catalogue, code):
    donnees = {'index': {'format': 1, 'greffons': [gref('bon', [pg('bon-p', 'ui_bon_t')]),
                                                    gref('autre', [pg('autre-p', 'ui_autre_t')])]},
               'catalogues': {'bon': catalogue, 'autre': {'ui_autre_t': 'Autre'}}}
    sortie = lancer("""
      hote.scripts['/admin/greffons/bon/p.js'] = inscrire('bon-p', 'ui_bon_t');
      hote.scripts['/admin/greffons/autre/p.js'] = inscrire('autre-p', 'ui_autre_t');
      await Paresia.demarrer();
      return {menu: menu(), noyau: Paresia.t('ui_web_menu'), bon: Paresia.a_cle('ui_bon_t'), diag: diag()};
    """, donnees)
    assert sortie['menu'] == ['autre-p'] and sortie['noyau'] == 'Navigation'
    assert sortie['bon'] is False and code in sortie['diag']


@avec_node
def test_collision_entre_greffons_et_prefixe_commun():
    # « a » et « a-b » : la clé ui_a_b_x est dans le préfixe des deux ; le premier (ordre du nom) la garde.
    donnees = {'index': {'format': 1, 'greffons': [gref('a-b', [pg('b-p', 'ui_a_b_x')]),
                                                    gref('a', [pg('a-p', 'ui_a_t')])]},
               'catalogues': {'a': {'ui_a_t': 'A', 'ui_a_b_x': 'vole'}, 'a-b': {'ui_a_b_x': 'B'}}}
    sortie = lancer("""
      hote.scripts['/admin/greffons/a-b/p.js'] = inscrire('b-p', 'ui_a_b_x');
      hote.scripts['/admin/greffons/a/p.js'] = inscrire('a-p', 'ui_a_t');
      await Paresia.demarrer();
      return {menu: menu(), x: Paresia.t('ui_a_b_x'), diag: diag()};
    """, donnees)
    assert sortie['menu'] == ['a-p'] and sortie['x'] == 'vole' and 'cle_en_collision' in sortie['diag']


@avec_node
def test_repli_catalogue_fr_fr():
    donnees = {'index': {'format': 1, 'greffons': [gref('g', [pg('p', 'ui_g_t')])]},
               'catalogues': {'g': {'ui_g_t': 'Repli'}}}
    sortie = hote_js.executer(PREAMBULE + """
      hote.api = ((ancien) => async (url) => {
        if (url.endsWith('/i18n/en-US.json')) return hote.reponse(404, 'text/plain', '');
        return ancien(url);
      })(hote.api);
      hote.scripts['/admin/greffons/g/p.js'] = inscrire('p', 'ui_g_t');
      await Paresia.demarrer();
      return {menu: menu(), t: Paresia.t('ui_g_t'), langue: Paresia.langue()};
    """, langue='en-US', donnees=donnees, scripts=hote_js.SCRIPTS_GREFFONS)
    assert sortie == {'menu': ['p'], 't': 'Repli', 'langue': 'en-US'}


@avec_node
def test_catalogue_absent_refuse_le_greffon():
    donnees = {'index': {'format': 1, 'greffons': [gref('g', [pg('p', 'ui_g_t')])]}, 'catalogues': {}}
    sortie = lancer("""
      hote.scripts['/admin/greffons/g/p.js'] = inscrire('p', 'ui_g_t');
      await Paresia.demarrer();
      return {menu: menu(), diag: diag()};
    """, donnees)
    assert sortie['menu'] == [] and 'catalogue_indisponible' in sortie['diag']


@avec_node
def test_script_introuvable_ou_non_enregistre():
    donnees = {'index': {'format': 1, 'greffons': [gref('g', [
        pg('introuvable', 'ui_g_t', 'x.js'), pg('muet', 'ui_g_t', 'm.js'),
        pg('bonne', 'ui_g_t', 'b.js')])]}, 'catalogues': {'g': {'ui_g_t': 'T'}}}
    sortie = lancer("""
      hote.scripts['/admin/greffons/g/m.js'] = () => {};
      hote.scripts['/admin/greffons/g/b.js'] = inscrire('bonne', 'ui_g_t');
      await Paresia.demarrer();
      return {menu: menu(), diag: diag()};
    """, donnees)
    assert sortie['menu'] == ['bonne']
    assert 'script_introuvable' in sortie['diag'] and 'non_enregistree' in sortie['diag']


@avec_node
def test_page_sans_chargement_ecartee_apres_delai():
    donnees = {'index': {'format': 1, 'greffons': [gref('g', [pg('lente', 'ui_g_t', 'a.js'),
                                                               pg('prompte', 'ui_g_t', 'b.js')])]},
               'catalogues': {'g': {'ui_g_t': 'T'}}}
    sortie = lancer("""
      const minuteurs = [];
      globalThis.setTimeout = (f, ms) => { minuteurs.push({f, ms, vivant: true}); return minuteurs.length; };
      globalThis.clearTimeout = (n) => { minuteurs[n - 1].vivant = false; };
      hote.scripts['/admin/greffons/g/a.js'] = () => false;
      hote.scripts['/admin/greffons/g/b.js'] = inscrire('prompte', 'ui_g_t');
      await Paresia.charger_langue();
      const attente = Paresia.decouvrir();
      for (let i = 0; i < 100; i++) await null;
      const delais = minuteurs.map((m) => m.ms);
      for (const m of minuteurs) if (m.vivant && m.ms === 10000) m.f();
      await attente;
      return {delais, pages: Paresia.pages().map((p) => p.id), diag: diag()};
    """, donnees)
    assert 10000 in sortie['delais']
    assert sortie['pages'] == ['prompte'] and 'delai_depasse' in sortie['diag']


# Minuteur simulé : les échéances ne se déclenchent que sur ordre du scénario.
MINUTEURS = """
const minuteurs = [];
globalThis.setTimeout = (f, ms) => { minuteurs.push({f, ms, vivant: true}); return minuteurs.length; };
globalThis.clearTimeout = (n) => { if (minuteurs[n - 1]) minuteurs[n - 1].vivant = false; };
const attendre_tours = async () => { for (let i = 0; i < 100; i++) await null; };
const echoir = (ms) => { for (const m of minuteurs) if (m.vivant && m.ms === ms) { m.vivant = false; m.f(); } };
"""


@avec_node
@pytest.mark.parametrize('mode', ['fetch', 'corps'])
def test_index_en_attente_infinie_menu_du_noyau_et_delai(mode):
    sortie = lancer(MINUTEURS + """
      const mode = %r;
      hote.api = async (url) => {
        if (mode === 'fetch') return new Promise(() => {});
        const r = hote.reponse(200, 'application/json', '{}');
        r.text = () => new Promise(() => {});
        return r;
      };
      Paresia.enregistrer({id: 'noyau', titre_cle: 'ui_web_menu', afficher: () => {}});
      await Paresia.charger_langue();
      const attente = Paresia.decouvrir();
      await attendre_tours();
      const delais = minuteurs.map((m) => m.ms);
      echoir(10000);
      await attente;
      Paresia.construire_menu();
      return {delais, menu: menu(), diag: diag(), vivants: minuteurs.filter((m) => m.vivant).length};
    """ % mode, {})
    assert 10000 in sortie['delais'] and 30000 in sortie['delais']
    assert sortie['menu'] == ['noyau'] and 'indisponibles' in sortie['diag'] and '(delai)' in sortie['diag']
    assert sortie['vivants'] == 0


@avec_node
def test_catalogue_en_attente_infinie_refuse_ce_greffon_seulement():
    donnees = {'index': {'format': 1, 'greffons': [gref('a-lent', [pg('lent', 'ui_a_lent_t')]),
                                                   gref('b-sain', [pg('sain', 'ui_b_sain_t')])]},
               'catalogues': {'b-sain': {'ui_b_sain_t': 'T'}}}
    sortie = lancer(MINUTEURS + """
      const api = hote.api;
      hote.api = (url) => (url.startsWith('/admin/greffons/a-lent/i18n/') ? new Promise(() => {}) : api(url));
      hote.scripts['/admin/greffons/a-lent/p.js'] = inscrire('lent', 'ui_a_lent_t');
      hote.scripts['/admin/greffons/b-sain/p.js'] = inscrire('sain', 'ui_b_sain_t');
      await Paresia.charger_langue();
      const attente = Paresia.decouvrir();
      await attendre_tours();
      echoir(10000);
      await attente;
      return {pages: Paresia.pages().map((p) => p.id), diag: diag(),
              appels_lent: hote.appels.filter((a) => a.url.includes('a-lent/i18n')).length};
    """, donnees)
    assert sortie['pages'] == ['sain']
    assert 'a-lent (delai)' in sortie['diag']
    assert sortie['appels_lent'] == 1


@avec_node
def test_duree_totale_bornee_greffons_restants_abandonnes():
    donnees = {'index': {'format': 1, 'greffons': [gref('a-bloque', [pg('bloque', 'ui_a_bloque_t')]),
                                                   gref('b-suite', [pg('suite', 'ui_b_suite_t')])]},
               'catalogues': {'a-bloque': {'ui_a_bloque_t': 'T'}, 'b-suite': {'ui_b_suite_t': 'T'}}}
    sortie = lancer(MINUTEURS + """
      hote.scripts['/admin/greffons/a-bloque/p.js'] = () => false;
      hote.scripts['/admin/greffons/b-suite/p.js'] = inscrire('suite', 'ui_b_suite_t');
      Paresia.enregistrer({id: 'noyau', titre_cle: 'ui_web_menu', afficher: () => {}});
      await Paresia.charger_langue();
      const attente = Paresia.decouvrir();
      await attendre_tours();
      echoir(30000);
      await attente;
      echoir(10000);
      await attendre_tours();
      Paresia.construire_menu();
      return {menu: menu(), diag: diag()};
    """, donnees)
    assert sortie['menu'] == ['noyau'] and 'delai_total' in sortie['diag']


@avec_node
def test_script_retire_du_document_apres_delai():
    donnees = {'index': {'format': 1, 'greffons': [gref('g', [pg('lente', 'ui_g_t', 'a.js')])]},
               'catalogues': {'g': {'ui_g_t': 'T'}}}
    sortie = lancer(MINUTEURS + """
      hote.scripts['/admin/greffons/g/a.js'] = () => false;
      await Paresia.charger_langue();
      const attente = Paresia.decouvrir();
      await attendre_tours();
      const avant = hote.document.body.children.filter((n) => n.nom === 'script').length;
      echoir(10000);
      await attente;
      return {avant, apres: hote.document.body.children.filter((n) => n.nom === 'script').length};
    """, donnees)
    assert sortie == {'avant': 1, 'apres': 0}


INDEX_INVALIDES = [
    ('absent', {'index_statut': 404, 'index': {}}),
    ('mauvais_type', {'index_type': 'text/html', 'index': {'format': 1, 'greffons': []}}),
    ('trop_gros', {'index_remplissage': 70000, 'remplissage': 'a'}),
    ('trop_gros_octets', {'index_remplissage': 33000}),
    ('format_2', {'index': {'format': 2, 'greffons': []}}),
    ('format_texte', {'index': {'format': '1', 'greffons': []}}),
    ('cle_inconnue', {'index': {'format': 1, 'greffons': [], 'x': 1}}),
    ('cle_manquante', {'index': {'format': 1}}),
    ('greffons_pas_tableau', {'index': {'format': 1, 'greffons': {}}}),
    ('dix_sept_greffons', {'index': {'format': 1, 'greffons': [gref('g%s' % 'abcdefghijklmnopq'[i], []) for i in range(17)]}}),
    ('json_invalide', {'index_brut': '{pas du json'}),
    ('tableau', {'index': []}),
]


@avec_node
@pytest.mark.parametrize('nom,donnees', INDEX_INVALIDES, ids=[x[0] for x in INDEX_INVALIDES])
def test_index_invalide_aucune_page_de_greffon(nom, donnees):
    donnees = dict(donnees, catalogues={'g': {'ui_g_t': 'T'}})
    sortie = lancer("""
      hote.scripts['/admin/greffons/g/p.js'] = inscrire('p', 'ui_g_t');
      Paresia.enregistrer({id: 'noyau', titre_cle: 'ui_web_menu', afficher: (c) => { c.textContent = 'n'; }});
      await Paresia.demarrer();
      return {menu: menu(), pages: Paresia.pages().length, diag: diag(),
              contenu: hote.document.getElementById('contenu').textContent};
    """, donnees)
    assert sortie['menu'] == ['noyau'] and sortie['pages'] == 1 and sortie['contenu'] == 'n'
    assert 'Pages des greffons indisponibles' in sortie['diag']


@avec_node
def test_index_inaccessible_reseau():
    sortie = hote_js.executer("""
      await Paresia.demarrer();
      return {diag: hote.document.getElementById('diagnostic-texte').textContent};
    """, scripts=hote_js.SCRIPTS_GREFFONS)
    assert 'illisible' in sortie['diag']


@avec_node
def test_chemins_recomposes_et_texte_filtre():
    donnees = {'index': {'format': 1, 'greffons': [gref('g', [pg('p', 'ui_g_t', 'p.js')])]},
               'catalogues': {'g': {'ui_g_t': 'a\u0007b'}}}
    sortie = lancer("""
      const sources = [];
      const ancien = hote.charger_script;
      hote.charger_script = (n) => { sources.push(n.getAttribute('src')); ancien(n); };
      hote.scripts['/admin/greffons/g/p.js'] = inscrire('p', 'ui_g_t');
      await Paresia.demarrer();
      return {sources, t: Paresia.t('ui_g_t'),
              urls: hote.appels.map((a) => a.url).filter((u) => u.startsWith('/admin/'))};
    """, donnees)
    assert sortie['sources'] == ['/admin/greffons/g/p.js']
    assert sortie['t'] == 'a�b'
    assert set(sortie['urls']) == {'/admin/greffons/index.json', '/admin/greffons/g/i18n/fr-FR.json'}


@avec_node
def test_dom_refuse_elements_et_attributs_herites():
    sortie = hote_js.executer("""
      const r = {};
      for (const nom of ['frame', 'frameset', 'applet', 'script', 'iframe']) {
        try { Paresia.el(nom); r[nom] = false; } catch (e) { r[nom] = e.message === 'element_refuse'; }
      }
      for (const valeur of ['/admin/x', 'quelconque']) {
        try { Paresia.el('table', {background: valeur}); r['bg' + valeur] = false; }
        catch (e) { r['bg' + valeur] = e.message === 'attribut_refuse'; }
      }
      return r;
    """)
    assert len(sortie) == 7 and all(sortie.values()), sortie


# --- Contrôles statiques -------------------------------------------------------------------

def test_en_tete_et_interdits_de_greffons_js():
    texte = lire('greffons.js')
    assert 'SPDX-License-Identifier: AGPL-3.0-or-later' in texte and 'Suivi des versions' in texte
    for motif in ('innerHTML', 'outerHTML', 'insertAdjacentHTML', 'document.write', 'eval(',
                  'new Function', 'http://', 'https://', 'localStorage', 'sessionStorage',
                  'indexedDB', 'document.cookie', 'X-Admin-Token', 'Origin'):
        assert motif not in texte, motif
    assert not re.search(r'set(Timeout|Interval)\(\s*[\'"`]', texte)
    assert not re.search(r'^\s*(import|export)\b', texte, re.M)
    assert not re.search(r'\b(T\d{3}|lot \d)\b', texte)


def test_aucun_nom_de_produit_dans_le_noyau():
    motif = re.compile(r'bunker|relay|legal|nisaba|strfry', re.I)
    fichiers = [WEB / 'greffons.js', WEB / 'app.js'] + sorted((RACINE / 'admin' / 'app').glob('*.py'))
    assert len(fichiers) > 2
    for fichier in fichiers:
        assert not motif.search(fichier.read_text(encoding='utf-8')), fichier.name


def test_index_html_charge_greffons_avant_app_et_csp_inchangee():
    html = lire('index.html')
    assert html.index('<script src="greffons.js"></script>') < html.index('<script src="app.js"></script>')
    csp = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
           "connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'none'")
    assert '<meta http-equiv="Content-Security-Policy" content="%s">' % csp in html


def test_cles_ui_web_greffon_dans_les_catalogues():
    fr = json.loads((RACINE / 'i18n' / 'fr-FR.json').read_text(encoding='utf-8'))
    en = json.loads((RACINE / 'i18n' / 'en-US.json').read_text(encoding='utf-8'))
    cles = [c for c in fr if c.startswith('ui_web_greffon_')]
    assert len(cles) >= 3 and set(cles) == {c for c in en if c.startswith('ui_web_greffon_')}
    for cle in cles:
        assert fr[cle].strip() and en[cle].strip()
