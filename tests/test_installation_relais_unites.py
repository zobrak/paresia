# Tests des unités de Castor et de Remus et de la suite de la procédure (T024, D46, D48, D49, D53,
# D65, D81, D84) : forme, isolation (Remus : conforme au tableau d'isolation-remus.md), arrêt,
# sockets et groupes, directives connues des pages de manuel, procédure pas à pas.
# Hors ligne : aucun root, aucun systemd actif (systemd-analyze verify et man seulement s'ils existent).
# Dépendances : bibliothèque standard, pytest.
# SPDX-License-Identifier: AGPL-3.0-or-later
# Suivi des versions
#   0.1.19  2026-11-08  Unité du tunnel sans [Install] et avec PartOf= (T118) ; en-têtes sans numéro de tâche (T117) : D46 attendu.
#   0.1.2  2026-11-07  Seul StateDirectory= admis dans les unités (valeur et mode exacts).
#   0.1.1  2026-11-07  Lecture de l'exemple avec les sections journal et métriques du socle.
#   0.1.1  2026-11-07  Isolation du tunnel par dossiers tmpfiles et groupes ; contrôle des quatre dossiers distincts.
#   3.0.0-alpha.34  2026-11-06  Première version (T024).
#   3.0.0-alpha  2026-11-06  Retours arrière par l'outil de sauvegarde (C36, D83, D103).
#   3.0.0-alpha.40  2026-11-06  Cycle de correction 2 de T032 : garde PYTHONPATH avant les appels de l'outil.
#   0.1.0  2026-11-07  Descriptions du relais strfry et attendus de l'essai local de Castor.
import configparser
import ipaddress
import re
import shlex
import shutil
import subprocess
import unicodedata
from pathlib import Path

import pytest

from server.castor import SCHEMA as SCHEMA_CASTOR
from server.commun.config import lire

RACINE = Path(__file__).resolve().parents[1]
RELAIS = RACINE / 'deploy' / 'backend-relais'
UNITES = RELAIS / 'etc' / 'systemd' / 'system'
TUNNEL = RACINE / 'deploy' / 'backend-admin' / 'etc' / 'systemd' / 'system' / 'paresia-tunnel.service'
CONF = RACINE / 'server' / 'conf' / 'paresia-relais.conf'
PROCEDURE = RELAIS / 'installer-backend-relais.sh'
TABLEAU = RELAIS / 'isolation-remus.md'
CHEMINS = {'castor': UNITES / 'castor.service', 'remus': UNITES / 'remus.service'}
FICHIERS = [*CHEMINS.values(), TUNNEL, PROCEDURE, TABLEAU]

# Isolation de T016 (valeurs de pollux.service).
ISOLATION = {
    'LimitCORE': '0', 'NoNewPrivileges': 'yes', 'CapabilityBoundingSet': '', 'AmbientCapabilities': '',
    'ProtectSystem': 'strict', 'ProtectHome': 'yes', 'PrivateTmp': 'yes', 'PrivateDevices': 'yes',
    'ProtectKernelTunables': 'yes', 'ProtectKernelModules': 'yes', 'ProtectKernelLogs': 'yes',
    'ProtectControlGroups': 'yes', 'ProtectClock': 'yes', 'ProtectHostname': 'yes',
    'ProtectProc': 'invisible', 'RestrictAddressFamilies': 'AF_UNIX', 'RestrictNamespaces': 'yes',
    'RestrictRealtime': 'yes', 'RestrictSUIDSGID': 'yes', 'LockPersonality': 'yes',
    'SystemCallArchitectures': 'native', 'SystemCallFilter': '@system-service',
}
# Directives d'isolation connues (tableau d'isolation-remus.md : ISOLATION et les lignes en plus).
DIRECTIVES_ISOLATION = set(ISOLATION) | {
    'UMask', 'MemoryDenyWriteExecute', 'PrivateUsers', 'ReadWritePaths', 'ReadOnlyPaths', 'DynamicUser'}
GROUPES = {'paresia-castor': 970, 'chef': 971, 'tunnel': 972, 'paresia-castor-tunnel': 973,
           'paresia-remus-tunnel': 974, 'paresia-castor-etat': 975}
COMPTE = {'castor': 'paresia-castor', 'remus': 'chef'}


def texte(chemin):
    return chemin.read_text(encoding='utf-8')


