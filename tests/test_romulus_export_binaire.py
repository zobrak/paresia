# SPDX-License-Identifier: AGPL-3.0-or-later
# Transport des exports de Romulus ; dépendances : bibliothèque standard, pytest, server.
# Suivi des versions
#   0.1.8  2026-11-07  Exports et chemins fournis au frontal ; action d'export nommée dans le test.
#   3.0.0-alpha.43  2026-11-07  Envoi tolérant au refus anticipé des requêtes.
#   3.0.0-alpha.41  2026-11-06  Host et Origin posés par défaut (T038).
#   3.0.0-alpha  2026-11-06  Clés backup_* du catalogue admises (outil de sauvegarde, C36).
#   3.0.0-alpha.39  2026-11-06  T036 : admission des clés de démarrage dans les catalogues.
#   3.0.0-alpha.32  2026-11-06  Intégrité, limites, nettoyage, audit et configuration (T013).
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timezone
from email.message import Message
import gzip
import hashlib
from http.client import HTTPConnection, HTTPResponse
import io
import json
import os
from pathlib import Path
import re
import secrets
import socket
import tarfile
import threading
from types import SimpleNamespace

import pytest

from server.commun.config import ErreurConfiguration
from server.commun.journal import Journal
from server.commun.jumeaux import DETAILS, ErreurProtocole, encoder
from romulus_outils import CHARGEUR
from server.romulus import SCHEMA, configuration
import server.romulus.http as module
from server.romulus.http import (ExportBinaire, FrontalHTTP, Requete,
                                 TAILLE_BLOC, _preparer_export)
from server.romulus.sessions import Sessions
from test_romulus_presence_http import (config_test, dossier_socket, envoyer,
                                        evenements, http, ouvrir, service)

ACTION_EXPORT = 'legal/journal/export'
CHEMIN = '/api/admin/' + ACTION_EXPORT
PERIODE = (date(2026, 1, 1), date(2026, 1, 2))
CONTENU = b'{"source":"192.0.2.1","publication":"factice"}\n'


def produire(destination):
    # Archive de test uniquement : la construction réelle appartient à T009.
    with tarfile.open(fileobj=destination, mode='w|gz') as archive:
        entree = tarfile.TarInfo('extraction.jsonl')
        entree.size = len(CONTENU)
        archive.addfile(entree, io.BytesIO(CONTENU))
    return {'count': 1, 'periode': PERIODE}


def creer_export(params, session):
    return ExportBinaire(produire)


class ConnexionMemoire:
    """Capture des délais et lecture HTTP sans ouvrir de socket."""

    def __init__(self, contenu=b''):
        self.contenu = contenu
        self.delais = []

    def settimeout(self, delai):
        self.delais.append(delai)

    def makefile(self, *_):
        return io.BytesIO(self.contenu)


def requete_memoire(frontal, token, *, corps=b'', entetes=None, methode='POST', chemin=CHEMIN,
                     sortie=None, connexion=None):
    requete = object.__new__(Requete)
    requete.server = frontal
    requete.command, requete.path = methode, chemin
    requete.request_version = 'HTTP/1.1'
    requete.headers = Message()
    requete.headers['Content-Length'] = str(len(corps))
    requete.headers['Host'] = 'localhost'
    requete.headers['Origin'] = 'http://localhost'
    if token is not None:
        requete.headers['X-Admin-Token'] = token
    for nom, valeur in (entetes or {}).items():
        requete.headers[nom] = valeur
    requete.connection = connexion if connexion is not None else ConnexionMemoire()
    requete.rfile = io.BytesIO(corps)
    requete.wfile = sortie if sortie is not None else io.BytesIO()
    return requete


def decoder_http(contenu):
    reponse = HTTPResponse(ConnexionMemoire(contenu))
    reponse.begin()
    return reponse.status, dict(reponse.getheaders()), reponse.read()


