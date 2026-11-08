# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests des pages du noyau (admin/web/noyau.js) : état, journaux, catalogue ; dépendances : pytest, node.
# Suivi des versions
#   0.1.16  2026-11-08  Première version.
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
SCRIPTS = hote_js.SCRIPTS + ('noyau.js',)

PREAMBULE = """
const D = donnees;
const demandes = [];
hote.api = async (url, init) => {
  if (!url.startsWith('/api/admin/')) return hote.reponse(404, 'text/plain', '');
  const action = url.slice('/api/admin/'.length);
  const params = JSON.parse(init.body);
  demandes.push({action, params});
  let r = D.reponses[action];
  if (action.endsWith('/catalog/describe')) r = (D.descriptions || {})[params.action];
  if (typeof r === 'undefined') return hote.reponse(200, 'application/json', {ok: false, error: {code: 'unknown_action'}});
  if (r && r.__erreur) return hote.reponse(200, 'application/json', {ok: false, error: {code: r.__erreur}});
  if (r && r.__attente) { await r.__attente; }
  return hote.reponse(200, 'application/json', {ok: true, data: r});
};
const pause = async () => { for (let i = 0; i < 6; i++) await new Promise((r) => setTimeout(r, 0)); };
const contenu = () => hote.document.getElementById('contenu');
const boutons = (racine, texte) => racine.trouver((n) => n.nom === 'button' && n.textContent === texte);
const bouton = (racine, texte) => boutons(racine, texte)[0];
const cliquer = async (racine, texte) => { bouton(racine, texte).click(); await pause(); };
const ouvrir = async (id) => { await Paresia.demarrer(); await pause(); if (id) { demandes.length = 0; Paresia.selectionner(id); await pause(); } };
const t = (cle) => Paresia.t(cle);
const SANS_HTML = (n) => n.trouver((x) => x.nom === 'img' || x.nom === 'script').length === 0;
"""

STATUS = {'version': '0.1.16', 'uptime_s': 42, 'sessions': 2, 'activity_detail': 2,
          'daemons': [{'name': 'pollux', 'unit': 'paresia-pollux.service', 'metrics': 'enabled', 'sample_age_s': 3},
                      {'name': 'romulus', 'unit': 'paresia-romulus.service', 'metrics': 'disabled'}]}
SERVICES = {'services': [
    {'domain': 'alpha', 'greffon': 'g1', 'target': 'principale', 'catalog': 'declaration', 'available': True},
    {'domain': 'beta', 'greffon': 'g2', 'target': 'principale', 'catalog': 'none', 'available': False},
    {'domain': 'gamma', 'greffon': 'g3', 'target': 'principale', 'catalog': 'pair', 'available': True}]}


def lancer(scenario, donnees):
    return hote_js.executer(PREAMBULE + scenario, donnees=donnees, scripts=SCRIPTS)


def lire(nom):
    return (WEB / nom).read_text(encoding='utf-8')


@avec_node
def test_etat_resume_metriques_configuration():
    donnees = {'reponses': {
        'kernel/state/status': STATUS,
        'kernel/state/metrics': {'daemon': 'pollux', 'available': True, 'samples': [
            {'name': 'm_total', 'labels': {'k': '<img onerror=x>\x1b[31m'}, 'value': 7}]},
        'kernel/state/config': {'daemon': 'romulus', 'options': [
            {'section': 'journal', 'key': 'niveau', 'type': 'niveau', 'value': 'info', 'masked': False},
            {'section': 's', 'key': 'secret_x', 'type': 'texte', 'value': None, 'masked': True},
            {'section': 's', 'key': 'autre', 'type': 'texte', 'value': 'SECRETVALUE', 'masked': True}]}}}
    sortie = lancer("""
      await ouvrir();
      const menu = hote.document.getElementById('menu').children.map((b) => b.getAttribute('data-page'));
      const resume = contenu().textContent;
      await cliquer(contenu(), 'pollux');
      const metr = contenu().textContent;
      const sans_html = SANS_HTML(contenu());
      boutons(contenu(), 'romulus')[1].click(); await pause();
      const config = contenu().textContent;
      return {menu, resume, metr, config, sans_html, demandes};
    """, donnees)
    assert sortie['menu'] == ['noyau-etat', 'noyau-journaux', 'noyau-catalogue']
    assert '0.1.16' in sortie['resume'] and 'paresia-pollux.service' in sortie['resume']
    assert 'Activées' in sortie['resume'] and 'Désactivées' in sortie['resume']
    assert [d['action'] for d in sortie['demandes']] == [
        'kernel/state/status', 'kernel/state/metrics', 'kernel/state/config']
    assert sortie['demandes'][0]['params'] == {}
    assert sortie['demandes'][1]['params'] == {'daemon': 'pollux'}
    assert sortie['demandes'][2]['params'] == {'daemon': 'romulus'}
    assert 'm_total' in sortie['metr'] and '\x1b' not in sortie['metr'] and sortie['sans_html']
    assert '<img onerror=x>' in sortie['metr']
    assert sortie['config'].count('masquée') >= 2 and 'SECRETVALUE' not in sortie['config']