def sans_commentaires(chemin):
    return re.sub(r'(?m)^\s*#.*$', '', texte(chemin))


def analyser(chemin):
    sections, courante = {}, None
    for ligne in texte(chemin).splitlines():
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


def valeurs(chemin, cle, section='Service'):
    return [v for k, v in analyser(chemin)[section] if k == cle]


def une(chemin, cle):
    trouvees = valeurs(chemin, cle)
    assert len(trouvees) == 1, (chemin.name, cle, trouvees)
    return trouvees[0]


def ini():
    c = configparser.ConfigParser(interpolation=None, strict=True)
    c.read_string(texte(CONF))
    return c


def tableau():
    """{directive: (décision, valeur, compensation)} lu dans isolation-remus.md."""
    lignes = [[c.strip() for c in l.strip().strip('|').split('|')]
              for l in texte(TABLEAU).splitlines() if l.startswith('| ')][2:]
    resultat = {}
    for nom, decision, valeur, _citation, compensation in lignes:
        valeur = valeur.strip('`').strip()
        valeur = re.sub(r' \(.*\)$', '', valeur) if not valeur.startswith('absente') else valeur
        resultat[nom] = (decision, valeur, compensation)
    return resultat


@pytest.mark.parametrize(('nom', 'description'), [
    ('remus', 'Paresia : Remus (exécuteur de commandes du relais strfry)'),
    ('castor', 'Paresia : Castor (feu de session du relais strfry)'),
])
def test_description_relais_strfry(nom, description):
    assert valeurs(CHEMINS[nom], 'Description', section='Unit') == [description]


def test_unites_forme():
    for nom, chemin in CHEMINS.items():
        sections = analyser(chemin)
        assert set(sections) == {'Unit', 'Service', 'Install'}
        assert une(chemin, 'Type') == 'notify'
        assert une(chemin, 'Restart') == 'on-failure' and une(chemin, 'RestartSec') == '5'
        assert une(chemin, 'User') == COMPTE[nom] and une(chemin, 'Group') == COMPTE[nom]
        assert une(chemin, 'Environment') == 'PYTHONPATH=/usr/local/lib/paresia'
        assert une(chemin, 'RuntimeDirectory') == f'paresia-{nom}'
        assert une(chemin, 'RuntimeDirectoryMode') == '0711'
        assert une(chemin, 'ConfigurationDirectory') == 'paresia::ro'
        assert une(chemin, 'ConfigurationDirectoryMode') == '0755'
        assert une(chemin, 'UMask') == '0077'
        exec_start = une(chemin, 'ExecStart')
        assert exec_start == f'/usr/bin/python3 -P -s -B -m server.{nom}'
        assert not re.search(r'sh -c|;|&&|\||--config', exec_start)
        assert 'PARESIA_' not in sans_commentaires(chemin)
        assert sections['Install'] == [('WantedBy', 'multi-user.target')]
        en_tete = texte(chemin).split('[Unit]')[0]
        assert 'SPDX-License-Identifier: AGPL-3.0-or-later' in en_tete and 'D46' in en_tete
        assert 'deploy/backend-relais/installer-backend-relais.sh' in en_tete and f'{nom}(8)' in en_tete
    assert 'TOUS les feux au rouge' in texte(CHEMINS['castor'])
    assert 'JAMAIS une' in texte(CHEMINS['remus']) and 'D53' in texte(CHEMINS['remus'])


def test_tunnel_forme():
    sections = analyser(TUNNEL)
    assert set(sections) == {'Unit', 'Service'}      # pas de [Install] : le tunnel suit Pollux et Romulus (exigence 8 de T118)
    assert une(TUNNEL, 'User') == 'paresia-tunnel' and une(TUNNEL, 'Group') == 'paresia-tunnel'
    assert une(TUNNEL, 'ExecStart') == '/usr/bin/ssh -F /etc/paresia/tunnel/ssh_config -N paresia-relais'
    assert une(TUNNEL, 'Restart') == 'always' and une(TUNNEL, 'RestartSec') == '5'
    assert une(TUNNEL, 'UMask') == '0077' and not valeurs(TUNNEL, 'ConfigurationDirectory')
    assert not valeurs(TUNNEL, 'TimeoutStopSec')
    assert sections['Unit'] == [('Description', 'Paresia : tunnel SSH vers backend-relais'),
                                ('After', 'network-online.target'), ('Wants', 'network-online.target'),
                                ('PartOf', 'pollux.service romulus.service')]
    assert 'Install' not in sections and not valeurs(TUNNEL, 'WantedBy')
    assert 'PARESIA_' not in sans_commentaires(TUNNEL)
    en_tete = texte(TUNNEL).split('[Unit]')[0]
    assert 'procédure du tunnel' in en_tete and 'tmpfiles.d/paresia-tunnel.conf' in en_tete and 'D8' in en_tete
    assert 'SPDX-License-Identifier: AGPL-3.0-or-later' in en_tete


