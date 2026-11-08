# SPDX-License-Identifier: AGPL-3.0-or-later
# Faux « ssh » de test imitant pollux-session ; dépendances : bibliothèque standard.
# Suivi des versions
#   0.1.8  2026-11-07  Action challenge et contrôle de la signature de open.
#   3.0.0-alpha.41  2026-11-06  Scénarios d'ouverture, de battement et de perte.
# Variables lues : FAUX_SSH_SCENARIO, FAUX_SSH_JOURNAL, FAUX_SSH_JETON,
# FAUX_SSH_BATTEMENT, FAUX_SSH_DELAI, FAUX_SSH_DEFI (JSON : données de challenge),
# FAUX_SSH_CODE (code d'erreur des scénarios code_defi et code_open).
import json
import os
import re
import sys

SCENARIO = os.environ.get('FAUX_SSH_SCENARIO', 'ok')
JOURNAL = os.environ.get('FAUX_SSH_JOURNAL')
JETON = os.environ.get('FAUX_SSH_JETON', '')
BATTEMENT = float(os.environ.get('FAUX_SSH_BATTEMENT', '30'))
DELAI = float(os.environ.get('FAUX_SSH_DELAI', '90'))
CODE = os.environ.get('FAUX_SSH_CODE', 'bad_request')
DEFI = os.environ.get('FAUX_SSH_DEFI')


def noter(objet):
    if JOURNAL:
        with open(JOURNAL, 'a', encoding='utf-8') as sortie:
            sortie.write(json.dumps(objet) + '\n')


def emettre(octets):
    sys.stdout.buffer.write(octets)
    sys.stdout.buffer.flush()


def reponse(requete, **champs):
    emettre((json.dumps({'id': requete['id'], **champs}) + '\n').encode())


def succes(requete, **data):
    reponse(requete, ok=True, data=data)


def echec(requete, code):
    reponse(requete, ok=False, error={'code': code})


def defi(requete):
    if SCENARIO == 'code_defi':
        echec(requete, CODE)
    elif SCENARIO == 'defi_silence':
        pass
    elif SCENARIO == 'defi_mauvais_id':
        succes({'id': '0' * 16}, challenge='a' * 64, namespace='paresia-presence', expires_s=60)
    elif SCENARIO == 'defi_ok_booleen':
        reponse(requete, ok=1, data={})
    elif DEFI is not None:
        reponse(requete, ok=True, data=json.loads(DEFI))
    else:
        succes(requete, challenge='ab' * 32, namespace='paresia-presence', expires_s=60)


def signature_valide(requete):
    params = requete.get('params')
    valeur = params.get('signature') if isinstance(params, dict) else None
    return (isinstance(params, dict) and set(params) == {'signature'}
            and isinstance(valeur, str) and 0 < len(valeur) <= 2048 and valeur.isascii()
            and re.fullmatch(r'[A-Za-z0-9+/=]+', valeur) is not None)


def ouvrir(requete):
    if not signature_valide(requete):
        echec(requete, 'bad_request')
        os._exit(0)
    ok = {'session': 7, 'token': JETON, 'heartbeat_s': BATTEMENT, 'timeout_s': DELAI}
    if SCENARIO == 'code_open':
        echec(requete, CODE)
    elif SCENARIO == 'session_limit':
        echec(requete, 'session_limit')
    elif SCENARIO == 'auth_info_unavailable':
        echec(requete, 'auth_info_unavailable')
    elif SCENARIO == 'code_inconnu':
        echec(requete, 'texte_libre')
    elif SCENARIO == 'silence':
        pass
    elif SCENARIO == 'illisible':
        emettre(b'pas du json\n')
    elif SCENARIO == 'trop_longue':
        emettre(b'a' * (1024 * 1024 + 16) + b'\n')
    elif SCENARIO == 'mauvais_id':
        succes({'id': '0' * 16}, **ok)
    elif SCENARIO == 'jeton_court':
        succes(requete, **{**ok, 'token': JETON[:63]})
    elif SCENARIO == 'jeton_majuscules':
        succes(requete, **{**ok, 'token': JETON.upper()})
    elif SCENARIO == 'delais_incoherents':
        succes(requete, **{**ok, 'heartbeat_s': 90, 'timeout_s': 30})
    elif SCENARIO == 'delai_nul':
        succes(requete, **{**ok, 'heartbeat_s': 0})
    elif SCENARIO == 'session_zero':
        succes(requete, **{**ok, 'session': 0})
    elif SCENARIO == 'ok_booleen':
        reponse(requete, ok=1, data=ok)
    elif SCENARIO == 'brutal':
        os._exit(255)
    else:
        succes(requete, **ok)


def ping(requete):
    if SCENARIO == 'ping_session_closed':
        echec(requete, 'session_closed')
    elif SCENARIO == 'ping_fin_brutale':
        os._exit(255)
    elif SCENARIO == 'ping_illisible':
        emettre(b'pas du json\n')
    elif SCENARIO == 'ping_trop_long':
        emettre(b'a' * (1024 * 1024 + 16) + b'\n')
    elif SCENARIO == 'ping_id_inconnu':
        succes({'id': '1' * 16})
    elif SCENARIO == 'ping_silence':
        pass
    else:
        succes(requete)


def main():
    noter({'argv': sys.argv[1:]})
    for ligne in sys.stdin.buffer:
        requete = json.loads(ligne)
        noter(requete)
        if requete['action'] == 'presence/session/challenge':
            defi(requete)
        elif requete['action'] == 'presence/session/open':
            ouvrir(requete)
        elif requete['action'] == 'presence/session/ping':
            ping(requete)


main()
