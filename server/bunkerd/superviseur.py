# Processus nak de bunkerd ; dépendances : bibliothèque standard, nak.
# Suivi des versions
#   2.0.0  2026-11-05  Repris de bunkerd 1.9.0 ; journal JSON (D5), chemins issus de la configuration.
import os
import pty
import re
import signal
import subprocess
import threading
import time

DEFAULT_TIMEOUT = 900                     # secondes (15 min)
UNLOCK_WAIT = 60                          # secondes max pour déchiffrer et se connecter
ANSI_RE = re.compile(rb"\x1b\[[0-9;?]*[A-Za-z]")
URI_RE = re.compile(rb"bunker://[0-9a-f]{64}\?[A-Za-z0-9%=&._~-]+")
PUBKEY_RE = re.compile(rb"pubkey:\s*([0-9a-f]{64})")
REQUEST_MARK = b"got request from"
PROMPT_MARK = b"password"
RETRY_MARK = b"[2/3]"                     # nak redemande : le mot de passe était faux


def reader_thread(entry, password):
    """Lit la sortie de nak (jamais écrite ailleurs) ; tape le mot de passe à l'invite."""
    master_fd = entry["master_fd"]
    pending = bytearray()
    password_sent = False
    try:
        while True:
            try:
                chunk = os.read(master_fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            pending += chunk
            clean = ANSI_RE.sub(b"", bytes(pending))
            if not password_sent and PROMPT_MARK in clean:
                os.write(master_fd, bytes(password) + b"\n")
                password[:] = b"\x00" * len(password)
                password_sent = True
                del pending[:]
                continue
            if password_sent and not entry["ready"] and RETRY_MARK in clean:
                break                                   # mot de passe refusé par nak
            uris = URI_RE.findall(clean)
            if uris:
                entry["uri"] = uris[-1].decode()        # le secret de l'adresse change après usage
            if entry["pubkey"] is None:
                match = PUBKEY_RE.search(clean)
                if match:
                    entry["pubkey"] = match.group(1).decode()
            if entry["uri"] and entry["pubkey"] and not entry["ready"]:
                entry["last"] = time.monotonic()
                entry["ready"] = True
            if entry["ready"] and REQUEST_MARK in clean:
                entry["last"] = time.monotonic()
            # On ne garde que la fin, pour repérer une marque coupée entre deux lectures.
            del pending[:-512]
    finally:
        password[:] = b"\x00" * len(password)
        if not entry["ready"]:
            entry["failed"] = True


class Superviseur:
    """Identités déverrouillées (un processus nak chacune) sous un verrou global (B9)."""

    def __init__(self, depot, nak, journal, *, unlock_wait=UNLOCK_WAIT):
        self.depot = depot
        self.nak = nak
        self.journal = journal
        self.unlock_wait = unlock_wait
        self.lock = threading.RLock()
        self.running = {}     # identité -> dict(process, master_fd, last, uri, pubkey, ready, failed)

    def start_identity(self, identity, password, source="ctl"):
        if identity in self.running:
            return {"ok": False, "error": "identité déjà déverrouillée"}
        if not self.depot.exists(identity):
            return {"ok": False, "error": "identité inconnue"}
        master_fd, slave_fd = pty.openpty()
        env = {"HOME": self.depot.home, "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
               "TERM": "dumb", "NO_COLOR": "1"}
        process = subprocess.Popen(
            [self.nak, "bunker", "--persist", "--profile", identity],
            stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
            env=env, cwd=self.depot.home, start_new_session=True, close_fds=True)
        os.close(slave_fd)
        entry = {"process": process, "master_fd": master_fd, "last": time.monotonic(),
                 "uri": None, "pubkey": None, "ready": False, "failed": False}
        self.running[identity] = entry
        threading.Thread(target=reader_thread, args=(entry, password), daemon=True).start()

        deadline = time.monotonic() + self.unlock_wait
        while time.monotonic() < deadline:
            if entry["ready"]:
                state = self.depot.load_state()
                state.setdefault(identity, {})["pubkey"] = entry["pubkey"]
                self.depot.save_state(state)
                self.journal.ecrire("info", "identity_unlocked", identity=identity, source=source)
                return {"ok": True}
            if process.poll() is not None or entry["failed"]:
                break
            time.sleep(0.2)
        self.stop_identity(identity, "unlock_failed")
        return {"ok": False,
                "error": "déverrouillage impossible (mot de passe incorrect, ou relais injoignable)"}

    def stop_identity(self, identity, reason):
        entry = self.running.pop(identity, None)
        if not entry:
            return False
        process = entry["process"]
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        try:
            os.close(entry["master_fd"])
        except OSError:
            pass
        self.journal.ecrire("info", "identity_locked", identity=identity, reason=reason)
        return True

    def verifier_inactivite(self):
        """Une passe de idle_watcher de 1.9.0."""
        with self.lock:
            state = self.depot.load_state()
            now = time.monotonic()
            for identity in list(self.running):
                entry = self.running[identity]
                if not entry["ready"]:
                    continue                            # déverrouillage en cours
                if entry["process"].poll() is not None:
                    self.stop_identity(identity, "nak_exited")
                    continue
                timeout = int(state.get(identity, {}).get("timeout", DEFAULT_TIMEOUT))
                if now - entry["last"] >= timeout:
                    self.stop_identity(identity, "idle")

    def surveiller(self, pause=5):
        while True:
            time.sleep(pause)
            try:
                self.verifier_inactivite()
            except (OSError, ValueError):
                self.journal.ecrire("error", "idle_check_failed")

    def tout_verrouiller(self, reason):
        with self.lock:
            for identity in list(self.running):
                self.stop_identity(identity, reason)
