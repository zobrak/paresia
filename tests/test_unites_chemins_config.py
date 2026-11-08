# SPDX-License-Identifier: AGPL-3.0-or-later
# Non-régression : un chemin explicite de la configuration livrée, lu par un démon, n'est pas masqué
# par l'unité livrée de ce démon (ProtectHome=, InaccessiblePaths=) sans exception explicite
# (BindReadOnlyPaths= ou BindPaths=). Lecture des fichiers livrés seulement : pas d'analyse du code.
# Dépendances : bibliothèque standard, pytest.
# Suivi des versions
#   0.1.2  2026-11-07  Dossier d'état des unités (StateDirectory=), métriques inactives, garde pour Nisaba.
#   0.1.1  2026-11-07  Unités Type=notify : NotifyAccess=, RestartPreventExitStatus=, TimeoutStartSec=.
#   3.0.0-alpha.42  2026-11-07  Première version : Pollux lisait authorized_keys sous un /home masqué.
#   0.1.0  2026-11-07  Comptes hors /home et paramètres sans invite.
import re
import configparser
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
DEPLOY = RACINE / 'deploy'
CONF = RACINE / 'server' / 'conf'
# unité -> (fichier d'unité, fichiers de configuration en couches, préfixes de sections lues par le démon)
DEMONS = {
    'pollux': (DEPLOY / 'backend-admin/etc/systemd/system/pollux.service',
               [CONF / 'paresia.conf', DEPLOY / 'backend-admin/etc/paresia/conf.d/10-backend-admin.conf'],
               ('pollux.',)),
    'romulus': (DEPLOY / 'backend-admin/etc/systemd/system/romulus.service',
                [CONF / 'paresia.conf', DEPLOY / 'backend-admin/etc/paresia/conf.d/10-backend-admin.conf'],
                ('romulus.',)),
    'castor': (DEPLOY / 'backend-relais/etc/systemd/system/castor.service',
               [CONF / 'paresia-relais.conf'], ('castor.',)),
    'remus': (DEPLOY / 'backend-relais/etc/systemd/system/remus.service',
              [CONF / 'paresia-relais.conf'], ('remus.',)),
}
# Répertoires que ProtectHome= masque (systemd.exec(5), ProtectHome=).
HOME = ('/home', '/root', '/run/user')


def valeurs_unite(chemin):
    resultat = {}
    for ligne in chemin.read_text(encoding='utf-8').splitlines():
        ligne = ligne.strip()
        if '=' in ligne and not ligne.startswith(('#', '[')):
            cle, valeur = ligne.split('=', 1)
            resultat.setdefault(cle, []).extend(valeur.split())
    return resultat


def chemins_lus(fichiers, prefixes):
    config = configparser.ConfigParser(interpolation=None)
    for f in fichiers:
        config.read(f, encoding='utf-8')
    return sorted((s, cle, v) for s in config.sections() if s.startswith(prefixes)
                  for cle, v in config[s].items() if v.startswith('/'))


def sous(chemin, racine):
    return chemin == racine or chemin.startswith(racine.rstrip('/') + '/')


def masque(chemin, unite):
    """Vrai si l'unité masque le chemin sans exception explicite."""
    exceptions = [e.lstrip('-').split(':')[0] for cle in ('BindReadOnlyPaths', 'BindPaths')
                  for e in unite.get(cle, [])]
    if any(sous(chemin, e) or sous(e, chemin) for e in exceptions):
        return False
    inaccessibles = [p.lstrip('-+') for p in unite.get('InaccessiblePaths', [])]
    if any(sous(chemin, p) for p in inaccessibles):
        return True
    protege = unite.get('ProtectHome', ['no'])[0] in ('yes', 'true', 'on', '1', 'tmpfs')
    return protege and any(sous(chemin, h) for h in HOME)


@pytest.mark.parametrize('nom', sorted(DEMONS))
def test_chemin_de_configuration_visible(nom):
    fichier, couches, prefixes = DEMONS[nom]
    unite = valeurs_unite(fichier)
    for section, cle, chemin in chemins_lus(couches, prefixes):
        assert not masque(chemin, unite), (nom, section, cle, chemin)


