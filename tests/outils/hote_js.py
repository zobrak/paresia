# SPDX-License-Identifier: AGPL-3.0-or-later
# Hôte de test des scripts de admin/web : node, vm, DOM et fetch simulés ; bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha.41  2026-11-06  Première version.
#   0.1.15  2026-11-08  Scripts chargés par élément simulé (hote.scripts), minuterie et AbortController du bac.
import json
import os
from pathlib import Path
import shutil
import subprocess

RACINE = Path(__file__).resolve().parents[2]
WEB = RACINE / 'admin' / 'web'
SCRIPTS = ('texte.js', 'dom.js', 'api.js', 'confirmation.js', 'app.js')
SCRIPTS_GREFFONS = ('texte.js', 'dom.js', 'api.js', 'confirmation.js', 'greffons.js', 'app.js')
NODE = shutil.which('node')

HOTE = r"""
'use strict';
const fs = require('fs');
const vm = require('vm');
const config = JSON.parse(process.env.HOTE_CONFIG);

class Noeud {
  constructor(nom) {
    this.nom = nom; this.attributs = new Map(); this.enfants = []; this.parent = null;
    this.ecouteurs = {}; this.texte = null; this.value = ''; this.disabled = false; this.ouvert = false;
  }
  get children() { return this.enfants.filter((e) => e.nom !== '#texte'); }
  get textContent() {
    if (this.nom === '#texte') return this.texte;
    return this.enfants.map((e) => e.textContent).join('');
  }
  set textContent(valeur) {
    for (const e of this.enfants) e.parent = null;
    this.enfants = [];
    if (valeur !== '') { const t = new Noeud('#texte'); t.texte = String(valeur); t.parent = this; this.enfants.push(t); }
  }
  appendChild(enfant) {
    enfant.parent = this; this.enfants.push(enfant);
    if (enfant.nom === 'script') hote.charger_script(enfant);
    return enfant;
  }
  remove() { if (this.parent) { this.parent.enfants = this.parent.enfants.filter((e) => e !== this); this.parent = null; } }
  setAttribute(cle, valeur) { this.attributs.set(cle, String(valeur)); }
  getAttribute(cle) { return this.attributs.has(cle) ? this.attributs.get(cle) : null; }
  hasAttribute(cle) { return this.attributs.has(cle); }
  addEventListener(type, f) { (this.ecouteurs[type] = this.ecouteurs[type] || []).push(f); }
  emettre(type) { for (const f of this.ecouteurs[type] || []) f({ type, target: this }); }
  click() { if (!this.disabled) this.emettre('click'); }
  saisir(valeur) { this.value = valeur; this.emettre('input'); }
  showModal() { this.ouvert = true; }
  close() { if (this.ouvert) { this.ouvert = false; this.emettre('close'); } }
  trouver(pred, sortie = []) {
    if (pred(this)) sortie.push(this);
    for (const e of this.enfants) e.trouver(pred, sortie);
    return sortie;
  }
}

const racine = new Noeud('html');
const corps = new Noeud('body');
racine.appendChild(corps);
const ids = {};
function creer(nom, id) { const n = new Noeud(nom); if (id) { n.setAttribute('id', id); ids[id] = n; } return n; }
for (const [nom, id] of [['nav', 'menu'], ['main', 'contenu'], ['link', 'feuille-langue'],
    ['summary', 'diagnostic-titre'], ['pre', 'diagnostic-texte']]) corps.appendChild(creer(nom, id));

const document = {
  documentElement: racine, body: corps, title: '', readyState: 'loading', ecouteurs: {},
  createElement: (nom) => new Noeud(nom),
  createTextNode: (t) => { const n = new Noeud('#texte'); n.texte = String(t); return n; },
  getElementById: (id) => ids[id] || null,
  addEventListener(type, f) { (this.ecouteurs[type] = this.ecouteurs[type] || []).push(f); },
};
racine.lang = '';

function reponse(statut, type, contenu) {
  const texte = typeof contenu === 'string' ? contenu : JSON.stringify(contenu);
  return {
    ok: statut >= 200 && statut < 300, status: statut,
    headers: { get: (n) => (n.toLowerCase() === 'content-type' ? type : null) },
    text: async () => texte,
  };
}

const hote = { appels: [], api: null, scripts: {}, reponse, document, Noeud };
// Un élément script ajouté au document : hote.scripts[src] s'exécute puis déclenche load ;
// absent : error ; une fonction qui rend false ne déclenche aucun événement.
hote.charger_script = (noeud) => {
  const src = noeud.getAttribute('src');
  Promise.resolve().then(async () => {
    const f = hote.scripts[src];
    if (typeof f !== 'function') { noeud.emettre('error'); return; }
    if ((await f()) === false) return;
    noeud.emettre('load');
  });
};
const navigator = { language: config.langue };
async function fetch(url, init) {
  hote.appels.push({ url, init });
  const m = /^i18n\/(fr-FR|en-US)\.json$/.exec(url);
  if (m) return reponse(200, 'application/json', fs.readFileSync(config.racine + '/i18n/' + m[1] + '.json', 'utf8'));
  if (hote.api) return hote.api(url, init);
  throw new TypeError('reseau');
}

const bac = { setTimeout, clearTimeout, AbortController, document, navigator, fetch, hote, donnees: JSON.parse(config.donnees), console };
const contexte = vm.createContext(bac);
for (const nom of config.scripts) {
  vm.runInContext(fs.readFileSync(config.web + '/' + nom, 'utf8'), contexte, { filename: nom });
}
(async () => {
  const r = await vm.runInContext('(async () => {' + config.scenario + '\n})()', contexte);
  console.log('RESULTAT ' + JSON.stringify(r === undefined ? null : r));
})().catch((e) => { console.error(String(e && e.stack || e)); process.exit(1); });
"""


def executer(scenario, *, langue='fr-FR', donnees=None, scripts=SCRIPTS):
    """Exécute le scénario (corps de fonction asynchrone) dans node ; retourne la valeur rendue.

    Le scénario voit `Paresia`, `hote` (appels, api, reponse, document), `donnees` et
    `navigator`. Les données sont transmises en JSON à caractères échappés.
    """
    config = {
        'racine': str(RACINE), 'web': str(WEB), 'scripts': list(scripts), 'langue': langue,
        'donnees': json.dumps(donnees, ensure_ascii=True), 'scenario': scenario,
    }
    env = {'PATH': os.environ.get('PATH', ''), 'HOTE_CONFIG': json.dumps(config, ensure_ascii=True)}
    fin = subprocess.run([NODE, '-e', HOTE], capture_output=True, text=True, env=env,
                         timeout=60, check=False)
    assert fin.returncode == 0, fin.stderr
    ligne = [x for x in fin.stdout.splitlines() if x.startswith('RESULTAT ')][-1]
    return json.loads(ligne[len('RESULTAT '):])
