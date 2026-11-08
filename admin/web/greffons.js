// SPDX-License-Identifier: AGPL-3.0-or-later
// Découverte des pages déclarées par les greffons : index statique, catalogues fusionnés sans
// collision, scripts du même site. Dépend de texte.js, dom.js et app.js (enregistrement des pages).
// Une page de greffon s'enregistre par Paresia.enregistrer pendant l'exécution de son script,
// utilise le seul conteneur reçu et contrôle Paresia.actif avant toute écriture tardive.
// Suivi des versions
//   0.1.15  2026-11-08  Première version ; délai de lecture (AbortController) et durée totale bornée.
(function (global) {
  'use strict';
  const P = global.Paresia = global.Paresia || {};
  const RACINE = '/admin/greffons/';
  const NOM = /^[a-z][a-z0-9-]{0,31}$/;
  const IDENTIFIANT = /^[a-z][a-z0-9-]{0,31}$/;
  const SCRIPT = /^[a-z0-9][a-z0-9._-]*\.js$/;
  const CLE_TITRE = /^ui_[a-z0-9_]{1,100}$/;
  const CLE_TEXTE = /^[a-z][a-z0-9_]{0,100}$/;
  const MAX_GREFFONS = 16;
  const MAX_PAGES = 16;
  const MAX_INDEX = 64 * 1024;
  const MAX_CATALOGUE = 1024 * 1024;
  const DELAI_MS = 10000;
  const DELAI_TOTAL_MS = 30000;
  const a_cle_noyau = P.a_cle;
  const t_noyau = P.t;
  const externes = new Map();
  let en_cours = null;

  // Les textes des greffons s'ajoutent à ceux du noyau, qui gardent toujours la priorité.
  P.a_cle = function (cle) {
    return a_cle_noyau(cle) || (typeof cle === 'string' && externes.has(cle));
  };

  P.t = function (cle) {
    if (typeof cle === 'string' && !a_cle_noyau(cle) && externes.has(cle)) {
      return P.filtrer(externes.get(cle));
    }
    return t_noyau(cle);
  };

  function refus(code) {
    const erreur = new Error(code);
    erreur.refus = code;
    return erreur;
  }

  function octets(texte) {
    let total = 0;
    for (const caractere of texte) {
      const point = caractere.codePointAt(0);
      total += point < 0x80 ? 1 : point < 0x800 ? 2 : point < 0x10000 ? 3 : 4;
    }
    return total;
  }

  // Lecture d'un document JSON du même site, de taille et de type contrôlés.
  async function lire_json(url, limite) {
    const controleur = new global.AbortController();
    let minuteur = null;
    // Le délai couvre la requête et la lecture du corps ; il rejette même si fetch ignore le signal.
    const echeance = new Promise(function (resolve, reject) {
      minuteur = global.setTimeout(function () {
        controleur.abort();
        reject(refus('delai'));
      }, DELAI_MS);
    });
    echeance.catch(function () {});
    const attendre = async function (promesse) {
      try {
        return await Promise.race([promesse, echeance]);
      } catch (erreur) {
        throw refus(erreur && erreur.refus === 'delai' ? 'delai' : 'illisible');
      }
    };
    try {
      const reponse = await attendre(global.fetch(url, { credentials: 'same-origin', signal: controleur.signal }));
      if (!reponse || !reponse.ok) throw refus('absent');
      const type = reponse.headers && reponse.headers.get('content-type');
      if (typeof type !== 'string' || !/^application\/json\s*(;|$)/i.test(type)) throw refus('type');
      const annonce = Number(reponse.headers.get('content-length'));
      if (Number.isFinite(annonce) && annonce > limite) throw refus('taille');
      const texte = await attendre(reponse.text());
      if (typeof texte !== 'string' || octets(texte) > limite) throw refus('taille');
      try {
        return JSON.parse(texte);
      } catch (erreur) {
        throw refus('json');
      }
    } finally {
      global.clearTimeout(minuteur);
    }
  }

  function objet(valeur) {
    return valeur !== null && typeof valeur === 'object' && !Array.isArray(valeur);
  }

  function cles_exactes(valeur, attendues) {
    const cles = Object.keys(valeur).sort();
    return cles.length === attendues.length && attendues.every((cle, i) => cle === cles[i]);
  }

  // Valide un greffon ; retourne un objet propre (chaînes recopiées), ou lève un refus.
  function valider_greffon(brut) {
    if (!objet(brut) || !cles_exactes(brut, ['nom', 'pages'])) throw refus('descripteur_invalide');
    if (typeof brut.nom !== 'string' || !NOM.test(brut.nom)) throw refus('nom_invalide');
    if (!Array.isArray(brut.pages) || brut.pages.length > MAX_PAGES) throw refus('pages_invalides');
    const ids = new Set();
    const pages = brut.pages.map(function (page) {
      if (!objet(page) || !cles_exactes(page, ['id', 'script', 'titre_cle'])) throw refus('page_invalide');
      if (typeof page.id !== 'string' || !IDENTIFIANT.test(page.id) || ids.has(page.id)) {
        throw refus('page_invalide');
      }
      if (typeof page.titre_cle !== 'string' || !CLE_TITRE.test(page.titre_cle)) {
        throw refus('page_invalide');
      }
      if (typeof page.script !== 'string' || !SCRIPT.test(page.script) || page.script.includes('..')) {
        throw refus('page_invalide');
      }
      ids.add(page.id);
      return { id: page.id, titre_cle: page.titre_cle, script: page.script };
    });
    pages.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
    return { nom: brut.nom, pages };
  }

  // Catalogue de la langue courante, sinon de fr-FR ; objet de chaînes aux clés préfixées.
  async function lire_catalogue(greffon) {
    const base = RACINE + greffon.nom + '/i18n/';
    let brut = null;
    for (const langue of [P.langue(), 'fr-FR']) {
      try {
        brut = await lire_json(base + langue + '.json', MAX_CATALOGUE);
        break;
      } catch (erreur) {
        if (!erreur.refus || erreur.refus === 'delai') throw erreur;
      }
    }
    if (brut === null) throw refus('catalogue_indisponible');
    if (!objet(brut)) throw refus('catalogue_invalide');
    const prefixe = 'ui_' + greffon.nom.replace(/-/g, '_') + '_';
    const textes = new Map();
    for (const cle of Object.keys(brut)) {
      if (typeof brut[cle] !== 'string' || !CLE_TEXTE.test(cle)) throw refus('catalogue_invalide');
      if (!cle.startsWith(prefixe)) throw refus('cle_hors_prefixe');
      if (a_cle_noyau(cle) || externes.has(cle)) throw refus('cle_en_collision');
      textes.set(cle, brut[cle]);
    }
    return textes;
  }

  // Charge un script du dossier du greffon ; chemin recomposé ici, jamais repris tel quel.
  function charger_script(greffon, page) {
    return new Promise(function (resolve) {
      let fini = false;
      let minuteur = null;
      const finir = function (code) {
        if (fini) return;
        fini = true;
        if (minuteur !== null) global.clearTimeout(minuteur);
        resolve(code);
      };
      const element = global.document.createElement('script');
      element.async = false;
      element.setAttribute('src', RACINE + greffon.nom + '/' + page.script);
      element.addEventListener('load', function () { finir(null); });
      element.addEventListener('error', function () { finir('script_introuvable'); });
      minuteur = global.setTimeout(function () {
        element.remove();
        finir('delai_depasse');
      }, DELAI_MS);
      global.document.body.appendChild(element);
    });
  }

  async function charger_pages(greffon, lignes, etat) {
    for (const page of greffon.pages) {
      if (etat.abandon) return;
      const libelle = greffon.nom + '/' + page.id;
      if (P.pages().some((autre) => autre.id === page.id)) {
        lignes.push(t_noyau('ui_web_greffon_page_ecartee') + ' : ' + libelle + ' (page_en_collision)');
        continue;
      }
      const code = await charger_script(greffon, page);
      const inscrite = P.pages().some((autre) => autre.id === page.id);
      if (code !== null || !inscrite) {
        lignes.push(t_noyau('ui_web_greffon_page_ecartee') + ' : ' + libelle + ' (' + (code || 'non_enregistree') + ')');
      }
    }
  }

  async function decouvrir(lignes, etat) {
    let index;
    try {
      index = await lire_json(RACINE + 'index.json', MAX_INDEX);
      if (!objet(index) || !cles_exactes(index, ['format', 'greffons']) || index.format !== 1
          || !Array.isArray(index.greffons) || index.greffons.length > MAX_GREFFONS) {
        throw refus('index_invalide');
      }
    } catch (erreur) {
      lignes.push(t_noyau('ui_web_greffon_index_indisponible') + ' (' + (erreur.refus || 'illisible') + ')');
      return;
    }
    const valides = [];
    index.greffons.forEach(function (brut, rang) {
      try {
        valides.push(valider_greffon(brut));
      } catch (erreur) {
        // Aucune valeur reçue n'est recopiée : seul le rang et le code de refus sont signalés.
        lignes.push(t_noyau('ui_web_greffon_refuse') + ' : #' + rang + ' (' + (erreur.refus || 'descripteur_invalide') + ')');
      }
    });
    // Un nom présent deux fois ne désigne aucun greffon de confiance : tous ses exemplaires sont écartés.
    const doubles = new Set(valides.map((g) => g.nom).filter((nom, i, tous) => tous.indexOf(nom) !== i));
    const retenus = valides.filter(function (greffon) {
      if (!doubles.has(greffon.nom)) return true;
      lignes.push(t_noyau('ui_web_greffon_refuse') + ' : ' + greffon.nom + ' (nom_en_double)');
      return false;
    });
    retenus.sort((a, b) => (a.nom < b.nom ? -1 : a.nom > b.nom ? 1 : 0));
    for (const greffon of retenus) {
      if (etat.abandon) return;
      try {
        const textes = await lire_catalogue(greffon);
        if (etat.abandon) return;
        for (const [cle, valeur] of textes) externes.set(cle, valeur);
      } catch (erreur) {
        lignes.push(t_noyau('ui_web_greffon_refuse') + ' : ' + greffon.nom + ' (' + (erreur.refus || 'catalogue_invalide') + ')');
        continue;
      }
      await charger_pages(greffon, lignes, etat);
    }
  }

  // Appelée une fois au démarrage, après le chargement de la langue ; ne lève jamais.
  // La durée totale est bornée : à l'échéance, les greffons restants sont abandonnés et le noyau
  // construit son menu avec les pages déjà enregistrées.
  P.decouvrir = function () {
    if (en_cours === null) {
      const lignes = [];
      const etat = { abandon: false };
      let minuteur = null;
      const borne = new Promise(function (resolve) {
        minuteur = global.setTimeout(function () {
          etat.abandon = true;
          lignes.push(t_noyau('ui_web_greffon_refuse') + ' : * (delai_total)');
          resolve();
        }, DELAI_TOTAL_MS);
      });
      const travail = decouvrir(lignes, etat).catch(function () {
        lignes.push(t_noyau('ui_web_greffon_index_indisponible'));
      });
      en_cours = Promise.race([travail, borne]).then(function () {
        global.clearTimeout(minuteur);
        if (lignes.length > 0) P.diagnostiquer(lignes.join(' ; '));
      });
    }
    return en_cours;
  };
})(globalThis);
