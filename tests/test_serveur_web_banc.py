# SPDX-License-Identifier: AGPL-3.0-or-later
# Suivi des versions
#   0.1.0  2026-11-08  Banc d'un lighttpd éphémère configuré par l'extrait de docs/serveur-web.md.
"""Banc : vérifie que les exigences de docs/serveur-web.md sont satisfaisables.

Un lighttpd non privilégié, éphémère, dans un dossier temporaire, est configuré par l'extrait
de la page ; un amont Python écoute sur une socket Unix ; un frontal Python simule la règle
« set-header » de HAProxy (suppression de toute occurrence reçue, puis adresse du pair).
Ce banc n'éprouve pas un vrai HAProxy et ne configure aucune installation.
Ignoré, avec message, si le binaire lighttpd est absent.
"""
import http.client
import os
import re
import secrets
import shutil
import socket
import socketserver
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
PAGE = RACINE / 'docs' / 'serveur-web.md'
DEBUT = '<!-- extrait-lighttpd:debut -->'
FIN = '<!-- extrait-lighttpd:fin -->'
ENTETE_CLIENT = 'X-Paresia-Client-IP'
VERSION_ATTENDUE = '1.4.79'
# Essai de silence prolongé : durée fixée ici (5 min au plus), activé par la variable d'environnement.
DUREE_SILENCE_S = 90
VARIABLE_ESSAI_LONG = 'PARESIA_BANC_SILENCE'

LIGHTTPD = shutil.which('lighttpd') or (
    '/usr/sbin/lighttpd' if os.path.exists('/usr/sbin/lighttpd') else None)

pytestmark = pytest.mark.skipif(
    LIGHTTPD is None, reason='lighttpd absent : banc ignoré (exécuté en CI, jamais vert par omission)')

assert DUREE_SILENCE_S <= 300


def extrait():
    texte = PAGE.read_text(encoding='utf-8')
    bloc = texte.split(DEBUT, 1)[1].split(FIN, 1)[0]
    return re.search(r'```\n(.*?)\n```', bloc, re.S).group(1)