@pytest.fixture
def frontal_memoire(monkeypatch, tmp_path):
    # Seul le constructeur réseau est remplacé ; l'initialisation de Romulus est réelle.
    monkeypatch.setattr(module.ThreadingHTTPServer, '__init__', lambda *a, **k: None)
    flux = io.StringIO()
    journal = Journal('romulus', flux=flux)
    sessions = Sessions(journal)
    frontal = FrontalHTTP(
        config_test(tmp_path)['http'], sessions, journal, exports=frozenset({ACTION_EXPORT}),
        chemins={'/api/admin/relay/state/status', '/api/admin/relay/backup/export'})
    ouverture = sessions.traiter(
        {'id': secrets.token_hex(8), 'session': 0, 'action': 'presence/session/open',
         'params': {'admin': 'test@example', 'source': '192.0.2.1'}}, object())['data']
    return SimpleNamespace(frontal=frontal, flux=flux, **ouverture)


@pytest.fixture(params=['memoire', 'unix'])
def transport(request):
    if request.param == 'memoire':
        banc = request.getfixturevalue('frontal_memoire')

        def appeler(token, **options):
            req = requete_memoire(banc.frontal, token, **options)
            req._traiter()
            return decoder_http(req.wfile.getvalue())
    else:
        demon, _, flux, _ = service_local = request.getfixturevalue('service')
        banc = SimpleNamespace(frontal=demon.http, flux=flux, **ouvrir(service_local))

        def appeler(token, *, corps=b'', entetes=None, methode='POST', chemin=CHEMIN):
            entetes = {'Origin': 'http://localhost', **(entetes or {})}
            if token is not None:
                entetes['X-Admin-Token'] = token
            with socket.socket(socket.AF_UNIX) as sock:
                sock.settimeout(3)
                sock.connect(banc.frontal.server_address)
                connexion = HTTPConnection('localhost')
                connexion.sock = sock
                try:
                    envoyer(connexion, methode, chemin, corps, entetes)
                    reponse = connexion.getresponse()
                    return reponse.status, dict(reponse.getheaders()), reponse.read()
                finally:
                    connexion.close()

    banc.appeler = appeler
    banc.frontal.actions[ACTION_EXPORT] = creer_export
    return banc


def verifier_erreur(reponse, statut, code):
    obtenu, entetes, corps = reponse
    assert obtenu == statut
    assert entetes['Content-Type'] == 'application/json'
    assert 'Content-Disposition' not in entetes and 'X-Paresia-Sha256' not in entetes
    assert json.loads(corps) == {'ok': False, 'error': {'code': code}}


@pytest.fixture
def temporaires(monkeypatch, tmp_path):
    origine = module.tempfile.TemporaryFile
    fichiers = []
    dossier = tmp_path / 'temporaires'
    dossier.mkdir()

    class FichierObserve:
        def __init__(self, fichier):
            self.fichier = fichier
            self.ferme = threading.Event()

        def __getattr__(self, nom):
            return getattr(self.fichier, nom)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            try:
                self.fichier.close()
            finally:
                self.ferme.set()

    def creer(*args, **kwargs):
        fichier = origine(*args, **kwargs, dir=dossier)
        assert os.fstat(fichier.fileno()).st_nlink == 0
        assert list(dossier.iterdir()) == []
        observe = FichierObserve(fichier)
        fichiers.append(observe)
        return observe

    monkeypatch.setattr(module.tempfile, 'TemporaryFile', creer)
    yield fichiers, dossier
    assert all(f.ferme.wait(2) for f in fichiers)
    assert all(f.closed for f in fichiers)
    assert list(dossier.iterdir()) == []


def test_export_entetes(transport):
    statut, entetes, corps = transport.appeler(transport.token)
    assert statut == 200
    assert entetes['Content-Type'] == 'application/gzip'
    assert int(entetes['Content-Length']) == len(corps)
    assert entetes['X-Paresia-Sha256'] == hashlib.sha256(corps).hexdigest()
    assert re.fullmatch(r'attachment; filename="requisition-[0-9]{8}-[0-9]{6}\.tar\.gz"',
                        entetes['Content-Disposition'])
    assert entetes['Cache-Control'] == 'no-store'
    assert entetes['X-Content-Type-Options'] == 'nosniff'
    assert entetes['Connection'] == 'close'
    assert not {'Set-Cookie', 'Content-Encoding', 'Content-Digest'} & entetes.keys()
    assert all(32 <= ord(c) <= 126 for v in entetes.values() for c in v)
    with tarfile.open(fileobj=io.BytesIO(corps), mode='r:gz') as archive:
        assert archive.extractfile('extraction.jsonl').read() == CONTENU


