# SPDX-License-Identifier: AGPL-3.0-or-later
# Entrée de bunkerd (python3 -m server.bunkerd) ; dépendances : bibliothèque standard, nak, setfacl.
# Suivi des versions
#   0.1.1  2026-11-07  Raccordement au socle commun : Type=notify, options, codes sysexits ; attente par tranches.
#   3.0.0-alpha.32  2026-11-06  T007 : migration sous verrou avant toute écoute.
#   2.0.0  2026-11-05  Démarrage, arrêt sur signal, ctl.sock, socket d'administration, page web.
import os
import sys
import threading

from server.commun.demon import Demon, ErreurDonnees, lancer
from server.commun.version import lire_version

from . import SCHEMA, configuration
from .admin import demarrer_administration, donner_acces
from .ctl import lier_controle, traiter_connexion
from .depot import Depot
from .operations import Operations
from .superviseur import Superviseur
from .state import ErreurEtat, message, migrer
from .web import demarrer_web


def _accepter(ops, serveur):
    while True:
        try:
            connexion, _ = serveur.accept()
        except OSError:
            return
        threading.Thread(target=traiter_connexion, args=(ops, connexion), daemon=True).start()


def corps(config, journal, cycle):
    os.umask(0o077)
    depot = Depot(config["etat"]["home"])
    superviseur = Superviseur(depot, config["outils"]["nak"], journal)
    try:
        with superviseur.lock:
            migrer(depot, journal)
    except ErreurEtat as erreur:
        journal.ecrire("error", "state_unreadable", cause=erreur.cause)
        print(message(erreur.code), file=sys.stderr)
        raise ErreurDonnees("state_unreadable") from None
    os.makedirs(depot.profile_dir, mode=0o700, exist_ok=True)
    ops = Operations(superviseur, journal, config["general"]["relay_identity"])
    ops.verifier_relay_identity()
    admin = web = None
    controle = lier_controle(config["controle"]["socket"])
    threading.Thread(target=superviseur.surveiller, daemon=True).start()
    try:
        if config["web"]["socket"]:
            try:
                web = demarrer_web(config, ops, journal, donner_acces)
            except OSError:
                journal.ecrire("error", "web_disabled", reason="socket_failed")
        admin = demarrer_administration(config, ops, journal, config["outils"]["setfacl"])
        threading.Thread(target=_accepter, args=(ops, controle), daemon=True).start()
        cycle.pret()
        journal.ecrire("info", "bunkerd_ready", version=lire_version(), identities=len(depot.identities()))
        cycle.attendre()
    finally:
        superviseur.tout_verrouiller("shutdown")
        if admin is not None:
            admin.arreter()
        if web is not None:
            web.shutdown()
            web.server_close()
        controle.close()
        for chemin in (config["controle"]["socket"], config["web"]["socket"]):
            try:
                if chemin:
                    os.unlink(chemin)
            except FileNotFoundError:
                pass
        journal.ecrire("info", "bunkerd_stopped")


def _configurer(*, argv, environ):
    return configuration(argv=argv, environ=environ)


DEMON = Demon("bunkerd", lire_version, SCHEMA, corps, _configurer)


def main(argv=None):
    return lancer(DEMON, argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
