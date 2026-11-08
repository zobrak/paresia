# SPDX-License-Identifier: AGPL-3.0-or-later
# Suivi des versions
#   0.1.1  2026-11-07  Priorité notice transmise à syslog.
#   0.1.1  2026-11-07  Détection unique par flux et préfixes forcés.
#   0.1.1  2026-11-07  Vérification du socle commun.
import io
import json
import secrets
import pytest
from server.commun.journal import Journal

@pytest.mark.parametrize('niveau,priorite', [('debug',7), ('info',6), ('notice',5), ('warning',4), ('error',3), ('critical',2)])
def test_priorites(niveau, priorite):
    flux = io.StringIO()
    journal = Journal('test', flux=flux, niveau='debug', prefixe=True)
    jetable = secrets.token_hex(24)
    journal.ecrire(niveau, 'evenement', token=jetable, texte='a\nb')
    assert flux.getvalue().startswith(f'<{priorite}>')
    assert jetable not in flux.getvalue()
    assert json.loads(flux.getvalue()[3:])['texte'] == 'a�b'

def test_seuil():
    flux = io.StringIO()
    journal = Journal('test', flux=flux)
    journal.ecrire('debug', 'cache')
    assert not flux.getvalue()
    journal.definir_niveau('debug')
    journal.ecrire('debug', 'visible')
    assert json.loads(flux.getvalue())['event'] == 'visible'
    with pytest.raises(ValueError):
        journal.ecrire('debug', 'objet', contenu=object())


def test_detection_et_syslog(tmp_path, monkeypatch):
    import os
    import syslog
    with (tmp_path / 'flux').open('w+') as flux:
        st = os.fstat(flux.fileno())
        monkeypatch.setenv('JOURNAL_STREAM', f'{st.st_dev}:{st.st_ino}')
        Journal('test', flux=flux).ecrire('notice', 'visible')
        flux.seek(0)
        assert flux.read().startswith('<5>')
    appels = []
    monkeypatch.setattr(syslog, 'syslog', lambda *args: appels.append(args))
    Journal('test', destination='syslog').ecrire('critical', 'critique')
    assert appels[0][0] == syslog.LOG_CRIT


@pytest.mark.parametrize('prefixe,detecte,present', [
    (None, True, True), (None, False, False), (True, False, True), (False, True, False),
])
def test_detection_memorisee(tmp_path, monkeypatch, prefixe, detecte, present):
    appels = []

    def reconnaitre(fd):
        appels.append(fd)
        return detecte

    monkeypatch.setattr('server.commun.journal.flux_journal', reconnaitre)
    with (tmp_path / 'flux').open('w+') as flux:
        journal = Journal('test', flux=flux, prefixe=prefixe)
        journal.ecrire('info', 'premier')
        journal.ecrire('error', 'second')
        assert appels == ([flux.fileno()] if prefixe is None else [])
        flux.seek(0)
        lignes = flux.read().splitlines()
    assert [ligne.startswith('<') for ligne in lignes] == [present, present]


def test_detection_renouvelee_si_flux_change(tmp_path, monkeypatch):
    import sys

    with (tmp_path / 'flux').open('w+') as flux:
        journal = Journal('test')
        monkeypatch.setattr('server.commun.journal.flux_journal', lambda fd: fd == flux.fileno())
        monkeypatch.setattr(sys, 'stdout', flux)
        journal.ecrire('info', 'premier')
        capture = io.StringIO()
        monkeypatch.setattr(sys, 'stdout', capture)
        journal.ecrire('info', 'second')
        assert json.loads(capture.getvalue())['event'] == 'second'


def test_notice_syslog(monkeypatch):
    import syslog

    appels = []
    monkeypatch.setattr(syslog, 'syslog', lambda *args: appels.append(args))
    Journal('test', destination='syslog').ecrire('notice', 'avis')
    assert len(appels) == 1
    priorite, ligne = appels[0]
    assert priorite == syslog.LOG_NOTICE
    assert json.loads(ligne)['level'] == 'notice'