def test_export_nom_serveur(transport, monkeypatch):
    class Horloge:
        @staticmethod
        def now(zone):
            assert zone is timezone.utc
            return datetime(2026, 2, 3, 4, 5, 6, tzinfo=zone)

    monkeypatch.setattr(module, 'datetime', Horloge)
    hostile = '../"\r\nX-Injection: oui'
    statut, entetes, _ = transport.appeler(
        transport.token, corps=encoder({'critere': hostile, 'valeur': hostile}))
    assert statut == 200
    assert entetes['Content-Disposition'] == (
        'attachment; filename="requisition-20260203-040506.tar.gz"')
    assert hostile not in repr(entetes) and 'X-Injection' not in repr(entetes)


@pytest.mark.parametrize('nom', ['../export.tar.gz', 'requisition-20260101-000000.tar.gz\n',
                                '"\r\nSet-Cookie: injecte', 'requisition-20260101-000000\x00.tar.gz'])
def test_export_entetes_sains(transport, monkeypatch, temporaires, nom):
    monkeypatch.setattr(module, '_nom_export', lambda: nom)
    verifier_erreur(transport.appeler(transport.token), 500, 'internal_error')


def test_export_vide(transport, temporaires):
    transport.frontal.actions[ACTION_EXPORT] = lambda p, s: {'ok': True, 'data': {'count': 0}}
    statut, entetes, corps = transport.appeler(transport.token)
    assert statut == 200 and entetes['Content-Type'] == 'application/json'
    assert json.loads(corps) == {'ok': True, 'data': {'count': 0}}
    assert 'Content-Disposition' not in entetes
    assert temporaires[0] == []
    assert evenements(transport.flux, 'export_delivered') == []


@pytest.mark.parametrize('intercepter', [False, True])
def test_export_trop_gros(transport, temporaires, intercepter):
    transport.frontal.export_max_octets = 64

    def trop_gros(destination):
        destination.write(b'a' * 64)
        try:
            destination.write(b'b')
        except ErreurProtocole:
            if not intercepter:
                raise
        return {'count': 1, 'periode': PERIODE}

    transport.frontal.actions[ACTION_EXPORT] = lambda p, s: ExportBinaire(trop_gros)
    verifier_erreur(transport.appeler(transport.token), 422, 'export_too_large')
    assert evenements(transport.flux, 'export_failed')[-1]['code'] == 'export_too_large'
    assert all(f.closed for f in temporaires[0])
    transport.frontal.export_max_octets = 8388608
    transport.frontal.actions[ACTION_EXPORT] = creer_export
    assert transport.appeler(transport.token)[0] == 200


def test_export_occupe(transport):
    entre = threading.Event()
    sortir = threading.Event()
    termine = threading.Event()
    transport.frontal._exports = threading.BoundedSemaphore(1)
    origine = transport.frontal._exports.release

    def liberer():
        origine()
        termine.set()

    transport.frontal._exports.release = liberer

    def lent(params, session):
        entre.set()
        assert sortir.wait(3)
        return ExportBinaire(produire)

    transport.frontal.actions[ACTION_EXPORT] = lent
    with ThreadPoolExecutor(max_workers=1) as pool:
        en_cours = pool.submit(transport.appeler, transport.token)
        try:
            assert entre.wait(2)
            verifier_erreur(transport.appeler(transport.token), 503, 'export_busy')
        finally:
            sortir.set()
        assert en_cours.result(timeout=3)[0] == 200
    assert termine.wait(2)
    transport.frontal.actions[ACTION_EXPORT] = creer_export
    assert transport.appeler(transport.token)[0] == 200


