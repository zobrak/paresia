# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests de la session de présence du poste client ; dépendances : bibliothèque standard, pytest.
# Suivi des versions
#   0.1.12  2026-11-08  Défi signé : challenge, signature, open, refus et délais.
#   3.0.0-alpha.42  2026-11-06  Notifications de perte synchronisées et rejet des lignes longues sans échéance.
#   3.0.0-alpha.41  2026-11-06  Ouverture, erreurs, battement, perte, fermeture et jeton.
import io
import json
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from admin.app.signature import ErreurSignature
from admin.app.presence import ErreurPresence, Etat, SessionPresence
from admin.app.textes import charger
from server.commun.jumeaux import MAX_LINE

FAUX = str(Path(__file__).parent / 'outils' / 'faux_ssh.py')
RACINE = Path(__file__).resolve().parents[1]
ATTENDU = ['-T', '-i', '/cle/admin.pub', '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
           '--', 'admin@bunker.example.org']


SIGNATURE = 'U1NIU0lHAAAAAQ=='
CLES = dict(admin='essai', ssh_keygen='/usr/bin/ssh-keygen')


def signeur_ok(defi, admin, namespace, cle_publique, ssh_keygen, delai_s):
    return SIGNATURE


def signeur_interdit(*args):
    raise AssertionError('signature tentée')


class Horloge:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Banc:
    def __init__(self, tmp_path, scenario, ouverture=5, signeur=signeur_ok, **env):
        self.jeton = secrets.token_hex(32)
        self.journal = tmp_path / 'journal.ndjson'
        self.env = {'FAUX_SSH_SCENARIO': scenario, 'FAUX_SSH_JOURNAL': str(self.journal),
                    'FAUX_SSH_JETON': self.jeton, **env}
        self.appels = []
        self.procs = []
        self.evenements = []
        self.horloge = Horloge()
        self.session = SessionPresence(
            'ssh', 'bunker.example.org', 'admin', '/cle/admin.pub', ouverture,
            signeur=signeur, horloge=self.horloge, lancer=self._lancer, **CLES,
            ecouteur=lambda etat, code: self.evenements.append((etat, code)))

    def _lancer(self, commande, **kw):
        self.appels.append((list(commande), dict(kw)))
        import os
        proc = subprocess.Popen([sys.executable, FAUX, *commande[1:]],
                                env={**os.environ, **self.env}, **kw)
        self.procs.append(proc)
        return proc

    def lignes(self):
        if not self.journal.exists():
            return []
        return [json.loads(x) for x in self.journal.read_text().splitlines()]

    def pings(self):
        return [x for x in self.lignes() if x.get('action') == 'presence/session/ping']


def attendre(condition, delai=10.0):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if condition():
            return True
        threading.Event().wait(0.01)
    return condition()


@pytest.fixture
def banc(tmp_path):
    bancs = []

    def faire(scenario='ok', **env):
        b = Banc(tmp_path, scenario, **env)
        bancs.append(b)
        return b
    yield faire
    for b in bancs:
        b.session.fermer()


def test_ouverture_reussie(banc):
    b = banc(FAUX_SSH_BATTEMENT='12', FAUX_SSH_DELAI='40')
    b.session.ouvrir()
    s = b.session
    assert s.etat is Etat.OUVERTE
    assert (s.numero, s.heartbeat_s, s.timeout_s) == (7, 12, 40)
    assert s.jeton() == b.jeton
    commande, kw = b.appels[0]
    assert commande == ['ssh'] + ATTENDU
    assert kw == {'stdin': subprocess.PIPE, 'stdout': subprocess.PIPE,
                  'stderr': subprocess.PIPE, 'bufsize': 0}
    defi, ouverture = b.lignes()[1], b.lignes()[2]
    assert defi['action'] == 'presence/session/challenge' and defi['session'] == 0
    assert defi['params'] == {} and len(defi['id']) == 16
    assert ouverture['action'] == 'presence/session/open' and ouverture['session'] == 0
    assert ouverture['params'] == {'signature': SIGNATURE} and len(ouverture['id']) == 16
    assert defi['id'] != ouverture['id']
    assert b.lignes()[0]['argv'] == ATTENDU
    assert b.evenements == [(Etat.OUVERTE, None)]


