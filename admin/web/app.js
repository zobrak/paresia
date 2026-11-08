// SPDX-License-Identifier: AGPL-3.0-or-later
// Coquille des pages d'administration : enregistrement des pages, menu, erreurs, diagnostic.
// Dépend de texte.js, dom.js et api.js.
// Suivi des versions
//   3.0.0-alpha.41  2026-11-06  Première version.
//   0.1.13  2026-11-08  Conteneur propre à chaque page ; réponses d'une page quittée ignorées.
//   0.1.15  2026-11-08  Découverte des pages des greffons avant la construction du menu.
(function (global) {
  'use strict';
  const P = global.Paresia = global.Paresia || {};
  const IDENTIFIANT = /^[a-z][a-z0-9-]*$/;
  const pages = [];
  const perimes = new WeakSet();
  let courant = null;

  P.pages = function () { return pages.slice(); };

  // Les pages s'enregistrent elles-mêmes ; le menu est construit à partir de ces enregistrements.
  P.enregistrer = function (page) {
    if (page === null || typeof page !== 'object' || typeof page.id !== 'string'
        || !IDENTIFIANT.test(page.id) || typeof page.titre_cle !== 'string'
        || typeof page.afficher !== 'function' || pages.some((autre) => autre.id === page.id)) {
      throw new TypeError('page_refusee');
    }
    pages.push({ id: page.id, titre_cle: page.titre_cle, afficher: page.afficher });
  };

  // Zone de diagnostic repliée : texte filtré, 200 caractères au plus.
  // Vrai tant que le conteneur n'a pas été quitté par l'utilisateur.
  P.actif = function (conteneur) {
    return conteneur !== null && typeof conteneur === 'object' && !perimes.has(conteneur);
  };

  P.diagnostiquer = function (detail, conteneur) {
    if (conteneur !== undefined && !P.actif(conteneur)) return;
    const zone = global.document.getElementById('diagnostic-texte');
    if (zone) zone.textContent = Array.from(P.filtrer(detail)).slice(0, 200).join('');
  };

  // Affiche l'erreur dans le conteneur ; rejouer, s'il est fourni, sert au bouton « réessayer ».
  P.afficher_erreur = function (conteneur, erreur, rejouer) {
    const presentation = P.presenter_erreur(erreur);
    if (!P.actif(conteneur)) return presentation;
    P.vider(conteneur);
    conteneur.appendChild(P.el('p', { role: 'alert' }, presentation.message));
    if (presentation.reessayer && typeof rejouer === 'function') {
      const bouton = P.el('button', { type: 'button' }, P.t('ui_web_reessayer'));
      bouton.addEventListener('click', function () { rejouer(); });
      conteneur.appendChild(bouton);
    }
    P.diagnostiquer(presentation.detail, conteneur);
    return presentation;
  };

  P.selectionner = function (id) {
    const page = pages.find((candidate) => candidate.id === id);
    const contenu = global.document.getElementById('contenu');
    if (!page || !contenu) return;
    if (courant !== null) {
      perimes.add(courant);
      courant.remove();
    }
    P.vider(contenu);
    const conteneur = P.el('div', { 'data-page': page.id });
    courant = conteneur;
    contenu.appendChild(conteneur);
    try {
      const suite = page.afficher(conteneur);
      if (suite && typeof suite.catch === 'function') {
        suite.catch(function (erreur) { P.afficher_erreur(conteneur, erreur); });
      }
    } catch (erreur) {
      P.afficher_erreur(conteneur, erreur);
    }
  };

  P.construire_menu = function () {
    const menu = global.document.getElementById('menu');
    P.vider(menu);
    menu.setAttribute('aria-label', P.t('ui_web_menu'));
    for (const page of pages) {
      const bouton = P.el('button', { type: 'button', 'data-page': page.id }, P.t(page.titre_cle));
      bouton.addEventListener('click', function () { P.selectionner(page.id); });
      menu.appendChild(bouton);
    }
  };

  P.demarrer = async function () {
    await P.charger_langue();
    const document = global.document;
    document.title = P.t('ui_web_titre');
    const contenu = document.getElementById('contenu');
    P.vider(contenu);
    contenu.appendChild(P.el('p', null, P.t('ui_web_chargement')));
    document.getElementById('diagnostic-titre').textContent = P.t('ui_web_diagnostic');
    if (typeof P.decouvrir === 'function') await P.decouvrir();
    P.construire_menu();
    if (pages.length > 0) P.selectionner(pages[0].id);
    else P.vider(contenu);
  };

  if (global.document.readyState === 'loading') {
    global.document.addEventListener('DOMContentLoaded', function () { P.demarrer(); });
  } else {
    P.demarrer();
  }
})(globalThis);
