# SPDX-License-Identifier: AGPL-3.0-or-later
# Contrôles des journaux du banc ; dépendances : bibliothèque standard.
# Suivi des versions : 0.1.1 · 2026-11-07 · Événements et refus des secrets.
"""Lecture des objets JSON préfixés par journald, sans dépendance au moteur."""
import json
import re
import unicodedata

ETAPES = ('E0', 'E1', 'E2', 'E3', 'E4', 'E5', 'E5 bis', 'E6')
ATTENDUS = {
    'E1': (('pollux', 'challenge_issued', {}), ('pollux', 'auth_ok', {}),
           ('pollux', 'session_opened', {})),
    'E2': (('romulus', 'session_opened', {}),),
    'E3': (('romulus', 'action_routed', {'destination': 'remus',
             'action': 'relay/state/status', 'result': 'not_available'}),),
    'E4': (('castor', 'light_green', {}),),
    'E5': (('pollux', 'session_closed', {'reason': 'close'}),
           ('castor', 'light_closed', {'reason': 'close'})),
    'E5 bis': (('castor', 'light_green', {}), ('castor', 'light_expired', {})),
    'E6': (('romulus', 'session_closed', {}),),
}
_PRIVEE = re.compile(r'-----BEGIN [A-Z ]*' + r'PRIVATE KEY-----')
_CHAMP = re.compile(r'"(?:token|signature|challenge)"\s*:\s*("(?:\\.|[^"\\])*"|[^,}\s]+)', re.I)
_HEXA = re.compile(r'(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])', re.I)
_EMPREINTE_IMAGE = re.compile(r'sha256:[0-9a-f]{64}(?![0-9a-f])', re.I)


class SecretPresent(ValueError):
    """Erreur sans contenu sensible."""


def filtrer(texte):
    return ''.join('\ufffd' if unicodedata.category(c) in {'Cc', 'Cf', 'Zl', 'Zp', 'Cs', 'Co'}
                   else c for c in texte)


def masquer_empreintes(texte):
    """Remplace condensats d'image et suites de 64 chiffres hexadécimaux d'une sortie de
    construction (publique) par une marque, puis filtre."""
    return filtrer(_HEXA.sub('<hexa>', _EMPREINTE_IMAGE.sub('sha256:<condensat>', texte)))


def verifier(texte, jetons=()):
    """Contrôler avant filtrage et avant toute écriture, y compris les sorties brutes."""
    # Les empreintes publiques des images ne sont pas des jetons ; une valeur connue
    # reste cependant refusée, même présentée avec ce préfixe.
    if (_PRIVEE.search(texte) or _HEXA.search(_EMPREINTE_IMAGE.sub('', texte))
            or any(m.group(1) != '""' for m in _CHAMP.finditer(texte))
            or any(jeton and jeton in texte for jeton in jetons)):
        raise SecretPresent('secret_present')
    return '\n'.join(filtrer(ligne) for ligne in texte.split('\n'))


def evenements(texte):
    resultat = []
    for ligne in texte.splitlines():
        debut = ligne.find('{')
        if debut < 0:
            continue
        try:
            objet = json.loads(ligne[debut:])
        except (ValueError, RecursionError):
            continue
        if isinstance(objet, dict) and isinstance(objet.get('event'), str):
            resultat.append((ligne, objet))
    return resultat


def observer(etape, texte, numero=None):
    """Renvoie les preuves dans l'ordre, ou nomme l'étape absente.

    L'ordre entre journaux de deux machines n'est pas déduit de leurs horloges.
    L'ordre challenge/auth/open de Pollux est vérifié dans son propre journal.
    """
    if etape == 'E0':
        lignes = [l for l in texte.splitlines()
                  if 'Accepted publickey for tunnel from 192.0.2.10' in l]
        if lignes:
            return lignes[-1:]
        raise ValueError(etape)
    objets = evenements(texte)
    preuves, position = [], 0
    for composant, evenement, champs in ATTENDUS[etape]:
        depart = position if etape in ('E1', 'E5 bis') else 0
        for index in range(depart, len(objets)):
            ligne, objet = objets[index]
            if (objet.get('component') == composant and objet.get('event') == evenement
                    and all(objet.get(cle) == valeur for cle, valeur in champs.items())
                    and (numero is None or evenement in ('challenge_issued', 'auth_ok')
                         or objet.get('session') == numero)):
                preuves.append(ligne)
                position = index + 1
                break
        else:
            raise ValueError(etape)
    # Une seule connexion doit porter le défi et son authentification.
    if etape == 'E1':
        selection = [json.loads(l[l.find('{'):]) for l in preuves]
        if selection[0].get('connexion') != selection[1].get('connexion'):
            raise ValueError(etape)
    return preuves
