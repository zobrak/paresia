# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests du socle des pages d'administration (admin/web) ; dépendances : pytest, node (facultatif).
# Suivi des versions
#   3.0.0-alpha.41  2026-11-06  Première version.
#   0.1.16  2026-11-08  Motif d'action aligné sur celui du catalogue du serveur.
import importlib.util
import json
from pathlib import Path
import re
import shutil

import pytest

from server.commun.jumeaux import CODES_ERREUR
from server.commun.texte import filtrer

RACINE = Path(__file__).resolve().parents[1]
WEB = RACINE / 'admin' / 'web'
FICHIERS = ['index.html', 'api.js', 'texte.js', 'dom.js', 'confirmation.js', 'app.js',
            'style.css', 'langues/fr-FR.css', 'langues/en-US.css']
CLES_WEB = ['ui_web_titre', 'ui_web_menu', 'ui_web_chargement', 'ui_web_session_requise',
            'ui_web_operation_indisponible', 'ui_web_reessayer', 'ui_web_annuler',
            'ui_web_confirmer', 'ui_web_saisir_nom', 'ui_web_diagnostic']

_spec = importlib.util.spec_from_file_location('hote_js', RACINE / 'tests' / 'outils' / 'hote_js.py')
hote_js = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hote_js)

avec_node = pytest.mark.skipif(shutil.which('node') is None, reason='node absent')


def lire(nom):
    return (WEB / nom).read_text(encoding='utf-8')


# --- Contrôles statiques -------------------------------------------------------------------

def test_fichiers_presents_et_en_tete():
    for nom in FICHIERS:
        texte = lire(nom)
        assert 'SPDX-License-Identifier: AGPL-3.0-or-later' in texte, nom
        assert 'Suivi des versions' in texte, nom


def test_controles_statiques():
    interdits = ['innerHTML', 'outerHTML', 'insertAdjacentHTML', 'document.write', 'eval(',
                 'new Function', 'http://', 'https://', 'localStorage', 'sessionStorage',
                 'indexedDB', 'document.cookie', 'X-Admin-Token', 'Origin']
    for nom in FICHIERS:
        texte = lire(nom)
        for motif in interdits:
            assert motif not in texte, (nom, motif)
    for nom in ('api.js', 'texte.js', 'dom.js', 'confirmation.js', 'app.js'):
        assert not re.search(r'set(Timeout|Interval)\(\s*[\'"`]', lire(nom)), nom
        assert not re.search(r'^\s*(import|export)\b', lire(nom), re.M), nom


def test_index_html():
    html = lire('index.html')
    sans_commentaires = re.sub(r'<!--.*?-->', '', html, flags=re.S)
    for script in re.findall(r'<script\b([^>]*)>(.*?)</script>', sans_commentaires, flags=re.S):
        assert 'src="' in script[0] and script[1].strip() == ''
    textes = re.sub(r'<[^>]*>', '', re.sub(r'<!DOCTYPE[^>]*>', '', sans_commentaires))
    assert textes.strip() == ''
    assert "script-src 'self'" in html and "default-src 'none'" in html
    assert "base-uri 'none'" in html and "form-action 'none'" in html
    for repere in ('<nav id="menu">', '<main id="contenu">', 'id="feuille-langue"',
                   'id="diagnostic-texte"', '<meta charset="utf-8">'):
        assert repere in html, repere
    assert not re.search(r'\son[a-z]+=|\sstyle=', sans_commentaires)


def test_cles_ui_web_catalogues():
    fr = json.loads((RACINE / 'i18n' / 'fr-FR.json').read_text(encoding='utf-8'))
    en = json.loads((RACINE / 'i18n' / 'en-US.json').read_text(encoding='utf-8'))
    for cle in CLES_WEB:
        assert fr[cle].strip() and en[cle].strip(), cle
    cles = list(fr)
    ui = [i for i, c in enumerate(cles) if c.startswith('ui_')]
    assert ui == list(range(ui[0], ui[-1] + 1))
    assert set(fr) == set(en)


def test_feuilles_par_langue():
    for langue in ('fr-FR', 'en-US'):
        texte = lire(f'langues/{langue}.css')
        assert 'direction' in texte and 'url(' not in texte and '@import' not in texte
    assert 'url(' not in lire('style.css') and '@import' not in lire('style.css')


