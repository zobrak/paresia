// SPDX-License-Identifier: AGPL-3.0-or-later
// Confirmation des opérations destructrices (boîte <dialog>) ; dépend de texte.js et dom.js.
// Suivi des versions
//   3.0.0-alpha.41  2026-11-06  Première version.
(function (global) {
  'use strict';
  const P = global.Paresia = global.Paresia || {};

  // Résout vrai seulement si l'utilisateur confirme ; avec nom_attendu, la saisie doit être exacte.
  P.confirmer = function (options) {
    const reglages = options || {};
    const nom = typeof reglages.nom_attendu === 'string' && reglages.nom_attendu !== ''
      ? reglages.nom_attendu : null;
    return new Promise(function (resoudre) {
      let confirme = false;
      const annuler = P.el('button', { type: 'button' }, P.t('ui_web_annuler'));
      const valider = P.el('button', { type: 'button' }, P.t('ui_web_confirmer'));
      const champs = [];
      let saisie = null;
      if (nom !== null) {
        saisie = P.el('input', { type: 'text', autocomplete: 'off', spellcheck: 'false' });
        champs.push(P.el('p', null, P.t('ui_web_saisir_nom') + ' ', P.el('code', null, nom)), saisie);
      }
      const boite = P.el('dialog', null,
        P.el('h2', null, P.t(reglages.titre_cle)),
        P.el('p', null, reglages.texte),
        ...champs,
        P.el('div', null, annuler, valider));

      const exact = function () { return nom === null || saisie.value === nom; };
      valider.disabled = !exact();
      if (saisie) {
        saisie.addEventListener('input', function () { valider.disabled = !exact(); });
      }
      annuler.addEventListener('click', function () { boite.close(); });
      valider.addEventListener('click', function () {
        if (!exact()) return;
        confirme = true;
        boite.close();
      });
      boite.addEventListener('close', function () {
        boite.remove();
        resoudre(confirme);
      });
      global.document.body.appendChild(boite);
      boite.showModal();
    });
  };
})(globalThis);
