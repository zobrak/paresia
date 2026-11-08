# Tests de l'installation de Pollux et de Romulus (T016, D40 à D44, D66) : unités systemd, sockets,
# groupes, identifiants, configuration en couches, bloc sshd et procédure pas à pas.
# Hors ligne : aucun root, aucun systemd ni sshd réel (systemd-analyze verify seulement s'il existe).
# Dépendances : bibliothèque standard, pytest.
# SPDX-License-Identifier: AGPL-3.0-or-later
# Suivi des versions
#   0.1.19  2026-11-08  Dépendance faible des services envers le tunnel.
#   0.1.8  2026-11-07  Déclarations posées par le banc, la procédure et le script.
#   0.1.8  2026-11-07  Schéma de Romulus assemblé à partir des déclarations livrées.
#   0.1.1  2026-11-07  Lecture de l'exemple avec les sections journal et métriques du socle.
#   3.0.0-alpha.42  2026-11-07  Exception de lecture du fichier de confiance de Pollux.
#   3.0.0-alpha.29  2026-11-06  Première version (T016).
#   3.0.0-alpha.39  2026-11-06  T036 : nom en minuscules de la procédure, C39.
#   3.0.0-alpha  2026-11-06  Sauvegardes par l'outil (C36, D83, D103) : assertions sur les extraits remplacés ; procédure de sauvegarde contrôlée comme celle du relais.
#   3.0.0-alpha.40  2026-11-06  Cycle de correction 2 de T032 : appel de l'outil gardé par PYTHONPATH.
#   3.0.0-alpha.41  2026-11-06  Cycle de correction 3 de T032 : copie root de server/ avant l'outil (D114).
#   0.1.0  2026-11-07  Comptes hors /home et paramètres sans invite ; Contrôles en sous-shell, refus du répertoire de app non conforme et retour arrière borné.
#   0.1.0  2026-11-07  Source des assertions : le script installer-backend-admin.sh (les assertions de fond sont conservées).
import ipaddress
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from server.commun.config import lire
from server.pollux import SCHEMA as SCHEMA_POLLUX
from server.pollux.session import SCHEMA as SCHEMA_SESSION
from romulus_outils import schema_romulus

RACINE = Path(__file__).resolve().parents[1]
DEPLOY = RACINE / 'deploy' / 'backend-admin'
UNITES = DEPLOY / 'etc' / 'systemd' / 'system'
BASE = RACINE / 'server' / 'conf' / 'paresia.conf'
SURCHARGE = DEPLOY / 'etc' / 'paresia' / 'conf.d' / '10-backend-admin.conf'
SSHD = DEPLOY / 'etc' / 'ssh' / 'sshd_config.d' / '50-paresia-app.conf'
PROCEDURE = DEPLOY / 'installer-backend-admin.sh'
ESSAI = RACINE / 'deploy' / 'essai-presence.md'
FICHIERS = [UNITES / 'pollux.service', UNITES / 'romulus.service', SURCHARGE, SSHD, PROCEDURE]

# Identifiants de D42.
COMPTES = {'paresia-pollux': 980, 'paresia-romulus': 981, 'paresia-tunnel': 982, 'app': 983}
GROUPES = {'paresia-sessions': 984, 'paresia-liaison': 985, 'paresia-http': 986}
WWW_DATA = 33

DOSSIERS = {'pollux': 'paresia-pollux', 'romulus': 'paresia-romulus'}
COMPTE_UNITE = {'pollux': 'paresia-pollux', 'romulus': 'paresia-romulus'}

ISOLATION = {
    'LimitCORE': '0', 'NoNewPrivileges': 'yes', 'CapabilityBoundingSet': '', 'AmbientCapabilities': '',
    'ProtectSystem': 'strict', 'ProtectHome': 'yes', 'PrivateTmp': 'yes', 'PrivateDevices': 'yes',
    'ProtectKernelTunables': 'yes', 'ProtectKernelModules': 'yes', 'ProtectKernelLogs': 'yes',
    'ProtectControlGroups': 'yes', 'ProtectClock': 'yes', 'ProtectHostname': 'yes',
    'ProtectProc': 'invisible', 'RestrictAddressFamilies': 'AF_UNIX', 'RestrictNamespaces': 'yes',
    'RestrictRealtime': 'yes', 'RestrictSUIDSGID': 'yes', 'LockPersonality': 'yes',
    'SystemCallArchitectures': 'native', 'SystemCallFilter': '@system-service',
}