@pytest.mark.parametrize('cas,statut,code', [
    ('absent', 403, 'token_missing'), ('inconnu', 403, 'token_unknown'),
    ('conflit', 400, 'token_conflict')])
def test_export_jeton(transport, temporaires, cas, statut, code):
    token = None if cas == 'absent' else secrets.token_hex(32) if cas == 'inconnu' else transport.token
    entetes = {'Cookie': 'admin_token=' + secrets.token_hex(32)} if cas == 'conflit' else {}
    verifier_erreur(transport.appeler(token, entetes=entetes), statut, code)
    assert temporaires[0] == []
    assert evenements(transport.flux, 'export_delivered') == []


def test_export_sans_trace(transport, temporaires):
    # La fermeture peut suivre de très près le dernier octet reçu : attendre la fin du traitement.
    termine = threading.Event()
    origine = transport.frontal._exports.release

    def liberer():
        origine()
        termine.set()

    transport.frontal._exports.release = liberer
    assert transport.appeler(transport.token)[0] == 200
    assert termine.wait(2)
    assert len(temporaires[0]) == 1 and temporaires[0][0].closed
    assert list(temporaires[1].iterdir()) == []


def test_export_journal(transport):
    termine = threading.Event()
    origine = transport.frontal._exports.release

    def liberer():
        origine()
        termine.set()

    transport.frontal._exports.release = liberer
    _, entetes, corps = transport.appeler(
        transport.token, corps=encoder({'critere': 'critere-confidentiel', 'valeur': 'valeur-confidentielle'}))
    assert termine.wait(2)
    even = evenements(transport.flux, 'export_delivered')
    assert len(even) == 1
    assert {k: even[0][k] for k in ('session', 'action', 'size', 'sha256', 'count', 'period')} == {
        'session': transport.session, 'action': ACTION_EXPORT, 'size': len(corps),
        'sha256': entetes['X-Paresia-Sha256'], 'count': 1,
        'period': [d.isoformat() for d in PERIODE]}
    texte = transport.flux.getvalue()
    for interdit in (transport.token, 'critere-confidentiel', 'valeur-confidentielle', CONTENU.decode().strip()):
        assert interdit not in texte


@pytest.mark.parametrize('erreur,statut,code', [
    (ErreurProtocole('bad_request'), 400, 'bad_request'),
    (ErreurProtocole('unknown_action'), 404, 'unknown_action'),
    (OSError('contenu-confidentiel'), 500, 'internal_error'),
    (TimeoutError('contenu-confidentiel'), 500, 'internal_error')])
def test_export_echec_creation(transport, temporaires, erreur, statut, code):
    def echouer(destination):
        destination.write(b'prefixe-incomplet')
        raise erreur

    transport.frontal.actions[ACTION_EXPORT] = lambda p, s: ExportBinaire(echouer)
    verifier_erreur(transport.appeler(transport.token), statut, code)
    assert all(f.closed for f in temporaires[0])
    assert 'contenu-confidentiel' not in transport.flux.getvalue()


def test_export_domaine(transport, temporaires):
    transport.frontal.actions['relay/backup/export'] = creer_export
    verifier_erreur(transport.appeler(transport.token, chemin='/api/admin/relay/backup/export'),
                    404, 'unknown_action')
    assert temporaires[0] == []


def test_export_sans_action(transport):
    transport.frontal.actions.clear()
    verifier_erreur(transport.appeler(transport.token), 501, 'not_available')
    assert evenements(transport.flux, 'export_failed') == []


def test_action_json(transport):
    transport.frontal.actions['relay/state/status'] = lambda p, s: {'ok': True, 'data': {'count': 1}}
    statut, _, corps = transport.appeler(transport.token, chemin='/api/admin/relay/state/status')
    assert statut == 200 and json.loads(corps) == {'ok': True, 'data': {'count': 1}}