@pytest.mark.parametrize('scenario', ['code_defi', 'code_open'])
@pytest.mark.parametrize('code', ['challenge_required', 'challenge_expired', 'signature_invalid',
                                  'session_limit', 'auth_info_unavailable', 'not_available',
                                  'bad_request'])
def test_refus_distants(banc, scenario, code):
    b = banc(scenario, FAUX_SSH_CODE=code)
    with pytest.raises(ErreurPresence) as e:
        b.session.ouvrir()
    assert e.value.code == code
    assert b.session.etat is Etat.FERMEE
    assert b.procs[0].poll() is not None
    assert b.session.jeton() is None


def _defi(**champs):
    base = {'challenge': 'ab' * 32, 'namespace': 'paresia-presence', 'expires_s': 60}
    base.update(champs)
    return json.dumps(base)


@pytest.mark.parametrize('defi,code', [
    (_defi(challenge='ab' * 31 + 'a'), 'ui_presence_reponse_invalide'),
    (_defi(challenge='AB' * 32), 'ui_presence_reponse_invalide'),
    (_defi(challenge=5), 'ui_presence_reponse_invalide'),
    (_defi(extra=1), 'ui_presence_reponse_invalide'),
    (json.dumps({'challenge': 'ab' * 32, 'namespace': 'paresia-presence'}),
     'ui_presence_reponse_invalide'),
    (_defi(expires_s=0), 'ui_presence_reponse_invalide'),
    (_defi(expires_s=-1), 'ui_presence_reponse_invalide'),
    (_defi(expires_s=True), 'ui_presence_reponse_invalide'),
    (_defi(expires_s='60'), 'ui_presence_reponse_invalide'),
    (_defi(expires_s=3601), 'ui_presence_reponse_invalide'),
    (_defi(namespace=None), 'ui_presence_reponse_invalide'),
    (_defi(namespace='autre'), 'ui_presence_espace_refuse'),
    (json.dumps([1]), 'ui_presence_reponse_invalide'),
])
def test_defi_mal_forme(banc, defi, code):
    b = banc('ok', signeur=signeur_interdit, FAUX_SSH_DEFI=defi)
    with pytest.raises(ErreurPresence) as e:
        b.session.ouvrir()
    assert e.value.code == code
    assert b.session.etat is Etat.FERMEE
    assert b.procs[0].poll() is not None


@pytest.mark.parametrize('scenario', ['defi_mauvais_id', 'defi_ok_booleen'])
def test_defi_reponse_invalide(banc, scenario):
    b = banc(scenario, signeur=signeur_interdit)
    with pytest.raises(ErreurPresence) as e:
        b.session.ouvrir()
    assert e.value.code == 'ui_presence_reponse_invalide'


def test_defi_silence(banc):
    b = banc('defi_silence', ouverture=0.3, signeur=signeur_interdit)
    with pytest.raises(ErreurPresence) as e:
        b.session.ouvrir()
    assert e.value.code == 'ui_presence_delai_ouverture'
    assert b.procs[0].poll() is not None


def test_signeur_arguments(banc):
    appels = []

    def signeur(*args):
        appels.append(args)
        return SIGNATURE
    b = banc(signeur=signeur)
    b.session.ouvrir()
    assert appels == [('ab' * 32, 'essai', 'paresia-presence', '/cle/admin.pub',
                       '/usr/bin/ssh-keygen', appels[0][5])]
    assert 0 < appels[0][5] <= 5


@pytest.mark.parametrize('erreur', ['ui_presence_defi_delai', 'ui_presence_signature_echec',
                                    'ui_presence_defi_invalide', 'ui_presence_espace_refuse'])
