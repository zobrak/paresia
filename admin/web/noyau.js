// SPDX-License-Identifier: AGPL-3.0-or-later
// Pages du noyau : état des démons, journal d'activité et catalogue générique des actions.
// Lecture seule hors lancement confirmé d'une action sans paramètre ; aucune connaissance d'un produit.
// Dépend de texte.js, dom.js, api.js, confirmation.js et app.js (chargé avant lui : Paresia.enregistrer).
// Suivi des versions
//   0.1.16  2026-11-08  Première version.
(function (global) {
  'use strict';
  const P = global.Paresia = global.Paresia || {};
  const DOMAINE = /^[a-z][a-z0-9_]{0,31}$/;
  const DEMON = /^[a-z][a-z0-9-]{0,31}$/;
  const ACTION = /^(?=.{1,128}$)[a-z][a-z0-9_-]*(?:\/[a-z][a-z0-9_-]*){1,3}$/;
  const SENSIBLE = /secret|pass|password|passphrase|token|jeton|key|cle|clé|signature|ncryptsec|nsec|auth|credential|bearer|seed|mnemonic|private|psk|cookie|hmac/i;
  const LIMITES = ['10', '50', '100', '200'];
  const NIVEAUX = ['1', '2', '3'];
  const TEXTE_MAX = 512;
  const PROFONDEUR_MAX = 6;
  const OCTETS_MAX = 64 * 1024;
  const METRIQUES = ['enabled', 'disabled', 'unreadable'];
  const CATALOGUES = ['none', 'declaration', 'pair'];
  const EVENEMENTS = ['action', 'refusal', 'session_open', 'session_close', 'protocol'];

  class Invalide extends Error {}

  function invalide() { throw new Invalide('invalide'); }
  function objet(v) { if (v === null || typeof v !== 'object' || Array.isArray(v)) invalide(); return v; }
  function tableau(v, max) { if (!Array.isArray(v) || v.length > max) invalide(); return v; }
  function texte(v) { if (typeof v !== 'string' || v.length > TEXTE_MAX) invalide(); return v; }
  function entier(v, min, max) {
    if (!Number.isSafeInteger(v) || v < min || v > max) invalide();
    return v;
  }
  function booleen(v) { if (typeof v !== 'boolean') invalide(); return v; }
  function nombre(v) { if (typeof v !== 'number' || !Number.isFinite(v)) invalide(); return v; }
  function parmi(v, liste) { if (!liste.includes(v)) invalide(); return v; }
  function ou_nul(v, controle) { return v === null ? null : controle(v); }
  // Champ facultatif : absent ou nul → undefined ; présent → contrôlé.
  function facultatif(o, cle, controle) {
    return Object.prototype.hasOwnProperty.call(o, cle) && o[cle] !== undefined ? controle(o[cle]) : undefined;
  }

  function paragraphe(cle, role) {
    return P.el('p', role ? { role: role } : null, P.t(cle));
  }

  function tableau_html(entetes, lignes) {
    const tete = P.el('tr', null, ...entetes.map((cle) => P.el('th', null, P.t(cle))));
    const corps = lignes.map((cellules) => P.el('tr', null, ...cellules.map(
      (c) => P.el('td', null, c))));
    return P.el('table', null, P.el('thead', null, tete), P.el('tbody', null, ...corps));
  }

  function libelle(cle) { return P.a_cle(cle) ? P.t(cle) : P.t('ui_noyau_invalide'); }

  // Appelle l'action, vérifie que la page est encore là, puis écrit le rendu dans le corps.
  // `rendre` valide la réponse et rend un élément ; une réponse inattendue donne la marque d'invalidité.
  async function requete(conteneur, corps, action, params, rendre) {
    const rejouer = function () { return requete(conteneur, corps, action, params, rendre); };
    let donnees;
    try {
      donnees = await P.appeler(action, params);
    } catch (erreur) {
      if (P.actif(conteneur)) P.afficher_erreur(corps, erreur, rejouer);
      return;
    }
    if (!P.actif(conteneur)) return;
    let rendu;
    try {
      rendu = rendre(donnees);
    } catch (erreur) {
      if (!(erreur instanceof Invalide)) throw erreur;
      rendu = paragraphe('ui_noyau_invalide', 'alert');
    }
    P.vider(corps);
    corps.appendChild(rendu);
  }

  function section(conteneur, titre_cle, recharger, avant) {
    const bouton = P.el('button', { type: 'button' }, P.t('ui_noyau_actualiser'));
    const corps = P.el('div', null);
    bouton.addEventListener('click', function () { recharger(); });
    const racine = P.el('section', null, P.el('h2', null, P.t(titre_cle)), bouton, avant || null, corps);
    conteneur.appendChild(racine);
    return corps;
  }

  // --- Page État ---------------------------------------------------------------------------

  function rendre_resume(d, etat) {
    objet(d);
    const demons = tableau(d.daemons, 16).map(function (x) {
      objet(x);
      return {
        name: texte(x.name), unit: texte(x.unit), metrics: parmi(x.metrics, METRIQUES),
        age: facultatif(x, 'sample_age_s', (v) => entier(v, 0, 2 ** 53))
      };
    });
    if (demons.some((x) => !DEMON.test(x.name))) invalide();
    const version = texte(d.version);
    const duree = entier(d.uptime_s, 0, 2 ** 53);
    const sessions = entier(d.sessions, 0, 2 ** 53);
    const detail = entier(d.activity_detail, 1, 3);
    etat.demons = demons.map((x) => x.name);
    const lignes = demons.map((x) => [x.name, x.unit, libelle('ui_noyau_metriques_' + x.metrics),
      x.age === undefined ? '' : String(x.age)]);
    return P.el('div', null,
      P.el('dl', null,
        P.el('dt', null, P.t('ui_noyau_version')), P.el('dd', null, version),
        P.el('dt', null, P.t('ui_noyau_uptime')), P.el('dd', null, String(duree)),
        P.el('dt', null, P.t('ui_noyau_sessions')), P.el('dd', null, String(sessions)),
        P.el('dt', null, P.t('ui_noyau_detail')), P.el('dd', null, String(detail))),
      tableau_html(['ui_noyau_demon', 'ui_noyau_unite', 'ui_noyau_metriques_etat', 'ui_noyau_age'], lignes));
  }

  function rendre_metriques(d) {
    objet(d);
    texte(d.daemon);
    if (!booleen(d.available)) {
      return P.el('div', null, paragraphe('ui_noyau_aucune_metrique'), paragraphe('ui_noyau_metriques_rappel'));
    }
    const lignes = tableau(d.samples, 500).map(function (s) {
      objet(s);
      const etiquettes = objet(s.labels);
      const liste = Object.keys(etiquettes).map((cle) => cle + '=' + texte(etiquettes[cle]));
      return [texte(s.name), liste.join(', '), String(nombre(s.value))];
    });
    return tableau_html(['ui_noyau_nom', 'ui_noyau_etiquettes', 'ui_noyau_valeur'], lignes);
  }

  function rendre_config(d) {
    objet(d);
    texte(d.daemon);
    const lignes = tableau(d.options, 500).map(function (o) {
      objet(o);
      const masquee = booleen(o.masked);
      const valeur = o.value;
      let affichee;
      if (masquee || valeur === null) {
        affichee = P.t('ui_noyau_masquee');
      } else if (typeof valeur === 'string') {
        affichee = texte(valeur);
      } else if (typeof valeur === 'boolean' || typeof valeur === 'number') {
        affichee = String(valeur);
      } else {
        invalide();
      }
      return [texte(o.section), texte(o.key), texte(o.type), affichee];
    });
    return tableau_html(['ui_noyau_section', 'ui_noyau_cle', 'ui_noyau_type', 'ui_noyau_valeur'], lignes);
  }

  function page_etat(conteneur) {
    const etat = { demons: [] };
    let choix_metriques = null;
    let choix_config = null;

    function proposer(zone, action, rendre, memoriser) {
      P.vider(zone.choix);
      for (const nom of etat.demons) {
        const bouton = P.el('button', { type: 'button', 'data-demon': nom }, nom);
        bouton.addEventListener('click', function () {
          memoriser(nom);
          requete(conteneur, zone.corps, action, { daemon: nom }, rendre);
        });
        zone.choix.appendChild(bouton);
      }
    }

    const resume = section(conteneur, 'ui_noyau_resume', function () { charger(); });
    const zone_m = { choix: P.el('div', null), corps: null };
    const zone_c = { choix: P.el('div', null), corps: null };
    zone_m.corps = section(conteneur, 'ui_noyau_metriques', function () {
      if (choix_metriques !== null) {
        requete(conteneur, zone_m.corps, 'kernel/state/metrics', { daemon: choix_metriques }, rendre_metriques);
      }
    }, zone_m.choix);
    zone_c.corps = section(conteneur, 'ui_noyau_configuration', function () {
      if (choix_config !== null) {
        requete(conteneur, zone_c.corps, 'kernel/state/config', { daemon: choix_config }, rendre_config);
      }
    }, zone_c.choix);
    zone_m.corps.appendChild(paragraphe('ui_noyau_choisir_demon'));
    zone_c.corps.appendChild(paragraphe('ui_noyau_choisir_demon'));

    function charger() {
      return requete(conteneur, resume, 'kernel/state/status', {}, function (d) {
        const rendu = rendre_resume(d, etat);
        proposer(zone_m, 'kernel/state/metrics', rendre_metriques, (n) => { choix_metriques = n; });
        proposer(zone_c, 'kernel/state/config', rendre_config, (n) => { choix_config = n; });
        return rendu;
      });
    }
    return charger();
  }

  // --- Page Journaux -----------------------------------------------------------------------

  const CHAMPS_ENTREE = {
    session: (v) => entier(v, 0, 2 ** 53),
    duration_ms: (v) => entier(v, 0, 2 ** 53),
    twin: (v) => ou_nul(v, texte),
    count: (v) => entier(v, 1, 10 ** 6),
    request_id: texte,
    step: (v) => parmi(v, ['sent', 'received']),
    ok: booleen,
    code: texte,
    bytes: (v) => entier(v, 0, 2 ** 53),
    http_status: (v) => entier(v, 100, 599),
    peer_uid: (v) => entier(v, 0, 2 ** 32)
  };
  const ETIQUETTES_ENTREE = {
    duration_ms: 'ui_noyau_duree', twin: 'ui_noyau_jumeau', count: 'ui_noyau_regroupe',
    request_id: 'ui_noyau_request_id', step: 'ui_noyau_etape', ok: 'ui_noyau_ok', code: 'ui_noyau_code',
    bytes: 'ui_noyau_taille', http_status: 'ui_noyau_http', peer_uid: 'ui_noyau_uid_pair'
  };

  function ligne_entree(e) {
    objet(e);
    const date = texte(e.ts);
    const niveau = entier(e.level, 1, 3);
    const evenement = libelle('ui_noyau_ev_' + parmi(e.event, EVENEMENTS));
    const admin = ou_nul(e.admin, texte);
    const domaine = facultatif(e, 'domain', (v) => ou_nul(v, texte));
    const action = facultatif(e, 'action', (v) => ou_nul(v, texte));
    const resultat = facultatif(e, 'result', texte);
    const details = [];
    for (const cle of Object.keys(CHAMPS_ENTREE)) {
      const v = facultatif(e, cle, CHAMPS_ENTREE[cle]);
      if (v === undefined || v === null || !ETIQUETTES_ENTREE[cle]) continue;
      let affichee = String(v);
      if (cle === 'step') affichee = libelle('ui_noyau_etape_' + v);
      else if (cle === 'ok') affichee = P.t(v ? 'ui_noyau_oui' : 'ui_noyau_non');
      details.push(P.t(ETIQUETTES_ENTREE[cle]) + ' : ' + affichee);
    }
    const cible = (domaine === null || domaine === undefined ? P.t('ui_noyau_inconnue') : domaine)
      + ' / ' + (action === null || action === undefined ? P.t('ui_noyau_inconnue') : action);
    return [date + ' (' + niveau + ')', admin === null ? P.t('ui_noyau_aucun') : admin, evenement,
      cible, resultat === undefined ? '' : resultat, details.join(' ; ')];
  }

  function rendre_journal(d, niveau_demande) {
    objet(d);
    const detail = entier(d.detail, 1, 3);
    const tronque = booleen(d.truncated);
    const lignes = tableau(d.entries, 200).map(function (e) {
      try {
        return ligne_entree(e);
      } catch (erreur) {
        if (!(erreur instanceof Invalide)) throw erreur;
        return [P.t('ui_noyau_invalide'), '', '', '', '', ''];
      }
    });
    return P.el('div', null,
      P.el('p', null, P.t('ui_noyau_detail') + ' : ' + detail),
      niveau_demande > detail ? paragraphe('ui_noyau_niveau_depasse') : null,
      tronque ? paragraphe('ui_noyau_tronque') : null,
      lignes.length === 0 ? paragraphe('ui_noyau_aucune_entree')
        : tableau_html(['ui_noyau_date', 'ui_noyau_admin', 'ui_noyau_evenement', 'ui_noyau_domaine_action',
          'ui_noyau_resultat', 'ui_noyau_details'], lignes));
  }

  function selecteur(valeurs, defaut) {
    const choix = P.el('select', null, ...valeurs.map((v) => P.el('option', { value: v }, v)));
    choix.value = defaut;
    return choix;
  }

  function page_journaux(conteneur) {
    const limite = selecteur(LIMITES, '50');
    const niveau = selecteur(NIVEAUX, '1');
    const domaine = P.el('input', { type: 'text', autocomplete: 'off', spellcheck: 'false', maxlength: '32' });
    const message = P.el('p', { role: 'alert' });
    const zone = P.el('div', null);

    function actualiser() {
      P.vider(message);
      const l = limite.value;
      const n = niveau.value;
      const dom = typeof domaine.value === 'string' ? domaine.value : '';
      if (!LIMITES.includes(l) || !NIVEAUX.includes(n) || (dom !== '' && !DOMAINE.test(dom))) {
        message.textContent = P.t('ui_noyau_parametre_invalide');
        return Promise.resolve();
      }
      const params = { limit: Number(l), level: Number(n) };
      if (dom !== '') params.domain = dom;
      return requete(conteneur, zone, 'kernel/activity/list', params, (d) => rendre_journal(d, Number(n)));
    }

    const bouton = P.el('button', { type: 'button' }, P.t('ui_noyau_actualiser'));
    bouton.addEventListener('click', function () { actualiser(); });
    conteneur.appendChild(P.el('section', null,
      P.el('h2', null, P.t('ui_noyau_journaux_titre')),
      P.el('label', null, P.t('ui_noyau_limite') + ' ', limite),
      P.el('label', null, P.t('ui_noyau_niveau') + ' ', niveau),
      P.el('label', null, P.t('ui_noyau_domaine') + ' ', domaine),
      bouton, message, zone));
    return actualiser();
  }

  // --- Page Catalogue ----------------------------------------------------------------------

  // Texte structuré borné ; les valeurs des clés sensibles sont remplacées par le libellé « masquée ».
  class Coupure extends Error {}

  function structurer(valeur, profondeur, etat, decalage) {
    const ajouter = function (morceau) {
      let octets = 0;
      for (const c of morceau) {
        const p = c.codePointAt(0);
        octets += p < 0x80 ? 1 : p < 0x800 ? 2 : p < 0x10000 ? 3 : 4;
      }
      etat.octets += octets;
      if (etat.octets > OCTETS_MAX) throw new Coupure('coupure');
      etat.sortie += morceau;
    };
    if (valeur === null || typeof valeur !== 'object') {
      ajouter(P.filtrer(typeof valeur === 'string' ? JSON.stringify(valeur) : String(valeur)));
      return;
    }
    if (profondeur >= PROFONDEUR_MAX) {
      etat.tronque = true;
      ajouter('…');
      return;
    }
    const interieur = decalage + '  ';
    if (Array.isArray(valeur)) {
      ajouter('[');
      valeur.forEach(function (x, i) {
        ajouter((i === 0 ? '\n' : ',\n') + interieur);
        structurer(x, profondeur + 1, etat, interieur);
      });
      ajouter(valeur.length === 0 ? ']' : '\n' + decalage + ']');
      return;
    }
    const cles = Object.keys(valeur);
    // Forme {name|key: <nom sensible>, value: …} : la valeur est masquée.
    const nom_sensible = ['name', 'key'].some((c) => typeof valeur[c] === 'string' && SENSIBLE.test(valeur[c]));
    ajouter('{');
    cles.forEach(function (cle, i) {
      ajouter((i === 0 ? '\n' : ',\n') + interieur + P.filtrer(JSON.stringify(cle)) + ': ');
      if (SENSIBLE.test(cle) || (nom_sensible && cle === 'value')) ajouter(P.t('ui_noyau_masquee'));
      else structurer(valeur[cle], profondeur + 1, etat, interieur);
    });
    ajouter(cles.length === 0 ? '}' : '\n' + decalage + '}');
  }

  function rendre_donnees(donnees) {
    const etat = { sortie: '', octets: 0, tronque: false };
    try {
      structurer(donnees, 0, etat, '');
    } catch (erreur) {
      if (!(erreur instanceof Coupure)) throw erreur;
      etat.tronque = true;
    }
    // Les retours à la ligne sont ceux de la mise en forme ; chaque donnée reçue est déjà filtrée.
    const pre = P.el('pre', null);
    pre.textContent = etat.sortie;
    return P.el('div', null,
      P.el('p', null, P.t('ui_noyau_ok')),
      etat.tronque ? paragraphe('ui_noyau_donnees_tronquees') : null,
      pre);
  }

  function rendre_services(d, etat) {
    objet(d);
    const services = tableau(d.services, 64).map(function (s) {
      objet(s);
      return {
        domain: texte(s.domain), greffon: texte(s.greffon), target: texte(s.target),
        catalog: parmi(s.catalog, CATALOGUES), available: booleen(s.available)
      };
    });
    if (services.some((s) => !DOMAINE.test(s.domain))) invalide();
    const lignes = services.map(function (s) {
      let cellule = '';
      if (s.catalog !== 'none') {
        cellule = P.el('button', { type: 'button', 'data-domaine': s.domain }, P.t('ui_noyau_voir_catalogue'));
        cellule.addEventListener('click', function () { etat.ouvrir(s.domain); });
      }
      return [s.domain, s.greffon, s.target, libelle('ui_noyau_catalogue_' + s.catalog),
        P.t(s.available ? 'ui_noyau_oui' : 'ui_noyau_non'), cellule];
    });
    return tableau_html(['ui_noyau_domaine', 'ui_noyau_greffon', 'ui_noyau_cible', 'ui_noyau_mode',
      'ui_noyau_disponible', 'ui_noyau_actions'], lignes);
  }

  function page_catalogue(conteneur) {
    const etat = { ouvrir: null };
    const zone_actions = P.el('div', null);
    const zone_description = P.el('div', null);
    const zone_resultat = P.el('div', null);
    let connues = [];

    function lancer(action) {
      P.vider(zone_resultat);
      return P.confirmer({
        titre_cle: 'ui_noyau_lancer_titre',
        texte: P.t('ui_noyau_lancer_texte') + ' ' + action
      }).then(function (accord) {
        if (!accord || !P.actif(conteneur)) return undefined;
        return requete(conteneur, zone_resultat, action, {}, rendre_donnees);
      });
    }

    function rendre_description(d, action) {
      objet(d);
      if (texte(d.action) !== action) invalide();
      const plugin = ou_nul(d.plugin, texte);
      const privilege = ou_nul(d.privilege, texte);
      const delai = ou_nul(d.delay_s, nombre);
      const parametres = tableau(d.parameters, 64).map(function (p) {
        objet(p);
        const bornes = objet(p.bounds);
        return [texte(p.name), texte(p.type), P.t(booleen(p.required) ? 'ui_noyau_oui' : 'ui_noyau_non'),
          rendre_donnees_brutes(bornes)];
      });
      const erreurs = tableau(d.errors, 64).map(texte);
      const sans_parametre = parametres.length === 0;
      let suite;
      if (sans_parametre && connues.includes(action) && ACTION.test(action)) {
        suite = P.el('button', { type: 'button', 'data-action': action }, P.t('ui_noyau_lancer'));
        suite.addEventListener('click', function () { lancer(action); });
      } else {
        suite = paragraphe('ui_noyau_non_lancable');
      }
      return P.el('div', null,
        P.el('h3', null, action),
        P.el('dl', null,
          P.el('dt', null, P.t('ui_noyau_greffon')), P.el('dd', null, plugin === null ? '' : plugin),
          P.el('dt', null, P.t('ui_noyau_privilege')), P.el('dd', null, privilege === null ? '' : privilege),
          P.el('dt', null, P.t('ui_noyau_delai')), P.el('dd', null, delai === null ? '' : String(delai)),
          P.el('dt', null, P.t('ui_noyau_erreurs')), P.el('dd', null, erreurs.join(', '))),
        tableau_html(['ui_noyau_nom', 'ui_noyau_type', 'ui_noyau_obligatoire', 'ui_noyau_bornes'], parametres),
        suite);
    }

    function rendre_actions(d, domaine) {
      objet(d);
      const liste = tableau(d.actions, 512).map(function (a) {
        objet(a);
        const action = texte(a.action);
        if (!ACTION.test(action) || !action.startsWith(domaine + '/')) invalide();
        return { action: action, plugin: ou_nul(a.plugin, texte) };
      });
      connues = liste.map((a) => a.action);
      const lignes = liste.map(function (a) {
        const bouton = P.el('button', { type: 'button', 'data-action': a.action }, a.action);
        bouton.addEventListener('click', function () {
          P.vider(zone_resultat);
          requete(conteneur, zone_description, domaine + '/catalog/describe', { action: a.action },
            (r) => rendre_description(r, a.action));
        });
        return [bouton, a.plugin === null ? '' : a.plugin];
      });
      return tableau_html(['ui_noyau_actions', 'ui_noyau_greffon'], lignes);
    }

    etat.ouvrir = function (domaine) {
      if (!DOMAINE.test(domaine)) return;
      P.vider(zone_description);
      P.vider(zone_resultat);
      connues = [];
      requete(conteneur, zone_actions, domaine + '/catalog/list', {}, (d) => rendre_actions(d, domaine));
    };

    const corps_services = section(conteneur, 'ui_noyau_catalogue_titre', function () { charger(); });
    conteneur.appendChild(zone_actions);
    conteneur.appendChild(zone_description);
    conteneur.appendChild(zone_resultat);

    function charger() {
      return requete(conteneur, corps_services, 'kernel/state/services', {}, (d) => rendre_services(d, etat));
    }
    return charger();
  }

  function rendre_donnees_brutes(valeur) {
    const etat = { sortie: '', octets: 0, tronque: false };
    try {
      structurer(valeur, PROFONDEUR_MAX - 2, etat, '');
    } catch (erreur) {
      if (!(erreur instanceof Coupure)) throw erreur;
    }
    return etat.sortie.replace(/\s+/g, ' ');
  }

  P.enregistrer({ id: 'noyau-etat', titre_cle: 'ui_noyau_etat_titre', afficher: page_etat });
  P.enregistrer({ id: 'noyau-journaux', titre_cle: 'ui_noyau_journaux_titre', afficher: page_journaux });
  P.enregistrer({ id: 'noyau-catalogue', titre_cle: 'ui_noyau_catalogue_titre', afficher: page_catalogue });
})(globalThis);