def unite(nom):
    """{section: [(clé, valeur), ...]} : clés répétables, commentaires ignorés."""
    sections, courante = {}, None
    for ligne in (UNITES / f'{nom}.service').read_text(encoding='utf-8').splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith('#'):
            continue
        if ligne.startswith('[') and ligne.endswith(']'):
            courante = sections.setdefault(ligne[1:-1], [])
            continue
        cle, separateur, valeur = ligne.partition('=')
        assert separateur and courante is not None, ligne
        courante.append((cle.strip(), valeur.strip()))
    return sections


def valeurs(nom, cle):
    return [v for k, v in unite(nom)['Service'] if k == cle]


def une(nom, cle):
    trouvees = valeurs(nom, cle)
    assert len(trouvees) == 1, (nom, cle, trouvees)
    return trouvees[0]


def lire_ini(chemin):
    import configparser
    ini = configparser.ConfigParser(interpolation=None, strict=True)
    ini.read_string(chemin.read_text(encoding='utf-8'))
    return ini


def configuration_fusionnee():
    base, surcharge = lire_ini(BASE), lire_ini(SURCHARGE)
    fusion = {}
    for ini in (base, surcharge):
        for section in ini.sections():
            fusion.setdefault(section, {}).update(ini[section])
    return fusion


@pytest.mark.parametrize('nom', ['pollux', 'romulus'])
def test_unites_forme(nom):
    sections = unite(nom)
    assert set(sections) == {'Unit', 'Service', 'Install'}
    assert une(nom, 'Type') == 'notify'
    assert une(nom, 'Restart') == 'on-failure' and une(nom, 'RestartSec') == '5'
    assert une(nom, 'User') == COMPTE_UNITE[nom] and une(nom, 'Group') == COMPTE_UNITE[nom]
    assert une(nom, 'RuntimeDirectory') == DOSSIERS[nom]
    assert une(nom, 'RuntimeDirectoryMode') == '0711'
    assert une(nom, 'Environment') == 'PYTHONPATH=/usr/local/lib/paresia'
    assert une(nom, 'ConfigurationDirectory') == 'paresia::ro'
    assert une(nom, 'ConfigurationDirectoryMode') == '0755'
    assert une(nom, 'UMask') == '0077'
    exec_start = une(nom, 'ExecStart')
    assert exec_start == f'/usr/bin/python3 -P -s -B -m server.{nom}'
    assert '--config' not in exec_start and not re.search(r'sh -c|;|&&|\|', exec_start)
    texte = (UNITES / f'{nom}.service').read_text(encoding='utf-8')
    assert 'PARESIA_' not in re.sub(r'(?m)^\s*#.*$', '', texte)
    assert 'WantedBy=multi-user.target' in texte and sections['Install'] == [('WantedBy', 'multi-user.target')]
    assert 'ReadWritePaths' not in texte
    assert [(cle, valeur) for cle, valeur in sections['Unit'] if cle != 'Description'] == [
        ('Wants', 'paresia-tunnel.service'), ('After', 'paresia-tunnel.service')]
    assert not any(cle in dict(sections['Unit']) for cle in ('Requires', 'BindsTo', 'Before'))
    assert 'D9' in texte.split('[Unit]')[0]
    assert une('pollux', 'RuntimeDirectory') != une('romulus', 'RuntimeDirectory')


@pytest.mark.parametrize('nom', ['pollux', 'romulus'])
def test_unites_isolation(nom):
    for cle, attendu in ISOLATION.items():
        assert valeurs(nom, cle) == [attendu], (nom, cle)
    assert valeurs(nom, 'BindReadOnlyPaths') == []
    assert not valeurs(nom, 'MemoryDenyWriteExecute')
    assert 'MemoryDenyWriteExecute' in (UNITES / f'{nom}.service').read_text(encoding='utf-8')
    assert valeurs(nom, 'MemorySwapMax') == (['0'] if nom == 'romulus' else [])
    assert valeurs(nom, 'TimeoutStopSec') == (['180'] if nom == 'pollux' else [])