# --- Comportement dans node ---------------------------------------------------------------

@avec_node
def test_codes_identiques_a_python():
    sortie = hote_js.executer('return Array.from(Paresia.CODES).sort();')
    assert sortie == sorted(CODES_ERREUR)


@avec_node
def test_filtrer_comme_python():
    cas = ['a\x1bb', 'x‮y', 'l m n', 'iso\ud800le', 'prive',
           'texte ordinaire é', 'émojis \U0001f600 ok', 'zw​j', '', 'tab\there']
    attendu = [filtrer(c) for c in cas]
    sortie = hote_js.executer(
        'return donnees.map((c) => Paresia.filtrer(c)).concat([Paresia.filtrer(5), Paresia.filtrer(null)]);',
        donnees=cas)
    assert sortie == attendu + ['', '']


@avec_node
def test_appeler_succes_et_requete():
    sortie = hote_js.executer("""
      hote.api = () => hote.reponse(200, 'application/json; charset=utf-8', {ok: true, data: {a: 1}});
      const data = await Paresia.appeler('bunker/identity/list', {x: 1});
      hote.api = () => hote.reponse(200, 'application/json', '{"ok":true}');
      const vide = await Paresia.appeler('bunker/identity/add');
      const appel = hote.appels.filter((a) => a.url.startsWith('/api/'))[0];
      return {data, vide, url: appel.url, init: JSON.parse(JSON.stringify(appel.init))};
    """)
    assert sortie['data'] == {'a': 1} and sortie['vide'] == {}
    assert sortie['url'] == '/api/admin/bunker/identity/list'
    init = sortie['init']
    assert init['method'] == 'POST' and init['credentials'] == 'same-origin'
    assert init['body'] == '{"x":1}'
    noms = {n.lower() for n in init['headers']}
    assert noms == {'content-type'} and init['headers']['Content-Type'] == 'application/json'


@avec_node
def test_appeler_erreurs():
    sortie = hote_js.executer("""
      const cas = {
        erreur: () => hote.reponse(403, 'application/json', {ok: false, error: {code: 'token_unknown'}}),
        inconnu: () => hote.reponse(400, 'application/json', {ok: false, error: {code: 'code_inventé'}}),
        non_json: () => hote.reponse(200, 'application/json', '<html>'),
        autre_type: () => hote.reponse(200, 'text/html', {ok: true, data: 1}),
        gzip: () => hote.reponse(200, 'application/gzip', 'xx'),
        forme: () => hote.reponse(200, 'application/json', {ok: true, data: 1, extra: 2}),
        forme2: () => hote.reponse(200, 'application/json', [1]),
        forme3: () => hote.reponse(200, 'application/json', {ok: false, error: {code: 'bad_request', x: 1}}),
        reseau: () => { throw new TypeError('x'); },
      };
      const rendu = {};
      for (const [nom, f] of Object.entries(cas)) {
        hote.api = f;
        try { await Paresia.appeler('relay/state/status'); rendu[nom] = 'succes'; }
        catch (e) { rendu[nom] = e instanceof Paresia.ErreurApi ? e.code : 'autre'; }
      }
      return rendu;
    """)
    assert sortie == {
        'erreur': 'token_unknown', 'inconnu': 'internal_error', 'non_json': 'internal_error',
        'autre_type': 'internal_error', 'gzip': 'internal_error', 'forme': 'internal_error',
        'forme2': 'internal_error', 'forme3': 'internal_error', 'reseau': 'internal_error'}


@avec_node
def test_action_mal_formee_non_envoyee():
    sortie = hote_js.executer("""
      const codes = [];
      const mauvaises = ['../x', 'Bunker/identity/list', 'bunker', 'a/b/c/d/e', 'a//b', 'a/B/c', 'a/b/c/',
                         '/a/b', '1a/b', 'a/b\\n', 'a/' + 'b'.repeat(127), '', 5, null, undefined, {}];
      for (const a of mauvaises) {
        try { await Paresia.appeler(a); codes.push('ok'); } catch (e) { codes.push(e.code); }
      }
      return {codes, envois: hote.appels.length, total: mauvaises.length};
    """)
    assert sortie['envois'] == 0 and sortie['codes'] == ['bad_request'] * sortie['total']


