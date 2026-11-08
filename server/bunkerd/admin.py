# Socket d'administration jumeaux/1 (appelant : Romulus) ; dépendances : bibliothèque standard, server.commun.
# Suivi des versions
#   3.0.0-alpha.32  2026-11-06  T006 : action bunker/relay-key/sign-mute-list (signature de la liste de sourdine).
#   2.0.0  2026-11-05  Première version : actions bunker/identity/* (T005).
import os
import pwd
import stat
import subprocess

from server.commun.jumeaux import reponse
from server.commun.texte import filtrer
from server.commun.serveur import Serveur

from .formats import IDENTITY_RE
from .operations import Refus
from .signature import ACTION as ACTION_SIGNATURE, PLAFOND_LOG_N, Signataire

PREFIXE = "bunker/identity/"
ACTIONS_ADMISES = frozenset(PREFIXE + nom for nom in (
    "list", "clients", "add", "secret", "relays", "authorize", "revoke", "timeout", "remove")) \
    | {"bunker/" + ACTION_SIGNATURE}
# nom -> (champs obligatoires, champs facultatifs) ; tout autre champ -> bad_request.
CHAMPS = {
    "list": (frozenset(), frozenset()),
    "clients": (frozenset({"identity"}), frozenset()),
    "add": (frozenset({"identity", "ncryptsec", "relays"}), frozenset({"timeout_min"})),
    "secret": (frozenset({"identity", "ncryptsec"}), frozenset()),
    "relays": (frozenset({"identity", "relays"}), frozenset()),
    "authorize": (frozenset({"identity", "client"}), frozenset()),
    "revoke": (frozenset({"identity", "client"}), frozenset()),
    "timeout": (frozenset({"identity", "minutes"}), frozenset()),
    "remove": (frozenset({"identity", "confirmation"}), frozenset()),
    ACTION_SIGNATURE: (frozenset({"identity", "passphrase", "pubkeys"}), frozenset()),
}


class Administration:
    """Traite les requêtes de la socket d'administration (verrou global, B9)."""

    def __init__(self, ops, journal, log_n_max=PLAFOND_LOG_N, **injection):
        self.ops = ops
        self.journal = journal
        self.signataire = Signataire(ops, log_n_max, **injection)

    def _liste(self):
        elements = []
        for e in self.ops.lister():
            item = {"identity": e["identity"], "unlocked": e["unlocked"]}
            if e["unlocked"]:
                item["remaining"] = e["remaining"]
            item.update(pubkey=e["pubkey"], relays=[filtrer(r) for r in e["relays"]], clients=e["clients"],
                        timeout=e["timeout"],
                        relay_key=e["identity"] == self.ops.relay_identity)
            elements.append(item)
        return {"identities": elements}

    def traiter(self, requete, contexte):
        action, params = requete["action"], requete["params"]
        nom = action[len(PREFIXE):] if action.startswith(PREFIXE) else action[len("bunker/"):]
        identite = params.get("identity")
        journalisee = identite if isinstance(identite, str) and IDENTITY_RE.fullmatch(identite) else None
        champs = {"session": requete["session"], "action": action}
        if journalisee is not None:
            champs["identity"] = journalisee
        if nom == ACTION_SIGNATURE and isinstance(params.get("pubkeys"), list):
            champs["keys"] = len(params["pubkeys"])
        try:
            obligatoires, facultatifs = CHAMPS[nom]
            if not obligatoires <= params.keys() or not params.keys() <= obligatoires | facultatifs:
                raise Refus("bad_request", "")
            if nom == ACTION_SIGNATURE:
                data = self.signataire.signer(params)
            else:
                with self.ops.sup.lock:
                    if nom == "list":
                        data = self._liste()
                    else:
                        identite = self.ops.identite(identite)
                        resultat = self.ops.executer(nom, identite, params,
                                                     source="admin", admin=True)
                        data = {"clients": resultat} if nom == "clients" else None
        except Refus as refus:
            self.journal.ecrire("info", "admin_operation", result="error", code=refus.code, **champs)
            return reponse(requete["id"], code=refus.code)
        except Exception:
            self.journal.ecrire("error", "admin_operation", result="error",
                                code="internal_error", **champs)
            raise
        self.journal.ecrire("info", "admin_operation", result="ok", **champs)
        return reponse(requete["id"], data)


def donner_acces(setfacl, compte, chemin, droits):
    resultat = subprocess.run([setfacl, "-m", f"u:{compte}:{droits}", chemin],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return resultat.returncode == 0


def demarrer_administration(configuration, ops, journal, outils_setfacl):
    """Lance la socket d'administration ; renvoie le Serveur, ou None (erreur journalisée, B8)."""
    admin = configuration["admin"]
    chemin, compte = admin["socket"], admin["romulus_user"]
    try:
        uid = pwd.getpwnam(compte).pw_uid
    except KeyError:
        journal.ecrire("error", "admin_disabled", reason="unknown_account")
        return None
    if uid == 0:
        journal.ecrire("error", "admin_disabled", reason="invalid_account")
        return None
    administration = Administration(ops, journal, configuration["signature"]["log_n"])
    serveur = Serveur(chemin, {uid}, ACTIONS_ADMISES, administration.traiter,
                      gid=os.getegid(), max_line=admin["max_line"], delai=admin["delai_s"],
                      journal=journal, max_connexions=admin["max_connexions"],
                      mode=0o600)
    try:
        try:
            if stat.S_ISSOCK(os.lstat(chemin).st_mode):     # socket périmée d'un arrêt brutal (comme 1.9.0)
                os.unlink(chemin)
        except FileNotFoundError:
            pass
        serveur.demarrer()
        # La socket n'est pas ouverte à un groupe : 0600 dès sa création, puis ACL du seul compte de Romulus.
        if not (donner_acces(outils_setfacl, compte, os.path.dirname(chemin), "x")
                and donner_acces(outils_setfacl, compte, chemin, "rw")):
            serveur.arreter()
            journal.ecrire("error", "admin_disabled", reason="acl_failed")
            return None
    except OSError:
        try:
            serveur.arreter()
        except OSError:
            pass
        journal.ecrire("error", "admin_disabled", reason="socket_failed")
        return None
    journal.ecrire("info", "admin_started")
    return serveur
