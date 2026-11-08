# bunkerd : superviseur de signataires Nostr distants (NIP-46) ; dépendances : bibliothèque standard, nak.
# Suivi des versions
#   0.1.1  2026-11-07  Version unique (server.commun.version) ; sections journal et metriques.
#   3.0.0-alpha.32  2026-11-06  T006 : option signature.log_n (plafond du coût scrypt de NIP-49, 20 au plus).
#   2.0.0  2026-11-05  Paquet issu de bunkerd 1.9.0 ; socket d'administration jumeaux/1 ; configuration
#                      par server.commun.config.lire ; journal JSON (D5) ; relais .onion en ws:// (B3).
#   2.0.0  2026-11-05  Cycle 1 (audit) : max_line par défaut 65536 ; romulus_user d'uid 0 refusé ; relais filtrés.
import os

from server.commun.config import ErreurConfiguration, Option, lire

from .formats import IDENTITY_RE

# Valeur « absente » des deux options facultatives : lire() n'admet de défaut que pour
# les durées et les limites ; le texte « (none) » ne peut être ni un nom d'identité ni un chemin.
AUCUNE = "(none)"
# Longueur de ligne par défaut de la socket d'administration (une requête tient en quelques centaines d'octets).
MAX_LIGNE_ADMIN = 65536
SCHEMA = {
    ("general", "relay_identity"): Option("texte"),
    ("etat", "home"): Option("chemin"),
    ("outils", "nak"): Option("chemin"),
    ("outils", "setfacl"): Option("chemin"),
    ("controle", "socket"): Option("chemin"),
    ("web", "socket"): Option("texte"),
    ("web", "user"): Option("compte"),
    ("admin", "socket"): Option("chemin"),
    ("admin", "romulus_user"): Option("compte"),
    ("admin", "delai_s"): Option("duree", 90),
    ("admin", "max_line"): Option("limite", MAX_LIGNE_ADMIN),
    ("admin", "max_connexions"): Option("limite", 16),
    ("signature", "log_n"): Option("limite", 20),
}


def configuration(argv=None, environ=None, **options):
    """Lit la configuration par lire() uniquement, puis valide les deux options facultatives."""
    config = lire("bunkerd", SCHEMA, argv=argv, environ=environ,
                  **{"journal": True, "metriques": True, **options})
    relais = config["general"]["relay_identity"]
    if relais == AUCUNE:
        config["general"]["relay_identity"] = None
    elif not IDENTITY_RE.fullmatch(relais):
        raise ErreurConfiguration("config_invalid", "general", "relay_identity")
    if config["signature"]["log_n"] > 20:
        raise ErreurConfiguration("config_invalid", "signature", "log_n")
    web = config["web"]["socket"]
    if web == AUCUNE:
        config["web"]["socket"] = ""
    elif not os.path.isabs(web):
        raise ErreurConfiguration("config_invalid", "web", "socket")
    return config
