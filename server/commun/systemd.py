# SPDX-License-Identifier: AGPL-3.0-or-later
# Suivi des versions
#   0.1.1  2026-11-07  Référence au manuel sans ambiguïté avec un appel.
#   0.1.1  2026-11-07  Longueur du chemin Unix contrôlée en octets avant ouverture.
#   0.1.1  2026-11-07  Notifications et détection du flux journal.
"""Transport sd_notify(3) ; identification du flux selon systemd.exec, section 5."""
import os
import re
import socket

from .texte import filtrer


def notifier(*champs, environ=None):
    env = os.environ if environ is None else environ
    adresse = env.get('NOTIFY_SOCKET')
    if not isinstance(adresse, str) or len(adresse) < 2 or adresse[0] not in '/@' or '\0' in adresse:
        return False
    try:
        # sd_notify(3) : conserver la place du NUL dans sun_path (108 octets sous Linux).
        if len(os.fsencode(adresse)) >= 108:
            return False
    except UnicodeError:
        return False
    lignes = []
    for champ in champs:
        if not isinstance(champ, str) or '=' not in champ:
            return False
        cle, valeur = champ.split('=', 1)
        if not re.fullmatch('[A-Z][A-Z0-9_]*', cle):
            return False
        if cle == 'STATUS':
            valeur = filtrer(valeur)[:1024]
        elif any(c in valeur for c in '\n\r\0'):
            return False
        lignes.append(cle + '=' + valeur)
    try:
        contenu = '\n'.join(lignes).encode('utf-8')
    except UnicodeError:
        return False
    if not contenu or len(contenu) > 8192:
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as flux:
            flux.settimeout(0.05)
            return flux.sendto(contenu, '\0' + adresse[1:] if adresse[0] == '@' else adresse) == len(contenu)
    except (OSError, ValueError, UnicodeError):
        return False


def pret(statut=None, *, environ=None):
    return notifier('READY=1', *(() if statut is None else ('STATUS=' + statut,)), environ=environ)


def arret(*, environ=None):
    return notifier('STOPPING=1', environ=environ)


def statut(texte, *, environ=None):
    return notifier('STATUS=' + texte, environ=environ)


def flux_journal(fd, environ=None):
    env = os.environ if environ is None else environ
    valeur = env.get('JOURNAL_STREAM', '')
    if not isinstance(valeur, str) or not re.fullmatch('[0-9]{1,20}:[0-9]{1,20}', valeur):
        return False
    try:
        attributs = os.fstat(fd)
        return tuple(map(int, valeur.split(':'))) == (attributs.st_dev, attributs.st_ino)
    except (OSError, ValueError, TypeError):
        return False