class Amont(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def __init__(self, chemin):
        self.vus = []
        self.verrou = threading.Lock()
        self.flux_fini = threading.Event()
        super().__init__(chemin, GestionAmont)


class GestionAmont(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def address_string(self):
        return 'unix'

    def lire_corps(self):
        if 'chunked' in self.headers.get('Transfer-Encoding', '').lower():
            corps = b''
            while True:
                taille = int(self.rfile.readline().split(b';')[0].strip() or b'0', 16)
                if taille == 0:
                    self.rfile.readline()
                    return corps
                corps += self.rfile.read(taille)
                self.rfile.readline()
        return self.rfile.read(int(self.headers.get('Content-Length') or 0))

    def do_POST(self):
        corps = self.lire_corps()
        with self.server.verrou:
            self.server.vus.append({'chemin': self.path, 'entetes': list(self.headers.items()),
                                    'corps': corps})
        if self.path.startswith('/api/admin/flux'):
            return self.flux(silence=self.path.startswith('/api/admin/flux-silence'))
        data = b'{"ok":true}'
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def flux(self, silence):
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        try:
            self.wfile.write(b'data: 1\n\n')
            self.wfile.flush()
            if silence:
                time.sleep(DUREE_SILENCE_S)
            else:
                time.sleep(1.0)
            self.wfile.write(b'data: 2\n\n')
            self.wfile.flush()
            time.sleep(0.2)
        except OSError:
            pass
        finally:
            self.server.flux_fini.set()


class Frontal(threading.Thread):
    """Simule « http-request set-header X-Paresia-Client-IP %[src] » de HAProxy."""

    def __init__(self, port_lighttpd):
        super().__init__(daemon=True)
        self.cible = port_lighttpd
        self.ecoute = socket.socket()
        self.ecoute.bind(('127.0.0.1', 0))
        self.ecoute.listen(16)
        self.port = self.ecoute.getsockname()[1]

    def run(self):
        while True:
            try:
                client, adr = self.ecoute.accept()
            except OSError:
                return
            threading.Thread(target=self.servir, args=(client, adr[0]), daemon=True).start()

    def servir(self, client, src):
        try:
            tete = b''
            while b'\r\n\r\n' not in tete:
                morceau = client.recv(4096)
                if not morceau:
                    client.close()
                    return
                tete += morceau
            entetes, reste = tete.split(b'\r\n\r\n', 1)
            lignes = entetes.split(b'\r\n')
            gardees = [ligne for ligne in lignes[1:]
                       if ligne.split(b':', 1)[0].strip().lower() != ENTETE_CLIENT.lower().encode()]
            gardees.append(('%s: %s' % (ENTETE_CLIENT, src)).encode())
            amont = socket.create_connection(('127.0.0.1', self.cible))
            amont.sendall(b'\r\n'.join([lignes[0]] + gardees) + b'\r\n\r\n' + reste)
        except OSError:
            client.close()
            return

        def pomper(a, b):
            try:
                while True:
                    d = a.recv(65536)
                    if not d:
                        break
                    b.sendall(d)
            except OSError:
                pass
            for s in (b,):
                try:
                    s.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
        threading.Thread(target=pomper, args=(client, amont), daemon=True).start()
        pomper(amont, client)
        time.sleep(0.05)
        client.close()
        amont.close()


def port_libre():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class Banc:
    frontal = None
    amont = None


@pytest.fixture(scope='module')
def banc(tmp_path_factory):
    base = tmp_path_factory.mktemp('banc')
    b = Banc()
    b.base = base
    b.jeton = secrets.token_hex(12)
    b.cookie = secrets.token_hex(12)
    web = base / 'web'
    greffons = web / 'greffons'
    (greffons / 'demo' / 'i18n').mkdir(parents=True)
    (greffons / 'vide').mkdir()
    (web / 'index.html').write_text('<html>admin</html>')
    (greffons / 'index.json').write_text('{"greffons":["demo"]}')
    (greffons / 'demo' / 'app.js').write_text('//marqueur-app')
    (greffons / 'demo' / 'i18n' / 'fr.json').write_text('{"a":"b"}')
    (base / 'hors.txt').write_text('marqueur-hors-racine')
    b.marqueur_app = 'marqueur-app'
    sock = base / 'romulus.sock'
    conf = extrait()
    conf = conf.replace('/usr/local/share/paresia/web/greffons/', str(greffons) + '/')
    conf = conf.replace('/usr/local/share/paresia/web/', str(web) + '/')
    conf = conf.replace('/run/paresia-romulus/romulus-http.sock', str(sock))
    conf = conf.replace(r'192\.0\.2\.254', r'127\.0\.0\.1')
    b.port = port_libre()
    b.acces, b.erreurs = base / 'acces.log', base / 'erreurs.log'
    complet = (conf + '\n\n# Complément du banc (hors extrait)\n'
               'server.document-root = "%s"\nserver.bind = "127.0.0.1"\nserver.port = %d\n'
               'server.errorlog = "%s"\naccesslog.filename = "%s"\n'
               % (base / 'racine', b.port, b.erreurs, b.acces))
    (base / 'racine').mkdir()
    b.conf = base / 'lighttpd.conf'
    b.conf.write_text(complet)
    b.version = subprocess.run([LIGHTTPD, '-v'], capture_output=True, text=True, timeout=20).stdout.strip()
    print('version du banc :', b.version)
    if VERSION_ATTENDUE not in b.version:
        print('ECART DE VERSION : banc conçu pour lighttpd', VERSION_ATTENDUE)
    b.test = subprocess.run([LIGHTTPD, '-tt', '-f', str(b.conf)], capture_output=True, text=True, timeout=30)
    b.amont = Amont(str(sock))
    threading.Thread(target=b.amont.serve_forever, daemon=True).start()
    proc = None
    proc = subprocess.Popen([LIGHTTPD, '-D', '-f', str(b.conf)], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    try:
        for _ in range(100):
            try:
                socket.create_connection(('127.0.0.1', b.port), timeout=0.2).close()
                break
            except OSError:
                if proc.poll() is not None:
                    raise RuntimeError('lighttpd arrêté : ' + proc.stdout.read().decode(errors='replace'))
                time.sleep(0.1)
        else:
            raise RuntimeError('lighttpd ne répond pas')
        b.frontal = Frontal(b.port)
        b.frontal.start()
        yield b
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        if b.amont is not None:
            b.amont.shutdown()
            b.amont.server_close()
        if b.frontal is not None:
            b.frontal.ecoute.close()


def requete_brute(port, octets, source=None, lire_tout=True, delai=10):
    s = socket.create_connection(('127.0.0.1', port), timeout=delai, source_address=source)
    try:
        s.sendall(octets)
        donnees = b''
        while True:
            try:
                d = s.recv(65536)
            except OSError:
                break
            if not d:
                break
            donnees += d
        return donnees
    except OSError:
        return b''
    finally:
        s.close()


def statut(reponse):
    m = re.match(rb'HTTP/1\.[01] (\d{3})', reponse)
    return int(m.group(1)) if m else None


def get(b, chemin, via_frontal=True, methode='GET', entetes='', corps=b''):
    port = b.frontal.port if via_frontal else b.port
    req = ('%s %s HTTP/1.1\r\nHost: bunker.example.org\r\nConnection: close\r\n%sContent-Length: %d\r\n\r\n'
           % (methode, chemin, entetes, len(corps))).encode() + corps
    return requete_brute(port, req)


def entete(reponse, nom):
    m = re.search(rb'^%s: (.*?)\r?$' % re.escape(nom.encode()), reponse, re.I | re.M)
    return m.group(1).decode() if m else None


def corps_de(reponse):
    return reponse.split(b'\r\n\r\n', 1)[-1]


def vus(b, depuis=0):
    with b.amont.verrou:
        return list(b.amont.vus[depuis:])


def test_l_extrait_passe_le_controle_de_syntaxe(banc):
    # (l), (j) : url-path-2f-reject sans 2f-decode, entrée proxy.server vers la socket
    assert banc.test.returncode == 0, banc.test.stdout + banc.test.stderr


def test_pages_et_types(banc):
    # (a), (b), (k), (m)
    r = get(banc, '/admin/')
    assert statut(r) == 200 and entete(r, 'Content-Type').startswith('text/html')
    assert 'nosniff' == (entete(r, 'X-Content-Type-Options') or '').lower()
    assert (entete(r, 'X-Frame-Options') or '').upper() == 'DENY'
    assert entete(r, 'Content-Security-Policy') == "frame-ancestors 'none'"
    r = get(banc, '/admin/greffons/index.json')
    assert statut(r) == 200 and entete(r, 'Content-Type').startswith('application/json')
    r = get(banc, '/admin/greffons/demo/app.js')
    assert statut(r) == 200 and entete(r, 'Content-Type').startswith('text/javascript')
    r = get(banc, '/admin/greffons/demo/i18n/fr.json')
    assert statut(r) == 200 and entete(r, 'Content-Type').startswith('application/json')


def test_hote_inattendu_refuse(banc):
    # exigence 10 : Host autre que le nom attendu, refus sans atteindre l'amont
    n = len(vus(banc))
    req = (b'POST /api/admin/x HTTP/1.1\r\nHost: evil.example.net\r\nConnection: close\r\n'
           b'Content-Length: 0\r\n\r\n')
    r = requete_brute(banc.frontal.port, req)
    assert statut(r) == 403 and len(vus(banc, n)) == 0


def test_origin_transmis_intact(banc):
    n = len(vus(banc))
    get(banc, '/api/admin/x', methode='POST', entetes='Origin: https://bunker.example.org\r\n')
    en = {k.lower(): v for k, v in vus(banc, n)[0]['entetes']}
    assert en['origin'] == 'https://bunker.example.org'


def test_post_atteint_l_amont_intact(banc):
    # (c)
    n = len(vus(banc))
    corps = ('{"jeton":"%s"}' % banc.jeton).encode()
    r = get(banc, '/api/admin/x', methode='POST', entetes='Cookie: s=%s\r\n' % banc.cookie, corps=corps)
    assert statut(r) == 200
    nouveaux = vus(banc, n)
    assert len(nouveaux) == 1
    en = {k.lower(): v for k, v in nouveaux[0]['entetes']}
    assert en['host'] == 'bunker.example.org'
    assert en['cookie'] == 's=%s' % banc.cookie
    assert en['content-length'] == str(len(corps)) and nouveaux[0]['corps'] == corps
    assert 'transfer-encoding' not in en


def test_pair_non_admis_refuse(banc):
    # (d) : la restriction figure dans l'extrait
    n = len(vus(banc))
    req = b'POST /api/admin/x HTTP/1.1\r\nHost: bunker.example.org\r\nConnection: close\r\nContent-Length: 0\r\n\r\n'
    r = requete_brute(banc.port, req, source=('127.0.0.2', 0))
    assert statut(r) == 403
    assert len(vus(banc)) == n


@pytest.mark.parametrize('forge', [
    'X-Paresia-Client-IP: 203.0.113.9\r\n',
    'X-Paresia-Client-IP: 203.0.113.9, 198.51.100.1\r\n',
    'X-Paresia-Client-IP: 203.0.113.9\r\nX-Paresia-Client-IP: 198.51.100.7\r\n',
    'x-paresia-client-ip: 203.0.113.9\r\n',
])
def test_adresse_du_client_une_seule_valeur(banc, forge):
    # (e)
    n = len(vus(banc))
    r = get(banc, '/api/admin/x', methode='POST', entetes=forge + 'X-Forwarded-For: 203.0.113.5\r\n')
    assert statut(r) == 200
    en = vus(banc, n)[0]['entetes']
    valeurs = [v for k, v in en if k.lower() == ENTETE_CLIENT.lower()]
    assert valeurs == ['127.0.0.1']
    xff = [v for k, v in en if k.lower() == 'x-forwarded-for']
    assert len(xff) == 1 and xff[0].endswith(', 127.0.0.1')


def lire_evenements(b, chemin, attendu):
    """Lit un flux ; retourne (instants d'arrivée, flux terminé à l'arrivée du 1er événement)."""
    b.amont.flux_fini.clear()
    req = ('POST %s HTTP/1.1\r\nHost: bunker.example.org\r\nConnection: close\r\nContent-Length: 0\r\n\r\n'
           % chemin).encode()
    s = socket.create_connection(('127.0.0.1', b.frontal.port), timeout=DUREE_SILENCE_S + 60)
    s.sendall(req)
    donnees, instants, fini_au_premier = b'', [], None
    try:
        while len(instants) < attendu:
            d = s.recv(4096)
            if not d:
                break
            donnees += d
            while len(instants) < donnees.count(b'data: '):
                instants.append(time.monotonic())
                if len(instants) == 1:
                    fini_au_premier = b.amont.flux_fini.is_set()
    except OSError:
        pass
    finally:
        s.close()
    return instants, fini_au_premier


def test_flux_evenement_par_evenement(banc):
    # (f), première partie
    instants, fini = lire_evenements(banc, '/api/admin/flux', 2)
    assert len(instants) == 2 and fini is False
    assert instants[1] - instants[0] > 0.5


@pytest.mark.skipif(not os.environ.get(VARIABLE_ESSAI_LONG),
                    reason='essai de silence prolongé : activé par %s (job du banc de la CI)' % VARIABLE_ESSAI_LONG)
def test_flux_silence_prolonge(banc):
    # (f), seconde partie : le résultat est consigné ; la page reste « non vérifié » s'il est inconcluant
    instants, _ = lire_evenements(banc, '/api/admin/flux-silence', 2)
    survecu = len(instants) == 2
    print('RESULTAT SILENCE : %d s sans octet, flux %s (max-read-idle par défaut)'
          % (DUREE_SILENCE_S, 'maintenu' if survecu else 'coupé'))


def test_journaux_sans_secret(banc):
    # (g)
    get(banc, '/api/admin/x?jeton=%s' % banc.jeton, methode='POST',
        entetes='Cookie: s=%s\r\n' % banc.cookie, corps=b'{}')
    get(banc, '/admin/?jeton=%s' % banc.jeton, entetes='Cookie: s=%s\r\n' % banc.cookie)
    time.sleep(0.5)
    for f in (banc.acces, banc.erreurs):
        contenu = f.read_text(errors='replace') if f.exists() else ''
        assert banc.jeton not in contenu and banc.cookie not in contenu
    assert banc.acces.read_text(errors='replace').strip()


def test_traversee_et_chemins_hostiles(banc):
    # (h)
    r = get(banc, '/admin/greffons/demo/app.js/suite')
    assert banc.marqueur_app.encode() not in r
    for chemin in ('/admin/greffons/../hors.txt', '/admin/greffons/%2e%2e/hors.txt',
                   '/admin/greffons/%2e%2e/%2e%2e/hors.txt', '/admin/greffons/..',
                   '/admin/greffons/demo/../../../hors.txt'):
        assert b'marqueur-hors-racine' not in get(banc, chemin), chemin
    r = get(banc, '/admin/greffons/demo%2fapp.js')
    assert (statut(r) or 400) >= 400 and banc.marqueur_app.encode() not in r
    r = get(banc, '/admin/greffons/vide/')
    assert (statut(r) or 400) in (403, 404) and b'Index of' not in r
    # Constat du banc (1.4.82) : mod_staticfile sert un POST comme un GET, sans effet ; l'extrait
    # n'a aucune directive relevée pour le refuser. On vérifie l'absence d'effet : la page servie
    # est celle du GET, et l'amont n'est pas atteint.
    n = len(vus(banc))
    r = get(banc, '/admin/index.html', methode='POST', corps=b'x')
    assert statut(r) in (200, 403, 405, 501) and len(vus(banc, n)) == 0
    if statut(r) == 200:
        assert corps_de(r) == corps_de(get(banc, '/admin/index.html'))
    r = get(banc, '/admin/greffons/demo/')
    assert b'app.js' not in r


def test_corps_trop_gros_et_chunked(banc):
    # (i)
    n = len(vus(banc))
    r = get(banc, '/api/admin/x', methode='POST', corps=b'a' * (100 * 1024))
    assert (statut(r) or 413) >= 400
    assert len(vus(banc, n)) == 0
    chunked = (b'POST /api/admin/x HTTP/1.1\r\nHost: bunker.example.org\r\nConnection: close\r\n'
               b'Transfer-Encoding: chunked\r\n\r\n3\r\nabc\r\n0\r\n\r\n')
    r = requete_brute(banc.frontal.port, chunked)
    atteint = vus(banc, n)
    print('RESULTAT CHUNKED : statut %s, amont atteint : %s' % (statut(r), bool(atteint)))
    for vu in atteint:
        en = {k.lower(): v for k, v in vu['entetes']}
        assert 'transfer-encoding' not in en
        assert en.get('content-length') == '3' and vu['corps'] == b'abc'
