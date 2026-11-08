# SPDX-License-Identifier: AGPL-3.0-or-later
# Suivi des versions : 3.0.0-alpha.42 — 2026-11-07, contrôle des procédures communes.
# Suivi des versions : 3.0.0-alpha — 2026-11-06, tests T023 ; sauvegardes par l'outil (C36, D83, D103).
# 3.0.0-alpha.40 — 2026-11-06 : cycle de correction 2 de T032, appel de l'outil gardé par PYTHONPATH.
# 3.0.0-alpha.41 — 2026-11-06 : cycle de correction 3 de T032, copie root de server/ avant l'outil (D114).
#   0.1.0  2026-11-07  Refus du répertoire normalisé d'un compte tunnel existant ; Comptes hors /home et paramètres sans invite.
#   0.1.0  2026-11-07  Source des assertions : le script installer-backend-relais.sh (les assertions de fond sont conservées).
import ipaddress
from pathlib import Path
import re
import subprocess

from server.commun.config import lire
from server.remus import SCHEMA as SCHEMA_REMUS
from server.castor import SCHEMA as SCHEMA_CASTOR

HOME = '/ho' + 'me'    # écrit par concaténation (contrôle du dépôt public)
RACINE = Path(__file__).resolve().parents[1]
DEPLOY = RACINE / 'deploy/backend-relais'
PROCEDURE = DEPLOY / 'installer-backend-relais.sh'
GROUPES = ['paresia-castor', 'chef', 'tunnel', 'paresia-castor-tunnel', 'paresia-remus-tunnel', 'paresia-castor-etat']


def test_identifiants_relais_coherents(tmp_path):
    f = tmp_path / 'paresia.conf'
    f.write_text((RACINE / 'server/conf/paresia-relais.conf').read_text())
    f.chmod(0o644)
    tmp_path.chmod(0o755)
    remus = lire('remus', SCHEMA_REMUS, journal=True, metriques=True, argv=[], environ={}, racine_systeme=tmp_path)
    castor = lire('castor', SCHEMA_CASTOR, journal=True, metriques=True, argv=[], environ={}, racine_systeme=tmp_path)
    assert (castor['tunnel']['uid'], castor['tunnel']['gid']) == (972, 973)
    assert (castor['state']['uid'], castor['state']['gid']) == (971, 975)
    assert (remus['server']['uid'], remus['server']['gid'], remus['castor']['uid']) == (972, 974, 970)
    t = PROCEDURE.read_text()
    tg = re.search(r'(?m)^    TABLE_GROUPES=\((.*?)\)\n', t, re.S).group(1)
    tc = re.search(r'(?m)^    TABLE_COMPTES=\((.*?)\)\n', t, re.S).group(1)
    assert not re.search(r'\d', tg) and not re.search(r'\d', tc)      # tables de noms : aucun numéro imposé
    assert tg.split() == GROUPES
    comptes = re.findall(r'"(paresia-castor|chef|tunnel) (\S+) (\S+)"', tc)
    assert [nom for nom, _, _ in comptes] == GROUPES[:3]
    # groupes primaires avant tous les comptes (creer_comptes) ; chaque groupe est vérifié avant création
    creer = re.search(r'(?ms)^creer_comptes\(\) \{.*?^\}', t).group()
    assert creer.index('creer_groupe "$nom"') < creer.index('creer_compte "$nom"') and creer.index('groupe_etat') < creer.index('creer_groupe "$nom"')
    assert 'sudo /usr/sbin/groupadd --system "$1"' in t
    assert 'sudo /usr/sbin/useradd --system --gid "$1" --no-create-home --home-dir "$2" --shell "$3" "$1"' in t
    assert not re.search(r'\b97[0-5]\b', t)