def test_erreur_de_signature(banc, erreur):
    def signeur(*args):
        raise ErreurSignature(erreur)
    b = banc(signeur=signeur)
    with pytest.raises(ErreurPresence) as e:
        b.session.ouvrir()
    assert e.value.code == erreur
    assert b.session.etat is Etat.FERMEE and b.procs[0].poll() is not None
    assert [x['action'] for x in b.lignes()[1:]] == ['presence/session/challenge']


@pytest.mark.parametrize('signe', ['', 'é', 'a' * 2049, 5, None])
def test_signature_refusee_avant_envoi(banc, signe):
    b = banc(signeur=lambda *args: signe)
    with pytest.raises(ErreurPresence) as e:
        b.session.ouvrir()
    assert e.value.code == 'ui_presence_signature_echec'
    assert [x['action'] for x in b.lignes()[1:]] == ['presence/session/challenge']


def test_delai_expires_s(banc):
    b = banc(FAUX_SSH_DEFI=_defi(expires_s=0.2), ouverture=30,
             signeur=lambda *a: (time.sleep(0.5), SIGNATURE)[1])
    with pytest.raises(ErreurPresence) as e:
        b.session.ouvrir()
    assert e.value.code == 'ui_presence_defi_delai'
    assert b.session.etat is Etat.FERMEE and b.procs[0].poll() is not None
    assert [x['action'] for x in b.lignes()[1:]] == ['presence/session/challenge']


def test_delai_ouverture_borne_la_signature(banc):
    recu = []

    def signeur(*args):
        recu.append(args[5])
        time.sleep(0.5)
        return SIGNATURE
    b = banc(ouverture=0.3, signeur=signeur)
    with pytest.raises(ErreurPresence) as e:
        b.session.ouvrir()
    assert e.value.code == 'ui_presence_defi_delai'
    assert recu and recu[0] <= 0.3
    assert b.procs[0].poll() is not None


def test_secrets_absents(banc):
    b = banc()
    b.session.ouvrir()
    for secret in (b.jeton, 'ab' * 32, SIGNATURE):
        assert secret not in repr(b.session) + str(b.session) + b.session.diagnostic
    b2 = banc(FAUX_SSH_DEFI=_defi(namespace='autre'))
    with pytest.raises(ErreurPresence) as e:
        b2.session.ouvrir()
    assert 'ab' * 32 not in repr(e.value) + str(e.value)


@pytest.mark.parametrize('scenario,code', [
    ('session_limit', 'session_limit'),
    ('auth_info_unavailable', 'auth_info_unavailable'),
    ('code_inconnu', 'ui_presence_reponse_invalide'),
    ('illisible', 'ui_presence_reponse_invalide'),
    ('mauvais_id', 'ui_presence_reponse_invalide'),
    ('jeton_court', 'ui_presence_reponse_invalide'),
    ('jeton_majuscules', 'ui_presence_reponse_invalide'),
    ('delais_incoherents', 'ui_presence_reponse_invalide'),
    ('delai_nul', 'ui_presence_reponse_invalide'),
    ('session_zero', 'ui_presence_reponse_invalide'),
    ('ok_booleen', 'ui_presence_reponse_invalide'),
    ('brutal', 'ui_presence_ssh_echec'),
])
def test_ouverture_refusee(banc, scenario, code):
    b = banc(scenario)
    with pytest.raises(ErreurPresence) as e:
        b.session.ouvrir()
    assert e.value.code == code
    assert b.session.etat is Etat.FERMEE
    assert b.procs[0].poll() is not None
    assert b.session.jeton() is None
    assert b.jeton not in repr(e.value) + str(e.value)


