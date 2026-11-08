# Opérations sur les identités (ctl.sock et socket d'administration) ; dépendances : bibliothèque standard.
# Suivi des versions
#   2.0.0  2026-11-05  Contrôles de command() de 1.9.0 mis en commun ; codes de B7 ; relay_identity (B2) ;
#                      suppression de relay_identity refusée sur la socket d'administration seulement.
import time

from server.commun.texte import filtrer

from .formats import (HEX64_RE, IDENTITY_RE, NCRYPTSEC_RE, client_en_hex, minutes_valides,
                      relais_valide)
from .superviseur import DEFAULT_TIMEOUT


class Refus(Exception):
    """Refus d'une opération : code stable (B7) et message de ctl.sock (1.9.0)."""

    def __init__(self, code, message):
        super().__init__(code)
        self.code = code
        self.message = message


class Operations:
    def __init__(self, superviseur, journal, relay_identity=None):
        self.sup = superviseur
        self.depot = superviseur.depot
        self.journal = journal
        self.relay_identity = relay_identity

    def verifier_relay_identity(self):
        """Clé de relais inexistante : avertissement journalisé, aucune identité marquée (B2)."""
        if self.relay_identity and self.relay_identity not in self.depot.identities():
            self.journal.ecrire("warning", "relay_identity_unknown")
            return False
        return True

    # -- contrôles communs -------------------------------------------------
    @staticmethod
    def identite(valeur):
        if not isinstance(valeur, str) or not IDENTITY_RE.fullmatch(valeur):
            raise Refus("invalid_identity",
                        "nom d'identité invalide (a-z, 0-9, - et _, 32 caractères au plus)")
        return valeur

    @staticmethod
    def relais(valeur):
        if not isinstance(valeur, list) or not valeur or len(valeur) > 10:
            raise Refus("invalid_relays", "indique de 1 à 10 relais")
        for relais in valeur:
            if not relais_valide(relais):
                raise Refus("invalid_relays", "adresse de relais invalide")
        return list(dict.fromkeys(valeur))

    @staticmethod
    def ncryptsec(valeur):
        if not isinstance(valeur, str) or not NCRYPTSEC_RE.fullmatch(valeur):
            raise Refus("invalid_ncryptsec", "ncryptsec invalide")
        return valeur

    def existante(self, identite):
        if not self.depot.exists(identite):
            raise Refus("unknown_identity", "identité inconnue")

    # -- lecture -----------------------------------------------------------
    def lister(self):
        """Éléments internes ; chaque surface les met en forme."""
        state = self.depot.load_state()
        now = time.monotonic()
        elements = []
        for identite in self.depot.identities():
            profil = self.depot.read_profile(identite)
            entree = self.sup.running.get(identite)
            delai = int(state.get(identite, {}).get("timeout", DEFAULT_TIMEOUT))
            element = {"identity": identite, "unlocked": bool(entree and entree["ready"]),
                       "pubkey": state.get(identite, {}).get("pubkey"),
                       "clients": len(profil.get("clients") or []),
                       "relays": profil.get("relays") or [], "timeout": delai}
            if element["unlocked"]:
                element["remaining"] = max(0, int(delai - (now - entree["last"])))
            elements.append(element)
        return elements

    def clients(self, identite):
        self.existante(identite)
        resultat = []
        for client in self.depot.read_profile(identite).get("clients") or []:
            resultat.append({"pubkey": filtrer(str(client.get("pubkey", ""))),
                             "name": filtrer(str(client.get("name", ""))),
                             "url": filtrer(str(client.get("url", "")))})
        return resultat

    # -- écriture ----------------------------------------------------------
    def executer(self, nom, identite, a, *, source, admin=False):
        """Exécute l'une des opérations de command() de 1.9.0 (hors list, unlock, lock, uri).

        identite est déjà contrôlée par identite(). a : arguments bruts (relays, ncryptsec,
        minutes, client, confirmation). Renvoie la liste des clients pour « clients », None sinon.
        Lève Refus. L'ordre des contrôles est celui de 1.9.0. Le verrou est tenu par l'appelant.
        """
        depot, sup = self.depot, self.sup
        if nom == "clients":
            return self.clients(identite)
        if nom == "timeout":                           # permis aussi quand l'identité est déverrouillée
            self.existante(identite)
            minutes = a.get("minutes")
            if not minutes_valides(minutes):
                raise Refus("invalid_timeout", "délai invalide (1 à 1440 minutes)")
            state = depot.load_state()
            state.setdefault(identite, {})["timeout"] = minutes * 60
            depot.save_state(state)
            self.journal.ecrire("info", "identity_timeout_changed", identity=identite,
                                minutes=minutes, source=source)
            return None
        if identite in sup.running:
            raise Refus("identity_unlocked", "verrouille d'abord cette identité")
        if nom == "add":
            if depot.exists(identite):
                raise Refus("identity_exists", "cette identité existe déjà")
            ncryptsec = self.ncryptsec(a.get("ncryptsec"))
            relais = self.relais(a.get("relays"))
            minutes = a.get("timeout_min", DEFAULT_TIMEOUT // 60)
            if not minutes_valides(minutes):
                raise Refus("invalid_timeout", "délai invalide (1 à 1440 minutes)")
            depot.write_profile(identite, {"clients": [], "sec": ncryptsec, "relays": relais})
            state = depot.load_state()
            state[identite] = {"timeout": minutes * 60}
            depot.save_state(state)
            self.journal.ecrire("info", "identity_added", identity=identite, source=source)
            return None
        self.existante(identite)
        if nom == "remove":
            if admin and identite == self.relay_identity:      # clé du relais : jamais supprimée à distance
                raise Refus("relay_identity_protected", "identité désignée comme clé du relais")
            if admin and a.get("confirmation") != identite:
                raise Refus("confirmation_mismatch", "confirmation incorrecte")
            depot.remove_profile(identite)
            state = depot.load_state()
            state.pop(identite, None)
            depot.save_state(state)
            self.journal.ecrire("info", "identity_removed", identity=identite, source=source)
            return None
        if nom == "relays":
            relais = self.relais(a.get("relays"))
            profil = depot.read_profile(identite)
            profil["relays"] = relais
            depot.write_profile(identite, profil)
            self.journal.ecrire("info", "identity_relays_changed", identity=identite, source=source)
            return None
        if nom == "secret":
            ncryptsec = self.ncryptsec(a.get("ncryptsec"))
            profil = depot.read_profile(identite)
            profil["sec"] = ncryptsec
            depot.write_profile(identite, profil)
            state = depot.load_state()
            state.setdefault(identite, {}).pop("pubkey", None)   # connue au prochain déverrouillage
            depot.save_state(state)
            self.journal.ecrire("info", "identity_secret_replaced", identity=identite, source=source)
            return None
        if nom in ("authorize", "revoke"):
            if admin:
                client = client_en_hex(a.get("client"))
            else:
                client = str(a.get("client", ""))
                client = client if HEX64_RE.fullmatch(client) else None
            if client is None:
                raise Refus("invalid_client",
                            "clé de client invalide (64 caractères hex)")
            profil = depot.read_profile(identite)
            avant = profil.get("clients") or []
            clients = [c for c in avant if c.get("pubkey") != client]
            if nom == "revoke" and len(clients) == len(avant):
                raise Refus("client_not_authorized", "ce client n'est pas autorisé")
            if nom == "authorize":
                clients.append({"pubkey": client})
            profil["clients"] = clients
            depot.write_profile(identite, profil)
            self.journal.ecrire("info", "client_authorized" if nom == "authorize" else "client_revoked",
                                identity=identite, source=source)
            return None
        raise Refus("bad_request", "commande inconnue")