def test_unites_verify(tmp_path):
    outil = shutil.which('systemd-analyze')
    if outil is None:
        pytest.skip('systemd-analyze absent : vérification des unités ignorée')
    resultat = subprocess.run(
        [outil, 'verify', str(UNITES / 'pollux.service'), str(UNITES / 'romulus.service')],
        capture_output=True, text=True, cwd=tmp_path, timeout=60)
    erreurs = [ligne for ligne in resultat.stderr.splitlines() + resultat.stdout.splitlines()
               if ('pollux.service' in ligne or 'romulus.service' in ligne)]
    assert not erreurs, erreurs


def test_aucun_run_paresia_partage():
    for chemin in [BASE, SURCHARGE, PROCEDURE, *UNITES.glob('*.service')]:
        assert '/run/paresia/' not in chemin.read_text(encoding='utf-8'), chemin.name


def test_sockets_coherents():
    fusion = configuration_fusionnee()
    attendu_pollux = {
        ('pollux.sessions', 'pollux.sock'), ('pollux.relay', 'pollux-relay.sock')}
    # Sockets créées par chaque démon : dans le RuntimeDirectory de son unité.
    for section, fichier in attendu_pollux:
        assert fusion[section]['socket'] == f'/run/paresia-pollux/{fichier}'
    assert fusion['romulus.presence']['socket'] == '/run/paresia-romulus/romulus.sock'
    assert fusion['romulus.http']['socket'] == '/run/paresia-romulus/romulus-http.sock'
    # Sockets jointes.
    assert fusion['pollux.romulus']['socket'] == fusion['romulus.presence']['socket']
    assert fusion['pollux-session.transport']['socket'] == fusion['pollux.sessions']['socket']
    assert fusion['pollux-session.auth']['authorized_keys'] == '/var/lib/paresia-app/.ssh/authorized_keys'
    assert fusion['pollux.castor']['socket'] == '/run/paresia-tunnel/pollux/castor.sock'
    # Un chemin hors des deux dossiers : celui de Castor seulement.
    chemins = [v for s, o in fusion.items() for k, v in o.items()
               if k == 'socket' and s.split('.')[0] in {'pollux', 'pollux-session', 'romulus'}]
    dehors = [c for c in chemins if not c.startswith(('/run/paresia-pollux/', '/run/paresia-romulus/'))]
    assert dehors == ['/run/paresia-tunnel/pollux/castor.sock']
    # Le dossier d'exécution de chaque unité contient les sockets que le démon y crée.
    for nom, sections in {'pollux': ['pollux.sessions', 'pollux.relay'],
                          'romulus': ['romulus.presence', 'romulus.http']}.items():
        dossier = '/run/' + une(nom, 'RuntimeDirectory') + '/'
        assert all(fusion[s]['socket'].startswith(dossier) for s in sections)
    # La procédure contrôle les mêmes chemins.
    procedure = PROCEDURE.read_text(encoding='utf-8')
    for chemin in ('/run/paresia-pollux/pollux.sock', '/run/paresia-pollux/pollux-relay.sock',
                   '/run/paresia-romulus/romulus.sock', '/run/paresia-romulus/romulus-http.sock'):
        assert chemin in procedure


def test_groupes_supplementaires():
    fusion = configuration_fusionnee()
    gid_nom = {v: k for k, v in GROUPES.items()}
    # Sockets créées (chown) et jointes (connexion) par chaque démon : groupe attendu (D41).
    groupe_socket = {
        'pollux.sessions': GROUPES['paresia-sessions'], 'pollux.relay': GROUPES['paresia-liaison'],
        'romulus.presence': GROUPES['paresia-liaison'], 'romulus.http': GROUPES['paresia-http']}
    for section, gid in groupe_socket.items():
        assert int(fusion[section]['gid']) == gid
    creees = {'pollux': {'pollux.sessions', 'pollux.relay'}, 'romulus': {'romulus.presence', 'romulus.http'}}
    jointes = {'pollux': {'romulus.presence'}, 'romulus': {'pollux.relay'}}
    for nom in ('pollux', 'romulus'):
        voulus = {gid_nom[groupe_socket[s]] for s in creees[nom] | jointes[nom]}
        assert set(une(nom, 'SupplementaryGroups').split()) == voulus, nom
    # Le tableau D41 : le client de chaque socket est dans le groupe de la socket (uid admis).
    assert int(fusion['pollux.sessions']['uid']) == COMPTES['app']
    assert int(fusion['pollux.relay']['uid']) == COMPTES['paresia-romulus']
    assert int(fusion['romulus.presence']['uid_pollux']) == COMPTES['paresia-pollux']
    assert int(fusion['romulus.http']['uid_lighttpd']) == WWW_DATA