@avec_node
def test_metriques_desactivees_et_erreur():
    donnees = {'reponses': {
        'kernel/state/status': STATUS,
        'kernel/state/metrics': {'daemon': 'pollux', 'available': False, 'samples': []},
        'kernel/state/config': {'__erreur': 'not_available'}}}
    sortie = lancer("""
      await ouvrir();
      await cliquer(contenu(), 'pollux');
      const metr = contenu().textContent;
      boutons(contenu(), 'romulus')[1].click(); await pause();
      return {metr, fin: contenu().textContent, n: demandes.length};
    """, donnees)
    assert 'Aucune métrique' in sortie['metr'] and 'désactivées par défaut' in sortie['metr']
    assert 'Opération non disponible' in sortie['fin']


@avec_node
def test_etat_reponse_invalide():
    donnees = {'reponses': {'kernel/state/status': {'version': 3, 'daemons': []}}}
    sortie = lancer("await ouvrir(); return contenu().textContent;", donnees)
    assert 'Réponse inattendue' in sortie


def entree(**extra):
    base = {'ts': '2026-11-08T10:00:00Z', 'level': 1, 'event': 'action', 'admin': 'alice',
            'session': 1, 'domain': 'alpha', 'action': 'alpha/x/y', 'result': 'ok'}
    base.update(extra)
    return base


@avec_node
def test_journal_parametres_et_rendu():
    donnees = {'reponses': {'kernel/activity/list': {'detail': 2, 'truncated': True, 'entries': [
        entree(level=2, duration_ms=12, twin='remus'),
        entree(level=3, event='protocol', request_id='r1', step='sent', ok=True, code='ok',
               bytes=10, http_status=200, peer_uid=1000),
        entree(admin=None, domain=None, action=None, event='refusal', result='token_unknown', count=5),
        entree(admin='bob\x1b[0m<img onerror=x>', inconnu='zz'),
        entree(level='x'),
        ]}}}
    sortie = lancer("""
      await ouvrir('noyau-journaux');
      const premier = demandes.map((d) => d);
      const texte = contenu().textContent;
      const sans_html = SANS_HTML(contenu());
      const selects = contenu().trouver((n) => n.nom === 'select');
      selects[0].value = '200'; selects[1].value = '3';
      const champ = contenu().trouver((n) => n.nom === 'input')[0];
      champ.saisir('alpha');
      await cliquer(contenu(), t('ui_noyau_actualiser'));
      return {premier, texte, sans_html, demandes};
    """, donnees)
    assert sortie['premier'] == [{'action': 'kernel/activity/list', 'params': {'limit': 50, 'level': 1}}]
    assert sortie['demandes'][1]['params'] == {'limit': 200, 'level': 3, 'domain': 'alpha'}
    texte = sortie['texte']
    for attendu in ('alice', 'aucun', 'inconnue', 'remus', 'r1', '1000', '200', 'Réponse inattendue',
                    'Occurrences regroupées : 5', 'Résultat tronqué'):
        assert attendu in texte, attendu
    assert '\x1b' not in texte and '<img onerror=x>' in texte and sortie['sans_html']
    assert 'zz' not in texte


@avec_node
@pytest.mark.parametrize('limite,niveau,domaine', [
    ('0', '1', ''), ('500', '1', ''), ('true', '1', ''), ('', '1', ''), ('1.5', '1', ''),
    ('50', '0', ''), ('50', '4', ''), ('50', 'x', ''), ('50', '1', 'Alpha'), ('50', '1', 'a/b'),
    ('50', '1', '1a'), ('50', '1', 'a' * 33)])