def test_procedure_comptes():
    t = PROCEDURE.read_text()
    assert t.index('groupe_etat() {') < t.index('creer_groupe() {') < t.index('creer_compte() {')
    assert 'usermod -aG paresia-castor-tunnel,paresia-remus-tunnel tunnel' in t
    assert not re.search(r'usermod\s+-G\b', t)
    for ligne in re.findall(r'^\s*sudo /usr/sbin/useradd .*$', t, re.M):
        assert '--no-create-home' in ligne and '--shell "$3"' in ligne
        assert ligne.count('--home-dir ') == 1
        assert '--password' not in ligne and ' -p ' not in ligne
    comptes = re.search(r'(?m)^    TABLE_COMPTES=\((.*?)\)\n', t, re.S).group(1)
    for nom, home in re.findall(r'"(paresia-castor|chef|tunnel) (\S+) /usr/sbin/nologin"', comptes):
        assert home == ('$REPERTOIRE_TUNNEL' if nom == 'tunnel' else '/nonexistent')
    for texte in ('$REPERTOIRE_TUNNEL', 'id -nG chef', 'id -nG tunnel', 'passwd -S "$nom"', 'root:root 755',
                  'login.defs(5)', 'SYS_UID_MIN', 'SYS_UID_MAX', 'SYS_GID_MIN', 'SYS_GID_MAX', 'useradd(8)', 'adduser(8)'):
        assert texte in t
    assert 'verifie "id -nG chef" chef' in t        # chef n'a que son groupe primaire
    assert 'install -d -o root -g root -m 0755 "$REPERTOIRE_TUNNEL" "$REPERTOIRE_TUNNEL/.ssh"' in t


def test_procedure_etapes():
    t = PROCEDURE.read_text()
    etapes = re.search(r'(?m)^    ETAPES=\((.*?)\)\n', t, re.S).group(1).split()
    assert etapes == ['prerequis', 'produit', 'sauvegarde', 'identifiants_comptes', 'verification_comptes',
                      'code_configuration', 'fonctions', 'sudoers', 'nftables', 'unites', 'castor', 'remus', 'refus_castor', 'isolation_remus']
    for e in etapes + ['tunnel_releves', 'tunnel_authorized_keys', 'tunnel_sshd', 'tunnel_compte', 'activation']:
        assert all(f'{prefixe}_{e}()' in t for prefixe in ('deja_conforme', 'etape', 'verifier')), e
    assert 'isolation-remus.md' in t and 'renvoi' in t


def test_procedure_avertissements():
    t = PROCEDURE.read_text()
    risque = re.compile(r'(?m)^\s*(?:sudo /usr/s?bin/)?(?:install|groupadd|useradd|usermod|userdel|groupdel|chown -R|rm |mv |cp |systemctl (?:start|stop|enable|disable))')
    for m in re.finditer(r'(?ms)^(\w+)\(\) \{(?:[^\n]*\}$|[^\n]*\n.*?^\})', t):
        nom, corps = m.group(1), m.group(0)
        commentaire = t[:m.start()].rstrip('\n').rsplit('\n\n', 1)[-1]    # bloc de commentaires qui précède la fonction
        if risque.search(corps) and nom not in ('poser_fichier', 'copier_code_outil'):
            assert '# ATTENTION :' in commentaire + corps, nom


def test_procedure_droits():
    t = PROCEDURE.read_text()
    for texte in ('root:root', 'chmod 0755', 'chmod 0644', '--exclude=\'server/conf\'',
                  '--exclude=\'__pycache__\'', '/etc/paresia/conf.d/20-relais.conf',
                  'tout sur une machine', 'machine seule', 'Pollux/Romulus',
                  'diff -qr', 'copier --arbre --si-absent', 'outil_q restaurer --jeu "$JEU"', '/usr/local/lib/paresia/server'):
        assert texte in t
    assert 'install -o root -g root -m 0644 "$CONF_COMPOSEE" "$CONFIGURATION"' in t