def test_reponse_ouverture_trop_longue():
    s = SessionPresence('ssh', 'bunker.example.org', 'admin', '/cle/admin.pub', 5, **CLES)
    with io.BytesIO(b'a' * (MAX_LINE + 16) + b'\n') as flux:
        s._proc = SimpleNamespace(stdout=flux)
        # Le rejet dépend de la taille, sans imposer de débit au lecteur.
        # Les autres refus et le silence éprouvent ouvrir() avec le faux SSH.
        s._lire()
        assert flux.tell() == MAX_LINE + 1
    assert s._pret.is_set()
    assert s._echec == 'ui_presence_reponse_invalide'
    assert s.etat is Etat.FERMEE


def test_silence_a_l_ouverture(banc):
    b = banc('silence', ouverture=0.3)
    with pytest.raises(ErreurPresence) as e:
        b.session.ouvrir()
    assert e.value.code == 'ui_presence_delai_ouverture'
    assert b.procs[0].poll() is not None


def test_lancement_impossible(tmp_path):
    def echec(*a, **k):
        raise FileNotFoundError()
    s = SessionPresence('ssh', 'h.example.org', 'admin', '/c.pub', 1, lancer=echec, **CLES)
    with pytest.raises(ErreurPresence) as e:
        s.ouvrir()
    assert e.value.code == 'ui_presence_ssh_echec'


def test_battement(banc):
    b = banc(FAUX_SSH_BATTEMENT='30', FAUX_SSH_DELAI='90')
    b.session.ouvrir()
    threading.Event().wait(0.1)
    assert b.pings() == []
    b.horloge.t += 31
    assert attendre(lambda: len(b.pings()) == 1)
    ping = b.pings()[0]
    assert ping['session'] == 7 and ping['params'] == {} and ping['proto'] == 'jumeaux/1'
    assert len(ping['id']) == 16
    b.horloge.t += 31
    assert attendre(lambda: len(b.pings()) == 2)
    assert b.session.etat is Etat.OUVERTE


def test_un_seul_ping_en_attente(banc):
    b = banc('ping_silence', FAUX_SSH_BATTEMENT='30', FAUX_SSH_DELAI='90')
    b.session.ouvrir()
    b.horloge.t += 31
    assert attendre(lambda: len(b.pings()) == 1)
    b.horloge.t += 31
    threading.Event().wait(0.2)
    assert len(b.pings()) == 1


def test_perte_sans_reponse(banc):
    b = banc('ping_silence', FAUX_SSH_BATTEMENT='30', FAUX_SSH_DELAI='90')
    b.session.ouvrir()
    b.horloge.t += 31
    assert attendre(lambda: len(b.pings()) == 1)
    b.horloge.t += 60
    assert attendre(lambda: (Etat.PERDUE, 'ui_presence_perdue') in b.evenements)
    assert attendre(lambda: b.procs[0].poll() is not None)
    assert b.evenements.count((Etat.PERDUE, 'ui_presence_perdue')) == 1
    b.session.fermer()
    assert [e for e, _ in b.evenements].count(Etat.PERDUE) == 1


@pytest.mark.parametrize('scenario,code', [
    ('ping_session_closed', 'session_closed'),
    ('ping_fin_brutale', 'ui_presence_perdue'),
    ('ping_illisible', 'ui_presence_reponse_invalide'),
    ('ping_trop_long', 'ui_presence_reponse_invalide'),
    ('ping_id_inconnu', 'ui_presence_reponse_invalide'),
])
def test_perte_apres_ouverture(banc, scenario, code):
    b = banc(scenario, FAUX_SSH_BATTEMENT='30', FAUX_SSH_DELAI='90')
    b.session.ouvrir()
    b.horloge.t += 31
    assert attendre(lambda: (Etat.PERDUE, code) in b.evenements)
    assert b.evenements.count((Etat.PERDUE, code)) == 1
    assert attendre(lambda: b.procs[0].poll() is not None)


def test_fin_de_flux_apres_ouverture(banc):
    b = banc()
    b.session.ouvrir()
    b.procs[0].stdin.close()
    assert attendre(lambda: (Etat.PERDUE, 'ui_presence_perdue') in b.evenements)
    assert b.evenements.count((Etat.PERDUE, 'ui_presence_perdue')) == 1