def test_journal_parametres_invalides(limite, niveau, domaine):
    donnees = {'reponses': {'kernel/activity/list': {'detail': 1, 'entries': [], 'truncated': False}}}
    sortie = lancer("""
      await ouvrir('noyau-journaux');
      const avant = demandes.length;
      const selects = contenu().trouver((n) => n.nom === 'select');
      selects[0].value = donnees.l; selects[1].value = donnees.n;
      contenu().trouver((n) => n.nom === 'input')[0].saisir(donnees.d);
      await cliquer(contenu(), t('ui_noyau_actualiser'));
      return {envoyes: demandes.length - avant, texte: contenu().textContent};
    """, dict(donnees, l=limite, n=niveau, d=domaine))
    assert sortie['envoyes'] == 0 and 'Paramètre invalide' in sortie['texte']


@avec_node
def test_journal_niveau_depasse_et_vide():
    donnees = {'reponses': {'kernel/activity/list': {'detail': 1, 'entries': [], 'truncated': False}}}
    sortie = lancer("""
      await ouvrir('noyau-journaux');
      contenu().trouver((n) => n.nom === 'select')[1].value = '3';
      await cliquer(contenu(), t('ui_noyau_actualiser'));
      return contenu().textContent;
    """, donnees)
    assert 'dépasse le niveau de détail' in sortie and 'Aucune entrée' in sortie


CATALOGUE = {
    'proto': 'jumeaux/1', 'target': 'principale', 'domain': 'alpha', 'format': 1,
    'actions': [{'action': 'alpha/state/status', 'plugin': 'g1'},
                {'action': 'alpha/state/set', 'plugin': 'g1'}]}
DESCRIPTIONS = {
    'alpha/state/status': {'action': 'alpha/state/status', 'plugin': 'g1', 'privilege': 'g1::lire:admin',
                           'delay_s': 5, 'parameters': [], 'errors': ['not_available']},
    'alpha/state/set': {'action': 'alpha/state/set', 'plugin': 'g1', 'privilege': None, 'delay_s': None,
                        'parameters': [{'name': 'n', 'type': 'entier', 'required': True,
                                        'bounds': {'minimum': 1, 'maximum': 3}}], 'errors': []}}

PREAMBULE_CATALOGUE = """
const D2 = donnees;
"""


def donnees_catalogue(resultat):
    return {'reponses': {
        'kernel/state/services': SERVICES,
        'alpha/catalog/list': CATALOGUE,
        'gamma/catalog/list': dict(CATALOGUE, domain='gamma', actions=[
            {'action': 'alpha/state/status', 'plugin': 'g3'}]),
        'alpha/state/status': resultat}, 'descriptions': DESCRIPTIONS}


