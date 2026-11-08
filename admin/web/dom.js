// SPDX-License-Identifier: AGPL-3.0-or-later
// Création d'éléments sans HTML interprété ; dépend de texte.js.
// Suivi des versions
//   3.0.0-alpha.41  2026-11-06  Première version.
//   0.1.13  2026-11-08  Refus des attributs qui chargent ou envoient du contenu.
//   0.1.15  2026-11-08  Refus des éléments hérités frame, frameset, applet et de l'attribut background.
(function (global) {
  'use strict';
  const P = global.Paresia = global.Paresia || {};
  const NOM_ELEMENT = /^[a-z][a-z0-9]*$/;
  const NOM_ATTRIBUT = /^[a-z][a-z0-9-]*$/;
  const ELEMENTS_REFUSES = new Set(['script', 'iframe', 'object', 'embed', 'style', 'link', 'meta', 'base', 'frame', 'frameset', 'applet']);
  const LIENS = new Set(['href', 'src', 'action']);
  const ATTRIBUTS_REFUSES = new Set(['formaction', 'srcset', 'poster', 'ping', 'data', 'srcdoc', 'background']);

  function chemin_admis(valeur) {
    return typeof valeur === 'string'
      && (valeur.startsWith('/admin/') || valeur.startsWith('/api/admin/'))
      && !valeur.includes('..') && !/[\p{Cc}\\]/u.test(valeur);
  }

  P.el = function (nom, attributs, ...enfants) {
    if (typeof nom !== 'string' || !NOM_ELEMENT.test(nom) || ELEMENTS_REFUSES.has(nom)) {
      throw new TypeError('element_refuse');
    }
    const element = global.document.createElement(nom);
    for (const cle of Object.keys(attributs || {})) {
      const valeur = attributs[cle];
      if (!NOM_ATTRIBUT.test(cle) || cle.startsWith('on') || cle === 'style'
          || ATTRIBUTS_REFUSES.has(cle)) {
        throw new TypeError('attribut_refuse');
      }
      if (valeur === false || valeur === null || valeur === undefined) continue;
      if (LIENS.has(cle)) {
        if (!chemin_admis(valeur)) throw new TypeError('lien_refuse');
        element.setAttribute(cle, valeur);
      } else {
        element.setAttribute(cle, valeur === true ? '' : P.filtrer(String(valeur)));
      }
    }
    if (enfants.length === 1 && typeof enfants[0] === 'string') {
      element.textContent = P.filtrer(enfants[0]);
      return element;
    }
    for (const enfant of enfants) {
      if (enfant === null || enfant === undefined || enfant === false) continue;
      element.appendChild(typeof enfant === 'string'
        ? global.document.createTextNode(P.filtrer(enfant)) : enfant);
    }
    return element;
  };

  P.vider = function (conteneur) {
    conteneur.textContent = '';
    return conteneur;
  };
})(globalThis);
