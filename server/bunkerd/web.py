# Page web de déverrouillage et interface de l'applet ; dépendances : bibliothèque standard, setfacl, python3-qrcode (facultatif).
# Suivi des versions
#   2.0.0  2026-11-05  Repris de bunkerd 1.9.0 (comportement inchangé) ; journal JSON (D5), configuration par lire.
import html
import http.server
import json
import os
import pwd
import re
import socketserver
import threading
import time
from urllib.parse import parse_qsl

from .formats import IDENTITY_RE
from .operations import Refus

WEB_FAIL_LIMIT = 5                        # échecs avant blocage
WEB_FAIL_WINDOW = 900                     # secondes (fenêtre de comptage et durée du blocage)
WEB_MESSAGES = {
    "unlocked": ("ok", "Identité déverrouillée."),
    "locked": ("ok", "Identité verrouillée."),
    "failed": ("err", "Déverrouillage impossible : passphrase incorrecte, ou relais injoignable."),
    "already": ("err", "Cette identité est déjà déverrouillée."),
    "notlocked": ("err", "Cette identité est déjà verrouillée."),
    "unknown": ("err", "Identité inconnue."),
    "empty": ("err", "Indique l'identité et sa passphrase."),
    "blocked": ("err", "Trop d'échecs : déverrouillage bloqué pendant 15 minutes."),
}
WEB_CSP = ("default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'unsafe-inline'; "
           "form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
QR_ICON = ('<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" fill="currentColor">'
           '<path d="M3 3h8v8H3zm2 2v4h4V5zm8-2h8v8h-8zm2 2v4h4V5zM3 13h8v8H3zm2 2v4h4v-4zm8-2h2v2h-2z'
           'm2 2h2v2h-2zm2-2h2v2h-2zm2 2h2v2h-2zm-6 2h2v2h-2zm2 2h2v2h-2zm2-2h2v2h-2zm2 2h2v2h-2z"/></svg>')
APP_JS = """"use strict";
async function ask(path, id) {
  const r = await fetch(path, {method: "POST", cache: "no-store", credentials: "omit",
    headers: {"Content-Type": "application/x-www-form-urlencoded"},
    body: "identity=" + encodeURIComponent(id)});
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}
document.querySelectorAll("details.uri").forEach(function (d) {
  const id = d.dataset.id, code = d.querySelector("code");
  const box = d.querySelector(".qrbox"), btn = d.querySelector(".qrbtn");
  d.addEventListener("toggle", async function () {
    box.replaceChildren();
    if (!d.open) { code.textContent = ""; return; }
    code.textContent = "…";
    try {
      const j = await ask("/uri", id);
      code.textContent = j.ok ? j.uri : j.error;
    } catch (e) { code.textContent = "Erreur : " + e.message; }
  });
  btn.addEventListener("click", async function () {
    if (box.childElementCount) { box.replaceChildren(); return; }
    try {
      const j = await ask("/qr", id);
      if (!j.ok) { box.textContent = j.error; return; }
      code.textContent = j.uri;
      const svg = new DOMParser().parseFromString(j.svg, "image/svg+xml").documentElement;
      box.replaceChildren(document.importNode(svg, true));
    } catch (e) { box.textContent = "Erreur : " + e.message; }
  });
});
"""
def qr_svg(text):
    try:
        import qrcode
        import qrcode.image.svg
    except ImportError:
        return None
    image = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, border=4)
    return image.to_string(encoding="unicode")



def uri_panel(name):
    return (f'<tr class="sub"><td colspan="3"><details class="uri" data-id="{name}">'
            f'<summary>Afficher une URI</summary><div class="panel"><div class="line"><code></code>'
            f'<button class="qrbtn" type="button" title="Afficher le QR code" aria-label="Afficher le QR code">'
            f'{QR_ICON}</button></div><div class="qrbox"></div>'
            f'<p class="note">Secret à usage unique : le premier client qui utilise cette adresse est '
            f'autorisé durablement, puis une nouvelle adresse est créée.</p>'
            f'<noscript><p class="err">JavaScript requis pour afficher l\'adresse.</p></noscript>'
            f'</div></details></td></tr>')


