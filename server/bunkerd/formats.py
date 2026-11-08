# Formats et contrôles de bunkerd 2.0.0 ; dépendances : bibliothèque standard.
# Suivi des versions
#   2.0.0  2026-11-05  Reprise des formats de 1.9.0 ; relais ws:// limités à .onion (B3) ; npub (B10) ;
#                      fullmatch partout : un saut de ligne final est refusé (1.9.0 l'acceptait, durcissement voulu) ;
#                      adresse de relais limitée à 255 caractères.
import re

IDENTITY_RE = re.compile(r"[a-z0-9_-]{1,32}")
HEX64_RE = re.compile(r"[0-9a-f]{64}")
RELAY_RE = re.compile(r"(wss?)://([A-Za-z0-9.-]+)(:[0-9]+)?(/[A-Za-z0-9._~/-]*)?")
NCRYPTSEC_RE = re.compile(r"ncryptsec1[02-9ac-hj-np-z]{100,200}")
BECH32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
GENERATEUR = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
MAX_RELAIS = 255
MIN_MINUTES, MAX_MINUTES = 1, 1440


def relais_valide(relais):
    """wss:// partout ; ws:// seulement pour un hôte .onion (B3)."""
    if not isinstance(relais, str):
        return False
    if len(relais) > MAX_RELAIS:
        return False
    trouve = RELAY_RE.fullmatch(relais)
    if not trouve:
        return False
    if trouve.group(1) == "ws":
        hote = trouve.group(2).lower()
        return hote.endswith(".onion") and len(hote) > len(".onion")
    return True


def minutes_valides(minutes):
    return (isinstance(minutes, int) and not isinstance(minutes, bool)
            and MIN_MINUTES <= minutes <= MAX_MINUTES)


def somme_bech32_valide(valeurs):
    somme = 1
    for element in valeurs:
        haut = somme >> 25
        somme = ((somme & 0x1FFFFFF) << 5) ^ element
        for i in range(5):
            somme ^= GENERATEUR[i] if (haut >> i) & 1 else 0
    return somme == 1


def client_en_hex(valeur):
    """npub (somme bech32 comprise) ou 64 hex minuscules -> hex ; None si invalide.

    Reprend npub_to_hex de bunkerctl 1.1.0 (mêmes contrôles, sans fin de programme).
    """
    if not isinstance(valeur, str):
        return None
    valeur = valeur.strip().lower()
    if HEX64_RE.fullmatch(valeur):
        return valeur
    if not valeur.startswith("npub1") or len(valeur) > 90:
        return None
    if any(c not in BECH32 for c in valeur[5:]):
        return None
    donnees = [BECH32.index(c) for c in valeur[5:]]
    valeurs = [ord(c) >> 5 for c in "npub"] + [0] + [ord(c) & 31 for c in "npub"] + donnees
    if not somme_bech32_valide(valeurs):
        return None
    accumulateur, bits, sortie = 0, 0, []
    for element in donnees[:-6]:
        accumulateur = (accumulateur << 5) | element
        bits += 5
        while bits >= 8:
            bits -= 8
            sortie.append((accumulateur >> bits) & 0xFF)
    if len(sortie) != 32:
        return None
    return bytes(sortie).hex()