def test_pollux_lit_authorized_keys_hors_home():
    fichier, couches, prefixes = DEMONS['pollux']
    chemins = {c for _, _, c in chemins_lus(couches, prefixes)}
    assert '/var/lib/paresia-app/.ssh/authorized_keys' in chemins
    unite = valeurs_unite(fichier)
    assert unite['ProtectHome'] == ['yes']
    assert 'BindReadOnlyPaths' not in unite


def test_le_controle_detecte_le_masquage():
    assert masque('/home/app/.ssh/authorized_keys', {'ProtectHome': ['yes']})
    assert masque('/home/app/x', {'ProtectHome': ['tmpfs']})
    assert masque('/etc/x', {'InaccessiblePaths': ['/etc']})
    assert not masque('/home/app/.ssh/authorized_keys', {'ProtectHome': ['tmpfs'],
                      'BindReadOnlyPaths': ['-/home/app/.ssh/authorized_keys']})
    assert not masque('/etc/paresia/x', {'ProtectHome': ['yes'], 'ProtectSystem': ['strict']})


def test_aucun_repertoire_personnel_sous_home():
    for dossier in (DEPLOY, CONF):
        for fichier in dossier.rglob('*'):
            if fichier.is_file():
                assert not re.search(r'/home/[A-Za-z0-9._-]+', fichier.read_text()), fichier


@pytest.mark.parametrize('demon', sorted(DEMONS))
def test_unite_type_notify(demon):
    """sd_notify(3), systemd.service(5) : Type=notify, seul le processus principal notifie, aucun chien de garde."""
    valeurs = valeurs_unite(DEMONS[demon][0])
    assert valeurs['Type'] == ['notify']
    assert valeurs['NotifyAccess'] == ['main']
    assert valeurs['RestartPreventExitStatus'] == ['64', '65', '78']
    assert 'WatchdogSec' not in valeurs
    assert re.fullmatch(r'[0-9]+', valeurs['TimeoutStartSec'][0])
    # Les sockets Unix de la notification sont déjà permises par RestrictAddressFamilies=AF_UNIX.
    assert valeurs['RestrictAddressFamilies'] == ['AF_UNIX']
    assert 'ReadWritePaths' not in valeurs or demon == 'remus'


@pytest.mark.parametrize('demon', sorted(DEMONS))
def test_exemples_journal_et_metriques(demon):
    config = configparser.ConfigParser(interpolation=None)
    for f in DEMONS[demon][1]:
        config.read(f, encoding='utf-8')
    assert config.get(demon + '.journal', 'niveau') == 'info'
    assert config.get(demon + '.metriques', 'actif') == 'false'


@pytest.mark.parametrize('demon', sorted(DEMONS))
def test_unite_dossier_etat(demon):
    """systemd.exec(5) : StateDirectory= reste inscriptible sous ProtectSystem=strict ; aucun ReadWritePaths= pour lui."""
    chemin = DEMONS[demon][0]
    valeurs = valeurs_unite(chemin)
    assert valeurs['StateDirectory'] == ['paresia-' + demon]
    assert valeurs['StateDirectoryMode'] == ['0711']
    assert valeurs['ProtectSystem'] == ['strict'] and valeurs['ProtectHome'] == ['yes']
    assert not [v for v in valeurs.get('ReadWritePaths', []) if 'paresia-' + demon in v]
    brut = re.sub(r'(?m)^\s*#.*$', '', chemin.read_text(encoding='utf-8'))
    assert '/home' not in brut and 'node_exporter' not in brut.lower()


@pytest.mark.parametrize('demon', sorted(DEMONS))
def test_metriques_inactives_par_defaut(demon):
    for fichier in DEMONS[demon][1]:
        config = configparser.ConfigParser(interpolation=None)
        config.read(fichier, encoding='utf-8')
        if config.has_section(demon + '.metriques'):
            assert config.get(demon + '.metriques', 'actif') == 'false', fichier


def test_unite_nisaba_dossier_etat():
    unites = sorted(DEPLOY.rglob('nisaba.service'))
    if not unites:
        pytest.skip('nisaba.service non livrée : garde en attente')
    for unite in unites:
        valeurs = valeurs_unite(unite)
        assert valeurs['StateDirectory'] == ['paresia-nisaba']
        assert int(valeurs['StateDirectoryMode'][0], 8) & 0o077 <= 0o011
        assert not [v for v in valeurs.get('ReadWritePaths', []) if 'paresia-nisaba' in v]