def test_castor_isolation():
    chemin = CHEMINS['castor']
    for cle, attendu in ISOLATION.items():
        assert valeurs(chemin, cle) == [attendu], cle
    assert not valeurs(chemin, 'MemoryDenyWriteExecute') and not valeurs(chemin, 'ReadWritePaths')
    commentaire = texte(chemin)
    assert 'MemoryDenyWriteExecute' in commentaire and 'D84' in commentaire
    assert 'faute d\'essai réel' in commentaire and 'bibliothèque standard' in commentaire


def test_tunnel_unite_isolation():
    for cle, attendu in ISOLATION.items():
        if cle == 'RestrictAddressFamilies':
            assert valeurs(TUNNEL, cle) == ['AF_UNIX AF_INET AF_INET6']
        else:
            assert valeurs(TUNNEL, cle) == [attendu], cle
    assert valeurs(TUNNEL, 'ReadWritePaths') == [
        '/run/paresia-tunnel/romulus /run/paresia-tunnel/pollux']
    assert not valeurs(TUNNEL, 'MemoryDenyWriteExecute')
    assert 'Dérogation à l\'isolation de pollux.service' in texte(TUNNEL)


def test_remus_isolation_selon_tableau():
    chemin = CHEMINS['remus']
    lignes = tableau()
    assert DIRECTIVES_ISOLATION <= set(lignes)
    commentaires = '\n'.join(l for l in texte(chemin).splitlines() if l.lstrip().startswith('#'))
    presentes = {k for k, _ in analyser(chemin)['Service']} & DIRECTIVES_ISOLATION
    attendues = set()
    for nom, (decision, valeur, _) in lignes.items():
        if valeur.startswith('absente'):
            assert not valeurs(chemin, nom), nom
            assert nom in commentaires, nom
            continue
        attendues.add(nom)
        if decision == 'conservée' and nom in ISOLATION:
            assert valeur == ISOLATION[nom], nom
        if nom == 'ReadOnlyPaths':
            assert valeurs(chemin, nom) == [valeur]
        else:
            assert valeurs(chemin, nom) == [valeur], nom
        assert decision in ('conservée', 'adaptée'), nom
    assert presentes == attendues  # aucune directive d'isolation hors tableau, ni l'inverse
    assert 'isolation-remus.md' in commentaires
    assert 'L5-14' not in commentaires and not re.search(r'L\d+-\d+', commentaires)
    # Familles d'adresses : seulement celles du tableau.
    assert valeurs(chemin, 'RestrictAddressFamilies') == [lignes['RestrictAddressFamilies'][1]]


def test_no_new_privileges():
    assert valeurs(CHEMINS['castor'], 'NoNewPrivileges') == ['yes']
    assert valeurs(TUNNEL, 'NoNewPrivileges') == ['yes']
    decision, valeur, _ = tableau()['NoNewPrivileges']
    if decision == 'retirée':
        assert not valeurs(CHEMINS['remus'], 'NoNewPrivileges')
    else:
        assert valeurs(CHEMINS['remus'], 'NoNewPrivileges') == [valeur]


def test_tunnel_dossiers_tmpfiles():
    assert valeurs(TUNNEL, 'ExecStartPre') == []
    assert valeurs(TUNNEL, 'ExecStartPost') == []
    assert une(TUNNEL, 'Type') == 'simple'
    assert une(TUNNEL, 'ProtectSystem') == 'strict'
    assert valeurs(TUNNEL, 'ReadWritePaths') == [
        '/run/paresia-tunnel/romulus /run/paresia-tunnel/pollux']
    commentaire = texte(TUNNEL)
    assert not re.search(r'setfacl|RuntimeDirectory|\bACL\b', commentaire, re.I)
    for mot in ('systemd.service(5)', 'tmpfiles.d(5)', 'systemd.exec(5)',
                'StreamLocalBindUnlink yes', 'systemd.special(7)', 'D62'):
        assert mot in commentaire, mot