def copie_installee(tmp_path):
    """Copie de la base et de la surcharge aux modes de l'installation (D43)."""
    racine = tmp_path / 'etc-paresia'
    (racine / 'conf.d').mkdir(parents=True)
    shutil.copy(BASE, racine / 'paresia.conf')
    shutil.copy(SURCHARGE, racine / 'conf.d' / '10-backend-admin.conf')
    os.chmod(racine, 0o755)
    os.chmod(racine / 'conf.d', 0o755)
    os.chmod(racine / 'paresia.conf', 0o644)
    os.chmod(racine / 'conf.d' / '10-backend-admin.conf', 0o644)
    return racine


def test_configuration_installation(tmp_path):
    racine = copie_installee(tmp_path)
    pollux = lire('pollux', SCHEMA_POLLUX, journal=True, metriques=True, argv=[], environ={}, racine_systeme=racine)
    session = lire('pollux-session', SCHEMA_SESSION, argv=[], environnement=False, racine_systeme=racine)
    romulus = lire('romulus', schema_romulus(), journal=True, metriques=True, argv=[], environ={}, racine_systeme=racine)
    assert (pollux['sessions']['uid'], pollux['sessions']['gid']) == (983, 984)
    assert (pollux['relay']['uid'], pollux['relay']['gid']) == (981, 985)
    assert pollux['romulus']['uid'] == 981 and pollux['castor']['uid'] == 982
    assert (romulus['presence']['uid_pollux'], romulus['presence']['gid']) == (980, 985)
    assert (romulus['http']['uid_lighttpd'], romulus['http']['gid']) == (33, 986)
    assert session['transport']['socket'] == '/run/paresia-pollux/pollux.sock'
    assert session['auth']['authorized_keys'] == '/var/lib/paresia-app/.ssh/authorized_keys'


def tables_script():
    """(groupes, comptes) lus dans les tables du script : [noms], {nom: (home, shell)} ; aucun numéro."""
    texte = PROCEDURE.read_text(encoding='utf-8')
    groupes = re.search(r'(?m)^    TABLE_GROUPES=\((.*?)\)\n', texte, re.S).group(1)
    comptes = re.search(r'(?m)^    TABLE_COMPTES=\((.*?)\)\n', texte, re.S).group(1)
    assert not re.search(r'\d', groupes), groupes
    assert not re.search(r'\d', comptes), comptes
    return groupes.split(), {nom: (home, shell) for nom, home, shell in re.findall(r'"([\w-]+) (\S+) (\S+)"', comptes)}


def test_identifiants_coherents():
    procedure = PROCEDURE.read_text(encoding='utf-8')
    groupes, comptes = tables_script()
    assert set(comptes) == set(COMPTES) and set(groupes) == set(GROUPES) | set(COMPTES)
    assert comptes['app'] == ('$REPERTOIRE_APP', '/bin/sh')
    assert [c for n, c in comptes.items() if n != 'app'] == [('/nonexistent', '/usr/sbin/nologin')] * 3
    # les groupes sont créés avant les comptes (creer_comptes), sans mot de passe, sans répertoire créé
    corps = re.search(r'(?ms)^creer_comptes\(\) \{.*?^\}', procedure + _comptes_communs()).group()
    assert corps.index('creer_groupe "$nom"') < corps.index('creer_compte "$nom"')
    ligne = re.search(r'sudo /usr/sbin/useradd [^\n]*', _comptes_communs()).group()
    assert '--no-create-home' in ligne and ligne.count('--home-dir ') == 1 and '--password' not in ligne
    assert '--uid' not in ligne and '--gid "$1"' in ligne and '--system' in ligne
    assert 'sudo /usr/sbin/groupadd --system "$1"' in _comptes_communs()
    assert 'www-data:33' in procedure and 'useradd(8)' in procedure and 'adduser(8)' in procedure
    assert 'usermod -aG paresia-sessions app' in procedure and 'usermod -aG paresia-http www-data' in procedure
    assert not re.search(r'usermod -G', procedure)
    # aucun numéro de la plage d'exemple dans les tables ni dans les contrôles du script
    assert not re.search(r'\b98[0-6]\b', procedure)
    # Les noms des unités sont ceux des comptes de la procédure ; les numéros d'exemple viennent de la surcharge livrée.
    for nom in ('pollux', 'romulus'):
        assert une(nom, 'User') in COMPTES and une(nom, 'Group') in COMPTES
        assert set(une(nom, 'SupplementaryGroups').split()) <= set(GROUPES)
    fusion = lire_ini(SURCHARGE)
    valeurs_surcharge = {int(v) for s in fusion.sections() for k, v in fusion[s].items()}
    assert valeurs_surcharge == {980, 981, 982, 983, 984, 985, WWW_DATA, 986}


