# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests de la table de commandes et du rendu pour sudoers (T022) ; pytest et bibliothèque standard.
# Suivi des versions
#   0.1.7  2026-11-07  Table vide : chargement d'un dossier de fonctions vide.
#   0.1.1  2026-11-07  Lecture de l'exemple avec les sections journal et métriques.
#   3.0.0-alpha  2026-11-05  Table, rendu sudoers, configuration (T022, exigences 1 à 3, 17 à 20).
#   3.0.0-alpha  2026-11-05  Cycle 2 : comparaison directe du chemin sudo.
#   3.0.0-alpha  2026-11-06  L'exemple est lu avec le schéma fusionné de Remus.
import os
from pathlib import Path

import pytest

import io

from remus_outils import Banc
from server.commun.journal import Journal
from server.commun.config import lire
from server.remus import SCHEMA
from server.remus.fonctions import charger_fonctions, regles_sudoers
from server.remus.executeur import (
    CODES_EXECUTEUR, SCHEMA_EXECUTEUR, Choix, Commande, Entier, Executeur, Hexadecimal, Param,
    ParamOption, RenduSudo, Variable, construire_table)

P = ('sudo', '-n', '--', 'docker')
CONFIG = {'sudo': 's', 'docker': 'd', 'delai_s': 60, 'kill_grace_s': 5, 'sortie_max': 65536,
          'simultanes': 4, 'attente_s': 5}


def invalide(**champs):
    base = {'nom': 'c1', 'argv': P + ('ps',)}
    commande = Commande(**{**base, **champs})
    with pytest.raises(ValueError, match='^invalid_command_table$'):
        Executeur(CONFIG, {commande.nom: commande})


def test_table_validation():
    Executeur(CONFIG, {'c1': Commande('c1', P + ('ps', Param('n', Entier(0, 9))))})
    invalide(argv=('docker', 'ps'))
    invalide(argv=P)  # réduite au préfixe : aucun sous-programme
    invalide(argv=('sudo', '--', 'docker', 'ps'))
    invalide(argv=('sudo', '-n', 'docker', 'ps'))
    invalide(argv=('sudo', '-n', '--', '/usr/bin/docker', 'ps'))
    invalide(argv=P + ('',))
    invalide(argv=P + ('a\x1bb',))
    invalide(argv=P + ('a\x00b',))
    invalide(argv=P + ('ps', Param('n', Entier(0, 9)), ParamOption('--x', 'n', Entier(0, 9))))
    invalide(argv=P + ('ps', Param('N', Entier(0, 9))))
    invalide(argv=P + (Param('n', Entier(0, 9)),))  # valeur variable avant le sous-programme
    invalide(argv=P + ('ps', Param('n', object())))
    invalide(sortie='autre')
    invalide(codes_sortie={2: 'bad_request'})
    invalide(codes_sortie={0: 'command_failed'})
    invalide(delai_s=0)
    invalide(delai_s=3601)
    invalide(sortie_max=0)
    invalide(sortie_max=16 * 1024 * 1024 + 1)
    invalide(nom='C1')
    with pytest.raises(ValueError, match='invalid_command_table'):
        Executeur(CONFIG, {'autre': Commande('c1', P + ('ps',))})
    Executeur(CONFIG, {'c1': Commande('c1', P + ('ps',), codes_sortie={2: 'command_busy'},
                                      delai_s=3600, sortie_max=16 * 1024 * 1024)})


def test_table_doublons():
    a, b = {'c1': Commande('c1', P + ('ps',))}, {'c1': Commande('c1', P + ('images',))}
    with pytest.raises(ValueError, match='^duplicate_command$'):
        construire_table(a, b)
    assert set(construire_table(a, {'c2': Commande('c2', P + ('images',))})) == {'c1', 'c2'}