def test_tunnel_pas_de_donnee_en_dur():
    brut = sans_commentaires(TUNNEL)
    assert not re.search(r'\d{1,3}(\.\d{1,3}){3}', brut) and 'ssh-' not in brut and '.key' not in brut
    assert '-i ' not in brut and 'IdentityFile' not in brut and 'PRIVATE' not in brut


def test_timeout_stop_castor():
    delai = ini().getint('castor.transport', 'delai_s')
    assert int(une(CHEMINS['castor'], 'TimeoutStopSec')) == 90 >= 2 * delai + 30


def test_timeout_stop_remus():
    stop = ini().getint('remus.server', 'stop_s')
    assert int(une(CHEMINS['remus'], 'TimeoutStopSec')) == 150 >= stop + 30
    assert 'systemd.service(5)' in texte(CHEMINS['remus'])


def test_kill_mode_remus():
    assert valeurs(CHEMINS['remus'], 'KillMode') == ['mixed']
    assert not valeurs(CHEMINS['castor'], 'KillMode') and not valeurs(TUNNEL, 'KillMode')
    assert 'systemd.kill(5)' in texte(CHEMINS['remus']) and 'D81' in texte(CHEMINS['remus'])


def test_relais_sockets_coherents():
    c = ini()
    assert c['castor.tunnel']['socket'] == '/run/paresia-castor/castor.sock'
    assert c['castor.state']['socket'] == '/run/paresia-castor/castor-state.sock'
    assert c['remus.server']['socket'] == '/run/paresia-remus/remus.sock'
    assert c['remus.castor']['socket'] == c['castor.state']['socket']
    for nom, sections in {'castor': ['castor.tunnel', 'castor.state'], 'remus': ['remus.server']}.items():
        dossier = '/run/' + une(CHEMINS[nom], 'RuntimeDirectory') + '/'
        assert all(c[s]['socket'].startswith(dossier) for s in sections)


def test_relais_groupes_supplementaires():
    c = ini()
    assert (int(c['castor.tunnel']['gid']), int(c['castor.state']['gid']), int(c['remus.server']['gid'])) == (973, 975, 974)
    nom_groupe = {v: k for k, v in GROUPES.items()}
    creees = {'castor': ['castor.tunnel', 'castor.state'], 'remus': ['remus.server']}
    jointes = {'castor': [], 'remus': ['castor.state']}
    for nom in ('castor', 'remus'):
        voulus = {nom_groupe[int(c[s]['gid'])] for s in creees[nom] + jointes[nom]}
        assert set(une(CHEMINS[nom], 'SupplementaryGroups').split()) == voulus, nom


def test_dossiers_distincts():
    # Comparer des chemins absolus : ceux du relais sont relatifs à /run,
    # ceux du tunnel sont les deux dossiers tmpfiles ouverts en écriture.
    dossiers = ['/run/' + une(CHEMINS[nom], 'RuntimeDirectory') for nom in ('castor', 'remus')]
    dossiers.extend(une(TUNNEL, 'ReadWritePaths').split())
    assert len(dossiers) == 4
    assert len(set(dossiers)) == len(dossiers)
    assert '/run/paresia/' not in ''.join(texte(p) for p in FICHIERS)


def test_relais_identifiants_unites(tmp_path):
    racine = tmp_path / 'etc-paresia'
    racine.mkdir()
    shutil.copy(CONF, racine / 'paresia.conf')
    racine.chmod(0o755)
    (racine / 'paresia.conf').chmod(0o644)
    castor = lire('castor', SCHEMA_CASTOR, journal=True, metriques=True, argv=[], environ={}, racine_systeme=racine)
    assert (castor['tunnel']['uid'], castor['tunnel']['gid']) == (GROUPES['tunnel'], GROUPES['paresia-castor-tunnel'])
    assert (castor['state']['uid'], castor['state']['gid']) == (GROUPES['chef'], GROUPES['paresia-castor-etat'])
    procedure = texte(PROCEDURE)
    tg = re.search(r'(?m)^    TABLE_GROUPES=\((.*?)\)\n', procedure, re.S).group(1)
    tc = re.search(r'(?m)^    TABLE_COMPTES=\((.*?)\)\n', procedure, re.S).group(1)
    assert tg.split() == list(GROUPES)      # tables de noms : les numéros sont attribués par le système
    for nom in ('paresia-castor', 'chef', 'tunnel'):
        assert re.search(rf'"{nom} ', tc), nom
    for nom, chemin in CHEMINS.items():
        assert une(chemin, 'User') == COMPTE[nom] and une(chemin, 'User') in GROUPES
        assert set(une(chemin, 'SupplementaryGroups').split()) <= set(GROUPES)


