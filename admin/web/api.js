// SPDX-License-Identifier: AGPL-3.0-or-later
// Client de l'API d'administration (POST /api/admin/<domaine>/<objet>/<opération>) ; dépend de texte.js.
// Le jeton d'administration est posé par l'application : ce script ne le lit ni ne l'écrit.
// Suivi des versions
//   3.0.0-alpha.41  2026-11-06  Première version ; CODES aligné sur les codes du défi signé.
//   0.1.16  2026-11-08  Motif d'action aligné sur celui du catalogue du serveur.
(function (global) {
  'use strict';
  const P = global.Paresia = global.Paresia || {};
  // Identique à CODES_ERREUR de server/commun/jumeaux.py (vérifié par un test).
  P.CODES = Object.freeze([
    'auth_info_unavailable', 'bad_passphrase', 'bad_request', 'body_too_large',
    'challenge_expired', 'challenge_required', 'client_not_authorized',
    'command_busy', 'command_failed', 'command_timeout', 'confirmation_mismatch',
    'export_busy', 'export_too_large', 'identity_exists', 'identity_unlocked',
    'internal_error', 'invalid_client', 'invalid_identity', 'invalid_ncryptsec',
    'invalid_passphrase', 'invalid_pubkeys', 'invalid_relays', 'invalid_timeout',
    'line_too_long', 'log_n_too_high', 'not_available', 'not_relay_key',
    'origin_refused', 'peer_unavailable', 'protocol_version_mismatch',
    'pubkey_mismatch', 'relay_identity_protected', 'relay_light_red',
    'session_closed', 'session_limit', 'signature_invalid', 'token_conflict',
    'token_missing', 'token_unknown', 'unknown_action', 'unknown_identity'
  ]);
  // Identique à MOTIF_ACTION de server/commun/catalogue.py : 2 à 4 segments, 128 caractères au plus.
  const ACTION = /^(?=.{1,128}$)[a-z][a-z0-9_-]*(?:\/[a-z][a-z0-9_-]*){1,3}$/;
  const SESSION = new Set(['token_missing', 'token_unknown', 'session_closed']);
  const REESSAI = new Set(['relay_light_red', 'command_busy']);

  function borner(detail) {
    return Array.from(P.filtrer(detail)).slice(0, 200).join('');
  }

  class ErreurApi extends Error {
    constructor(code, detail) {
      const connu = typeof code === 'string' && P.CODES.includes(code);
      super(connu ? code : 'internal_error');
      this.name = 'ErreurApi';
      this.code = connu ? code : 'internal_error';
      this.detail = borner(detail);
    }
  }
  P.ErreurApi = ErreurApi;

  function simple(valeur) {
    return valeur !== null && typeof valeur === 'object' && !Array.isArray(valeur);
  }

  function interpreter(corps) {
    if (!simple(corps)) throw new ErreurApi('internal_error');
    const cles = Object.keys(corps);
    if (corps.ok === true) {
      if (cles.some((cle) => cle !== 'ok' && cle !== 'data')) throw new ErreurApi('internal_error');
      return 'data' in corps ? corps.data : {};
    }
    if (corps.ok === false) {
      const erreur = corps.error;
      if (cles.length !== 2 || !simple(erreur) || typeof erreur.code !== 'string'
          || Object.keys(erreur).some((cle) => cle !== 'code' && cle !== 'detail')
          || ('detail' in erreur && typeof erreur.detail !== 'string')) {
        throw new ErreurApi('internal_error');
      }
      throw new ErreurApi(erreur.code, erreur.detail);
    }
    throw new ErreurApi('internal_error');
  }

  P.appeler = async function (action, params) {
    if (typeof action !== 'string' || !ACTION.test(action)) throw new ErreurApi('bad_request');
    let reponse;
    let texte;
    try {
      reponse = await global.fetch('/api/admin/' + action, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params ?? {}),
        credentials: 'same-origin',
        cache: 'no-store'
      });
      const type = (reponse.headers.get('Content-Type') || '').split(';')[0].trim().toLowerCase();
      if (type !== 'application/json') throw new ErreurApi('internal_error');
      texte = await reponse.text();
    } catch (erreur) {
      throw new ErreurApi('internal_error');
    }
    let corps;
    try {
      corps = JSON.parse(texte);
    } catch (erreur) {
      throw new ErreurApi('internal_error');
    }
    return interpreter(corps);
  };

  // Présentation d'une erreur : libellé du catalogue, jamais le détail distant (hors diagnostic).
  P.presenter_erreur = function (erreur) {
    let code = erreur instanceof ErreurApi ? erreur.code : 'internal_error';
    let cle = code;
    if (code === 'not_available') cle = 'ui_web_operation_indisponible';
    else if (SESSION.has(code)) cle = 'ui_web_session_requise';
    if (!P.a_cle(cle)) {
      code = 'internal_error';
      cle = 'internal_error';
    }
    return {
      code: code,
      cle: cle,
      message: P.t(cle),
      session: SESSION.has(code),
      reessayer: REESSAI.has(code),
      detail: erreur instanceof ErreurApi ? erreur.detail : ''
    };
  };
})(globalThis);