def _comptes_communs():
    """Fonctions communes de création des comptes (même texte dans les deux scripts)."""
    return PROCEDURE.read_text(encoding='utf-8')


# Mots-clés admis dans le bloc Match (liste fermée) et hors du bloc, selon sshd_config(5).
MOTS_MATCH = {'ExposeAuthInfo': 'yes', 'ClientAliveInterval': '15', 'ClientAliveCountMax': '3',
              'PasswordAuthentication': 'no', 'AuthenticationMethods': 'publickey'}
MOTS_GLOBAUX = {'StrictModes': 'yes', 'PermitUserEnvironment': 'no'}


def test_sshd_app():
    lignes = [l.strip() for l in SSHD.read_text(encoding='utf-8').splitlines()
              if l.strip() and not l.strip().startswith('#')]
    index = lignes.index('Match User app')
    hors, dans = lignes[:index], lignes[index + 1:]
    assert dict(l.split(None, 1) for l in hors) == MOTS_GLOBAUX
    assert dict(l.split(None, 1) for l in dans) == MOTS_MATCH
    assert len(dans) == len(MOTS_MATCH) and lignes.count('Match User app') == 1
    assert not any(l.lower().startswith(('acceptenv', 'setenv', 'forcecommand')) for l in lignes)
    procedure = PROCEDURE.read_text(encoding='utf-8')
    assert 'restrict,command="/usr/local/bin/pollux-session"' in ESSAI.read_text(encoding='utf-8')
    assert 'AcceptEnv' in procedure and 'LC_*' in procedure


def fonctions(texte):
    """{nom: corps} des fonctions du script."""
    return {m.group(1): m.group(0) for m in re.finditer(r'(?ms)^(\w+)\(\) \{(?:[^\n]*\}$|[^\n]*\n.*?^\})', texte)}


RISQUE = re.compile(
    r'(?m)(^\s*|[;&|(]\s*|\bdo\s+|\bthen\s+)(?:sudo /usr/s?bin/)?(rm |rmdir |userdel |groupdel |useradd |groupadd |usermod |gpasswd |'
    r'chown -R |install (?!-d)|mv |sed -i |systemctl (start|stop|restart|reload|enable|disable)\b|'
    r'cp -p |tar )')


def test_procedure_avertissements():
    procedure = PROCEDURE.read_text(encoding='utf-8')
    risques = 0
    for m in re.finditer(r'(?ms)^(\w+)\(\) \{(?:[^\n]*\}$|[^\n]*\n.*?^\})', procedure):
        nom, corps = m.group(1), m.group(0)
        commentaire = procedure[:m.start()].rstrip('\n').rsplit('\n\n', 1)[-1]    # bloc de commentaires qui précède la fonction
        if RISQUE.search(corps) and nom not in ('poser_fichier', 'copier_code_outil'):
            risques += 1
            assert '# ATTENTION :' in commentaire + corps, nom
    assert risques >= 8
    # Avertissements nommés : reload ssh, chown -R, userdel, groupdel, rmdir, rm -r.
    for mot in ('systemctl reload ssh', 'chown -R', 'userdel', 'groupdel', 'rmdir', 'rm -r retire'):
        assert mot in procedure
    assert re.search(r'ATTENTION[^\n]*Pollux ou Romulus[^\n]*sessions de présence', procedure)
    assert re.search(r'ATTENTION[^\n]*sauvegarde', procedure) and 'SESSION_SECOURS' in procedure
    # Nul `rm -rf` dans les commandes du script.
    assert not re.search(r'(?m)^[^#\n]*rm -rf', procedure)