def test_pas_de_dependance_croisee():
    for chemin in CHEMINS.values():
        brut = sans_commentaires(chemin)
        for mot in ('After=', 'Requires=', 'Wants=', 'BindsTo='):
            assert mot not in brut, (chemin.name, mot)


def test_unites_journald_sans_fichier():
    for chemin in CHEMINS.values():
        brut = sans_commentaires(chemin)
        for mot in ('StandardOutput', 'StandardError', 'LogsDirectory', 'CacheDirectory'):
            assert mot not in brut, (chemin.name, mot)
        # Seul dossier admis : le dossier d'état du démon (métriques), de valeur et de mode exacts.
        assert valeurs(chemin, 'StateDirectory') == ['paresia-' + chemin.stem], chemin.name
        assert valeurs(chemin, 'StateDirectoryMode') == ['0711'], chemin.name
        assert 'journald' in texte(chemin) and 'systemd.exec(5)' in texte(chemin)
    assert not [v for v in valeurs(CHEMINS['remus'], 'ReadWritePaths') if 'paresia' in v.lower()]


def pages_manuel():
    for outil in ('man', 'zcat'):
        if shutil.which(outil) is None:
            pytest.skip(f'{outil} absent : vérification des directives ignorée')
    pages = ('systemd.exec', 'systemd.service', 'systemd.kill', 'systemd.unit', 'systemd.resource-control')
    morceaux = []
    for page in pages:
        chemin = Path('/usr/share/man/man5') / f'{page}.5.gz'
        if not chemin.exists():
            pytest.skip(f'page {page}(5) absente : vérification des directives ignorée')
        brut = subprocess.run(['zcat', str(chemin)], capture_output=True, timeout=60).stdout
        rendu = subprocess.run(['man', '-l', '-'], input=brut, capture_output=True, timeout=60,
                               env={'MANWIDTH': '1000', 'LC_ALL': 'C.UTF-8', 'PATH': '/usr/bin:/bin'}).stdout
        morceaux.append(unicodedata.normalize('NFKC', rendu.decode('utf-8', 'replace')).replace('\x08', ''))
    return '\n'.join(morceaux)


def test_directives_connues():
    pages = pages_manuel()
    assert 'RuntimeDirectory=' in pages, 'pages de manuel illisibles'
    connues = set(re.findall(r'\b([A-Z][A-Za-z0-9]+)=', pages))
    for chemin in (*CHEMINS.values(), TUNNEL):
        for section, directives in analyser(chemin).items():
            for cle, _ in directives:
                assert cle in connues, (chemin.name, section, cle)


def test_unites_verify(tmp_path):
    outil = shutil.which('systemd-analyze')
    if outil is None:
        pytest.skip('systemd-analyze absent : vérification des unités ignorée')
    for chemin in (*CHEMINS.values(), TUNNEL):
        if chemin is TUNNEL and not Path('/usr/bin/ssh').exists():
            pytest.skip('ssh absent : vérification de l\'unité du tunnel ignorée')
        resultat = subprocess.run([outil, 'verify', str(chemin)], capture_output=True, text=True,
                                  cwd=tmp_path, timeout=60)
        erreurs = [l for l in resultat.stderr.splitlines() + resultat.stdout.splitlines() if chemin.name in l]
        assert not erreurs, erreurs


def test_noms_fichiers_minuscules():
    for chemin in FICHIERS:
        assert chemin.name == chemin.name.lower(), chemin.name
    assert {p.name for p in FICHIERS} >= {'castor.service', 'remus.service', 'paresia-tunnel.service',
                                          'installer-backend-relais.sh', 'isolation-remus.md'}
    # livrables de deploy/backend-relais/ : le script, le tableau d'isolation et (jusqu'à leur réécriture en page d'emploi) l'ancienne procédure
    livres = {p.name for p in RELAIS.iterdir() if p.is_file()}
    assert {'installer-backend-relais.sh', 'isolation-remus.md'} <= livres <= {
        'installer-backend-relais.sh', 'installation-relais.md', 'isolation-remus.md'}
    assert 'deploy/backend-admin/INSTALLATION' not in ''.join(texte(p) for p in FICHIERS)


