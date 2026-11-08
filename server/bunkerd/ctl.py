# Socket de contrôle ctl.sock (root, bunkerctl) ; dépendances : bibliothèque standard.
# Suivi des versions
#   2.0.0  2026-11-05  Repris de bunkerd 1.9.0 : mêmes requêtes et mêmes réponses ; journal JSON (D5).
import json
import os
import socket
import struct

from .operations import Refus


def commande(ops, request, password):
    """command() de 1.9.0 : le verrou global est tenu par l'appelant."""
    sup = ops.sup
    nom = request.get("cmd")
    if nom == "list":
        elements = []
        for e in ops.lister():
            item = {"id": e["identity"], "unlocked": e["unlocked"], "pubkey": e["pubkey"],
                    "clients": e["clients"], "relays": e["relays"], "timeout": e["timeout"]}
            if e["unlocked"]:
                item["remaining"] = e["remaining"]
            elements.append(item)
        return {"ok": True, "identities": elements}
    try:
        identite = ops.identite(str(request.get("id", "")))
        if nom == "unlock":
            if not password:
                return {"ok": False, "error": "mot de passe vide"}
            return sup.start_identity(identite, password, "ctl")
        if nom == "lock":
            if sup.stop_identity(identite, "admin_request"):
                return {"ok": True}
            return {"ok": False, "error": "identité déjà verrouillée"}
        if nom == "uri":
            entree = sup.running.get(identite)
            if not entree or not entree["ready"]:
                return {"ok": False,
                        "error": "identité verrouillée : déverrouille-la pour obtenir son adresse"}
            return {"ok": True, "uri": entree["uri"]}
        # Seuls les champs de 1.9.0 sont lus (pas de timeout_min ni de confirmation ici).
        champs = {cle: request[cle] for cle in ("relays", "ncryptsec", "minutes", "client")
                  if cle in request}
        resultat = ops.executer(nom, identite, champs, source="ctl")
    except Refus as refus:
        return {"ok": False, "error": refus.message}
    if nom == "clients":
        return {"ok": True, "clients": resultat}
    return {"ok": True}


def traiter_connexion(ops, connexion):
    donnees = bytearray()
    password = bytearray()
    try:
        connexion.settimeout(10)
        creds = connexion.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _, uid, _ = struct.unpack("3i", creds)
        if uid != 0:
            ops.journal.ecrire("warning", "ctl_peer_refused", uid=uid)
            connexion.sendall(b'{"ok": false, "error": "reserve a root"}\n')
            return
        while not donnees.endswith(b"\n") and len(donnees) < 65536:
            morceau = connexion.recv(4096)
            if not morceau:
                break
            donnees += morceau
        request = json.loads(bytes(donnees))
        donnees[:] = b"\x00" * len(donnees)
        if not isinstance(request, dict):
            raise ValueError("requête invalide")
        if isinstance(request.get("password"), str):
            password += request.pop("password").encode("utf-8")
        request.pop("password", None)
        with ops.sup.lock:
            reponse = commande(ops, request, password)
        request = None
        connexion.sendall((json.dumps(reponse, ensure_ascii=False) + "\n").encode("utf-8"))
    except Exception:  # noqa: BLE001 — jamais de détail (il pourrait contenir un secret)
        try:
            connexion.sendall(b'{"ok": false, "error": "requete invalide"}\n')
        except OSError:
            pass
    finally:
        donnees[:] = b"\x00" * len(donnees)
        password[:] = b"\x00" * len(password)
        connexion.close()


def lier_controle(chemin):
    """Socket d'écoute de ctl.sock, root seul (umask 0o077 posé par main, puis 0600)."""
    try:
        os.unlink(chemin)
    except FileNotFoundError:
        pass
    serveur = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    serveur.bind(chemin)
    os.chmod(chemin, 0o600)
    serveur.listen(8)
    return serveur