def test_procedure_sauvegardes():
    procedure = PROCEDURE.read_text(encoding='utf-8')
    assert 'dossier=$(outil_q jeu)' in procedure
    assert 'PYTHONPATH=/run/paresia-installation' in procedure and 'export PYTHONPATH' not in procedure
    assert 'outil() { sudo /usr/bin/env PYTHONPATH=/run/paresia-installation' in procedure
    assert '.bak-' not in procedure and '$SAUVEGARDE' not in procedure
    assert 'python3 -m server.sauvegarde' not in procedure
    for ligne in procedure.splitlines():
        if re.search(r' > .*avant| > .*apres| > .*initial', ligne) or 'cp -p' in ligne:
            assert 'outil' in ligne or 'releve' in ligne
    # D114 : copie root de server/ avant le premier appel de l'outil, aucun contrôle du clone
    copie = fonctions(procedure)['copier_code_outil']
    assert 'install -d -o root -g root -m 0700 "$TRAVAIL"' in copie and 'install -o root -g root -m 0644 --' in copie
    assert 'find "$DEPOT/server" ! -type d ! -type f -print -quit' in copie
    assert "stat -c '%u' -- \"$DEPOT\"" not in procedure
    assert fonctions(procedure)['jeu_pret'].index('copier_code_outil') < fonctions(procedure)['jeu_pret'].index('outil_q jeu')
    # chaque commande privilégiée garde son sudo ; aucun shell root
    for ligne in procedure.splitlines():
        ligne = ligne.strip()
        assert not re.match(r'(?:systemctl(?! --version)|journalctl|runuser|install|groupadd|useradd|usermod|userdel|groupdel)\b', ligne), ligne
        assert not re.search(r'sudo\s+(-i|-s|su\b|sh\b|bash\b)|sudo[^\n|]*\b(sh|bash)\s+-c', ligne), ligne


def test_procedure_etapes():
    procedure = PROCEDURE.read_text(encoding='utf-8')
    construction = procedure[procedure.index('    ETAPES=(prerequis'):procedure.index('fin_machine() {')]
    noms = re.findall(r'\b[a-z_]+\b', construction.split('ETAPES+=(tunnel_client')[0].split('ETAPES=(')[1].split(')')[0])
    assert noms == ['prerequis', 'sauvegarde', 'identifiants_comptes', 'appartenances', 'dossier_app', 'code',
                    'configuration', 'web', 'sshd_app', 'unites', 'demarrage', 'refus', 'tunnel_releves', 'tunnel_cle']
    assert 'ETAPES+=(tunnel_client tunnel_known_hosts tunnel_unite tunnel_sockets)' in construction
    fonc = fonctions(procedure)
    for nom in noms + ['tunnel_client', 'tunnel_known_hosts', 'tunnel_unite', 'tunnel_sockets', 'activation']:
        assert f'etape_{nom}' in fonc or f'etape_{nom}()' in procedure, nom
        assert f'deja_conforme_{nom}()' in procedure and f'verifier_{nom}()' in procedure, nom
    # Démarrage dans l'ordre Romulus puis Pollux, sans enable avant l'activation.
    demarrage = fonc['etape_demarrage']
    assert demarrage.index('systemctl start romulus.service') < demarrage.index('systemctl start pollux.service')
    assert [n for n, c in fonc.items() if 'systemctl enable' in c] == ['etape_activation']
    assert 'systemd-analyze verify pollux.service romulus.service' in procedure
    assert 'token_missing' in procedure and '405' in procedure


