// SPDX-License-Identifier: AGPL-3.0-or-later
// Filtrage des textes affichés, choix de la langue et catalogues ; aucune dépendance.
// Suivi des versions
//   3.0.0-alpha.41  2026-11-06  Première version.
(function (global) {
  'use strict';
  const P = global.Paresia = global.Paresia || {};
  const LANGUES = ['fr-FR', 'en-US'];
  const DEFAUT = 'fr-FR';
  const INTERDITS = /[\p{Cc}\p{Cf}\p{Zl}\p{Zp}\p{Cs}\p{Co}]/gu;
  let catalogue = {};
  let langue = DEFAUT;

  // Équivalent de server.commun.texte.filtrer : les caractères de contrôle deviennent U+FFFD.
  P.filtrer = function (texte) {
    return typeof texte === 'string' ? texte.replace(INTERDITS, '�') : '';
  };

  // Étiquette BCP 47 exacte, sinon langue seule, sinon langue par défaut.
  P.choisir_langue = function (etiquette) {
    if (typeof etiquette !== 'string') return DEFAUT;
    const minuscule = etiquette.toLowerCase();
    for (const candidate of LANGUES) {
      if (candidate.toLowerCase() === minuscule) return candidate;
    }
    const base = minuscule.split('-')[0];
    for (const candidate of LANGUES) {
      if (candidate.toLowerCase().split('-')[0] === base) return candidate;
    }
    return DEFAUT;
  };

  P.langue = function () { return langue; };

  P.a_cle = function (cle) {
    return typeof cle === 'string' && Object.prototype.hasOwnProperty.call(catalogue, cle);
  };

  // Texte du catalogue, ou la clé elle-même si elle manque ; toujours filtré.
  P.t = function (cle) {
    if (typeof cle !== 'string') return '';
    return P.filtrer(P.a_cle(cle) ? catalogue[cle] : cle);
  };

  P.charger_langue = async function () {
    langue = P.choisir_langue(global.navigator && global.navigator.language);
    const charge = {};
    try {
      const reponse = await global.fetch('i18n/' + langue + '.json', { credentials: 'same-origin' });
      if (reponse.ok) {
        const brut = JSON.parse(await reponse.text());
        if (brut !== null && typeof brut === 'object' && !Array.isArray(brut)) {
          for (const cle of Object.keys(brut)) {
            if (typeof brut[cle] === 'string') charge[cle] = brut[cle];
          }
        }
      }
    } catch (erreur) {
      // Catalogue indisponible : les clés servent de repli.
    }
    catalogue = charge;
    const document = global.document;
    document.documentElement.lang = langue;
    const feuille = document.getElementById('feuille-langue');
    if (feuille) feuille.setAttribute('href', 'langues/' + langue + '.css');
    return langue;
  };
})(globalThis);