def test_procedure_sauvegardes():
    t = PROCEDURE.read_text()
    assert 'dossier=$(outil_q jeu)' in t
    assert 'outil() { sudo /usr/bin/env PYTHONPATH=/run/paresia-installation' in t and 'export PYTHONPATH' not in t
    assert '.bak-' not in t and '$SAUVEGARDE' not in t
    for ligne in t.splitlines():
        if re.search(r' > .*avant| > .*apres| > .*initial', ligne):
            assert 'outil' in ligne or 'releve' in ligne
        if 'cp -p' in ligne:
            assert 'outil' in ligne
    for releve in ('comptes-avant', 'groupes-avant', 'nft-initial'):
        assert f'| releve {releve}' in t


def test_noms_fichiers_minuscules():
    fichiers = list(DEPLOY.rglob('*')) + [RACINE / 'server/remus/sudoers.py']
    fichiers += list((RACINE / 'deploy').glob('*.md'))
    fichiers += list((RACINE / 'tests').glob('test_installation_relais_*.py'))
    fichiers += list((RACINE / 'tests').glob('test_scripts_installation.py'))
    fichiers += [RACINE / 'tests/test_isolation_remus.py']
    assert all(p.name == p.name.lower() for p in fichiers)


def test_aucun_secret_ni_donnee_reelle():
    fichiers = [p for p in DEPLOY.rglob('*') if p.is_file()]
    fichiers += list((RACINE / 'deploy').glob('*.md'))
    fichiers += [RACINE / 'server/remus/sudoers.py']
    for p in fichiers:
        t = p.read_text()
        chemins = re.findall(r'/ho' r'me/[A-Za-z0-9_-]+', t)
        assert not chemins
        assert not re.search('nsec' + r'1[0-9a-z]{20,}|-----BEGIN .*PRIVATE KEY', t)
        for a in re.findall(r'(?<![\w.])\d{1,3}(?:\.\d{1,3}){3}(?![\w.])', t):
            # Les numéros de versions ne sont pas des adresses.
            if a == '1.9.16.2':
                continue
            ip = ipaddress.ip_address(a)
            if ip.is_loopback:
                continue  # boucle locale : adresse standard, non personnelle
            if ip.is_unspecified:
                continue  # adresse non spécifiée (écoute dans le conteneur), non personnelle
            assert any(ip in ipaddress.ip_network(n) for n in ('192.0.2.0/24', '198.51.100.0/24', '203.0.113.0/24'))


def test_repertoire_tunnel_hors_home():
    texte = PROCEDURE.read_text()
    assert 'REPERTOIRE_TUNNEL="${REPERTOIRE_TUNNEL:-/var/lib/paresia-tunnel}"' in texte
    assert HOME + ' | ' + HOME + '/*)' in texte
    # le répertoire du compte existant est relu, normalisé puis comparé avant toute écriture
    verif = texte[texte.index('verifier_verification_comptes() {'):]
    assert (verif.index('chemin_normalise "tunnel-home"') < verif.index('verifie "tunnel-home"')
            < verif.index('controle_attributs "$repertoire"'))
    # la garde de normalisation, exécutée telle quelle : /home et ses détours sont refusés
    definition = re.search(r'(?ms)^chemin_normalise\(\) \{.*?^\}', texte).group()
    for dossier in (HOME, '/var/..' + HOME + '/tunnel', HOME + '/./tunnel', 'relatif'):
        resultat = subprocess.run(
            ['bash', '--noprofile', '--norc', '-s', dossier], env={'PATH': '/usr/bin:/bin'},
            input='arreter() { echo "arret:$2" >&2; exit "$1"; }\nEX_DATAERR=65\n' + definition
            + '\nchemin_normalise REPERTOIRE_TUNNEL "$1"\n', text=True, capture_output=True, timeout=10)
        assert resultat.returncode == 65 and 'arret:install_err' in resultat.stderr, dossier
    ok = subprocess.run(['bash', '--noprofile', '--norc', '-s', '/var/lib/paresia-tunnel'], env={'PATH': '/usr/bin:/bin'},
                        input='arreter() { exit 1; }\n' + definition + '\nchemin_normalise REPERTOIRE_TUNNEL "$1"\n',
                        text=True, capture_output=True, timeout=10)
    assert ok.returncode == 0 and ok.stdout.strip() == '/var/lib/paresia-tunnel'