def test_procedure_droits():
    procedure = PROCEDURE.read_text(encoding='utf-8')
    attendu = [
        'install -d -m 0755 -o root -g root "$REPERTOIRE_APP" "$REPERTOIRE_APP/.ssh"',
        'install -m 0644 -o root -g root /dev/null "$REPERTOIRE_APP/.ssh/authorized_keys"',
        'install -d -m 0755 -o root -g root /usr/local/lib/paresia',
        'chown -R root:root /usr/local/lib/paresia/server',
        'find /usr/local/lib/paresia/server -type d -exec /usr/bin/chmod 0755 {} +',
        'find /usr/local/lib/paresia/server -type f -exec /usr/bin/chmod 0644 {} +',
        'install -m 0755 -o root -g root "$DEPOT/server/bin/pollux-session" /usr/local/bin/pollux-session',
        'install -d -m 0755 -o root -g root /etc/paresia /etc/paresia/conf.d',
        '/etc/paresia/paresia.conf',
        'poser_fichier "$DEPOT/server/conf/paresia.conf" "$CONF_BASE" 0644',
        'sudo /usr/bin/install -m "$3" -o root -g root "$1" "$2"',
        '/etc/paresia/conf.d/10-backend-admin.conf',
    ]
    for ligne in attendu:
        assert ligne in procedure, ligne
    # Aucun mode installé n'est inscriptible par groupe ou autres.
    for mode in re.findall(r'(?:install|chmod)(?: -[dm])* ?-?m? ?(?:-d )?0?([0-7]{3,4})\b', procedure):
        assert int(mode, 8) & 0o022 == 0, mode
    assert '--exclude=\'server/conf\'' in procedure
    assert 'sauvegarder_arbre' in procedure and 'outil_q copier' in procedure and 'bak-' not in procedure
    # Les fichiers livrés n'accordent rien à un compte de service sur /etc/paresia.
    for nom in ('pollux', 'romulus'):
        assert une(nom, 'ConfigurationDirectoryMode') == '0755'


@pytest.fixture
def faux_admin(tmp_path_factory):
    from tests.outils.installation_factice import Faux, copier_modele
    modele = tmp_path_factory.mktemp('modele')
    copier_modele(modele)
    return Faux(tmp_path_factory.mktemp('admin'), modele, 'admin')


def test_repertoire_app_non_conforme_refuse(faux_admin):
    procedure = PROCEDURE.read_text(encoding='utf-8')
    assert 'REPERTOIRE_APP="${REPERTOIRE_APP:-/var/lib/paresia-app}"' in procedure
    assert "# la configuration livrée désigne ce chemin" in procedure
    avant = faux_admin.arbre()
    resultat = faux_admin.lancer('--repertoire-app', '/var/lib/autre')
    assert resultat.returncode == 65 and 'REPERTOIRE_APP' in resultat.stderr
    assert faux_admin.arbre() == avant and faux_admin.appels() == []


@pytest.mark.parametrize(('repertoire', 'code'), [(None, 0), ('', 64), ('/', 65), ('/var/lib/paresia-app', 0),
                                                  ('/var/lib/paresia-app/', 0), ('/var/../ho' + 'me/app', 65)])
def test_repertoire_app_borne_pour_releve_et_retour(faux_admin, repertoire, code):
    options = [] if repertoire is None else ['--repertoire-app', repertoire]
    assert faux_admin.lancer('--verifier', *options).returncode == code


def test_restauration_en_echec_arrete_le_retour():
    """`restaurer` s'arrête au premier code 5 de l'outil : rien d'autre n'est lancé ensuite."""
    definition = re.search(r'(?ms)^restaurer\(\) \{.*?^\}', PROCEDURE.read_text(encoding='utf-8')).group()
    script = ('set -euo pipefail\nsudo() { printf "commande interdite\\n"; }\n'
              'outil_q() { return 5; }\nJEU=essai\n' + definition + '\nrestaurer /x\nprintf "suite\\n"\n')
    resultat = subprocess.run(['bash', '--noprofile', '--norc'], input=script, env={'PATH': '/usr/bin:/bin'},
                              capture_output=True, text=True, timeout=10)
    assert resultat.returncode == 5 and 'suite' not in resultat.stdout and 'interdite' not in resultat.stdout


ADRESSES_DOC = [ipaddress.ip_network(r) for r in ('192.0.2.0/24', '198.51.100.0/24', '203.0.113.0/24')]
MOTIFS_SECRETS = [r'nsec1[02-9ac-hj-np-z]{20,}', r'ncryptsec1', r'-----BEGIN [A-Z ]*PRIVATE KEY-----',
                  r'gh[pousr]_[A-Za-z0-9]{20,}', r'sk-[A-Za-z0-9_-]{20,}',
                  r'ssh-(ed25519|rsa) AAAA[A-Za-z0-9+/=]{20,}']