@avec_node
def test_catalogue_liste_description_et_lancement():
    resultat = {'etat': 'ok', 'token': 'AAA', 'x': {'Secret': 'BBB', 'passphrase': 'CCC', 'signature': 'DDD',
                'ncryptsec': 'EEE', 'cle': 'FFF', 'bearer': 'GGG', 'seed': 'HHH', 'mnemonic': 'III',
                'private_x': 'JJJ', 'psk': 'KKK', 'cookie': 'LLL', 'hmac': 'MMM', 'auth': 'NNN',
                'credential': 'OOO', 'pass': 'PPP',
                'l': [{'name': 'api_token', 'value': 'QQQ'}, {'key': 'Mot de passe', 'value': 'RRR'},
                      {'name': 'db_pass', 'value': 'SSS'}, {'name': 'nom', 'value': 'visible'}],
                'propre': '<img onerror=x>\x1b[0m'}}
    donnees = donnees_catalogue(resultat)
    sortie = lancer("""
      await ouvrir('noyau-catalogue');
      const services = contenu().textContent;
      const voir = contenu().trouver((n) => n.nom === 'button' && n.getAttribute('data-domaine'));
      const domaines_boutons = voir.map((b) => b.getAttribute('data-domaine'));
      voir[0].click(); await pause();
      const apres_liste = contenu().textContent;
      await cliquer(contenu(), 'alpha/state/set');
      const non_lancable = contenu().textContent;
      const lancer_set = boutons(contenu(), t('ui_noyau_lancer')).length;
      await cliquer(contenu(), 'alpha/state/status');
      const lancer_btn = boutons(contenu(), t('ui_noyau_lancer')).length;
      const avant = demandes.length;
      bouton(contenu(), t('ui_noyau_lancer')).click(); await pause();
      const boite = hote.document.body.trouver((n) => n.nom === 'dialog')[0];
      const texte_boite = boite.textContent;
      const sans_requete = demandes.length === avant;
      bouton(boite, t('ui_web_annuler')).click(); await pause();
      const apres_annulation = demandes.length === avant;
      bouton(contenu(), t('ui_noyau_lancer')).click(); await pause();
      const boite2 = hote.document.body.trouver((n) => n.nom === 'dialog')[0];
      bouton(boite2, t('ui_web_confirmer')).click(); await pause();
      return {services, domaines_boutons, apres_liste, non_lancable, lancer_set, lancer_btn, texte_boite,
              sans_requete, apres_annulation, demandes, fin: contenu().textContent,
              sans_html: SANS_HTML(contenu())};
    """, donnees)
    assert sortie['domaines_boutons'] == ['alpha', 'gamma']
    assert 'beta' in sortie['services']
    assert 'alpha/state/set' in sortie['apres_liste']
    assert 'ne peut pas être lancée' in sortie['non_lancable'] and sortie['lancer_set'] == 0
    assert sortie['lancer_btn'] == 1
    assert 'alpha/state/status' in sortie['texte_boite']
    assert sortie['sans_requete'] and sortie['apres_annulation']
    assert [d['action'] for d in sortie['demandes']] == [
        'kernel/state/services', 'alpha/catalog/list', 'alpha/catalog/describe',
        'alpha/catalog/describe', 'alpha/state/status']
    assert sortie['demandes'][-1]['params'] == {}
    assert sortie['demandes'][2]['params'] == {'action': 'alpha/state/set'}
    fin = sortie['fin']
    for secret in ('AAA', 'BBB', 'CCC', 'DDD', 'EEE', 'FFF', 'GGG', 'HHH', 'III', 'JJJ', 'KKK',
                   'LLL', 'MMM', 'NNN', 'OOO', 'PPP', 'QQQ', 'SSS'):
        assert secret not in fin, secret
    assert 'visible' in fin and fin.count('masquée') >= 16 and '\x1b' not in fin and sortie['sans_html']
    assert '<img onerror=x>' in fin


@avec_node
def test_catalogue_action_hors_domaine_ou_hors_catalogue():
    donnees = donnees_catalogue({'a': 1})
    sortie = lancer("""
      await ouvrir('noyau-catalogue');
      const voir = contenu().trouver((n) => n.nom === 'button' && n.getAttribute('data-domaine'));
      voir[1].click(); await pause();
      return {texte: contenu().textContent, n: demandes.map((d) => d.action),
              lancer: boutons(contenu(), t('ui_noyau_lancer')).length};
    """, donnees)
    assert 'Réponse inattendue' in sortie['texte'] and sortie['lancer'] == 0
    assert sortie['n'] == ['kernel/state/services', 'gamma/catalog/list']


@avec_node
def test_catalogue_description_incoherente_non_lancable():
    donnees = donnees_catalogue({'a': 1})
    donnees['descriptions'] = {'alpha/state/status': dict(DESCRIPTIONS['alpha/state/status'], action='alpha/autre/x')}
    sortie = lancer("""
      await ouvrir('noyau-catalogue');
      contenu().trouver((n) => n.nom === 'button' && n.getAttribute('data-domaine'))[0].click(); await pause();
      await cliquer(contenu(), 'alpha/state/status');
      return {texte: contenu().textContent, lancer: boutons(contenu(), t('ui_noyau_lancer')).length};
    """, donnees)
    assert 'Réponse inattendue' in sortie['texte'] and sortie['lancer'] == 0


@avec_node
@pytest.mark.parametrize('nom', ['profond', 'gros'])
def test_resultat_borne_en_profondeur_et_en_taille(nom):
    valeur = {'a': {'b': {'c': {'d': {'e': {'f': {'g': {'h': 'TROPPROFOND'}}}}}}}} if nom == 'profond' \
        else {'liste': ['x' * 100] * 1000}
    donnees = donnees_catalogue(valeur)
    sortie = lancer("""
      await ouvrir('noyau-catalogue');
      contenu().trouver((n) => n.nom === 'button' && n.getAttribute('data-domaine'))[0].click(); await pause();
      await cliquer(contenu(), 'alpha/state/status');
      bouton(contenu(), t('ui_noyau_lancer')).click(); await pause();
      bouton(hote.document.body.trouver((n) => n.nom === 'dialog')[0], t('ui_web_confirmer')).click(); await pause();
      const pre = contenu().trouver((n) => n.nom === 'pre')[0];
      return {texte: pre.textContent, tout: contenu().textContent};
    """, donnees)
    assert 'Données tronquées' in sortie['tout']
    assert 'TROPPROFOND' not in sortie['texte'] and len(sortie['texte'].encode()) <= 65536


