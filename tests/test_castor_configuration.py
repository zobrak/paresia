# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests de configuration de Castor ; dépendances : pytest et bibliothèque standard.
# Suivi des versions
#   0.1.1  2026-11-07  Lecture de l'exemple avec les sections journal et métriques du socle.
#   3.0.0-alpha  2026-11-05  Critères C de T020 (configuration en couches, T015).
#   3.0.0-alpha  2026-11-05  T021 : sections remus. admises dans l'exemple de configuration.
#   3.0.0-alpha  2026-11-05  T022 : section [remus.executor] admise.
#   3.0.0-alpha  2026-11-06  Section [sauvegarde.stockage] admise (C36, D83).
import inspect
from pathlib import Path
import re
import tempfile

import pytest

from castor_outils import configuration
from server.castor import Castor, SCHEMA
from server.commun import config as cfg
from server.commun.config import ErreurConfiguration, lire

COUCHES = 'racine_systeme' in inspect.signature(lire).parameters
requiert_t015 = pytest.mark.skipif(not COUCHES, reason='configuration en couches (T015) absente')
EXEMPLE = Path(__file__).resolve().parents[1] / 'server/conf/paresia-relais.conf'


def charger(texte, environ=None):
    with tempfile.TemporaryDirectory(prefix='castor-conf-') as dossier:
        racine = Path(dossier)
        (racine / 'paresia.conf').write_text(texte)
        (racine / 'paresia.conf').chmod(0o644)
        return lire('castor', SCHEMA, argv=[], racine_systeme=racine, environ=environ or {})


COMPLET = """[castor.tunnel]
socket = /run/x/a.sock
uid = 1
gid = 2
[castor.state]
socket = /run/x/b.sock
uid = 3
gid = 4
"""


@requiert_t015
def test_castor_configuration_defauts():
    c = charger(COMPLET)
    assert c['lights'] == {'heartbeat_s': 30, 'margin_s': 5, 'maximum': 64,
                           'closed_s': 10, 'verification_s': 1}
    assert c['transport']['max_connexions'] == 64


@requiert_t015
def test_castor_configuration_validation():
    with pytest.raises(ErreurConfiguration) as e:
        charger('[castor.state]\nsocket = /run/x/b.sock\nuid = 3\ngid = 4\n')
    assert e.value.code == 'config_missing'
    base = configuration('/run/x')
    base['lights']['margin_s'] = 3600
    with pytest.raises(ErreurConfiguration) as e:
        Castor(base)
    assert (e.value.code, e.value.section, e.value.cle) == ('config_invalid', 'lights', 'margin_s')
    base = configuration('/run/x')
    base['state']['socket'] = base['tunnel']['socket']
    with pytest.raises(ErreurConfiguration) as e:
        Castor(base)
    assert (e.value.code, e.value.section, e.value.cle) == ('config_invalid', 'state', 'socket')
    with pytest.raises(ErreurConfiguration):
        charger(COMPLET + '[castor.lights]\nmargin_s = 4000\n')


@requiert_t015
def test_paresia_relais_exemple_castor():
    texte = EXEMPLE.read_text()
    sections = re.findall(r'^\[([^\]]+)\]', texte, re.M)
    assert any(s.startswith('castor.') for s in sections)
    assert all(s.startswith(('castor.', 'remus.', 'sauvegarde.')) for s in sections)
    with tempfile.TemporaryDirectory(prefix='castor-conf-') as dossier:
        (Path(dossier) / 'paresia.conf').write_text(texte)
        (Path(dossier) / 'paresia.conf').chmod(0o644)
        c = lire('castor', SCHEMA, journal=True, metriques=True, argv=[], racine_systeme=dossier, environ={})
    assert c['tunnel'] == {'socket': '/run/paresia-castor/castor.sock', 'uid': 972, 'gid': 973}
    assert c['state'] == {'socket': '/run/paresia-castor/castor-state.sock', 'uid': 971, 'gid': 975}
    assert not re.search(r'\d+\.\d+\.\d+\.\d+|nsec|ncryptsec|passphrase', texte)


def test_castor_variables_sans_collision():
    from server.pollux import SCHEMA as POLLUX
    try:
        from server.romulus import SCHEMA as ROMULUS
    except ImportError:
        ROMULUS = {}
    def variables(demon, schema):
        return {f'PARESIA_{demon}_{d.upper()}_{c.upper()}' for d, c in schema}
    castor = variables('CASTOR', SCHEMA)
    assert len(castor) == len(SCHEMA)
    assert not castor & (variables('POLLUX', POLLUX) | variables('ROMULUS', ROMULUS))