def web_page(items, code):
    rows = []
    for item in items:
        name = html.escape(item["identity"])
        if item.get("unlocked"):
            remaining = int(item.get("remaining", 0))
            state = f"déverrouillée — encore {remaining // 60} min {remaining % 60:02d} s"
            action = (f'<form method="post" action="/lock"><input type="hidden" name="identity" '
                      f'value="{name}"><button type="submit">Verrouiller</button></form>')
        else:
            state, action = "verrouillée", ""
        rows.append(f"<tr><td>{name}</td><td>{html.escape(state)}</td><td>{action}</td></tr>")
        if item.get("unlocked"):
            rows.append(uri_panel(name))
    message = ""
    if code in WEB_MESSAGES:
        kind, text = WEB_MESSAGES[code]
        message = f'<p class="{kind}">{html.escape(text)}</p>'
    table = "".join(rows) or '<tr><td colspan="3">Aucune identité.</td></tr>'
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="same-origin">
<title>Bunker</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:32rem;margin:2rem auto;padding:0 1rem;background:#16161a;color:#e8e8ec}}
h1{{font-size:1.4rem}} table{{width:100%;border-collapse:collapse;margin-bottom:1.5rem}}
td{{padding:.45rem .3rem;border-bottom:1px solid #333}} label{{display:block;margin:.8rem 0 .3rem}}
input{{width:100%;box-sizing:border-box;padding:.6rem;font-size:1rem;border-radius:6px;border:1px solid #555;background:#222;color:#eee}}
button{{padding:.6rem 1.2rem;font-size:1rem;border-radius:6px;border:0;background:#7c5cd6;color:#fff;margin-top:1rem}}
td button{{margin:0;padding:.35rem .8rem;font-size:.9rem;background:#555}}
tr.sub td{{padding-top:0}} summary{{cursor:pointer;color:#b9a6ff}}
.panel{{border:1px solid #7c5cd6;border-radius:8px;padding:.6rem;margin-top:.5rem}}
.line{{display:flex;gap:.6rem;align-items:center}} .line code{{flex:1}}
.qrbtn{{margin:0;padding:.35rem;background:#555;line-height:0}}
.qrbox svg{{display:block;width:100%;max-width:18rem;height:auto;margin:.8rem auto 0;background:#fff;padding:.5rem;border-radius:6px;box-sizing:border-box}}
.note{{font-size:.8rem;color:#aaa;margin:.6rem 0 0}}
code{{word-break:break-all;user-select:all;font-size:.85rem}}
.ok{{color:#7fd88f}} .err{{color:#ff8a80}} a{{color:#b9a6ff}}
</style></head><body>
<h1>Bunker Nostr</h1>
{message}
<table>{table}</table>
<form method="post" action="/unlock" autocomplete="on">
<label for="identity">Identité</label>
<input id="identity" name="identity" type="text" autocomplete="username" autocapitalize="none" spellcheck="false" required>
<label for="password">Passphrase</label>
<input id="password" name="password" type="password" autocomplete="current-password" required>
<button type="submit">Déverrouiller</button>
</form>
<p><a href="/">Actualiser</a></p>
<script src="/app.js"></script>
</body></html>
"""

class WebHandler(http.server.BaseHTTPRequestHandler):
    app = None                                          # posé par creer_gestionnaire()
    server_version = "bunkerd"
    sys_version = ""
    timeout = 15

    def log_message(self, *_):
        pass                                            # aucun journal automatique (requêtes)

    def client(self):
        # HAProxy pose l'adresse du client, lighttpd ajoute ensuite la sienne
        # (celle de HAProxy) : l'adresse utile est l'avant-dernière.
        chain = [a.strip() for a in self.headers.get("X-Forwarded-For", "").split(",")]
        address = re.sub(r"[^0-9A-Fa-f.:]", "", chain[-2])[:45] if len(chain) >= 2 else ""
        return address or "unknown"

    def address_string(self):
        return "socket"

    def send_page(self, status, body, clear_message=False):
        data = body.encode("utf-8")
        self.send_response(status)
        if clear_message:
            self.send_header("Set-Cookie", "bunker_msg=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Strict")
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", WEB_CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, data):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def redirect(self, code):
        self.send_response(303)
        self.send_header("Location", "/")
        self.send_header("Set-Cookie", f"bunker_msg={code}; Path=/; Max-Age=30; Secure; HttpOnly; SameSite=Strict")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/app.js":
            data = APP_JS.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)
            return
        if path != "/":
            self.send_error(404)
            return
        code = ""
        for part in self.headers.get("Cookie", "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == "bunker_msg" and value in WEB_MESSAGES:
                code = value
        with self.app.sup.lock:
            items = self.app.ops.lister()
        self.send_page(200, web_page(items, code), clear_message=bool(code))

    def do_POST(self):
        app = self.app
        api = self.path.startswith("/api/")
        if self.path not in ("/unlock", "/lock", "/uri", "/qr", "/api/status", "/api/unlock", "/api/lock",
                             "/api/timeout"):
            self.send_error(404)
            return
        origin = self.headers.get("Origin", "")
        host = self.headers.get("Host", "")
        if not host or origin.split("://", 1)[-1] != host:
            self.send_error(403)                        # envoi depuis une autre page
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if not 0 <= length <= 4096 or (length == 0 and self.path != "/api/status"):
            self.send_error(400)
            return
        body = bytearray(self.rfile.read(length)) if length else bytearray()
        password = bytearray()
        identity = ""
        minutes = ""
        try:
            for key, value in parse_qsl(bytes(body), keep_blank_values=True):
                if key == b"minutes":
                    minutes = value.decode("ascii", "replace")
                elif key == b"identity":
                    identity = value.decode("utf-8", "replace").strip().lower()
                elif key == b"password":
                    password += value
        except ValueError:
            pass
        finally:
            body[:] = b"\x00" * len(body)
        source = "applet" if api else "web"
        try:
            if self.path == "/api/status":
                with app.sup.lock:
                    items = app.ops.lister()
                self.send_json({"ok": True, "identities": [
                    {"id": i["identity"], "unlocked": i["unlocked"], "remaining": i.get("remaining", 0),
                     "timeout": i["timeout"]} for i in items]})
                return
            if self.path == "/api/timeout":
                if not minutes.isdigit():
                    self.send_json({"ok": False, "error": "délai invalide (1 à 1440 minutes)"})
                    return
                try:
                    with app.sup.lock:
                        if not IDENTITY_RE.fullmatch(identity) or not app.depot.exists(identity):
                            self.send_json({"ok": False, "error": "Identité inconnue."})
                            return
                        app.ops.executer("timeout", identity, {"minutes": int(minutes)}, source=source)
                except Refus as refus:
                    self.send_json({"ok": False, "error": refus.message})
                    return
                app.journal.ecrire("info", "web_timeout_set", identity=identity, minutes=int(minutes),
                                   source=source, client=self.client())
                self.send_json({"ok": True, "message": f"Verrouillage après {int(minutes)} min d'inactivité."})
                return
            if self.path in ("/uri", "/qr"):
                with app.sup.lock:
                    entry = app.sup.running.get(identity) if IDENTITY_RE.fullmatch(identity) else None
                    uri = entry["uri"] if entry and entry["ready"] else None
                if not uri:
                    self.send_json({"ok": False, "error": "Identité verrouillée : déverrouille-la d'abord."})
                    return
                app.journal.ecrire("info", "uri_shown", identity=identity, qr=self.path == "/qr",
                                   client=self.client())
                if self.path == "/uri":
                    self.send_json({"ok": True, "uri": uri})
                    return
                svg = qr_svg(uri)
                if not svg:
                    self.send_json({"ok": False, "error": "QR code indisponible (paquet python3-qrcode absent sur ce serveur)."})
                    return
                self.send_json({"ok": True, "uri": uri, "svg": svg})
                return
            if self.path in ("/lock", "/api/lock"):
                code = "unknown"
                if IDENTITY_RE.fullmatch(identity):
                    with app.sup.lock:
                        done = app.sup.stop_identity(identity, "applet_request" if api else "web_request")
                    code = "locked" if done else "notlocked"
            else:
                code = self.unlock(identity, password, source)
            if api:
                kind, text = WEB_MESSAGES[code]
                self.send_json({"ok": kind == "ok", "message": text})
            else:
                self.redirect(code)
        finally:
            password[:] = b"\x00" * len(password)

    def unlock(self, identity, password, source):
        """Déverrouillage commun à la page web et à l'applet ; renvoie un code de WEB_MESSAGES."""
        app = self.app
        if not IDENTITY_RE.fullmatch(identity):
            return "unknown" if identity else "empty"
        now = time.monotonic()
        if now < app.blocked_until:
            app.journal.ecrire("warning", "web_unlock_refused", identity=identity, source=source,
                               reason="blocked", client=self.client())
            return "blocked"
        if not password:
            return "empty"
        with app.sup.lock:
            if not app.depot.exists(identity):
                return "unknown"
            if identity in app.sup.running:
                return "already"
            result = app.sup.start_identity(identity, password, source)
        if result.get("ok"):
            app.journal.ecrire("info", "web_unlock", identity=identity, source=source, result="ok",
                               client=self.client())
            return "unlocked"
        app.failures[:] = [t for t in app.failures if now - t < WEB_FAIL_WINDOW] + [now]
        app.journal.ecrire("warning", "web_unlock", identity=identity, source=source, result="failed",
                           client=self.client())
        if len(app.failures) >= WEB_FAIL_LIMIT:
            app.blocked_until = now + WEB_FAIL_WINDOW
            app.failures.clear()
            app.journal.ecrire("warning", "web_unlock_blocked", failures=WEB_FAIL_LIMIT,
                               window_s=WEB_FAIL_WINDOW)
        time.sleep(app.pause_echec)
        return "failed"


class ApplicationWeb:
    """État partagé de la page web : opérations et blocage après échecs répétés."""

    def __init__(self, ops, journal, *, pause_echec=2):
        self.ops, self.sup, self.depot, self.journal = ops, ops.sup, ops.depot, journal
        self.failures = []          # instants (monotonic) des échecs récents
        self.blocked_until = 0.0
        self.pause_echec = pause_echec

    def gestionnaire(self):
        return type("WebHandler", (WebHandler,), {"app": self})


class UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def demarrer_web(configuration, ops, journal, donner_acces):
    """Page web facultative ; renvoie le serveur ou None (comme start_web de 1.9.0)."""
    chemin, compte = configuration["web"]["socket"], configuration["web"]["user"]
    if not chemin:
        return None
    try:
        pwd.getpwnam(compte)
    except KeyError:
        journal.ecrire("error", "web_disabled", reason="unknown_account")
        return None
    try:
        os.unlink(chemin)
    except FileNotFoundError:
        pass
    serveur = UnixHTTPServer(chemin, ApplicationWeb(ops, journal).gestionnaire())
    os.chmod(chemin, 0o600)
    setfacl = configuration["outils"]["setfacl"]
    if not (donner_acces(setfacl, compte, os.path.dirname(chemin), "x")
            and donner_acces(setfacl, compte, chemin, "rw")):
        serveur.server_close()
        os.unlink(chemin)
        journal.ecrire("error", "web_disabled", reason="acl_failed")
        return None
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    journal.ecrire("info", "web_started")
    return serveur