def test_export_config(tmp_path):
    exemple = Path('server/conf/paresia.conf')
    base = configuration(argv=['--config', str(exemple)], environ={}, chargeur=CHARGEUR)
    assert base['http']['export_max_octets'] == 8388608
    assert base['http']['export_max_simultanes'] == 2
    assert SCHEMA['http', 'export_max_octets'].type == 'limite'
    assert SCHEMA['http', 'export_max_simultanes'].type == 'limite'
    # Défauts réellement appliqués par lire en l'absence des deux lignes.
    sans = tmp_path / 'sans.conf'
    sans.write_text(re.sub(r'(?m)^export_max_(?:octets|simultanes) = .*\n', '', exemple.read_text()))
    sans.chmod(0o600)
    assert configuration(argv=['--config', str(sans)], environ={}, chargeur=CHARGEUR) == base
    sur = configuration(argv=['--config', str(exemple)], environ={
        'PARESIA_ROMULUS_HTTP_EXPORT_MAX_OCTETS': '16777216',
        'PARESIA_ROMULUS_HTTP_EXPORT_MAX_SIMULTANES': '3'}, chargeur=CHARGEUR)
    assert sur['http']['export_max_octets'] == 16777216
    assert sur['http']['export_max_simultanes'] == 3
    for suffixe in ('OCTETS', 'SIMULTANES'):
        for valeur in ('0', '-1', '16777217', '1.5'):
            with pytest.raises(ErreurConfiguration):
                configuration(argv=['--config', str(exemple)], environ={
                    'PARESIA_ROMULUS_HTTP_EXPORT_MAX_' + suffixe: valeur}, chargeur=CHARGEUR)


def test_export_config_repli(frontal_memoire, tmp_path):
    banc = frontal_memoire
    assert banc.frontal.export_max_octets == 8388608
    assert banc.frontal.export_max_simultanes == 2
    for cle in ('export_max_octets', 'export_max_simultanes'):
        for valeur in (0, -1, True, 1.5, 16777217):
            config = config_test(tmp_path, **{cle: valeur})['http']
            with pytest.raises(ValueError):
                FrontalHTTP(config, banc.frontal.sessions, banc.frontal.journal)


def test_codes_export():
    racine = Path(__file__).resolve().parents[1]
    fr, en = [json.loads((racine / 'i18n' / (langue + '.json')).read_text())
              for langue in ('fr-FR', 'en-US')]
    assert fr.keys() == en.keys()
    assert DETAILS.keys() <= fr.keys()
    for code, statut in [('export_too_large', '422'), ('export_busy', '503')]:
        assert fr[code] and en[code] == DETAILS[code]
        assert all(ord(c) >= 32 and not 127 <= ord(c) <= 159 for c in fr[code] + en[code])
        doc = (racine / 'docs/protocole.md').read_text()
        assert re.search(r'^\| `' + code + r'` \|[^\n]+\| ' + statut + r' \|$', doc, re.M)


def produire_long(destination):
    with gzip.GzipFile(fileobj=destination, mode='wb', mtime=0) as archive:
        for _ in range(32):
            archive.write(secrets.token_bytes(TAILLE_BLOC))
    return {'count': 32, 'periode': PERIODE}


def test_export_deconnexion_memoire(frontal_memoire, temporaires):
    banc = frontal_memoire
    banc.frontal.actions[ACTION_EXPORT] = lambda p, s: ExportBinaire(produire_long)

    class SortieCoupee(io.BytesIO):
        appels = 0

        def write(self, bloc):
            self.appels += 1
            if self.appels == 3:
                raise BrokenPipeError()
            return super().write(bloc)

    sortie = SortieCoupee()
    req = requete_memoire(banc.frontal, banc.token, sortie=sortie)
    req._traiter()
    assert req.close_connection
    assert sortie.getvalue().count(b'HTTP/1.1') == 1
    assert b'internal_error' not in sortie.getvalue()
    assert evenements(banc.flux, 'export_delivered') == []
    assert evenements(banc.flux, 'export_failed')[-1]['code'] == 'internal_error'
    assert all(f.closed for f in temporaires[0])
    banc.frontal.actions[ACTION_EXPORT] = creer_export
    suivante = requete_memoire(banc.frontal, banc.token)
    suivante._traiter()
    assert decoder_http(suivante.wfile.getvalue())[0] == 200
    assert banc.frontal._exports.acquire(False)
    assert banc.frontal._exports.acquire(False)
    assert not banc.frontal._exports.acquire(False)
    banc.frontal._exports.release()
    banc.frontal._exports.release()