@avec_node
def test_action_valide_envoyee():
    longue = 'a/' + 'b' * 126
    sortie = hote_js.executer("""
      hote.api = async () => hote.reponse(200, 'application/json', {ok: true, data: {}});
      const valides = ['bunker/identity', 'a/b/c/d', 'a1_b/c-d/e2', 'kernel/state/status', donnees.longue];
      for (const a of valides) await Paresia.appeler(a);
      return {urls: hote.appels.map((x) => x.url), longueur: donnees.longue.length};
    """, donnees={'longue': longue})
    assert sortie['longueur'] == 128 and len(sortie['urls']) == 5
    assert sortie['urls'][0] == '/api/admin/bunker/identity'


@avec_node
def test_presentation_des_erreurs():
    sortie = hote_js.executer("""
      await Paresia.charger_langue();
      const r = {};
      for (const code of ['not_available', 'token_missing', 'token_unknown', 'session_closed',
                          'relay_light_red', 'command_busy', 'bad_request', 'zzz']) {
        const p = Paresia.presenter_erreur(new Paresia.ErreurApi(code));
        r[code] = [p.cle, p.reessayer, p.session];
      }
      const long = 'a\\u001b' + 'b'.repeat(300);
      const p = Paresia.presenter_erreur(new Paresia.ErreurApi('bad_request', long));
      r.detail = [p.detail.length, p.detail.slice(0, 3)];
      r.autre = Paresia.presenter_erreur(new Error('x')).cle;
      const conteneur = hote.document.createElement('div');
      let rejeu = 0;
      Paresia.afficher_erreur(conteneur, new Paresia.ErreurApi('command_busy', 'd\\u202e'), () => { rejeu++; });
      const bouton = conteneur.trouver((n) => n.nom === 'button')[0];
      bouton.click();
      r.bouton = [bouton.textContent, rejeu];
      r.message = conteneur.trouver((n) => n.nom === 'p')[0].textContent;
      r.diag = hote.document.getElementById('diagnostic-texte').textContent;
      return r;
    """)
    assert sortie['not_available'] == ['ui_web_operation_indisponible', False, False]
    for code in ('token_missing', 'token_unknown', 'session_closed'):
        assert sortie[code] == ['ui_web_session_requise', False, True]
    for code in ('relay_light_red', 'command_busy'):
        assert sortie[code] == [code, True, False]
    assert sortie['bad_request'][0] == 'bad_request' and sortie['zzz'][0] == 'internal_error'
    assert sortie['detail'] == [200, 'a�b']
    assert sortie['autre'] == 'internal_error'
    assert sortie['bouton'] == ['Réessayer', 1]
    assert sortie['message'] == 'Trop de commandes simultanées'
    assert sortie['diag'] == 'd�'


@avec_node
def test_presentation_sans_libelle_donne_erreur_interne():
    sortie = hote_js.executer("""
      const p = Paresia.presenter_erreur(new Paresia.ErreurApi('not_available'));
      return [p.cle, p.code];
    """)
    assert sortie == ['internal_error', 'internal_error']


@avec_node
@pytest.mark.parametrize('etiquette, attendu', [
    ('fr-FR', 'fr-FR'), ('en-US', 'en-US'), ('fr', 'fr-FR'), ('en', 'en-US'),
    ('de-DE', 'fr-FR'), ('EN-us', 'en-US')])
def test_langue(etiquette, attendu):
    sortie = hote_js.executer(
        'const l = await Paresia.charger_langue();'
        "return [l, hote.document.documentElement.lang,"
        " hote.document.getElementById('feuille-langue').getAttribute('href'),"
        " Paresia.t('ui_web_annuler'), Paresia.t('cle_absente')];", langue=etiquette)
    attendu_catalogue = json.loads(
        (RACINE / 'i18n' / f'{attendu}.json').read_text(encoding='utf-8'))
    assert sortie == [attendu, attendu, f'langues/{attendu}.css',
                      attendu_catalogue['ui_web_annuler'], 'cle_absente']