def test_etat_perdu_avant_notification(banc, monkeypatch):
    b = banc('ping_illisible', FAUX_SSH_BATTEMENT='30', FAUX_SSH_DELAI='90')
    entree = threading.Event()
    liberer = threading.Event()
    terminer = b.session._terminer_ssh
    evenement = (Etat.PERDUE, 'ui_presence_reponse_invalide')

    def terminer_bloque():
        entree.set()
        liberer.wait()
        terminer()

    monkeypatch.setattr(b.session, '_terminer_ssh', terminer_bloque)
    try:
        b.session.ouvrir()
        b.horloge.t += 31
        assert attendre(entree.is_set)
        # L'état précède la notification : il ne permet pas d'attendre l'écouteur.
        assert b.session.etat is Etat.PERDUE
        assert evenement not in b.evenements
    finally:
        liberer.set()
    assert attendre(lambda: evenement in b.evenements)
    b.session.fermer()
    assert b.evenements.count(evenement) == 1
    assert all(not fil.is_alive() for fil in b.session._fils)


def test_fermeture_idempotente(banc):
    b = banc()
    b.session.ouvrir()
    avant = threading.active_count()
    b.session.fermer()
    b.session.fermer()
    assert b.session.etat is Etat.FERMEE
    assert b.procs[0].poll() is not None
    assert threading.active_count() <= avant - 2
    assert [e for e, _ in b.evenements].count(Etat.FERMEE) == 1
    assert b.session.jeton() is None


def test_fermeture_sans_ouverture(banc):
    b = banc()
    b.session.fermer()
    assert b.session.etat is Etat.FERMEE and b.evenements == []


def test_reouverture_apres_fermeture(banc):
    b = banc()
    b.session.ouvrir()
    b.session.fermer()
    b.session.ouvrir()
    assert b.session.etat is Etat.OUVERTE and len(b.procs) == 2


def test_jeton_non_expose(banc):
    b = banc('jeton_court')
    b.session = SessionPresence('ssh', 'h.example.org', 'admin', '/c.pub', 5, lancer=b._lancer,
                              signeur=signeur_ok, **CLES)
    with pytest.raises(ErreurPresence):
        b.session.ouvrir()
    b = banc()
    b.session.ouvrir()
    s = b.session
    assert b.jeton not in repr(s) + str(s) + s.diagnostic
    for commande, kw in b.appels:
        assert b.jeton not in ' '.join(commande) + repr(kw)
        assert 'env' not in kw
    assert s.jeton() == b.jeton


def test_diagnostic_borne_et_filtre(tmp_path):
    script = tmp_path / 'bruit.py'
    script.write_text("import sys\nsys.stderr.write('\\x1b[31m' + 'x' * 5000)\n"
                      "sys.stderr.flush()\nsys.stdin.read()\n")

    def lancer(commande, **kw):
        return subprocess.Popen([sys.executable, str(script)], **kw)
    s = SessionPresence('ssh', 'h.example.org', 'admin', '/c.pub', 0.5, lancer=lancer, **CLES)
    with pytest.raises(ErreurPresence):
        s.ouvrir()
    assert len(s.diagnostic) <= 2048 and '\x1b' not in s.diagnostic


def test_catalogues_presence():
    cles = ['ui_presence_ssh_echec', 'ui_presence_delai_ouverture',
            'ui_presence_reponse_invalide', 'ui_presence_perdue', 'ui_presence_fermee',
            'ui_presence_defi_invalide', 'ui_presence_defi_delai',
            'ui_presence_signature_echec', 'ui_presence_espace_refuse']
    for langue in ('fr-FR', 'en-US'):
        catalogue = charger(langue, RACINE / 'i18n')
        for cle in cles:
            assert catalogue.libelle(cle) != cle
            assert catalogue.erreur(cle) == catalogue.libelle(cle)
