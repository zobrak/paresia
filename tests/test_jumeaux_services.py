# Tests des services communs ; dépendances : pytest, bibliothèque standard, server.commun.
# Suivi des versions
#   3.0.0-alpha  2026-11-05  Configuration en couches (T015) : sections [composant.domaine], exemple paresia.conf.
#   3.0.0-alpha  2026-11-05  Filtrage, journaux et configuration.
import io
import json
import re
import secrets
import syslog

import pytest

from server.commun.config import ErreurConfiguration, Option, lire
from server.commun.journal import Journal
from server.commun.texte import filtrer


def test_filtrage_controle():
    controles = ''.join(chr(i) for i in [*range(32), *range(127, 160),
                                       *range(0x202a, 0x202f), *range(0x2066, 0x206a)])
    assert filtrer(controles) == '\ufffd' * len(controles)
    assert filtrer('été 日本語\u200d') == 'été 日本語\ufffd'


def test_journal_sans_secret():
    flux = io.StringIO()
    jetable = secrets.token_hex(32)
    Journal('test', flux=flux).ecrire('info', 'test_event', token=jetable,
                                    passphrase=jetable, contenu=[{'X-Admin-Token': jetable,
                                    'private_key': jetable, 'ncryptsec': jetable,
                                    'secret': jetable, 'password': jetable}])
    assert jetable not in flux.getvalue()
    assert json.loads(flux.getvalue())['token'] == '[REDACTED]'


def test_journal_format(capsys):
    Journal('com\x00posant').ecrire('warning', 'test_event', action='a\n\u202eb', session=0)
    lignes = capsys.readouterr().out.splitlines()
    assert len(lignes) == 1
    objet = json.loads(lignes[0])
    assert re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z', objet['ts'])
    assert list(objet)[:4] == ['ts', 'level', 'component', 'event']
    assert objet['level'] == 'warning'
    assert objet['component'] == 'com\ufffdposant'
    assert objet['event'] == 'test_event'
    assert objet['action'] == 'a\ufffd\ufffdb'


def test_journal_syslog(monkeypatch, capsys):
    appels = []
    monkeypatch.setattr(syslog, 'syslog', lambda *args: appels.append(args))
    Journal('test', destination='syslog').ecrire('error', 'test_event')
    assert appels[0][0] == syslog.LOG_ERR
    assert json.loads(appels[0][1])['event'] == 'test_event'
    assert capsys.readouterr().out == ''


@pytest.mark.parametrize('champs', [{'params': {}}, {'request': {}}, {'ts': 'autre'}])
def test_journal_refuse_contenu_brut(champs):
    with pytest.raises(ValueError):
        Journal('test').ecrire('info', 'test_event', **champs)


SCHEMA = {('transport', 'socket'): Option('chemin'), ('transport', 'uid'): Option('uid'),
          ('transport', 'compte'): Option('compte'), ('transport', 'delai'): Option('duree', 30),
          ('transport', 'max_line'): Option('limite', 1048576)}


def fichier_config(tmp_path, suite=''):
    chemin = tmp_path / 'test.ini'
    chemin.write_text(f'[pollux.transport]\nsocket = {tmp_path / "s"}\nuid = 0\ncompte = test\n' + suite)
    return chemin


def test_config(tmp_path):
    chemin = fichier_config(tmp_path, 'delai = 2.5\n')
    configuration = lire('pollux', SCHEMA, argv=['--config', str(chemin)], environ={})
    assert configuration['transport'] == {'socket': str(tmp_path / 's'), 'uid': 0,
                                         'compte': 'test', 'delai': 2.5, 'max_line': 1048576}
    env = {'PARESIA_POLLUX_CONFIG': str(chemin), 'PARESIA_POLLUX_TRANSPORT_UID': '42'}
    assert lire('pollux', SCHEMA, argv=[], environ=env)['transport']['uid'] == 42
    env['PARESIA_POLLUX_CONFIG'] = str(tmp_path / 'absent')
    assert lire('pollux', SCHEMA, argv=['--config', str(chemin)], environ=env)['transport']['uid'] == 42


@pytest.mark.parametrize('valeur', ['-1', 'true', 'nan', 'inf', '0', 'secret\nvaleur'])
def test_config_valeur_invalide(tmp_path, valeur):
    chemin = fichier_config(tmp_path)
    with pytest.raises(ErreurConfiguration) as erreur:
        lire('pollux', SCHEMA, argv=[], environ={'PARESIA_POLLUX_CONFIG': str(chemin),
             'PARESIA_POLLUX_TRANSPORT_DELAI': valeur})
    assert str(erreur.value) == 'config_invalid:transport:delai'


def test_config_manquante(tmp_path):
    with pytest.raises(ErreurConfiguration, match='config_path_missing'):
        lire('pollux', SCHEMA, argv=['--config', ''], environ={})
    with pytest.raises(ErreurConfiguration, match='config_missing:transport:socket'):
        lire('pollux', SCHEMA, argv=[], environ={}, racine_systeme=tmp_path / 'absente')
    chemin = tmp_path / 'test.ini'
    chemin.write_text('[pollux.transport]\nuid=0\ncompte=test\n')
    with pytest.raises(ErreurConfiguration, match='config_missing:transport:socket'):
        lire('pollux', SCHEMA, argv=['--config', str(chemin)], environ={})


@pytest.mark.parametrize('contenu', ['[pollux.transport\n', '[pollux.transport]\nx=1\n', '[pollux.inconnue]\nx=1\n',
                                   '[DEFAULT]\nsocket=autre\n', '[pollux.transport]\nuid=1\nuid=2\n'])
def test_config_fichier_invalide(tmp_path, contenu):
    chemin = tmp_path / 'test.ini'
    chemin.write_text(contenu)
    with pytest.raises(ErreurConfiguration):
        lire('pollux', SCHEMA, argv=['--config', str(chemin)], environ={})


def test_config_defauts_interdits():
    for type_option in ('chemin', 'uid', 'compte'):
        with pytest.raises(ValueError, match='config_default_forbidden'):
            Option(type_option, 'valeur')