@avec_node
def test_demarrage_et_menu():
    sortie = hote_js.executer("""
      Paresia.enregistrer({id: 'essai', titre_cle: 'ui_web_menu', afficher: (c) => { c.textContent = 'page'; }});
      let refus = 0;
      for (const p of [{}, {id: 'Essai', titre_cle: 'a', afficher() {}}, {id: 'essai', titre_cle: 'a', afficher() {}}]) {
        try { Paresia.enregistrer(p); } catch (e) { refus++; }
      }
      await Paresia.demarrer();
      const d = hote.document;
      return {refus, titre: d.title, menu: d.getElementById('menu').children.map((b) => b.textContent),
              contenu: d.getElementById('contenu').textContent,
              diag: d.getElementById('diagnostic-titre').textContent};
    """)
    assert sortie == {'refus': 3, 'titre': 'Administration de Paresia', 'menu': ['Navigation'],
                      'contenu': 'page', 'diag': 'Diagnostic'}


@avec_node
def test_el_texte_et_attributs():
    sortie = hote_js.executer("""
      const piege = '<img src=x onerror=alert(1)>';
      const e = Paresia.el('p', {class: 'x'}, piege);
      const mixte = Paresia.el('p', null, 'a\\u001b', Paresia.el('b', null, 'c'));
      const refus = {};
      const essais = {
        onclick: ['a', {onclick: 'x'}], style: ['a', {style: 'x'}], href: ['a', {href: 'https://x.test/'}],
        href2: ['a', {href: '/autre/chemin'}], href3: ['a', {href: '/admin/../x'}],
        src: ['img', {src: '//x.test/a.png'}], script: ['script', null], majuscule: ['P', null],
      };
      for (const [n, [nom, attr]] of Object.entries(essais)) {
        try { Paresia.el(nom, attr); refus[n] = false; } catch (err) { refus[n] = true; }
      }
      const ok1 = Paresia.el('a', {href: '/admin/x.html'}, 't').getAttribute('href');
      const ok2 = Paresia.el('a', {href: '/api/admin/legal/journal/export'}, 't').getAttribute('href');
      return {texte: e.textContent, enfants: e.children.length, mixte: mixte.textContent, refus, ok1, ok2,
              classe: e.getAttribute('class')};
    """)
    assert sortie['texte'] == '<img src=x onerror=alert(1)>' and sortie['enfants'] == 0
    assert sortie['mixte'] == 'a�c' and sortie['classe'] == 'x'
    assert all(sortie['refus'].values()), sortie['refus']
    assert sortie['ok1'] == '/admin/x.html' and sortie['ok2'] == '/api/admin/legal/journal/export'


@avec_node
def test_confirmer():
    sortie = hote_js.executer("""
      await Paresia.charger_langue();
      const body = hote.document.body;
      const dialogue = () => body.trouver((n) => n.nom === 'dialog')[0];
      const bouton = (d, i) => d.trouver((n) => n.nom === 'button')[i];
      const r = {};
      let p = Paresia.confirmer({titre_cle: 'ui_web_confirmer', texte: 'sûr ?'});
      let d = dialogue();
      r.libelles = [bouton(d, 0).textContent, bouton(d, 1).textContent];
      bouton(d, 1).click(); r.sans_nom_oui = await p; r.retire = dialogue() === undefined;
      p = Paresia.confirmer({titre_cle: 'ui_web_confirmer', texte: 'x'});
      bouton(dialogue(), 0).click(); r.annuler = await p;
      p = Paresia.confirmer({titre_cle: 'ui_web_confirmer', texte: 'x'});
      dialogue().close(); r.echap = await p;
      p = Paresia.confirmer({titre_cle: 'ui_web_confirmer', texte: 'x', nom_attendu: 'Alice'});
      d = dialogue();
      const champ = d.trouver((n) => n.nom === 'input')[0];
      r.invite = d.textContent.includes('Saisissez le nom exact');
      r.desactive = bouton(d, 1).disabled;
      champ.saisir('alice'); r.casse = bouton(d, 1).disabled; bouton(d, 1).click();
      r.encore_ouvert = d.ouvert;
      champ.saisir('Alice'); r.exact = bouton(d, 1).disabled; bouton(d, 1).click();
      r.avec_nom = await p;
      return r;
    """)
    assert sortie == {
        'libelles': ['Annuler', 'Confirmer'], 'sans_nom_oui': True, 'retire': True,
        'annuler': False, 'echap': False, 'invite': True, 'desactive': True, 'casse': True,
        'encore_ouvert': True, 'exact': False, 'avec_nom': True}
