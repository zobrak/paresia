# SPDX-License-Identifier: AGPL-3.0-or-later
# Dépôt des profils nak et de bunker.json ; dépendances : bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha.32  2026-11-06  T007 : état versionné, lecture stricte et vue historique conservée.
#   2.0.0  2026-11-05  Repris de bunkerd 1.9.0, chemins issus de la configuration (aucun défaut) ;
#                      écriture atomique : .tmp en O_EXCL|O_NOFOLLOW (périmé supprimé), fsync du fichier et du dossier.
import json
import os

from .formats import IDENTITY_RE


def ecrire_atomique(chemin, ecrire):
    """Écrit chemin (0600) via un .tmp exclusif, fsync du fichier puis du dossier, os.replace."""
    tmp = chemin + ".tmp"
    try:
        os.unlink(tmp)                               # .tmp périmé (arrêt brutal) ; un lien est retiré, jamais suivi
    except FileNotFoundError:
        pass
    descripteur = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descripteur, "w", encoding="utf-8") as handle:
            ecrire(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, chemin)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    dossier = os.open(os.path.dirname(chemin) or ".", os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(dossier)
    finally:
        os.close(dossier)


class Depot:
    """Profils (contenant le ncryptsec, mode 0600) et état sans secret (bunker.json)."""

    def __init__(self, home):
        self.home = home
        self.profile_dir = os.path.join(home, ".config", "nak", "bunker")
        self.state_file = os.path.join(home, "bunker.json")

    def load_state(self):
        from .state import decoder, lire
        octets = lire(self.state_file)
        return {} if octets is None else decoder(octets)[1]

    def save_state(self, state):
        from .state import FORMAT, valider
        valider(state)
        ecrire_atomique(self.state_file,
                        lambda handle: json.dump({'format': FORMAT, 'identities': state},
                                                 handle, indent=2, sort_keys=True))

    def profile_path(self, identity):
        if not IDENTITY_RE.fullmatch(identity):          # jamais de chemin sans contrôle préalable
            raise ValueError("invalid_identity")
        return os.path.join(self.profile_dir, identity)

    def exists(self, identity):
        return os.path.exists(self.profile_path(identity))

    def read_profile(self, identity):
        with open(self.profile_path(identity), encoding="utf-8") as handle:
            return json.load(handle)

    def write_profile(self, identity, profile):
        os.makedirs(self.profile_dir, mode=0o700, exist_ok=True)
        path = self.profile_path(identity)
        ecrire_atomique(path, lambda handle: json.dump(profile, handle, indent=2))

    def remove_profile(self, identity):
        os.unlink(self.profile_path(identity))

    def identities(self):
        try:
            return sorted(n for n in os.listdir(self.profile_dir) if IDENTITY_RE.fullmatch(n))
        except FileNotFoundError:
            return []