def test_export_deconnexion_unix(service, temporaires, monkeypatch):
    demon = service[0]
    token = ouvrir(service)['token']
    termine = threading.Event()
    origine_release = demon.http._exports.release
    origine_reponse = Requete._repondre_binaire

    def liberer():
        origine_release()
        termine.set()

    def repondre(req, archive):
        req.connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        return origine_reponse(req, archive)

    monkeypatch.setattr(demon.http._exports, 'release', liberer)
    monkeypatch.setattr(Requete, '_repondre_binaire', repondre)
    demon.http.actions[ACTION_EXPORT] = lambda p, s: ExportBinaire(produire_long)
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(3)
        sock.connect(demon.http.server_address)
        connexion = HTTPConnection('localhost')
        connexion.sock = sock
        try:
            envoyer(connexion, 'POST', CHEMIN, b'', {'X-Admin-Token': token, 'Origin': 'http://localhost'})
            reponse = connexion.getresponse()
            assert reponse.status == 200 and reponse.read(1)
            sock.shutdown(socket.SHUT_RDWR)
            reponse.close()
        finally:
            connexion.close()
    assert termine.wait(3)
    assert all(f.closed for f in temporaires[0])
    assert evenements(service[2], 'export_failed')[-1]['code'] == 'internal_error'
    assert evenements(service[2], 'export_delivered') == []
    # Le serveur traite encore une requête après avoir libéré les deux ressources.
    demon.http.actions[ACTION_EXPORT] = lambda p, s: {'ok': True, 'data': {'count': 0}}
    assert http(service, token, chemin=CHEMIN) == (200, {'ok': True, 'data': {'count': 0}})


def test_export_echeance_et_blocs(frontal_memoire, temporaires, monkeypatch):
    banc = frontal_memoire
    banc.frontal.actions[ACTION_EXPORT] = lambda p, s: ExportBinaire(produire_long)
    horloge = [0.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: horloge[0])
    tailles = []

    class SortieLente(io.BytesIO):
        def write(self, bloc):
            tailles.append(len(bloc))
            horloge[0] += .25
            return super().write(bloc)

    req = requete_memoire(banc.frontal, banc.token, sortie=SortieLente())
    req._traiter()
    assert req.connection.delais == [.5, .25]
    assert tailles[1:] == [TAILLE_BLOC]
    assert b'internal_error' not in req.wfile.getvalue()
    assert evenements(banc.flux, 'export_failed')[-1]['code'] == 'internal_error'
    assert all(f.closed for f in temporaires[0])


def test_export_place_pendant_envoi(frontal_memoire):
    banc = frontal_memoire
    banc.frontal.delai = 5
    banc.frontal.actions[ACTION_EXPORT] = creer_export
    banc.frontal._exports = threading.BoundedSemaphore(1)
    entre, sortir = threading.Event(), threading.Event()

    class SortieBloquee(io.BytesIO):
        def write(self, bloc):
            entre.set()
            assert sortir.wait(3)
            return super().write(bloc)

    req = requete_memoire(banc.frontal, banc.token, sortie=SortieBloquee())
    with ThreadPoolExecutor(max_workers=1) as pool:
        premiere = pool.submit(req._traiter)
        try:
            assert entre.wait(2)
            suivante = requete_memoire(banc.frontal, banc.token)
            suivante._traiter()
            verifier_erreur(decoder_http(suivante.wfile.getvalue()), 503, 'export_busy')
        finally:
            sortir.set()
        premiere.result(timeout=3)
    assert decoder_http(req.wfile.getvalue())[0] == 200