@avec_node
def test_reponse_tardive_apres_changement_de_page():
    donnees = {'reponses': {'kernel/state/status': STATUS, 'kernel/activity/list': {
        'detail': 1, 'entries': [], 'truncated': False}}}
    sortie = lancer("""
      let liberer;
      donnees.reponses['kernel/state/status'] = {__attente: new Promise((r) => { liberer = r; })};
      await Paresia.demarrer(); await pause();
      Paresia.selectionner('noyau-journaux'); await pause();
      const avant = contenu().textContent;
      liberer(); await pause();
      return {avant, apres: contenu().textContent};
    """, donnees)
    assert sortie['avant'] == sortie['apres'] and 'Version' not in sortie['apres']


@avec_node
def test_erreur_de_session_et_occupation():
    donnees = {'reponses': {'kernel/state/status': {'__erreur': 'token_unknown'}}}
    sortie = lancer("await ouvrir(); return contenu().textContent;", donnees)
    assert 'Session' in sortie
    donnees = {'reponses': {'kernel/state/status': {'__erreur': 'command_busy'}}}
    sortie = lancer("await ouvrir(); return {t: contenu().textContent, b: boutons(contenu(), t('ui_web_reessayer')).length};",
                    donnees)
    assert sortie['b'] == 1


# --- Contrôles statiques ---------------------------------------------------------------------

def test_noyau_js_statique():
    texte = lire('noyau.js')
    assert 'SPDX-License-Identifier: AGPL-3.0-or-later' in texte and 'Suivi des versions' in texte
    for motif in ('innerHTML', 'outerHTML', 'insertAdjacentHTML', 'document.write', 'eval(', 'new Function',
                  'http://', 'https://', 'localStorage', 'sessionStorage', 'indexedDB', 'document.cookie',
                  'X-Admin-Token', 'Origin'):
        assert motif not in texte, motif
    assert not re.search(r'^\s*(import|export)\b', texte, re.M)
    for produit in ('bunker', 'relay', 'legal', 'nisaba', 'strfry'):
        assert produit not in texte.lower(), produit
    assert 'type: \'password\'' not in texte
    assert '<script src="noyau.js"></script>' in lire('index.html')


def test_cles_noyau_dans_les_catalogues():
    fr = json.loads((RACINE / 'i18n' / 'fr-FR.json').read_text(encoding='utf-8'))
    en = json.loads((RACINE / 'i18n' / 'en-US.json').read_text(encoding='utf-8'))
    utilisees = set(re.findall(r'ui_noyau_[a-z_]+', lire('noyau.js')))
    fixes = {c for c in utilisees if not c.endswith('_')}
    for cle in fixes:
        assert fr.get(cle, '').strip() and en.get(cle, '').strip(), cle
    for prefixe, suffixes in (('ui_noyau_ev_', ['action', 'refusal', 'session_open', 'session_close', 'protocol']),
                              ('ui_noyau_etape_', ['sent', 'received']),
                              ('ui_noyau_catalogue_', ['none', 'declaration', 'pair']),
                              ('ui_noyau_metriques_', ['enabled', 'disabled', 'unreadable'])):
        for suffixe in suffixes:
            assert fr[prefixe + suffixe] and en[prefixe + suffixe], prefixe + suffixe
    assert set(fr) == set(en)


def test_actions_appelees_documentees():
    """Les actions kernel/* de la page sont celles du tableau du protocole (§ 5.6)."""
    protocole = (RACINE / 'docs' / 'protocole.md').read_text(encoding='utf-8')
    if '`kernel/state/status`' not in protocole:
        pytest.skip('tableau du domaine kernel absent de ce protocole')
    for action in set(re.findall(r"'(kernel/[a-z/]+)'", lire('noyau.js'))):
        assert f'`{action}`' in protocole, action
