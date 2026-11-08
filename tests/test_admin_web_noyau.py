# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests du noyau web : attributs refusés et isolation de chaque page ; dépendances : pytest, node.
# Suivi des versions
#   0.1.13  2026-11-08  Première version.
import importlib.util
from pathlib import Path
import shutil

import pytest

RACINE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('hote_js', RACINE / 'tests' / 'outils' / 'hote_js.py')
hote_js = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hote_js)

avec_node = pytest.mark.skipif(shutil.which('node') is None, reason='node absent')


@avec_node
def test_attributs_refuses_et_admis():
    sortie = hote_js.executer("""
      const refus = {};
      for (const nom of ['formaction', 'srcset', 'poster', 'ping', 'data', 'srcdoc']) {
        for (const valeur of ['/admin/x', 'quelconque']) {
          try { Paresia.el('a', {[nom]: valeur}); refus[nom + valeur] = false; }
          catch (e) { refus[nom + valeur] = e instanceof TypeError && e.message === 'attribut_refuse'; }
        }
      }
      const ok = Paresia.el('input', {class: 'c', type: 'text'});
      return {refus, classe: ok.getAttribute('class'), type: ok.getAttribute('type')};
    """)
    assert len(sortie['refus']) == 12 and all(sortie['refus'].values()), sortie['refus']
    assert sortie['classe'] == 'c' and sortie['type'] == 'text'


@avec_node
def test_reponse_apres_sortie_ignoree():
    sortie = hote_js.executer("""
      let resoudre;
      const attente = new Promise((r) => { resoudre = r; });
      let conteneurA = null;
      Paresia.enregistrer({id: 'a', titre_cle: 'ui_web_menu', afficher: (c) => {
        conteneurA = c;
        return attente.then(() => { if (Paresia.actif(c)) c.textContent = 'tardif'; });
      }});
      Paresia.enregistrer({id: 'b', titre_cle: 'ui_web_menu', afficher: (c) => { c.textContent = 'b'; }});
      await Paresia.demarrer();
      const d = hote.document;
      const avant_actif = Paresia.actif(conteneurA);
      Paresia.selectionner('b');
      const apres = d.getElementById('contenu').textContent;
      const diag = d.getElementById('diagnostic-texte').textContent;
      resoudre();
      await attente; await Promise.resolve();
      return {avant_actif, actif: Paresia.actif(conteneurA), retire: conteneurA.parent === null,
              apres, contenu: d.getElementById('contenu').textContent,
              diag, diag_fin: d.getElementById('diagnostic-texte').textContent};
    """)
    assert sortie['avant_actif'] is True and sortie['actif'] is False and sortie['retire'] is True
    assert sortie['apres'] == 'b' and sortie['contenu'] == 'b'
    assert sortie['diag'] == sortie['diag_fin']


@avec_node
def test_rejet_apres_sortie_sans_message():
    sortie = hote_js.executer("""
      let rejeter;
      const attente = new Promise((_, r) => { rejeter = r; });
      Paresia.enregistrer({id: 'a', titre_cle: 'ui_web_menu', afficher: () => attente});
      Paresia.enregistrer({id: 'b', titre_cle: 'ui_web_menu', afficher: (c) => { c.textContent = 'b'; }});
      await Paresia.demarrer();
      Paresia.selectionner('b');
      rejeter(new Paresia.ErreurApi('command_busy', 'detail'));
      for (let i = 0; i < 5; i++) await Promise.resolve();
      const d = hote.document;
      return {contenu: d.getElementById('contenu').textContent,
              diag: d.getElementById('diagnostic-texte').textContent,
              alertes: d.getElementById('contenu').trouver((n) => n.getAttribute('role') === 'alert').length};
    """)
    assert sortie == {'contenu': 'b', 'diag': '', 'alertes': 0}


@avec_node
def test_rejet_page_courante_affiche_erreur():
    sortie = hote_js.executer("""
      Paresia.enregistrer({id: 'a', titre_cle: 'ui_web_menu', afficher: () => Promise.reject(new Paresia.ErreurApi('command_busy', 'detail'))});
      await Paresia.demarrer();
      for (let i = 0; i < 5; i++) await Promise.resolve();
      return hote.document.getElementById('contenu').trouver((n) => n.getAttribute('role') === 'alert').length;
    """)
    assert sortie == 1