def test_preparation_limite_exacte_et_empreinte(temporaires):
    blocs = [b'a' * 73, b'b' * 91, b'c' * 17]

    def ecrire(destination):
        assert not hasattr(destination, 'seek') and not hasattr(destination, 'fileno')
        for bloc in blocs:
            assert destination.write(bloc) == len(bloc)
        return {'count': 2, 'periode': PERIODE}

    with _preparer_export(ExportBinaire(ecrire), sum(map(len, blocs))) as archive:
        assert archive.taille == sum(map(len, blocs))
        assert archive.sha256 == hashlib.sha256(b''.join(blocs)).hexdigest()
        assert archive.fichier.read() == b''.join(blocs)
    assert archive.fichier.closed


@pytest.mark.parametrize('bilan', [None, {}, {'count': True, 'periode': PERIODE},
    {'count': 0, 'periode': PERIODE}, {'count': 1, 'periode': ('secret', 'secret')},
    {'count': 1, 'periode': PERIODE[::-1]}, {'count': 1, 'periode': (PERIODE[0],)},
    {'count': 1, 'periode': PERIODE, 'critere': 'secret'}])
def test_export_metadonnees_invalides(frontal_memoire, temporaires, bilan):
    banc = frontal_memoire

    def ecrire(destination):
        destination.write(b'incomplet')
        return bilan

    banc.frontal.actions[ACTION_EXPORT] = lambda p, s: ExportBinaire(ecrire)
    req = requete_memoire(banc.frontal, banc.token)
    req._traiter()
    verifier_erreur(decoder_http(req.wfile.getvalue()), 500, 'internal_error')
    assert 'secret' not in banc.flux.getvalue()
    assert all(f.closed for f in temporaires[0])


@pytest.mark.parametrize('champ,valeur', [('sha256', 'a' * 64 + '\r\n'),
    ('sha256', 'A' * 64), ('type_contenu', 'application/gzip\r\nX: oui'),
    ('type_contenu', 'text/plain'), ('taille', -1), ('taille', True)])
def test_export_descripteur_invalide(frontal_memoire, champ, valeur):
    req = requete_memoire(frontal_memoire.frontal, frontal_memoire.token)
    with _preparer_export(ExportBinaire(produire), 8388608) as archive:
        with pytest.raises(ValueError):
            req._repondre_binaire(replace(archive, **{champ: valeur}))
    assert req.wfile.getvalue() == b''


@pytest.mark.parametrize('partielle', [False, True])
def test_export_erreur_disque_interceptee(frontal_memoire, temporaires, monkeypatch, partielle):
    origine = module.tempfile.TemporaryFile

    def creer(*args, **kwargs):
        fichier = origine(*args, **kwargs)

        def ecrire(bloc):
            if partielle:
                return fichier.fichier.write(bloc[:1])
            raise OSError('disque-indisponible')

        fichier.write = ecrire
        return fichier

    def produire_erreur(destination):
        try:
            destination.write(b'incomplet')
        except OSError:
            pass
        return {'count': 1, 'periode': PERIODE}

    monkeypatch.setattr(module.tempfile, 'TemporaryFile', creer)
    banc = frontal_memoire
    banc.frontal.actions[ACTION_EXPORT] = lambda p, s: ExportBinaire(produire_erreur)
    req = requete_memoire(banc.frontal, banc.token)
    req._traiter()
    verifier_erreur(decoder_http(req.wfile.getvalue()), 500, 'internal_error')
    assert all(f.closed for f in temporaires[0])


def test_export_journal_en_echec_apres_envoi(frontal_memoire, temporaires, monkeypatch):
    banc = frontal_memoire
    banc.frontal.actions[ACTION_EXPORT] = creer_export

    def echouer(*args, **kwargs):
        raise OSError('journal-indisponible')

    monkeypatch.setattr(banc.frontal.journal, 'ecrire', echouer)
    req = requete_memoire(banc.frontal, banc.token)
    req._traiter()
    contenu = req.wfile.getvalue()
    assert contenu.count(b'HTTP/1.1') == 1 and b'internal_error' not in contenu
    statut, entetes, corps = decoder_http(contenu)
    assert statut == 200 and hashlib.sha256(corps).hexdigest() == entetes['X-Paresia-Sha256']
    assert all(f.closed for f in temporaires[0])