def fonctions_script():
    return {m.group(1): m.group(0) for m in re.finditer(r'(?ms)^(\w+)\(\) \{(?:[^\n]*\}$|[^\n]*\n.*?^\})', texte(PROCEDURE))}


RISQUE = re.compile(
    r'(?m)(^\s*|[;&|(]\s*|\bdo\s+|\bthen\s+)(?:sudo /usr/s?bin/)?(rm |install (?!-d)|mv |cp |sed -i |chown -R |'
    r'systemctl (start|stop|restart|reload|enable|disable)\b)')


def test_procedure_unites_etapes():
    procedure = texte(PROCEDURE)
    etapes = re.search(r'(?m)^    ETAPES=\((.*?)\)\n', procedure, re.S).group(1).split()
    assert etapes[etapes.index('unites'):] == ['unites', 'castor', 'remus', 'refus_castor', 'isolation_remus']
    for e in etapes:
        assert f'etape_{e}()' in procedure and f'deja_conforme_{e}()' in procedure and f'verifier_{e}()' in procedure, e
    fonc = fonctions_script()
    assert fonc['etape_castor'].index('systemctl start castor.service') >= 0
    assert procedure.index('etape_castor() {') < procedure.index('etape_remus() {')
    assert [n for n, c in fonc.items() if 'systemctl enable castor.service' in c] == ['etape_activation']
    assert 'systemd-analyze verify castor.service remus.service' in procedure
    # attendus de stat (D48, D49)
    for attendu in ('paresia-castor:paresia-castor 711', 'paresia-castor:paresia-castor-tunnel 660',
                    'paresia-castor:paresia-castor-etat 660', 'chef:chef 711',
                    'chef:paresia-remus-tunnel 660', 'root:root 755', 'KillMode=mixed', '150 s'):
        assert attendu in procedure, attendu
    assert "ne pas démarrer le tunnel avant elle" in procedure
    apres = ''.join(fonc[n] for n in fonc if n.split('_', 2)[-1] in ('unites', 'castor', 'remus', 'refus_castor', 'isolation_remus'))
    assert 'ssh_config' not in apres


def test_procedure_unites_avertissements():
    risques = 0
    for nom, corps in fonctions_script().items():
        if nom.endswith(('_unites', '_castor', '_remus', '_refus_castor', '_activation')) and RISQUE.search(corps):
            risques += 1
            assert 'attention ' in corps or '# ATTENTION :' in corps, nom
    assert risques >= 3
    procedure = texte(PROCEDURE)
    assert re.search(r'ATTENTION[^\n]*(remet|feux au rouge)', procedure)
    assert 'sed -i' in procedure and '/var/backups/paresia/relais/' in procedure
    assert not re.search(r'(?m)^[^#\n]*rm -rf', procedure)


def corps_entre(debut, fin):
    t = texte(PROCEDURE)
    return t[t.index(debut):t.index(fin)]


def test_procedure_essais_isolation():
    e12 = corps_entre('# Étape refus_castor', '# Étape isolation_remus')
    e13 = corps_entre('# Étape isolation_remus', '# Partie « tunnel » de backend-relais')
    for socket in ('castor.sock', 'castor-state.sock', 'remus.sock'):
        assert socket in ''.join((e12 + texte(PROCEDURE)).split())
    assert 'PermissionError [Errno 13]' in e12
    assert 'session 1, light_green puis light_closed' in e12
    assert 'reason valant close' in e12
    for mot in ('PermissionError', 'castor/light/ping', 'castor/light/state', 'castor/light/close',
                'jumeaux/1', 'secrets.token_hex(8)', 'runuser -u'):
        assert mot in e12 + texte(PROCEDURE)[texte(PROCEDURE).index('jumeaux() {'):], mot
    assert 'NoNewPrivs|CapBnd|CapEff|CapAmb' in e13
    assert 'systemctl show -p MainPID --value remus.service' in e13
    assert 'systemd-run --wait --pipe --collect' in e13 and 'sudo -n -l' in e13
    assert "à relever" in e13 and 'table non vide' in e13 and 'coordinateur' not in e13
    # une entrée pour chaque ligne « à vérifier sur la cible »
    for nom, (_, _, compensation) in tableau().items():
        if 'à vérifier sur la cible' in compensation:
            assert f'| {nom} |' in e13, nom