def test_table_vide(tmp_path):
    for nom in ('livre', 'local'):
        (tmp_path / nom).mkdir(mode=0o755)
    tmp_path.chmod(0o755)
    config = {'plugins': {'fonctions': str(tmp_path / 'livre'), 'locales': str(tmp_path / 'local'),
                          'domaine': 'exemple'}, 'executor': CONFIG}
    options = {'proprietaires': {os.geteuid()}, 'racine_confiance': tmp_path}
    charge = charger_fonctions(config, Journal('essai', flux=io.StringIO()), **options)
    assert dict(charge.actions) == {}
    assert sorted(charge.catalogue.actions) == ['exemple/catalog/describe', 'exemple/catalog/list']
    table = construire_table()
    assert table == {}
    assert Executeur(CONFIG, table).commandes_sudo() == ()
    assert regles_sudoers(config, **options) == ()


def test_commandes_sudo_gabarits():
    g1, g2 = Entier(0, 9), Hexadecimal(8)
    c = Commande('c1', P + ('exec', 'strfry', Param('n', g1), ParamOption('--id', 'h', g2)))
    rendu = Executeur({**CONFIG, 'docker': '/chemin/docker'}, {'c1': c}).commandes_sudo()
    assert rendu == (RenduSudo('c1', ('/chemin/docker', 'exec', 'strfry',
                                      Variable('n', g1, None), Variable('h', g2, '--id'))),)
    elements = rendu[0].elements
    assert elements[3].gabarit is g1 and elements[4].gabarit is g2
    assert all(type(e) is str for e in elements[:3])
    assert 'sudo' not in elements and '-n' not in elements and '--' not in elements


def test_commandes_sudo_source_unique(tmp_path):
    banc = Banc(tmp_path)
    c = Commande('c1', P + ('echo', Param('a', Choix('x1', 'x2')), ParamOption('--id', 'h', Hexadecimal(4))))
    ex = banc.executeur([c])
    assert ex.lancer('c1', {'a': 'x2', 'h': 'ab12'}).ok
    recu = banc.recu()['argv']
    rendu = ex.commandes_sudo()[0].elements
    valeurs = {'a': 'x2', 'h': 'ab12'}
    attendu = []
    for e in rendu:
        if isinstance(e, Variable):
            if e.drapeau:
                attendu.append(e.drapeau)
            attendu.append(valeurs[e.nom])
        else:
            attendu.append(e)
    assert recu[:2] == ['-n', '--'] and recu[2:] == attendu


def test_executeur_configuration(tmp_path):
    racine = tmp_path / 'etc'
    racine.mkdir()
    fichier = racine / 'paresia.conf'
    fichier.write_text('[remus.executor]\nsudo = /a/sudo\ndocker = /a/docker\n')
    fichier.chmod(0o644)
    racine.chmod(0o755)
    c = lire('remus', SCHEMA_EXECUTEUR, argv=[], racine_systeme=racine, environ={})['executor']
    assert c == {'sudo': '/a/sudo', 'docker': '/a/docker', 'delai_s': 60, 'kill_grace_s': 5,
                 'sortie_max': 65536, 'simultanes': 4, 'attente_s': 5}
    with pytest.raises(Exception) as e:
        lire('remus', SCHEMA_EXECUTEUR, argv=[], racine_systeme=tmp_path / 'vide', environ={})
    assert 'config_missing' in str(e.value)
    c = lire('remus', SCHEMA_EXECUTEUR, argv=[], racine_systeme=racine,
             environ={'PARESIA_REMUS_EXECUTOR_SIMULTANES': '2'})['executor']
    assert c['simultanes'] == 2
    assert CODES_EXECUTEUR == ('command_failed', 'command_timeout', 'command_busy')


def test_paresia_relais_exemple_executeur(tmp_path):
    exemple = Path(__file__).resolve().parents[1] / 'server/conf/paresia-relais.conf'
    racine = tmp_path / 'etc'
    racine.mkdir()
    cible = racine / 'paresia.conf'
    cible.write_text(exemple.read_text())
    cible.chmod(0o644)
    racine.chmod(0o755)
    c = lire('remus', SCHEMA, argv=[], racine_systeme=racine, environ={}, journal=True, metriques=True)['executor']
    assert c['sudo'] == '/usr/bin/sudo' and c['simultanes'] == 4