def test_aucun_secret_ni_donnee_reelle():
    for chemin in FICHIERS + [BASE]:
        texte = chemin.read_text(encoding='utf-8')
        for motif in MOTIFS_SECRETS:
            assert not re.search(motif, texte), (chemin.name, motif)
        for adresse in re.findall(r'\b\d{1,3}(?:\.\d{1,3}){3}\b', texte):
            ip = ipaddress.ip_address(adresse)
            assert ip.is_loopback or ip.is_unspecified or any(ip in r for r in ADRESSES_DOC), (chemin.name, adresse)
        assert not re.search(r'(?i)' + 'clau' + 'de' + r'\.ai|' + 'lap' + 'top|' + 'home' + 'lab|' + 'opn' + 'sense', texte), chemin.name
    # Les noms d'hôte de la procédure sont génériques.
    procedure = PROCEDURE.read_text(encoding='utf-8')
    for hote in re.findall(r'host=([A-Za-z0-9.-]+)', procedure):
        assert hote.endswith('.example.org'), hote


NOMS_DECLARATIONS = ['paresia-yang-bunkerd', 'paresia-yang-journal-legal', 'paresia-yang-nisaba', 'paresia-yang-strfry', 'paresia-yang-webui']
DOSSIER_DECLARATIONS = '/usr/local/lib/paresia/romulus/services'
BANC = RACINE / 'tests' / 'banc' / 'admin.containerfile'
MANUEL_PROCEDURE = DEPLOY / 'installation-pollux-romulus.md'


def test_declarations_posees_par_banc_procedure_et_script():
    """Sans les déclarations, Romulus sort en code 78 : banc, procédure et script les posent."""
    livrees = sorted(p.name for p in (DEPLOY / 'usr/local/lib/paresia/romulus/services').glob('*.toml'))
    assert livrees == [n + '.toml' for n in NOMS_DECLARATIONS]
    banc = BANC.read_text(encoding='utf-8')
    assert f'/usr/local/lib/paresia/romulus {DOSSIER_DECLARATIONS}' in banc
    assert re.search(r'install -d -o root -g root -m 0755 [^\n]*' + re.escape(DOSSIER_DECLARATIONS), banc)
    copies = [ligne for ligne in banc.splitlines() if ligne.startswith('COPY --chmod=0644 ') and ligne.endswith(f' {DOSSIER_DECLARATIONS}/')]
    assert len(copies) == 1
    for nom in NOMS_DECLARATIONS:
        assert f'deploy/backend-admin/usr/local/lib/paresia/romulus/services/{nom}.toml' in copies[0]
    manuel = MANUEL_PROCEDURE.read_text(encoding='utf-8')
    etape = manuel.split('## Étape 7 bis', 1)[1].split('## Étape 8', 1)[0]
    for nom in NOMS_DECLARATIONS:
        assert nom in etape
    assert f'install -d -m 0755 -o root -g root /usr/local/lib/paresia /usr/local/lib/paresia/romulus "$D"' in etape
    assert 'install -m 0644 -o root -g root "$S/$n.toml" "$D/$n.toml"' in etape
    assert etape.index('outil copier --si-absent') < etape.index('install -m 0644')
    assert manuel.index('## Étape 7 bis') < manuel.index('## Étape 10')
    script = PROCEDURE.read_text(encoding='utf-8')
    assert 'DECLARATIONS_DEPOT=deploy/backend-admin/usr/local/lib/paresia/romulus/services' in script
    assert f'DECLARATIONS_DOSSIER={DOSSIER_DECLARATIONS}' in script
    assert "find \"$DEPOT/$DECLARATIONS_DEPOT\" -maxdepth 1 -type f -name '*.toml'" in script
    assert 'poser_fichier "$DEPOT/$DECLARATIONS_DEPOT/$nom.toml" "$DECLARATIONS_DOSSIER/$nom.toml" 0644' in script
    assert 'controle_attributs "$DECLARATIONS_DOSSIER/$nom.toml" "root:root 644"' in script
    retour = script.split('pose_complete() {', 1)[1]      # la liste des fichiers posés sert au retour arrière d'une installation et d'une mise à jour
    assert 'lire_declarations' in retour and 'POSE+=("$DECLARATIONS_DOSSIER/$nom.toml")' in retour
    assert f'{DOSSIER_DECLARATIONS} /usr/local/lib/paresia/romulus \\' in script