def test_procedure_systemd_run_proprietes():
    t = texte(PROCEDURE)
    debut = t.index('/usr/bin/systemd-run --wait --pipe --collect', t.index('verifier_isolation_remus() {')) + len('/usr/bin/systemd-run --wait --pipe --collect')
    commande = t[debut:t.index('/usr/bin/sudo -n -l 2>&1', debut)].replace('\\\n', ' ')
    jetons = shlex.split(commande)
    proprietes = [jetons[i + 1] for i, j in enumerate(jetons) if j == '-p']
    assert proprietes
    unite = CHEMINS['remus']
    for p in proprietes:
        cle, _, valeur = p.partition('=')
        assert valeurs(unite, cle) == [valeur], p
    cles = {p.partition('=')[0] for p in proprietes}
    # chaque directive d'isolation présente dans l'unité figure dans l'essai
    presentes = {k for k, _ in analyser(unite)['Service']} & DIRECTIVES_ISOLATION
    assert presentes <= cles and {'User', 'Group', 'SupplementaryGroups'} <= cles
    assert 'NoNewPrivileges' not in cles


MOTIFS_RENVOI = (r'T\d{3}', r'(?i)\blots?\b', r'(?i)coordinateur', r'(?i)\bfiche', r'documentaliste')


def test_procedure_sans_renvoi_interne():
    contenu = texte(PROCEDURE)
    for motif in MOTIFS_RENVOI:
        assert not re.search(motif, contenu), motif
    assert contenu.splitlines()[0] == '#!/bin/bash'
    assert 'aucune unité Castor/Remus' not in contenu


def test_isolation_sans_renvoi_interne():
    contenu = texte(TABLEAU)
    for motif in (*MOTIFS_RENVOI, r'L\d+-\d+'):
        assert not re.search(motif, contenu), motif
    assert 'aucune unité remus.service' not in contenu


def test_procedure_etape9_ordre_et_retour():
    t = texte(PROCEDURE)
    assert 0 <= t.index("sed -i 's/^ConfigurationDirectory=paresia::ro$/ConfigurationDirectory=paresia/'") < t.index('verifier_unites() {')
    assert '/var/backups/paresia/relais/' in t
    assert 'outil_q restaurer --jeu "$JEU" "$1"' in t
    retour = fonctions_script()['retour_arriere']
    assert 'restaurer_si_pose' in retour and retour.index('restaurer_si_pose') < retour.index('systemctl daemon-reload')


def test_procedure_retour_sans_rm_de_repli():
    t = texte(PROCEDURE)
    assert 'rm -f "/etc/systemd/system/' not in t
    retour = fonctions_script()['retour_arriere']
    assert 'sudo /usr/bin/rm ' not in retour and 'sudo /usr/bin/cp ' not in retour
    poser = fonctions_script()['poser_fichier']
    assert poser.index('sauvegarder "$2"') < poser.index('install -m "$3"')


ADRESSES_DOC = [ipaddress.ip_network(r) for r in ('192.0.2.0/24', '198.51.100.0/24', '203.0.113.0/24')]
MOTIFS_SECRETS = [r'nsec1[02-9ac-hj-np-z]{20,}', r'ncryptsec1', r'-----BEGIN [A-Z ]*PRIVATE KEY-----',
                  r'gh[pousr]_[A-Za-z0-9]{20,}', r'sk-[A-Za-z0-9_-]{20,}',
                  r'ssh-(ed25519|rsa) AAAA[A-Za-z0-9+/=]{20,}']


def test_aucun_secret_ni_donnee_reelle_unites():
    for chemin in FICHIERS:
        contenu = texte(chemin)
        for motif in MOTIFS_SECRETS:
            assert not re.search(motif, contenu), (chemin.name, motif)
        for adresse in re.findall(r'\b\d{1,3}(?:\.\d{1,3}){3}\b', contenu):
            ip = ipaddress.ip_address(adresse)
            assert ip.is_loopback or ip.is_unspecified or any(ip in r for r in ADRESSES_DOC), (chemin.name, adresse)
        assert not re.search(r'(?i)' + 'clau' + 'de' + r'\.ai|' + 'lap' + 'top|' + 'home' + 'lab|' + 'opn' + 'sense', contenu), chemin.name
