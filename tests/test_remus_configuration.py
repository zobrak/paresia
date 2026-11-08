# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests de configuration de Remus ; dépendances : pytest et bibliothèque standard.
# Suivi des versions
#   0.1.7  2026-11-07  Schéma complété de la section [remus.plugins].
#   0.1.1  2026-11-07  Lecture de l'exemple avec les sections journal et métriques du socle.
#   3.0.0-alpha  2026-11-05  Critère A de T021 (configuration en couches, T015).
#   3.0.0-alpha  2026-11-06  Fusion avec le schéma de l'exécuteur (T022).
import inspect
from pathlib import Path
import re
import tempfile

import pytest

from remus_outils import Enregistreur, configuration
from server import castor, pollux, romulus
from server.commun.config import ErreurConfiguration, lire
from server.remus import Remus, SCHEMA, SCHEMA_PLUGINS, SCHEMA_SOCLE
from server.remus.executeur import SCHEMA_EXECUTEUR

COUCHES = 'racine_systeme' in inspect.signature(lire).parameters
requiert_t015 = pytest.mark.skipif(not COUCHES, reason='configuration en couches (T015) absente')
EXEMPLE = Path(__file__).resolve().parents[1] / 'server/conf/paresia-relais.conf'

COMPLET = """[remus.server]
socket = /run/x/r.sock
uid = 1
gid = 2
[remus.castor]
socket = /run/x/c.sock
uid = 3
[remus.executor]
sudo = /a/sudo
docker = /a/docker
"""


def charger(texte, environ=None):
    with tempfile.TemporaryDirectory(prefix='remus-conf-') as dossier:
        racine = Path(dossier)
        (racine / 'paresia.conf').write_text(texte)
        (racine / 'paresia.conf').chmod(0o644)
        return lire('remus', SCHEMA, argv=[], racine_systeme=racine, environ=environ or {})


def test_remus_schema_egal_socle():
    assert SCHEMA == {**SCHEMA_SOCLE, **SCHEMA_EXECUTEUR, **SCHEMA_PLUGINS}
    assert not set(SCHEMA_SOCLE) & set(SCHEMA_EXECUTEUR)
    assert not set(SCHEMA_PLUGINS) & (set(SCHEMA_SOCLE) | set(SCHEMA_EXECUTEUR))


@requiert_t015
def test_remus_configuration_defauts():
    c = charger(COMPLET)
    assert c['server'] == {'socket': '/run/x/r.sock', 'uid': 1, 'gid': 2, 'stop_s': 120}
    assert c['castor'] == {'socket': '/run/x/c.sock', 'uid': 3, 'delai_s': 2}
    assert c['light'] == {'wait_s': 5, 'poll_s': 0.25, 'check_s': 5}
    assert c['transport'] == {'delai_s': 600, 'max_line': 1048576, 'max_connexions': 16}
    executeur = '[remus.executor]\nsudo = /a/sudo\ndocker = /a/docker\n'
    for manquant in ('[remus.castor]\nsocket = /run/x/c.sock\nuid = 3\n' + executeur,
                     '[remus.server]\nsocket = /run/x/r.sock\nuid = 1\ngid = 2\n' + executeur):
        with pytest.raises(ErreurConfiguration) as e:
            charger(manquant)
        assert e.value.code == 'config_missing'
    with pytest.raises(ErreurConfiguration):
        charger(COMPLET.replace('/run/x/r.sock', 'relatif'))


def _refus(config, actions=None):
    with pytest.raises(ErreurConfiguration) as e:
        Remus(config, actions=actions or {})
    return (e.value.code, e.value.section, e.value.cle)


def test_remus_configuration_validation():
    d = '/run/x'
    c = configuration(d)
    c['light']['poll_s'] = 6
    assert _refus(c) == ('config_invalid', 'light', 'poll_s')
    c = configuration(d)
    c['castor']['delai_s'] = 6
    assert _refus(c) == ('config_invalid', 'castor', 'delai_s')
    # delai_s insuffisant pour une action de delai_max_s donné
    a = Enregistreur(delai_max_s=596).action
    c = configuration(d)
    c['transport']['delai_s'] = 600
    assert _refus(c, {a.nom: a}) == ('config_invalid', 'transport', 'delai_s')
    ok = Enregistreur(delai_max_s=595).action           # 5 + 595 = 600 : accepté
    Remus(c, actions={ok.nom: ok})


@requiert_t015
def test_paresia_relais_exemple_remus():
    texte = EXEMPLE.read_text()
    with tempfile.TemporaryDirectory(prefix='remus-conf-') as dossier:
        (Path(dossier) / 'paresia.conf').write_text(texte)
        (Path(dossier) / 'paresia.conf').chmod(0o644)
        c = lire('remus', SCHEMA, journal=True, metriques=True, argv=[], racine_systeme=dossier, environ={})
        lire('castor', castor.SCHEMA, journal=True, metriques=True, argv=[], racine_systeme=dossier, environ={})
    assert c['server'] == {'socket': '/run/paresia-remus/remus.sock', 'uid': 972, 'gid': 974,
                           'stop_s': 120}
    assert c['castor'] == {'socket': '/run/paresia-castor/castor-state.sock', 'uid': 970, 'delai_s': 2}
    assert c['light'] == {'wait_s': 5, 'poll_s': 0.25, 'check_s': 5}
    assert c['transport'] == {'delai_s': 600, 'max_line': 1048576, 'max_connexions': 16}
    assert not re.search(r'\d+\.\d+\.\d+\.\d+|nsec|ncryptsec|passphrase', texte)
    Remus(c, actions={})                                # contraintes de l'exigence 2 respectées


@requiert_t015
def test_remus_variables_sans_collision():
    noms = {}
    for demon, schema in (('castor', castor.SCHEMA), ('pollux', pollux.SCHEMA),
                          ('romulus', romulus.SCHEMA), ('remus', SCHEMA)):
        for domaine, cle in schema:
            noms.setdefault(f'PARESIA_{demon.upper()}_{domaine.upper()}_{cle.upper()}', demon)
    pris = [n for n in noms if n.startswith('PARESIA_REMUS_')]
    assert pris and all(noms[n] == 'remus' for n in pris)
    # une variable de Remus ne modifie pas la configuration de Castor, et inversement
    env = {'PARESIA_REMUS_LIGHT_WAIT_S': '4'}
    assert charger(COMPLET, env)['light']['wait_s'] == 4
    assert charger(COMPLET, {'PARESIA_CASTOR_STATE_UID': '9'})['castor']['uid'] == 3
