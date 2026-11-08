# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests des scripts d'installation de backend-admin et de backend-relais : formes (bash -n, shellcheck,
# en-tête, interdits), cohérence des catalogues, puis exécution réelle en environnement factice (racine
# temporaire, sudo et commandes d'administration simulés, aucun root, aucun réseau sortant).
# Dépendances : bibliothèque standard, pytest ; shellcheck seulement s'il est installé.
# Suivi des versions
#   0.1.19  2026-11-08  Prérequis OpenSSL, propriétaire du journal sous sudo et activation des seuls services.
#   0.1.19  2026-11-08  Étape web : seuls dpkg-query -W et dpkg --compare-versions (lecture du prérequis libssl3t64) sont admis parmi les appels dpkg.
#   0.1.0  2026-11-07  Première version.
#   0.1.1  2026-11-07  Sécurité des scripts (python3 -I, cd /, clé publique, journal, tar, journalctl, DEPOT) et cas de test manquants ; contrôle des chemins sous le dossier personnel.
#   0.1.2  2026-11-07  Port d'essai propre à chaque instance ; refus d'un port en écoute ; port en TIME_WAIT non pris pour une écoute.
#   0.1.3  2026-11-08  Mode --mise-a-jour : prérequis accumulés (accumuler), noms de fichiers du greffon admis dans les chemins de sauvegarde.
#   0.1.3  2026-11-08  Étape web : pages, index, aucun serveur web touché.
import base64
import hashlib
import json
import os
import pty
import re
import select
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path

import pytest

from tests.outils.installation_factice import Faux, SENTINELLE, copier_modele

HOME = '/ho' + 'me'    # écrit par concaténation (contrôle du dépôt public)
RACINE = Path(__file__).resolve().parents[1]
ADMIN = RACINE / 'deploy/backend-admin/installer-backend-admin.sh'
RELAIS = RACINE / 'deploy/backend-relais/installer-backend-relais.sh'
SCRIPTS = [ADMIN, RELAIS]
CATALOGUES = {l: json.loads((RACINE / 'i18n' / f'{l}.json').read_text(encoding='utf-8')) for l in ('fr-FR', 'en-US')}
MARQUE = 'Commandes lancées par `sudo`'
ECHEC_BASH = 'echec'


def texte(chemin):
    return chemin.read_text(encoding='utf-8')


def code(chemin):
    """Lignes de code (hors commentaires et lignes vides), jointes sur les continuations."""
    brut = texte(chemin).replace('\\\n', ' ')
    return [l.strip() for l in brut.splitlines() if l.strip() and not l.strip().startswith('#')]


def fonctions(chemin):
    """{nom: corps} des fonctions du script (définition `nom() {` jusqu'à la `}` en colonne 0)."""
    return {m.group(1): m.group(0) for m in re.finditer(r'(?ms)^(\w+)\(\) \{(?:[^\n]*\}$|[^\n]*\n.*?^\})', texte(chemin))}


# -- formes -------------------------------------------------------------------------------------

@pytest.mark.parametrize('script', SCRIPTS, ids=lambda p: p.name)
def test_syntaxe_et_shellcheck(script):
    assert subprocess.run(['bash', '-n', str(script)], capture_output=True, timeout=60).returncode == 0
    if shutil.which('shellcheck') is None:
        pytest.skip('shellcheck absent')
    resultat = subprocess.run(['shellcheck', '-s', 'bash', str(script)], capture_output=True, text=True, timeout=120)
    assert resultat.returncode == 0, resultat.stdout


@pytest.mark.parametrize('script', SCRIPTS, ids=lambda p: p.name)
def test_forme_entete(script):
    lignes = texte(script).splitlines()
    assert lignes[0] == '#!/bin/bash'
    assert 'SPDX-License-Identifier: AGPL-3.0-or-later' in lignes[1]
    assert os.access(script, os.X_OK)
    assert script.name == script.name.lower()
    t = texte(script)
    assert 'set -euo pipefail' in t.split('# DEBUT commun')[0] and 'umask 0022' in t
    assert re.search(r'(?m)^trap sortie_script EXIT|^\s+trap sortie_script EXIT', t)
    for mot in ('Suivi des versions', 'Codes de sortie', 'Prérequis', 'Retour arrière', 'temporaire', 'Paramètres'):
        assert mot in t, mot
    assert not re.search(r'(?i)\b(T0\d\d|fiche|lot\b|coordinateur)\b', t)
    assert not re.search(r'-----BEGIN [A-Z ]*PRIVATE KEY|nsec1[0-9a-z]{20,}', t)
    for adresse in re.findall(r'(?<![\w.])\d{1,3}(?:\.\d{1,3}){3}(?![\w.])', t):
        assert adresse.startswith(('192.0.2.', '198.51.100.', '203.0.113.', '127.0.0.1', '0.0.0.0')), adresse
    assert not re.search(r'/ho' r'me/[A-Za-z0-9_-]+', t)


@pytest.mark.parametrize('script', SCRIPTS, ids=lambda p: p.name)
def test_interdits(script):
    lignes = '\n'.join(code(script))
    for ligne in lignes.splitlines():
        assert not re.search(r'\|\s*(?:sudo \S+ )?(?:/usr/bin/)?grep\s+(?:-[A-Za-z]+ )*-[A-Za-z]*q', ligne), ligne    # SIGPIPE sous pipefail
    for motif in (r'\brm\s+-rf\b', r'\bset\s+-x\b', r'set\s+-o\s+xtrace', r'\bset\s+\+e\b', r'(?<![\w$-])eval\b',
                  r'systemctl\s+restart', r'sudo\s+-i\b', r'\bsu\s+-', r'sudo\s+(sh|bash)\s+-c', r'\|\s*head\b',
                  r'ProtectHome=tmpfs', r'BindReadOnlyPaths'):
        assert not re.search(motif, lignes), motif
    assert 'monté par son inode' not in texte(script)
    # les noms des fichiers de fonctions du greffon (strfry_*) sont des chemins de sauvegarde, jamais une unité touchée
    sans_fichiers = re.sub(r'/strfry_(?:arbres|etat|redemarrer)(?:\.toml)?"', '"', lignes)
    for service in ('strfry', 'lighttpd', 'bunkerd'):
        assert service not in sans_fichiers, service
    for ligne in code(script):
        if 'docker' in ligne and 'motif=docker' not in ligne:
            if "inspect --format" in ligne:
                # seule lecture de Docker du script : référence et identifiant de l'image du conteneur
                assert ligne == ("lecture=$(sudo /usr/bin/docker inspect --format '{{.Config.Image}} {{.Image}}' "
                                 "\"$nom\" 2> /dev/null) || lecture=''")
            else:
                assert ligne.endswith('/usr/bin/docker ps > /dev/null 2>&1; then') and 'sudo -u chef' in ligne
        # la clé privée du tunnel n'est jamais lue : aucune lecture de id_ed25519 hors clé publique
        if re.search(r'\b(cat|grep|diff|less|head|tail|cp|base64)\b', ligne):
            assert not re.search(r'id_ed25519(?!\.pub)', ligne), ligne


@pytest.mark.parametrize('script', SCRIPTS, ids=lambda p: p.name)
def test_sudo_chemins_absolus_et_liste_exacte(script):
    from tests.test_procedures_sudo import executables_sudo, annonces_script
    reels, erreurs = set(), []
    for ligne in code(script):
        if 'type -P' in ligne or ligne.startswith('command "sudo"'):
            continue
        t, e = executables_sudo(ligne)
        reels |= t
        erreurs += e
    assert not erreurs, erreurs
    annonce = annonces_script(script)
    assert not (reels - annonce), f'non listées : {sorted(reels - annonce)}'
    assert not (annonce - reels), f'listées sans emploi : {sorted(annonce - reels)}'
    assert 'pas un sudoers à recopier' in texte(script) and 'ne peuvent pas être restreintes' in texte(script)


def test_identite_admin_root_relais_ordinaire():
    admin, relais = texte(ADMIN), texte(RELAIS)
    assert re.search(r'(?m)^sudo\(\) \{', admin) and not re.search(r'(?m)^sudo\(\) \{', relais)
    assert 'type -P "sudo"' in admin and 'install_err_root_requis' in admin and 'sans `sudo`' in admin
    assert 'install_err_root_interdit' in relais and 'Aucun shell root' in relais
    for nom in ('ADRESSE_ADMIN', 'CLE_PUBLIQUE_TUNNEL', 'PROFIL', 'PORT_ESSAI', 'REPERTOIRE_TUNNEL'):
        assert nom not in admin, nom
    for nom in ('ADRESSE_RELAIS', 'EMPREINTE_HOTE_RELAIS', 'REPERTOIRE_APP'):
        assert nom not in relais, nom


@pytest.mark.parametrize('script', SCRIPTS, ids=lambda p: p.name)
def test_parametres_entete_egaux_au_code(script):
    t = texte(script)
    entete = set(re.findall(r'(?m)^#   ([A-Z][A-Z_0-9]+)  +--', t))
    dans_code = set(re.findall(r'(?m)^\s+([A-Z][A-Z_0-9]+)="\$\{\1:-', t))
    assert entete == dans_code and entete


@pytest.mark.parametrize('script', SCRIPTS, ids=lambda p: p.name)
def test_ordre_defaut_validation_usage(script):
    t = texte(script)
    principal = t[t.index('\nprincipal() {'):]
    ordre = ['defauts_machine', 'analyser "$@"', 'valider_depot', 'charger_catalogue', 'valider_communs',
             'valider_machine', 'controle_identite', 'construire_etapes', 'retour_arriere', 'alpha_demarrer',
             'lancer_etapes']
    positions = [principal.index(m) for m in ordre]
    assert positions == sorted(positions)
    # chaque défaut est posé avec `${NOM:-défaut}` avant toute validation de ce paramètre
    assert t.index('defauts_machine() {') < t.index('valider_machine() {')
    if script == RELAIS:
        assert 'PROFIL="${PROFIL:-relais}"' in t and 'PORT_ESSAI="${PORT_ESSAI:-49152}"' in t


@pytest.mark.parametrize('script', SCRIPTS, ids=lambda p: p.name)
def test_attention_avant_commandes_destructives(script):
    destructif = re.compile(r'sudo /usr/(s?bin)/(userdel|groupdel|useradd|groupadd|usermod|gpasswd|rm|rmdir|mv|cp|'
                            r'chown -R|install (?!-d)|sed -i|nft delete|systemctl (start|stop|enable|disable|reload))\b|\boutil_q restaurer')
    t = texte(script)
    fautes = []
    for nom, corps in fonctions(script).items():
        if nom in ('outil', 'outil_q'):
            continue
        debut = t.index(corps)
        precedent = t[:debut].rstrip('\n').splitlines()
        commentaire = []
        while precedent and precedent[-1].startswith('#'):
            commentaire.insert(0, precedent.pop())
        for ligne in corps.splitlines():
            if destructif.search(ligne) and not ligne.strip().startswith('#'):
                avant = '\n'.join(commentaire) + '\n' + corps[:corps.index(ligne)]
                if '# ATTENTION :' not in avant:
                    fautes.append((nom, ligne.strip()))
                break
    assert not fautes, fautes


@pytest.mark.parametrize('script', SCRIPTS, ids=lambda p: p.name)
def test_reload_ssh_precede_de_sshd_t(script):
    corps = fonctions(script)['recharger_ssh']
    assert corps.index('sshd_t') < corps.index('systemctl reload ssh')
    assert 'SESSION_SECOURS' in corps
    reloads = [l for l in code(script) if 'reload ssh' in l and l.startswith('sudo')]
    assert reloads == ['sudo /usr/bin/systemctl reload ssh']


@pytest.mark.parametrize('script', SCRIPTS, ids=lambda p: p.name)
def test_etapes_ont_leurs_trois_fonctions(script):
    fonc = fonctions(script)
    etapes = re.findall(r'(?m)^etape_(\w+)\(\)', texte(script))
    etapes = [e for e in etapes if e != 'sautee']
    assert len(etapes) >= 12
    for e in etapes:
        assert re.search(rf'(?m)^deja_conforme_{e}\(\)', texte(script)), e
        assert re.search(rf'(?m)^verifier_{e}\(\)', texte(script)), e


def test_bloc_alpha_test_isole():
    for script in SCRIPTS:
        t = texte(script)
        bloc = t[t.index('# DEBUT alpha-test'):t.index('# FIN alpha-test')]
        assert re.findall(r'(?m)^(\w+)\(\) \{', bloc) and all(n.startswith('alpha_') for n in re.findall(r'(?m)^(\w+)\(\) \{', bloc))
        sans = t.replace(bloc, '')
        assert 'alpha_' not in re.sub(r'hook alpha_\w+', '', sans).replace('ALPHA_', '')
        # le script sans le bloc reste valide et s'exécute (les crochets deviennent inertes)
        resultat = subprocess.run(['bash', '-n'], input=sans, text=True, capture_output=True)
        assert resultat.returncode == 0


# -- catalogues ---------------------------------------------------------------------------------

def cles_script(script):
    return set(re.findall(r'\binstall_[a-z][a-z_0-9]*', texte(script)))


def test_cles_install_coherentes():
    fr = {k for k in CATALOGUES['fr-FR'] if k.startswith('install_')}
    en = {k for k in CATALOGUES['en-US'] if k.startswith('install_')}
    assert fr == en and fr
    utilisees = cles_script(ADMIN) | cles_script(RELAIS)
    assert utilisees <= fr, sorted(utilisees - fr)
    assert fr <= utilisees, sorted(fr - utilisees)
    for catalogue in CATALOGUES.values():
        for cle in fr:
            placeholders = set(re.findall(r'\{([a-z_]+)\}', catalogue[cle]))
            assert all(re.fullmatch(r'[a-z_]+', p) for p in placeholders)


@pytest.mark.parametrize('script', SCRIPTS, ids=lambda p: p.name)
def test_aucun_texte_en_dur(script):
    for ligne in code(script):
        assert not re.search(r'[à-ÿÀ-ß]', re.sub(r'\s+#\s.*$', '', ligne)), ligne
        for m in re.finditer(r'(?<![-\w])(?:echo|printf)\s+(.*)', ligne):
            reste = m.group(1)
            reste = re.sub(r'^-v \w+ ', '', reste)        # printf -v variable : l'horodatage est une donnée
            # seuls des formats de données (« %s ») ou des jetons de comparaison sont affichés
            assert re.match(r"""('[^']*%s[^']*'|'%\(%[^']*'|"%[^"]*"|'(fr-FR|en-US)\\n'|'enabled( enabled)+ '|oui|non|loaded|absent|[A-Za-z0-9_-]+\b ?(\|\||;|\)|$))""", reste) or '|| echo' in ligne, ligne
    # les messages ne sont affichés que par msg/msg_out/arreter ; le programme python ne contient pas de texte français
    assert "python3 -I -P -c" in texte(script)


# -- exécution en environnement factice ---------------------------------------------------------

@pytest.fixture(scope='session')
def modele(tmp_path_factory):
    dossier = tmp_path_factory.mktemp('modele')
    copier_modele(dossier)
    return dossier


@pytest.fixture(params=['admin', 'relais'])
def machine(request):
    return request.param


@pytest.fixture
def faux(tmp_path, modele, machine):
    return Faux(tmp_path, modele, machine)


@pytest.fixture
def faux_admin(tmp_path, modele):
    return Faux(tmp_path, modele, 'admin')


@pytest.fixture
def faux_relais(tmp_path, modele):
    return Faux(tmp_path, modele, 'relais')


MODIFIANTS = {'useradd', 'groupadd', 'usermod', 'userdel', 'groupdel', 'gpasswd', 'chown', 'chmod', 'tee', 'tar', 'cp',
              'mv', 'rm', 'rmdir', 'ssh-keygen'}


def modifiant(appel):
    nom = os.path.basename(appel[0])
    if nom in MODIFIANTS:
        return not (nom == 'ssh-keygen' and '-lf' in appel)
    if nom == 'install':
        return True
    if nom == 'sed':
        return '-i' in appel
    if nom == 'systemctl':
        return appel[1] in ('start', 'stop', 'enable', 'disable', 'daemon-reload', 'reload')
    if nom == 'nft':
        return appel[1] in ('delete',)
    return False


def modifiants(faux, appels):
    """Appels modifiants qui touchent autre chose que la zone de travail (copie du code, sauvegardes, journal)."""
    zone = tuple(str(faux.racine / d) for d in ('run/paresia-installation', 'var/backups'))
    retenus = []
    for appel in appels:
        if not modifiant(appel):
            continue
        chemins = [x for x in appel if x.startswith(str(faux.racine))]
        if chemins and all(c.startswith(zone) for c in chemins):
            continue
        retenus.append(appel)
    return retenus


def etat_initial(faux):
    return faux.arbre(), faux.comptes()


def parametres_tunnel_relais(cle, empreinte):
    return ['--adresse-admin', '192.0.2.50', '--cle-publique-tunnel', cle, '--empreinte-cle-tunnel', empreinte]


def tunnel_valeurs(sortie_admin):
    return (re.search(r'CLE_PUBLIQUE_TUNNEL=(ssh-ed25519 \S+ \S+)', sortie_admin).group(1),
            re.search(r'EMPREINTE_CLE_TUNNEL=(SHA256:\S+)', sortie_admin).group(1))


def test_installation_complete_etat_final(installes, machine):
    faux, premiere = getattr(installes, machine), installes.premiere[machine]
    faux.restaurer('installe')
    lignes = premiere.stderr.splitlines()
    assert all(re.fullmatch(r'étape \d+/\d+ [a-z_]+ : (faite|sautée)', l) for l in lignes if not l.startswith('Suite')), lignes
    assert re.search(r'(?m)^Jeu : \d{8}-\d{6}$', premiere.stdout)
    appels = installes.appels_premiere[machine]
    noms = [os.path.basename(a[0]) for a in appels]
    commandes = [' '.join(a) for a in appels]
    assert not any(a[0].endswith('systemctl') and a[1] == 'restart' for a in appels)
    def sans_env(a):
        return [x for x in a if not re.fullmatch(r'[A-Za-z_]+=.*', x)]
    # Seul le nom de la commande compte (le chemin du dépôt peut contenir ces mots) ; docker inspect est en lecture seule.
    interdits = [a for a in map(sans_env, appels)
                 if re.fullmatch(r'strfry|docker|lighttpd|bunkerd', os.path.basename(a[0]))
                 and not (os.path.basename(a[0]) == 'docker' and a[1:2] == ['inspect'])]
    assert not interdits, interdits
    # sshd -t avant chaque reload ssh
    for i, a in enumerate(appels):
        if a[0].endswith('systemctl') and a[1:3] == ['reload', 'ssh']:
            assert any(b[0].endswith('sshd') and b[1] == '-t' for b in appels[:i])
    # comptes avant dossiers ; sauvegarde (copier) avant tout écrasement
    premier_groupe = next(i for i, n in enumerate(noms) if n == 'groupadd')
    premier_install = next(i for i, c in enumerate(commandes) if '/usr/bin/install' in c and '/etc/' in c)
    assert premier_groupe < premier_install
    assert faux.jeux() and (faux.racine / 'var/backups/paresia' / faux.machine / faux.jeux()[0] / 'manifeste.json').exists()
    assert faux.existe('/etc/paresia/paresia.conf')
    assert faux.lire('/usr/local/lib/paresia/VERSION') == (faux.clone / 'VERSION').read_text()     # à côté de server/
    assert etat_initial(faux) != installes.initial[machine]
    enabled = json.loads((faux.etat / 'enabled.json').read_text())
    assert ('pollux.service' in enabled) if machine == 'admin' else ('castor.service' in enabled)
    if machine == 'admin':
        assert {'pollux.service', 'romulus.service'} <= set(enabled)
        assert 'paresia-tunnel.service' not in enabled
    # sans --alpha-test : aucun journal, aucune écriture sous DOSSIER_JOURNAL
    assert not list(faux.travail.iterdir())
    assert not any('alpha-test' in ' '.join(a) for a in appels)


def test_activation_sans_partie_tunnel(installes):
    # --activer sans la partie tunnel (première passe) : seules pollux et romulus sont activées
    installes.admin.restaurer('passe1')
    enabled = json.loads((installes.admin.etat / 'enabled.json').read_text())
    assert 'pollux.service' in enabled and 'romulus.service' in enabled
    assert 'paresia-tunnel.service' not in enabled
    installes.admin.restaurer('installe')


TUNNEL_FACTICE = ('ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIcleDeTestTunnel0123456789abcdefghijKLMNOPQR paresia-tunnel',
                  'SHA256:' + 'A' * 43)


def empreinte_de(cle):
    """Empreinte que le ssh-keygen factice calcule pour une clé publique de test."""
    return 'SHA256:' + base64.b64encode(hashlib.sha256(cle.split()[1].encode()).digest()).decode().rstrip('=')


def test_deuxieme_execution_deja_en_place(installe):
    faux, installes = installe
    extra = arguments_reinstallation(installes, faux.machine)
    jeux, nb_appels = faux.jeux(), len(faux.appels())
    arbre, comptes = faux.arbre(), faux.comptes()
    seconde = faux.installation('--activer', *extra)
    assert seconde.returncode == 0, seconde.stderr
    nouveaux = faux.appels()[nb_appels:]
    assert [a for a in nouveaux if modifiant(a)] == []
    assert faux.jeux() == jeux
    assert faux.arbre() == arbre and faux.comptes() == comptes
    assert 'déjà en place' in seconde.stderr
    assert 'identifiants_comptes : déjà en place' in seconde.stderr
    assert not re.search(r'(?m)^Jeu :', seconde.stdout)


class Installes:
    """Installations complètes faites une seule fois par session (admin en deux passes, relais avec tunnel), puis
    restaurées en place pour chaque test qui part d'un état installé."""


@pytest.fixture(scope='session')
def installes(tmp_path_factory, modele):
    base = tmp_path_factory.mktemp('installes')
    ens = Installes()
    ens.admin, ens.relais = Faux(base / 'a', modele, 'admin'), Faux(base / 'r', modele, 'relais')
    ens.initial = {m: (f.arbre(), f.comptes()) for m, f in (('admin', ens.admin), ('relais', ens.relais))}
    for f in (ens.admin, ens.relais):
        f.instantane('initial')
    p1 = ens.admin.installation('--activer')
    assert p1.returncode == 0, p1.stderr
    cle, empreinte = tunnel_valeurs(p1.stdout)
    jeu = re.search(r'Jeu : (\d{8}-\d{6})', p1.stdout).group(1)
    ens.appels_premiere = {'admin': list(ens.admin.appels())}
    ens.admin.instantane('passe1')
    pr = ens.relais.installation('--activer', *parametres_tunnel_relais(cle, empreinte), '--acces-tunnel-sans-nftables', 'oui')
    assert pr.returncode == 0, pr.stderr
    ens.appels_premiere['relais'] = list(ens.relais.appels())
    hote = re.search(r'EMPREINTE_HOTE_RELAIS=(SHA256:\S+)', pr.stdout).group(1)
    p2 = ens.admin.installation('--activer', '--jeu', jeu, '--adresse-relais', '192.0.2.200', '--empreinte-hote-relais', hote)
    assert p2.returncode == 0, p2.stderr
    ens.premiere = {'admin': p1, 'relais': pr}
    ens.jeu = {'admin': jeu, 'relais': re.search(r'Jeu : (\d{8}-\d{6})', pr.stdout).group(1)}
    ens.tunnel = (cle, empreinte, hote)
    for f in (ens.admin, ens.relais):
        f.instantane('installe')
    return ens


@pytest.fixture
def installe(installes, machine):
    """(Faux restauré à l'état installé, ensemble des installations)."""
    f = getattr(installes, machine)
    f.restaurer('installe')
    return f, installes


def arguments_reinstallation(installes, machine):
    """Paramètres d'une nouvelle passe qui laisse toutes les étapes, tunnel compris, conformes."""
    if machine == 'admin':
        return ['--adresse-relais', '192.0.2.200', '--empreinte-hote-relais', installes.tunnel[2]]
    return parametres_tunnel_relais(installes.tunnel[0], installes.tunnel[1]) + ['--acces-tunnel-sans-nftables', 'oui']


def sans_ecriture(faux, resultat, code_attendu):
    assert resultat.returncode == code_attendu, (resultat.returncode, resultat.stderr)
    assert faux.appels() == [], faux.appels()
    assert faux.jeux() == []


PARAMETRES_INVALIDES = {
    'admin': [
        (['--adresse-relais', '192.0.2.200'], 64), (['--empreinte-hote-relais', 'SHA256:' + 'A' * 43], 64),
        (['--adresse-relais', '192.0.2.200', '--empreinte-hote-relais', 'SHA256:court'], 65),
        (['--adresse-relais', '192.0.2.x y', '--empreinte-hote-relais', 'SHA256:' + 'A' * 43], 65),
        (['--adresse-relais', 'relais.example.org', '--empreinte-hote-relais', 'SHA256:' + 'A' * 43], 65),
        (['--repertoire-app', HOME + '/app'], 65), (['--repertoire-app', '/var/..' + HOME + '/app'], 65),
        (['--repertoire-app', '/var/lib/autre'], 65), (['--repertoire-app', 'relatif'], 65),
        (['--sauter', 'inconnu'], 65), (['--sauter', 'sudoers,tout'], 65),
        (['--adresse-relais', '300.1.1.1', '--empreinte-hote-relais', 'SHA256:' + 'A' * 43], 65),
        (['--dossier-journal', '/var/log/a b'], 65), (['--dossier-journal', '/var/log/a;b'], 65),
        (['--depot', '/nonexistent'], 65), (['--option-inconnue'], 64), (['--depot'], 64),
        (['--session-secours', 'peut-etre'], 65), (['--langue', 'francais'], 65),
        (['--jeu', 'pas-un-jeu'], 65), (['--retour-arriere'], 64), (['--retour-arriere', '--jeu', '20260101-000000'], 64),
        (['--confirme'], 64), (['--verifier', '--alpha-test'], 64),
        (['--dossier-journal', '/var/log/paresia'], 65), (['--dossier-journal', '/var/log/paresia/x'], 65),
    ],
    'relais': [
        (['--adresse-admin', '192.0.2.50'], 64),
        (['--adresse-admin', '192.0.2.50', '--cle-publique-tunnel', TUNNEL_FACTICE[0]], 64),
        (['--cle-publique-tunnel', TUNNEL_FACTICE[0], '--empreinte-cle-tunnel', TUNNEL_FACTICE[1]], 64),
        (['--adresse-admin', '192.0.2.5 0', '--cle-publique-tunnel', TUNNEL_FACTICE[0],
          '--empreinte-cle-tunnel', TUNNEL_FACTICE[1]], 65),
        (['--adresse-admin', '192.0.2.50', '--cle-publique-tunnel', 'ssh-rsa AAAAB3 x',
          '--empreinte-cle-tunnel', TUNNEL_FACTICE[1]], 65),
        (['--adresse-admin', '192.0.2.50', '--cle-publique-tunnel', 'AAAAC3NzaC1lZDI1NTE5 x',
          '--empreinte-cle-tunnel', TUNNEL_FACTICE[1]], 65),
        (['--adresse-admin', '192.0.2.50', '--cle-publique-tunnel', TUNNEL_FACTICE[0],
          '--empreinte-cle-tunnel', 'SHA256:court'], 65),
        (['--profil', 'autre'], 65), (['--profil', ''], 64), (['--port-essai', '1023'], 65),
        (['--port-essai', '65536'], 65), (['--port-essai', 'abc'], 65), (['--port-essai', '80'], 65),
        (['--repertoire-tunnel', HOME + '/tunnel'], 65), (['--repertoire-tunnel', HOME], 65),
        (['--repertoire-tunnel', '/var/..' + HOME + '/tunnel'], 65), (['--repertoire-tunnel', 'relatif'], 65),
        (['--sauter', 'inconnu'], 65), (['--depot', '/nonexistent'], 65),
        (['--acces-tunnel-sans-nftables', 'x'], 65),
        (['--adresse-admin', '192.0.2.999', '--cle-publique-tunnel', TUNNEL_FACTICE[0],
          '--empreinte-cle-tunnel', TUNNEL_FACTICE[1]], 65),
        (['--repertoire-tunnel', '/var/lib/a b'], 65), (['--repertoire-tunnel', '/var/lib/a;b'], 65),
        (['--repertoire-tunnel', '/var/lib/$(id)'], 65),
    ],
}


@pytest.mark.parametrize('machine_', ['admin', 'relais'])
def test_parametres_invalides_aucune_ecriture(tmp_path, modele, machine_):
    for i, (options, attendu) in enumerate(PARAMETRES_INVALIDES[machine_]):
        faux = Faux(tmp_path / f'c{i}', modele, machine_)
        avant = faux.arbre()
        resultat = faux.lancer(*options)
        assert resultat.returncode == attendu, (options, resultat.returncode, resultat.stderr)
        assert faux.appels() == [] and faux.jeux() == [] and faux.arbre() == avant, options


def test_valeurs_par_defaut_posees_avant_controle(faux):
    # PROFIL, PORT_ESSAI, REPERTOIRE_* et DOSSIER_JOURNAL ont un défaut valide : --verifier réussit sans option
    resultat = faux.lancer('--verifier')
    assert resultat.returncode == 0, resultat.stderr
    assert faux.appels() and all(not modifiant(a) for a in faux.appels())
    assert faux.jeux() == []
    if faux.machine == 'relais':
        assert faux.lancer('--verifier', '--port-essai', '1024').returncode == 0
        assert faux.lancer('--verifier', '--port-essai', '65535').returncode == 0
        assert faux.lancer('--verifier', '--profil', 'partage').returncode == 0
        assert faux.lancer('--verifier', env={'PORT_ESSAI': '1023'}).returncode == 65
        assert faux.lancer('--verifier', env={'PROFIL': 'x'}).returncode == 65


def test_variables_denvironnement_et_options(faux_relais):
    f = faux_relais
    assert f.lancer('--verifier', env={'REPERTOIRE_TUNNEL': HOME + '/x'}).returncode == 65
    assert f.lancer('--verifier', '--repertoire-tunnel', '/var/lib/ailleurs', env={'REPERTOIRE_TUNNEL': HOME + '/x'}).returncode == 0


def test_verifier_prerequis(faux):
    arbre = faux.arbre()
    assert faux.lancer('--verifier').returncode == 0
    assert faux.arbre() == arbre and faux.jeux() == []
    faux.ecrire('/etc/os-release', 'ID=debian\nVERSION_ID="12"\n')
    resultat = faux.lancer('--verifier')
    assert resultat.returncode == 69 and 'debian-13' in resultat.stderr


def test_prerequis_module_cryptography():
    # python3 est le vrai /usr/bin/python3 du faux système : l'absence du module n'y est pas simulable ; on vérifie le contrôle
    corps = fonctions(ADMIN)['controle_prerequis']
    assert "if ! /usr/bin/python3 -I -c 'import cryptography'; then" in corps
    assert re.search(r"import cryptography'; then[^\n]*\n\s+accumuler python3-cryptography\n", corps)
    assert 'python3-cryptography' in texte(ADMIN).split('Codes de sortie')[0]


def test_depot_defaut_racine_du_clone_et_controles(tmp_path, modele):
    f = Faux(tmp_path, modele, 'admin')
    assert f.lancer('--verifier').returncode == 0      # le script se trouve dans le clone : DEPOT par défaut
    isole = tmp_path / 'isole/deploy/backend-admin'
    isole.mkdir(parents=True)
    shutil.copy(ADMIN, isole / 'installer-backend-admin.sh')
    resultat = subprocess.run(['/bin/bash', str(isole / 'installer-backend-admin.sh'), '--verifier'],
                              env=f.environnement(), text=True, capture_output=True, timeout=60)
    assert resultat.returncode == 65 and 'install_err_depot' in resultat.stderr    # clés brutes avant le catalogue
    lien = tmp_path / 'lien'
    lien.symlink_to(f.clone)
    assert f.lancer('--verifier', '--depot', str(lien)).returncode == 65


def test_roles_root_et_compte_ordinaire(tmp_path, modele):
    relais = Faux(tmp_path / 'r', modele, 'relais', uid=0)
    r = relais.lancer('--verifier')
    assert r.returncode == 77 and relais.appels() == []
    admin = Faux(tmp_path / 'a', modele, 'admin', uid=1000)
    r = admin.lancer('--verifier')
    assert r.returncode == 77 and admin.appels() == []


def test_messages_par_catalogue(faux):
    en = faux.lancer('--sauter', 'x', '--langue', 'en-US')
    fr = faux.lancer('--sauter', 'x', '--langue', 'fr-FR')
    assert en.returncode == fr.returncode == 65
    assert 'Invalid value for --sauter: x' in en.stderr and 'Valeur invalide pour --sauter : x' in fr.stderr
    # langue dérivée de l'environnement
    assert 'Invalid value' in faux.lancer('--sauter', 'x', env={'LC_ALL': 'en' + '_US.UTF-8'}).stderr
    assert 'Valeur invalide' in faux.lancer('--sauter', 'x', env={'LC_ALL': 'C'}).stderr
    # clé retirée d'un catalogue de test : la clé elle-même est affichée
    chemin = faux.clone / 'i18n/fr-FR.json'
    catalogue = json.loads(chemin.read_text(encoding='utf-8'))
    del catalogue['install_err_param_invalide']
    chemin.write_text(json.dumps(catalogue, ensure_ascii=False), encoding='utf-8')
    assert faux.lancer('--sauter', 'x', '--langue', 'fr-FR').stderr.strip() == 'install_err_param_invalide'
    # caractère de contrôle dans une valeur : absent de l'affichage
    resultat = faux.lancer('--sauter', 'a\x07b\x1b[31m', '--langue', 'fr-FR')
    assert '\x07' not in resultat.stderr and '\x1b' not in resultat.stderr
    # catalogue illisible : clé brute et code 66
    chemin.write_text('{pas du json', encoding='utf-8')
    brut = faux.lancer('--verifier', '--langue', 'fr-FR')
    assert brut.returncode == 66 and brut.stderr.strip() == 'install_err_catalogue'


def test_etat_non_conforme_compte_existant_autre_uid(faux):
    if faux.machine == 'admin':
        nom, ligne, groupe = 'app', 'app:x:5000:5000::' + HOME + '/x:/bin/sh', 'app:x:5000:'
    else:
        nom, ligne, groupe = 'chef', 'chef:x:5000:5000::/nonexistent:/usr/sbin/nologin', 'chef:x:5000:'
    (faux.etat / 'passwd').write_text((faux.etat / 'passwd').read_text() + ligne + '\n')
    (faux.etat / 'group').write_text((faux.etat / 'group').read_text() + groupe + '\n')
    avant = (faux.arbre(), faux.comptes())
    resultat = faux.installation()
    assert resultat.returncode == 78 and 'ÉCART' in resultat.stderr and nom in resultat.stderr
    assert (faux.arbre(), faux.comptes()) == avant
    assert modifiants(faux, faux.appels()) == []


def test_repertoire_tunnel_sous_home_refuse(faux_relais):
    f = faux_relais
    (f.etat / 'passwd').write_text((f.etat / 'passwd').read_text() + 'tunnel:x:972:972::' + HOME + '/tunnel:/usr/sbin/nologin\n')
    (f.etat / 'group').write_text((f.etat / 'group').read_text() + 'tunnel:x:972:\n')
    avant = (f.arbre(), f.comptes())
    resultat = f.installation()
    assert resultat.returncode == 78 and HOME + '/tunnel' in resultat.stderr
    assert (f.arbre(), f.comptes()) == avant and modifiants(f, f.appels()) == []


@pytest.mark.parametrize('cas', ['unite_active', 'code_sans_confirmation', 'unite_sans_confirmation'])
def test_etat_non_conforme_unite_et_code(installe, cas):
    faux, _ = installe
    unite = '/etc/systemd/system/' + ('pollux.service' if faux.machine == 'admin' else 'castor.service')
    code_chemin = '/usr/local/lib/paresia/server/commun/__init__.py'
    if cas == 'code_sans_confirmation':
        faux.ecrire(code_chemin, '# modifié\n')
    else:
        faux.ecrire(unite, faux.lire(unite) + '# modifiée\n')
    arbre, nb = faux.arbre(), len(faux.appels())
    env_confirme = ['--code-remplacement-confirme', 'oui'] if cas == 'unite_active' else []
    resultat = faux.installation(*env_confirme)
    assert resultat.returncode == 78, resultat.stderr
    if cas == 'unite_active':
        assert 'est active' in resultat.stderr
    assert faux.arbre() == arbre
    assert modifiants(faux, faux.appels()[nb:]) == []


def test_session_secours_absent_aucun_reload_ni_sshd(faux):
    args = ['--session-secours', 'non']
    if faux.machine == 'relais':
        cle = TUNNEL_FACTICE[0]
        args += parametres_tunnel_relais(cle, empreinte_de(cle)) + ['--acces-tunnel-sans-nftables', 'oui']
    resultat = faux.lancer(*args, *(['--port-essai', str(faux.port)] if faux.machine == 'relais' else []))
    assert resultat.returncode == 78 and '--session-secours' in resultat.stderr
    assert not any(a[0].endswith('systemctl') and a[1:3] == ['reload', 'ssh'] for a in faux.appels())
    assert not faux.existe('/etc/ssh/sshd_config.d/50-paresia-app.conf')
    assert not faux.existe('/etc/ssh/sshd_config.d/50-paresia-tunnel.conf')


def test_sshd_t_en_echec_restaure_le_fichier(faux_admin):
    f = faux_admin
    f.regler(sshd_t_echec=True)
    resultat = f.installation()
    assert resultat.returncode == 78 and 'sshd -t a échoué' in resultat.stderr
    assert not f.existe('/etc/ssh/sshd_config.d/50-paresia-app.conf')
    assert not any(a[0].endswith('systemctl') and a[1:3] == ['reload', 'ssh'] for a in f.appels())


def test_tunnel_deux_machines_et_empreintes(tmp_path, modele):
    admin = Faux(tmp_path / 'a', modele, 'admin')
    relais = Faux(tmp_path / 'r', modele, 'relais')
    premiere = admin.installation()
    assert premiere.returncode == 0, premiere.stderr
    cle, empreinte = tunnel_valeurs(premiere.stdout)
    # relais : empreinte divergente -> refus, aucun authorized_keys
    mauvaise = 'SHA256:' + 'B' * 43
    r = relais.installation('--sauter', 'nftables', *parametres_tunnel_relais(cle, mauvaise), '--acces-tunnel-sans-nftables', 'oui')
    assert r.returncode == 78 and 'empreinte divergente' in r.stderr
    assert not relais.existe('/var/lib/paresia-tunnel/.ssh/authorized_keys')
    assert not relais.existe('/etc/ssh/sshd_config.d/50-paresia-tunnel.conf')
    # relais : table absente sans autorisation -> refus
    r = relais.installation('--sauter', 'nftables', *parametres_tunnel_relais(cle, empreinte))
    assert r.returncode == 78 and 'paresia_relais' in r.stderr
    # relais : succès et empreinte de la clé d'hôte affichée
    r = relais.installation('--sauter', 'nftables', *parametres_tunnel_relais(cle, empreinte), '--acces-tunnel-sans-nftables', 'oui')
    assert r.returncode == 0, r.stderr
    hote = re.search(r'EMPREINTE_HOTE_RELAIS=(SHA256:\S+)', r.stdout).group(1)
    autorized = relais.lire('/var/lib/paresia-tunnel/.ssh/authorized_keys')
    assert autorized == f'restrict,port-forwarding,from="192.0.2.50",command="/bin/false" {cle}\n'
    assert relais.existe('/etc/ssh/sshd_config.d/50-paresia-tunnel.conf')
    # admin : empreinte d'hôte divergente -> refus, known_hosts non posé
    r = admin.installation('--adresse-relais', '192.0.2.200', '--empreinte-hote-relais', 'SHA256:' + 'C' * 43)
    assert r.returncode == 78 and 'empreinte divergente' in r.stderr
    assert not admin.existe('/etc/paresia/tunnel/known_hosts')
    # admin : 2e passe conforme ; les étapes de la 1re passe sont reconnues
    r = admin.installation('--adresse-relais', '192.0.2.200', '--empreinte-hote-relais', hote)
    assert r.returncode == 0, r.stderr
    assert 'dossier_app : déjà en place' in r.stderr and 'tunnel_cle : déjà en place' in r.stderr
    assert 'tunnel_known_hosts : faite' in r.stderr and 'tunnel_unite : faite' in r.stderr
    assert 'HostName 192.0.2.200' in admin.lire('/etc/paresia/tunnel/ssh_config.d/10-relais.conf')
    assert admin.lire('/etc/paresia/tunnel/known_hosts').startswith('192.0.2.200 ssh-ed25519 ')
    # la clé privée n'est jamais affichée ni copiée
    for sortie in (premiere.stdout + premiere.stderr + r.stdout + r.stderr,):
        assert SENTINELLE not in sortie
    sauvegardes = ''.join(p.read_text(errors='ignore') for p in (admin.racine / 'var/backups').rglob('*') if p.is_file())
    assert SENTINELLE not in sauvegardes


def test_retour_arriere(installe):
    faux, installes = installe
    jeu = installes.jeu[faux.machine]
    assert (faux.arbre(), faux.comptes()) != installes.initial[faux.machine]
    # refus sans --confirme ou sans --jeu
    assert faux.lancer('--retour-arriere', '--jeu', jeu).returncode == 64
    assert faux.lancer('--retour-arriere', '--confirme').returncode == 64
    sans_secours = faux.lancer('--retour-arriere', '--jeu', jeu, '--confirme')
    assert sans_secours.returncode == 78 and '--session-secours' in sans_secours.stderr
    retour = faux.lancer('--retour-arriere', '--jeu', jeu, '--confirme', '--session-secours', 'oui')
    assert retour.returncode == 0, retour.stderr
    assert (faux.arbre(), faux.comptes()) == installes.initial[faux.machine]
    assert json.loads((faux.etat / 'actives.json').read_text()) == []
    # idempotent
    nb = len(faux.appels())
    encore = faux.lancer('--retour-arriere', '--jeu', jeu, '--confirme', '--session-secours', 'oui')
    assert encore.returncode == 0, encore.stderr
    assert (faux.arbre(), faux.comptes()) == installes.initial[faux.machine]
    assert not any(a[0].endswith(('useradd', 'userdel', 'groupdel')) for a in faux.appels()[nb:])


def test_retour_arriere_sans_sauvegarde_echoue(faux_admin):
    f = faux_admin
    r = f.lancer('--retour-arriere', '--jeu', '20260101-000000', '--confirme', '--stockage-actif', 'non')
    assert r.returncode == 78 and 'sauvegardes sont désactivées' in r.stderr


# -- --alpha-test sous pseudo-terminal ----------------------------------------------------------

INVITE = 'Entrée pour continuer'.encode()


def lancer_pty(faux, args, env=None, repondre=True, timeout=240):
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(faux.travail)
        os.execve('/bin/bash', ['bash', str(faux.script), *args], faux.environnement(env))
    sortie, envoyees, fin = b'', 0, time.time() + timeout
    while True:
        if time.time() > fin:
            os.kill(pid, signal.SIGKILL)
            pytest.fail('délai dépassé : ' + sortie.decode(errors='replace')[-2000:])
        lisible, _, _ = select.select([fd], [], [], 1)
        if not lisible:
            continue
        try:
            donnees = os.read(fd, 4096)
        except OSError:
            break
        if not donnees:
            break
        sortie += donnees
        if repondre and sortie.count(INVITE) > envoyees:
            envoyees = sortie.count(INVITE)
            os.write(fd, b'\n')
    _, statut = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(statut), sortie.decode(errors='replace'), envoyees


def journaux(faux):
    return sorted(faux.travail.glob('alpha-test-*.log'))


def test_alpha_test_pause_par_etape_et_journal(faux):
    extra = ['--sauter', 'nftables'] if faux.machine == 'relais' else []
    (faux.etat / 'knobs.json').write_text(json.dumps({'journal_extra': 'ligne\x07piegee\x1b[2J'}))
    code_sortie, sortie, pauses = lancer_pty(faux, ['--alpha-test', '--session-secours', 'oui', *extra,
                                                    *(['--port-essai', str(faux.port)] if faux.machine == 'relais' else [])])
    assert code_sortie == 0, sortie[-3000:]
    etapes = re.findall(r'étape (\d+)/(\d+) ', sortie)
    assert pauses == len(etapes) - sortie.count(' : sautée') + 0 or pauses >= len(etapes) - 2
    assert 'vérifié : ' in sortie and 'constaté : ' in sortie and 'ATTENTION' in sortie
    fichiers = journaux(faux)
    assert len(fichiers) == 1
    journal = fichiers[0]
    assert re.fullmatch(rf'alpha-test-{faux.machine}-\d{{8}}-\d{{6}}\.log', journal.name)
    assert oct(journal.stat().st_mode & 0o777) == '0o600' and journal.parent == faux.travail
    assert journal.stat().st_uid == os.getuid()      # créé par le compte qui lance le script, jamais par sudo
    assert not any(os.path.basename(a[0]) in ('tee', 'install') and str(journal) in ' '.join(a) for a in faux.appels())
    contenu = journal.read_text(encoding='utf-8')
    lignes = contenu.splitlines()
    assert lignes and all(re.match(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z ', l) for l in lignes), [l for l in lignes if not re.match(r'\d{4}-', l)][:3]
    assert '\x07' not in contenu and '\x1b' not in contenu and '\x07' not in sortie and '\x1b[2J' not in sortie
    chemin = str(journal)
    assert sortie.count(f'Journal : {chemin}') >= 2 and f'/usr/bin/cat {chemin}' in sortie and f'sudo /usr/bin/cat {chemin}' not in sortie
    assert SENTINELLE not in sortie and SENTINELLE not in contenu
    if faux.machine == 'admin':       # la valeur sentinelle n'existe que dans la fausse clé privée du tunnel
        assert faux.lire('/etc/paresia/tunnel/id_ed25519').count(SENTINELLE) == 1
        for p in faux.racine.rglob('*'):
            if p.is_file() and p.name != 'id_ed25519':
                assert SENTINELLE not in p.read_text(errors='ignore'), p


def test_alpha_test_arret_au_premier_ecart_et_chemin_a_la_fin(faux):
    nom, ligne, groupe = ('app', 'app:x:5000:5000::' + HOME + '/x:/bin/sh', 'app:x:5000:') if faux.machine == 'admin' \
        else ('chef', 'chef:x:5000:5000::/nonexistent:/usr/sbin/nologin', 'chef:x:5000:')
    (faux.etat / 'passwd').write_text((faux.etat / 'passwd').read_text() + ligne + '\n')
    (faux.etat / 'group').write_text((faux.etat / 'group').read_text() + groupe + '\n')
    code_sortie, sortie, pauses = lancer_pty(faux, ['--alpha-test', '--session-secours', 'oui'])
    assert code_sortie == 78 and 'ÉCART : ' in sortie
    assert pauses == (2 if faux.machine == 'admin' else 3)   # prérequis, sauvegarde (et, sur le relais, contrôle du produit)
    assert sortie.index('ÉCART') > sortie.rindex('Entrée pour continuer')
    assert sortie.count('Journal : ') >= 2          # au début et à la fin, y compris en cas d'échec
    assert len(journaux(faux)) == 1 and 'ÉCART' in journaux(faux)[0].read_text(encoding='utf-8')


def test_alpha_test_refuse_sans_terminal(faux):
    avant = faux.arbre()
    resultat = faux.lancer('--alpha-test', entree='')
    assert resultat.returncode == 64 and 'terminal' in resultat.stderr
    assert faux.arbre() == avant and journaux(faux) == []


# -- aide, version, remplacement confirmé -------------------------------------------------------

def test_aide_et_version(faux):
    avant = faux.arbre()
    aide = faux.lancer('--aide')
    assert aide.returncode == 0 and '--retour-arriere' in aide.stdout and aide.stderr == ''
    assert faux.lancer('--help').stdout == aide.stdout
    anglais = faux.lancer('--aide', '--langue', 'en-US')
    assert 'No question is asked' in anglais.stdout
    version = faux.lancer('--version')
    assert version.returncode == 0 and re.fullmatch(rf'installer-backend-{faux.machine} \d+\.\d+\.\d+\n', version.stdout)
    assert faux.arbre() == avant and faux.appels() == []


def test_remplacement_confirme_rétablit_le_code(installe):
    faux, _ = installe
    fichier = '/usr/local/lib/paresia/server/commun/__init__.py'
    origine = faux.lire(fichier)
    faux.ecrire(fichier, '# modifié à la main\n')
    refus = faux.installation()
    assert refus.returncode == 78 and '--code-remplacement-confirme' in refus.stderr
    assert faux.lire(fichier) == '# modifié à la main\n'
    encore_actif = faux.installation('--code-remplacement-confirme', 'oui')
    assert encore_actif.returncode == 78 and 'est active' in encore_actif.stderr      # le script ne redémarre rien
    (faux.etat / 'actives.json').write_text('[]')                                     # l'administrateur arrête les démons
    accepte = faux.installation('--code-remplacement-confirme', 'oui')
    assert accepte.returncode == 0, accepte.stderr
    assert faux.lire(fichier) == origine
    # l'ancien contenu a été sauvegardé avant d'être remplacé
    sauvegardes = [p for p in (faux.racine / 'var/backups').rglob('__init__.py') if p.read_text() == '# modifié à la main\n']
    assert sauvegardes


# -- corrections du premier cycle de relecture ---------------------------------------------------

def test_releves_etat_avant_dans_le_jeu(installe):
    faux, _ = installe
    releves = faux.racine / 'var/backups/paresia' / faux.machine / faux.jeux()[0] / 'releves'
    noms = {p.name for p in releves.iterdir()}
    assert {'comptes-avant', 'groupes-avant', 'unites-actives-avant', 'sshd-app-avant', 'sshd-tunnel-avant'} <= noms
    assert SENTINELLE not in ''.join(p.read_text() for p in releves.iterdir())


def test_depot_modifiable_refuse(faux):
    os.chmod(faux.clone, 0o775)
    assert faux.lancer('--verifier').returncode == 65
    os.chmod(faux.clone, 0o755)
    assert faux.lancer('--verifier').returncode == 0


@pytest.mark.parametrize('mode', [0o775, 0o757, 0o777])
def test_dossier_journal_modifiable_par_d_autres_refuse_avant_creation(faux, mode):
    os.chmod(faux.travail, mode)
    code_sortie, sortie, pauses = lancer_pty(faux, ['--alpha-test', '--session-secours', 'oui'])
    assert code_sortie == 78 and 'Le dossier du journal' in sortie and pauses == 0, sortie[-1500:]
    assert oct(faux.travail.stat().st_mode & 0o777) == oct(mode) and not list(faux.travail.iterdir())
    assert not any(a[0].endswith('chmod') and str(faux.travail) in ' '.join(a) for a in faux.appels())
    assert faux.jeux() == []


def test_sshd_t_en_echec_restaure_les_fichiers_du_relais(faux_relais):
    f = faux_relais
    cle = TUNNEL_FACTICE[0]
    f.regler(sshd_t_echec=True, allowusers='quelquun')
    r = f.installation('--sauter', 'nftables', *parametres_tunnel_relais(cle, empreinte_de(cle)),
                       '--acces-tunnel-sans-nftables', 'oui')
    assert r.returncode == 78 and 'sshd -t a échoué' in r.stderr
    assert not f.existe('/etc/ssh/sshd_config.d/50-paresia-tunnel.conf')
    assert not f.existe('/etc/ssh/sshd_config.d/40-paresia-tunnel-allowusers.conf')
    assert not any(a[0].endswith('systemctl') and a[1:3] == ['reload', 'ssh'] for a in f.appels())


def test_known_hosts_a_plusieurs_lignes_refuse(installes):
    admin = installes.admin
    admin.restaurer('passe1')
    admin.regler(keyscan_lignes=2)
    r = admin.installation('--adresse-relais', '192.0.2.200', '--empreinte-hote-relais', installes.tunnel[2])
    assert r.returncode == 78 and 'known_hosts.nouveau:lignes' in r.stderr
    assert not admin.existe('/etc/paresia/tunnel/known_hosts') and not admin.existe('/run/paresia-installation/known_hosts.nouveau')


def test_systemctl_version_a_sortie_longue(faux):
    faux.regler(version_longue=20000)       # sortie bien plus longue que le tube : aucun SIGPIPE sous pipefail
    r = faux.lancer('--verifier')
    assert r.returncode == 0, r.stderr


def test_nsenter_en_ecart_detecte():
    t = ADMIN.read_text(encoding='utf-8')
    definition = re.search(r'(?ms)^attributs_vus_par_pollux\(\) \{.*?^\}', t).group()
    def releve(ligne):
        script = ('systemctl() { echo 4242; }\nsudo() { printf "%s\\n" "$1" > /dev/null; printf "%s\\n" "$LIGNE"; }\n'
                  'filtre_sortie() { cat; }\n' + definition + '\nattributs_vus_par_pollux\n')
        return subprocess.run(['bash', '--noprofile', '--norc'], input=script, env={'PATH': '/usr/bin:/bin', 'LIGNE': ligne},
                              text=True, capture_output=True, timeout=10).stdout.strip()
    assert releve('-rw-r--r-- 1 root root 0 nov. 7 12:00 f') == 'root:root 644'
    assert releve('-rw-r--r-- 1 app app 0 nov. 7 12:00 f') == 'app:app 644'
    assert releve('-rw-rw-rw- 1 root root 0 nov. 7 12:00 f') == 'root:root -rw-rw-rw-'
    assert 'root:root 644' != releve('-rw------- 1 root root 0 nov. 7 12:00 f')


def test_version_installee_a_cote_du_code(installe):
    faux, _ = installe
    assert faux.lire('/usr/local/lib/paresia/VERSION') == (faux.clone / 'VERSION').read_text()
    assert oct(faux.chemin('/usr/local/lib/paresia/VERSION').stat().st_mode & 0o777) == '0o644'
    assert faux.existe('/usr/local/lib/paresia/server')
    # fichier absent ou modifié : l'état n'est plus conforme
    faux.ecrire('/usr/local/lib/paresia/VERSION', '0.0.0\n')
    assert faux.installation().returncode == 78
    faux.chemin('/usr/local/lib/paresia/VERSION').unlink()
    assert faux.installation().returncode == 78
    # la copie root qui sert à l'outil de sauvegarde la porte aussi
    assert (faux.clone / 'VERSION').read_text() == faux.lire('/run/paresia-installation/VERSION')


def test_tunnel_tmpfiles_installe_et_dossiers_attendus(installes):
    admin = installes.admin
    admin.restaurer('installe')
    assert admin.lire('/etc/tmpfiles.d/paresia-tunnel.conf') == (admin.clone / 'deploy/backend-admin/etc/tmpfiles.d/paresia-tunnel.conf').read_text()
    assert oct(admin.chemin('/etc/tmpfiles.d/paresia-tunnel.conf').stat().st_mode & 0o777) == '0o644'
    appels = [' '.join(a) for a in admin.appels()]
    creation = next(i for i, c in enumerate(appels) if 'systemd-tmpfiles --create' in c)
    demarrage = next(i for i, c in enumerate(appels) if 'systemctl start paresia-tunnel.service' in c)
    assert creation < demarrage
    assert not any('setfacl' in c or 'getfacl' in c for c in appels)
    assert not any('setfacl' in l for l in code(ADMIN))
    for chemin in ('/run/paresia-tunnel', '/run/paresia-tunnel/romulus', '/run/paresia-tunnel/pollux'):
        assert admin.existe(chemin)       # créés par tmpfiles ; leurs modes et propriétaires sont contrôlés par le script


def test_tmpfiles_en_echec_arrete_avant_le_demarrage(installes):
    admin = installes.admin
    admin.restaurer('passe1')
    admin.regler(echec_commande='systemd-tmpfiles')
    nb = len(admin.appels())
    r = admin.installation('--adresse-relais', '192.0.2.200', '--empreinte-hote-relais', installes.tunnel[2])
    assert r.returncode != 0
    nouveaux = [' '.join(a) for a in admin.appels()[nb:]]
    assert any('systemd-tmpfiles --create' in c for c in nouveaux)
    assert not any('start paresia-tunnel' in c or 'systemd-analyze verify paresia-tunnel' in c for c in nouveaux)


# -- cycle de correction : sécurité des scripts (python3 -I, dossier courant, clé publique, journal, tar, journalctl, DEPOT)

def lignes_python_c(script):
    return [l for l in code(script) if re.search(r'python3\b.*\s-c\b', l)]


@pytest.mark.parametrize('script', SCRIPTS, ids=lambda p: p.name)
def test_python3_c_toujours_en_mode_isole(script):
    lignes = lignes_python_c(script)
    assert lignes
    for ligne in lignes:
        assert re.search(r'python3 (?:-\w+ )*-I\b', ligne), ligne          # python3(1) : -I isole du dossier courant et de PYTHON*


@pytest.mark.parametrize('script', SCRIPTS, ids=lambda p: p.name)
def test_cd_racine_apres_resolution_du_chemin_du_script(script):
    t = texte(script)
    principal = t[t.index('\nprincipal() {'):]
    avant_cd = principal[:principal.index('    cd /\n')]
    commandes = [l.strip() for l in avant_cd.splitlines()[2:] if l.strip() and not l.strip().startswith('#')]
    assert commandes == ['resoudre_racine_clone', 'DOSSIER_LANCEMENT=$(pwd -P 2> /dev/null || true)']
    assert principal.index('    cd /\n') < principal.index('trap sortie_script EXIT') < principal.index('defauts_machine')
    assert 'BASH_SOURCE' in fonctions(script)['resoudre_racine_clone']


def test_runuser_python_avec_option_i_a_lexecution(installes, machine):
    appels = [a for a in installes.appels_premiere[machine] if os.path.basename(a[0]) == 'runuser']
    sous_python = [a for a in appels if '-c' in a and any(x.endswith('python3') for x in a)]
    assert sous_python
    for a in sous_python:
        assert a[a.index('-c') - 1] == '-I', a


def test_dossier_de_lancement_piege_sans_effet(tmp_path, modele, machine):
    faux = Faux(tmp_path / 'f', modele, machine)
    piege = tmp_path / 'piege'
    piege.mkdir()
    sentinelle = tmp_path / 'piege-execute'
    for nom in ('socket.py', 'json.py', 'ipaddress.py', 're.py'):
        (piege / nom).write_text(f'open({str(sentinelle)!r}, "w").write("x")\n')
    base = ['--session-secours', 'oui'] + (['--port-essai', str(faux.port)] if machine == 'relais' else [])
    chemin_relatif = os.path.relpath(faux.script, piege)           # chemin relatif : DEPOT est résolu avant le cd /
    resultat = subprocess.run(['/bin/bash', chemin_relatif, *base], env=faux.environnement(),
                              text=True, capture_output=True, timeout=240, cwd=piege)
    assert resultat.returncode == 0, resultat.stderr
    assert not sentinelle.exists()
    assert faux.existe('/etc/paresia/paresia.conf')


CORPS_VALIDE = 'AAAAC3NzaC1lZDI1NTE5AAAAI' + 'cleDeTestTunnel0123456789abcdefghijKLMNOPQR'


@pytest.mark.parametrize('cle', [
    'ssh-ed25519 ' + CORPS_VALIDE, 'ssh-ed25519 ' + CORPS_VALIDE + ' paresia-tunnel',
    'ssh-ed25519 ' + CORPS_VALIDE + ' ' + 'c' * 64, 'ssh-ed25519 AAAA' + 'A' * 64, 'ssh-ed25519 AAAA' + 'A' * 128 + '=='])
def test_cle_publique_de_forme_valide_acceptee(faux_relais, cle):
    resultat = faux_relais.lancer('--verifier', *parametres_tunnel_relais(cle, TUNNEL_FACTICE[1]))
    assert resultat.returncode == 0, resultat.stderr


@pytest.mark.parametrize('cle', [
    'ssh-rsa ' + CORPS_VALIDE, 'ssh-ed25519 AAAA' + 'A' * 63, 'ssh-ed25519 AAAA' + 'A' * 129,
    'ssh-ed25519 ' + CORPS_VALIDE + '\r', 'ssh-ed25519 ' + CORPS_VALIDE + ' a\tb', 'ssh-ed25519 ' + CORPS_VALIDE + ' a\x07b',
    'ssh-ed25519 ' + CORPS_VALIDE + '\n', 'ssh-ed25519 ' + CORPS_VALIDE + ' ' + 'c' * 65,
    'ssh-ed25519 ' + CORPS_VALIDE + '\nssh-ed25519 ' + CORPS_VALIDE, 'ssh-ed25519 ' + CORPS_VALIDE + ' é',
    'ssh-ed25519 BBBB' + 'A' * 64])
def test_cle_publique_hors_forme_refusee_sans_ecriture(faux_relais, cle):
    avant = faux_relais.arbre()
    resultat = faux_relais.lancer(*parametres_tunnel_relais(cle, TUNNEL_FACTICE[1]), '--session-secours', 'oui')
    sans_ecriture(faux_relais, resultat, 65)
    assert faux_relais.arbre() == avant


def test_dossier_journal_absent_refuse_avant_creation(faux):
    code_sortie, sortie, pauses = lancer_pty(faux, ['--alpha-test', '--session-secours', 'oui',
                                                    '--dossier-journal', '/var/absent/journal'])
    assert code_sortie == 78 and 'Le dossier du journal' in sortie and pauses == 0, sortie[-1500:]
    assert not (faux.racine / 'var/absent').exists() and not list(faux.travail.iterdir())
    assert faux.jeux() == []


def test_dossier_journal_option_dans_dossier_conforme(faux):
    # un compte en conflit arrête l'essai à la troisième étape (quatrième sur le relais, qui contrôle d'abord le produit), ce qui borne la durée
    ligne, groupe = ('app:x:5000:5000::/nonexistent:/bin/sh', 'app:x:5000:') if faux.machine == 'admin' \
        else ('chef:x:5000:5000::/nonexistent:/usr/sbin/nologin', 'chef:x:5000:')
    (faux.etat / 'passwd').write_text((faux.etat / 'passwd').read_text() + ligne + '\n')
    (faux.etat / 'group').write_text((faux.etat / 'group').read_text() + groupe + '\n')
    ailleurs = faux.base / 'ailleurs'
    ailleurs.mkdir()
    os.chmod(ailleurs, 0o700)
    code_sortie, sortie, pauses = lancer_pty(faux, ['--alpha-test', '--session-secours', 'oui', '--dossier-journal', str(ailleurs)])
    assert code_sortie == 78 and 'ÉCART' in sortie and pauses == (2 if faux.machine == 'admin' else 3), sortie[-1500:]
    assert oct(ailleurs.stat().st_mode & 0o777) == '0o700'
    journal = sorted(ailleurs.glob('alpha-test-*.log'))
    assert len(journal) == 1 and oct(journal[0].stat().st_mode & 0o777) == '0o600' and journal[0].stat().st_uid == os.getuid()
    assert not list(faux.travail.iterdir())


@pytest.mark.parametrize('dossier', ['/root', '/root/journal', HOME + '/utilisateur'])
def test_dossier_journal_personnel_ou_root_non_refuse_par_le_chemin(faux, dossier):
    # ni /root ni le dossier personnel ne sont refusés pour le journal (65) : seule l'inexistence l'est, à l'ouverture
    resultat = faux.lancer('--verifier', '--dossier-journal', dossier)
    assert resultat.returncode == 0, resultat.stderr


def test_tar_du_code_relais_force_le_proprietaire_root(installes):
    lignes = [l for l in code(RELAIS) if '/usr/bin/tar' in l and '-cf -' in l]
    assert len(lignes) == 2 and all('--owner=0' in l and '--group=0' in l for l in lignes)   # code, puis fonctions
    creations = [a for a in installes.appels_premiere['relais'] if os.path.basename(a[0]) == 'tar' and '-cf' in a]
    assert creations and all('--owner=0' in a and '--group=0' in a for a in creations)


@pytest.mark.parametrize('script', SCRIPTS, ids=lambda p: p.name)
def test_depot_valide_par_la_liste_blanche_sans_refus_de_home(script):
    t = fonctions(script)['valider_depot']
    assert 'chemin_normalise DEPOT "$DEPOT" depot' in t and 'install_err_home' not in t
    assert 'depot' in fonctions(script)['chemin_normalise']


@pytest.mark.parametrize('depot', ['/var/lib/un depot', '/var/lib/$x', '/var/lib/a;b', '/var/lib/a\nb', 'relatif'])
def test_depot_hors_liste_blanche_refuse_en_cles_brutes(faux, depot):
    resultat = faux.lancer('--verifier', '--depot', depot)
    sans_ecriture(faux, resultat, 65)
    assert resultat.stderr.strip() == 'install_err_param_invalide'


def test_depot_sous_home_non_refuse_comme_home(faux):
    resultat = faux.lancer('--verifier', '--depot', HOME + '/clone-absent')
    sans_ecriture(faux, resultat, 65)
    assert resultat.stderr.strip() == 'install_err_depot'          # refus d'un dossier sans server/, i18n/ ni VERSION, non de /home
    assert 'install_err_home' not in resultat.stderr


def test_depot_par_defaut_et_repertoires_sous_home(faux):
    assert faux.lancer('--verifier').returncode == 0
    option = '--repertoire-app' if faux.machine == 'admin' else '--repertoire-tunnel'
    assert faux.lancer('--verifier', option, HOME + '/x').returncode == 65


def test_journalctl_sudo_nombre_de_lignes_seul(faux_relais):
    f = faux_relais
    sentinelle_journal = 'SENTINELLE-JOURNAL-4d2e91'
    f.regler(journal_extra_sudo=sentinelle_journal)
    code_sortie, sortie, _ = lancer_pty(f, ['--alpha-test', '--session-secours', 'oui', '--sauter', 'nftables',
                                            '--port-essai', str(f.port)])
    assert code_sortie == 0, sortie[-1500:]
    assert sentinelle_journal not in sortie
    assert all(sentinelle_journal not in j.read_text(encoding='utf-8') for j in journaux(f))
    assert '3 ligne(s) constatée(s), contenu non affiché' in sortie


# -- cas de test manquants ------------------------------------------------------------------------

@pytest.mark.parametrize('script', SCRIPTS, ids=lambda p: p.name)
def test_sources_citees_pour_la_creation_des_comptes(script):
    t = texte(script)
    for element in ('useradd(8)', '--home-dir', '--no-create-home', 'adduser(8)', '/nonexistent'):
        assert element in t, element
    assert '--base-dir' in t or 'BASE_DIR' in t


def test_absences_dans_lunite_de_pollux_et_le_script_admin():
    unite = next((RACINE / 'deploy/backend-admin/etc/systemd/system').glob('pollux.service')).read_text(encoding='utf-8')
    for contenu in (unite, texte(ADMIN)):
        for interdit in ('ProtectHome=tmpfs', 'BindReadOnlyPaths', 'monté par son inode'):
            assert interdit not in contenu, interdit
    assert 'ProtectHome=yes' in unite


def instantane_final(faux):
    """Arbre final, comptes et appels, normalisés (nom du jeu, chemins temporaires), hors fichiers aléatoires."""
    def norm(s):
        for chemin, nom in ((faux.racine, '<R>'), (faux.etat, '<E>'), (faux.bin, '<B>'), (faux.clone, '<C>'), (faux.base, '<T>')):
            s = s.replace(str(chemin), nom)
        s = re.sub(r'\d{8}-\d{6}', 'JEU', s)
        return re.sub(r'(?<!\d)%d(?!\d)' % faux.port, '<P>', s)    # le port d'essai est propre à chaque instance
    arbre = {}
    for chemin, (genre, mode, contenu) in faux.arbre().items():
        aleatoire = os.path.basename(chemin) in ('id_ed25519', 'id_ed25519.pub')
        arbre[chemin] = (genre, mode, None if aleatoire or contenu is None else norm(contenu.decode(errors='replace')))
    appels = [norm(json.dumps(a)) for a in faux.appels() if not any('id_ed25519' in x for x in a)]
    return arbre, faux.comptes(), sorted(appels)    # ordre indifférent : les tubes journalisent leurs deux côtés dans le désordre


def installation_complete(tmp_path, modele, machine, nom, env=None, reglages=None):
    faux = Faux(tmp_path / nom, modele, machine)
    if reglages:
        faux.regler(**reglages)
    resultat = faux.installation(env=env)
    assert resultat.returncode == 0, resultat.stderr
    return faux, resultat


def test_variables_de_lautre_machine_sans_effet(tmp_path, modele, machine):
    reference, r0 = installation_complete(tmp_path, modele, machine, 'ref')
    if machine == 'admin':
        env = {'PROFIL': 'partage', 'PORT_ESSAI': '45678'}
    else:
        env = {'ADRESSE_RELAIS': '192.0.2.200'}
    autre, r1 = installation_complete(tmp_path, modele, machine, 'autre', env=env)
    assert instantane_final(autre) == instantane_final(reference)
    assert r1.stderr == r0.stderr


def test_ports_d_essai_distincts_et_libres(tmp_path, modele):
    a, b = Faux(tmp_path / 'a', modele, 'relais'), Faux(tmp_path / 'b', modele, 'relais')
    assert a.port != b.port
    for port in (a.port, b.port):
        with socket.socket() as libre:
            libre.bind(('127.0.0.1', port))


def test_faux_ss_ignore_time_wait_et_voit_l_ecoute(capsys):
    from tests.outils import faux_systeme
    with socket.socket() as serveur:
        serveur.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        serveur.bind(('127.0.0.1', 0))
        serveur.listen(1)
        port = serveur.getsockname()[1]
        faux_systeme.cmd_ss(['-H', '-ltn', 'sport = :%d' % port])
        assert 'LISTEN' in capsys.readouterr().out
        client = socket.create_connection(('127.0.0.1', port))
        connexion, _ = serveur.accept()
        connexion.close()    # fermeture côté serveur : TIME_WAIT sur le port d'écoute
        client.close()
    faux_systeme.cmd_ss(['-H', '-ltn', 'sport = :%d' % port])
    assert capsys.readouterr().out == ''


def test_port_d_essai_en_ecoute_refuse_avec_78(tmp_path, modele):
    faux = Faux(tmp_path, modele, 'relais')
    with socket.socket() as occupant:
        occupant.bind(('127.0.0.1', faux.port))
        occupant.listen(1)
        resultat = faux.installation()
    assert resultat.returncode == 78, resultat.stderr
    assert "Le port %d n'est pas libre" % faux.port in resultat.stderr


def test_sorties_longues_sous_pipefail_meme_etat_final(tmp_path, modele, machine):
    reference, _ = installation_complete(tmp_path, modele, machine, 'ref')
    # une seule exécution complète par script : toutes les sorties longues à la fois (le faux getent n'est pas
    # allongé : une ligne par clé demandée est sa définition, un ajout changerait le résultat attendu)
    longue, resultat = installation_complete(tmp_path, modele, machine, 'longue',
                                             reglages={'version_longue': 20000, 'sorties_longues': True})
    assert instantane_final(longue) == instantane_final(reference)
    assert 'SIGPIPE' not in resultat.stderr and 'Broken pipe' not in resultat.stderr


# -- chemins du poste de travail et chemins sous /home dans les tests (contrôle du dépôt public) -------------

FICHIERS_DE_TEST = ['tests/test_scripts_installation.py', 'tests/outils/faux_systeme.py', 'tests/outils/installation_factice.py',
                    'tests/test_installation_pollux_romulus.py', 'tests/test_installation_relais_comptes.py',
                    'tests/test_installation_relais_nftables.py', 'tests/test_installation_relais_sudoers.py',
                    'tests/test_installation_relais_unites.py', 'tests/test_installation_tunnel.py',
                    'tests/test_procedures_sans_invite.py', 'tests/test_procedures_sudo.py', 'tests/test_sauvegarde.py']


def test_aucun_chemin_litteral_sous_home_dans_les_tests():
    motif = re.compile('/ho' + 'me/' + '[A-Za-z]')       # motif construit par concaténation : ce fichier ne se contient pas
    for nom in FICHIERS_DE_TEST:
        for numero, ligne in enumerate((RACINE / nom).read_text(encoding='utf-8').splitlines(), 1):
            assert not motif.search(ligne), f'{nom}:{numero}'


# -- identifiants attribués par le système ------------------------------------------------------

COMPTES_TABLE = {'admin': ['paresia-pollux', 'paresia-romulus', 'paresia-tunnel', 'app'],
                 'relais': ['paresia-castor', 'chef', 'tunnel']}
GROUPES_TABLE = {'admin': ['paresia-sessions', 'paresia-liaison', 'paresia-http', 'paresia-pollux', 'paresia-romulus',
                           'paresia-tunnel', 'app'],
                 'relais': ['paresia-castor', 'chef', 'tunnel', 'paresia-castor-tunnel', 'paresia-remus-tunnel',
                            'paresia-castor-etat']}
# (section, clé) -> (genre, nom) : attendu indépendamment de la table du script
CONFIGURATION_ATTENDUE = {
    'admin': ('/etc/paresia/conf.d/10-backend-admin.conf', {
        ('pollux.sessions', 'uid'): ('compte', 'app'), ('pollux.sessions', 'gid'): ('groupe', 'paresia-sessions'),
        ('pollux.relay', 'uid'): ('compte', 'paresia-romulus'), ('pollux.relay', 'gid'): ('groupe', 'paresia-liaison'),
        ('pollux.romulus', 'uid'): ('compte', 'paresia-romulus'), ('pollux.castor', 'uid'): ('compte', 'paresia-tunnel'),
        ('romulus.presence', 'uid_pollux'): ('compte', 'paresia-pollux'),
        ('romulus.presence', 'gid'): ('groupe', 'paresia-liaison'), ('romulus.http', 'gid'): ('groupe', 'paresia-http'),
        ('romulus.relay', 'pollux_uid'): ('compte', 'paresia-pollux'),
        ('romulus.relay', 'remus_uid'): ('compte', 'paresia-tunnel')}),
    'relais': ('/etc/paresia/paresia.conf', {
        ('castor.tunnel', 'uid'): ('compte', 'tunnel'), ('castor.tunnel', 'gid'): ('groupe', 'paresia-castor-tunnel'),
        ('castor.state', 'uid'): ('compte', 'chef'), ('castor.state', 'gid'): ('groupe', 'paresia-castor-etat'),
        ('remus.server', 'uid'): ('compte', 'tunnel'), ('remus.server', 'gid'): ('groupe', 'paresia-remus-tunnel'),
        ('remus.castor', 'uid'): ('compte', 'paresia-castor')})}
LIVREE = {'admin': 'deploy/backend-admin/etc/paresia/conf.d/10-backend-admin.conf', 'relais': 'server/conf/paresia-relais.conf'}


def table_systeme(faux, nom_fichier):
    return [l.split(':') for l in (faux.etat / nom_fichier).read_text().splitlines() if l.strip()]


def numero_systeme(faux, genre, nom):
    colonnes = table_systeme(faux, 'passwd' if genre == 'compte' else 'group')
    return int(next(c[2] for c in colonnes if c[0] == nom))


def valeurs_configuration(texte_conf):
    import configparser
    lecteur = configparser.ConfigParser(interpolation=None)
    lecteur.read_string(texte_conf)
    return lecteur


def controle_configuration_installee(faux):
    chemin, attendus = CONFIGURATION_ATTENDUE[faux.machine]
    installee = faux.lire(chemin)
    lecteur = valeurs_configuration(installee)
    for (section, cle), (genre, nom) in attendus.items():
        assert int(lecteur[section][cle]) == numero_systeme(faux, genre, nom), (section, cle)
    # commentaires, ordre et clés étrangères à la table : intacts
    livree = (faux.clone / LIVREE[faux.machine]).read_text().split('\n')
    lignes = installee.split('\n')
    assert len(lignes) == len(livree)
    cles = {cle for (_, cle) in attendus}
    for a, b in zip(livree, lignes):
        if a != b:
            assert re.fullmatch(r'(%s) = \d+' % '|'.join(cles), a) and re.fullmatch(r'(%s) = \d+' % '|'.join(cles), b), (a, b)
    if faux.machine == 'admin':
        assert int(lecteur['romulus.http']['uid_lighttpd']) == 33


def test_identifiants_attribues_par_le_systeme(faux):
    groupes = (faux.etat / 'group').read_text()
    occupes = {999: 'occupe-a', 998: 'occupe-b', 986: 'occupe-c', 985: 'occupe-d'}
    (faux.etat / 'group').write_text(groupes + ''.join(f'{nom}:x:{n}:\n' for n, nom in occupes.items()))
    resultat = faux.installation()
    assert resultat.returncode == 0, resultat.stderr
    ids = [numero_systeme(faux, 'groupe', nom) for nom in GROUPES_TABLE[faux.machine]]
    assert len(set(ids)) == len(ids) and not set(ids) & set(occupes)
    assert all(100 <= n <= 999 for n in ids + [numero_systeme(faux, 'compte', n) for n in COMPTES_TABLE[faux.machine]])
    for nom in COMPTES_TABLE[faux.machine]:
        assert next(c[3] for c in table_systeme(faux, 'passwd') if c[0] == nom) == str(numero_systeme(faux, 'groupe', nom))
    controle_configuration_installee(faux)
    appels = faux.appels()
    creations = [a for a in appels if os.path.basename(a[0]) in ('useradd', 'groupadd')]
    assert creations and not any('--uid' in a for a in creations)
    assert all('--gid' not in a or a[a.index('--gid') + 1] == a[-1] for a in creations)    # groupe primaire donné par son nom
    # la seconde exécution ne change rien
    nb = len(appels)
    seconde = faux.installation()
    assert seconde.returncode == 0, seconde.stderr
    assert [a for a in faux.appels()[nb:] if modifiant(a)] == []


def preparer_compte_conforme(faux, nom, numero):
    home = '/nonexistent'
    (faux.etat / 'group').write_text((faux.etat / 'group').read_text() + f'{nom}:x:{numero}:\n')
    (faux.etat / 'passwd').write_text((faux.etat / 'passwd').read_text()
                                      + f'{nom}:x:{numero}:{numero}::{home}:/usr/sbin/nologin\n')


def test_compte_conforme_repris_et_conserve_au_retour(faux):
    nom = 'paresia-pollux' if faux.machine == 'admin' else 'chef'
    preparer_compte_conforme(faux, nom, 321)
    avant = faux.comptes()
    resultat = faux.installation()
    assert resultat.returncode == 0, resultat.stderr
    assert numero_systeme(faux, 'compte', nom) == 321 and numero_systeme(faux, 'groupe', nom) == 321
    controle_configuration_installee(faux)
    assert not any(os.path.basename(a[0]) in ('useradd', 'groupadd') and a[-1] == nom for a in faux.appels())
    jeu = re.search(r'Jeu : (\d{8}-\d{6})', resultat.stdout).group(1)
    retour = faux.lancer('--retour-arriere', '--jeu', jeu, '--confirme', '--session-secours', 'oui')
    assert retour.returncode == 0, retour.stderr
    assert faux.comptes() == avant        # seul le compte repris subsiste, tout ce que l'installation a créé disparaît
    assert not faux.existe(CONFIGURATION_ATTENDUE[faux.machine][0])


@pytest.mark.parametrize('cas', ['groupe_hors_plage', 'compte_hors_plage', 'groupe_primaire', 'repertoire_home'])
def test_compte_ou_groupe_non_conforme_refuse(faux, cas):
    nom = 'paresia-pollux' if faux.machine == 'admin' else 'chef'
    passwd, group = faux.etat / 'passwd', faux.etat / 'group'
    if cas == 'groupe_hors_plage':
        group.write_text(group.read_text() + f'{nom}:x:5000:\n')
    elif cas == 'compte_hors_plage':
        group.write_text(group.read_text() + f'{nom}:x:321:\n')
        passwd.write_text(passwd.read_text() + f'{nom}:x:5000:321::/nonexistent:/usr/sbin/nologin\n')
    elif cas == 'groupe_primaire':
        group.write_text(group.read_text() + f'{nom}:x:321:\nautre:x:322:\n')
        passwd.write_text(passwd.read_text() + f'{nom}:x:321:322::/nonexistent:/usr/sbin/nologin\n')
    else:
        group.write_text(group.read_text() + f'{nom}:x:321:\n')
        passwd.write_text(passwd.read_text() + f'{nom}:x:321:321::' + HOME + f'/{nom}:/usr/sbin/nologin\n')
    avant = (faux.arbre(), faux.comptes())
    resultat = faux.installation()
    assert resultat.returncode == 78 and 'ÉCART' in resultat.stderr and nom in resultat.stderr, resultat.stderr
    assert (faux.arbre(), faux.comptes()) == avant
    assert modifiants(faux, faux.appels()) == []


def test_couple_de_configuration_absent_refuse(faux):
    chemin = faux.clone / LIVREE[faux.machine]
    texte_conf = chemin.read_text()
    cible = 'remus_uid = 982\n' if faux.machine == 'admin' else 'uid = 970\n'
    assert texte_conf.count(cible) == 1
    chemin.write_text(texte_conf.replace(cible, ''))
    avant = (faux.arbre(), faux.comptes())
    resultat = faux.installation()
    assert resultat.returncode == 78 and 'ÉCART' in resultat.stderr, resultat.stderr
    assert (faux.arbre(), faux.comptes()) == avant
    assert modifiants(faux, faux.appels()) == []


# -- étape web : pages de l'interface et des greffons, index ----------------------------------------

WEB = '/usr/local/share/paresia/web'


def greffon_dans_le_clone(faux, nom, catalogue, scripts=('p.js',)):
    """Ajoute au clone d'essai un greffon à pages (déclaration livrée, dossier source, catalogue)."""
    services = faux.clone / 'deploy/backend-admin/usr/local/lib/paresia/romulus/services'
    texte = (f'format = 1\ngreffon = "paresia-yang-{nom}"\ndomaine = "{nom}"\nsans_destination = true\n'
             'catalogue = "aucun"\n')
    for i, script in enumerate(scripts):
        texte += f'[[pages]]\nid = "p{i}"\ntitre_cle = "ui_{nom}_t{i}"\nscript = "{script}"\n'
    (services / f'paresia-yang-{nom}.toml').write_text(texte)
    dossier = faux.clone / 'deploy/backend-admin/usr/local/share/paresia/web/greffons' / nom
    (dossier / 'i18n').mkdir(parents=True)
    for script in scripts:
        (dossier / script).write_text('// page\n')
    (dossier / 'i18n/fr-FR.json').write_text(json.dumps(catalogue))


def test_etape_web_etat_final(installes):
    faux = installes.admin
    faux.restaurer('installe')
    assert json.loads(faux.lire(WEB + '/greffons/index.json')) == {'format': 1, 'greffons': []}
    for nom in ('index.html', 'app.js', 'api.js'):
        assert faux.lire(f'{WEB}/{nom}') == (faux.clone / 'admin/web' / nom).read_text()
    for chemin in (WEB, WEB + '/greffons'):
        assert faux.chemin(chemin).stat().st_mode & 0o777 == 0o755
    assert faux.chemin(WEB + '/greffons/index.json').stat().st_mode & 0o777 == 0o644
    assert not [p for p in faux.chemin(WEB).rglob('*') if p.stat().st_mode & 0o022]
    # la commande de l'index est lancée par le module installé, puis vérifiée
    commandes = [' '.join(a) for a in installes.appels_premiere['admin']]
    assert any('server.romulus.pages --ecrire' in c for c in commandes)
    assert any('server.romulus.pages --verifier' in c for c in commandes)


def test_etape_web_ne_touche_aucun_serveur_web(installes):
    appels = installes.appels_premiere['admin']
    assert [a for a in appels if 'paresia/web' in ' '.join(a)]
    for appel in appels:
        ligne = ' '.join(appel)
        # Lectures sans effet du prérequis libssl3t64 (T118) : « dpkg-query -W » et « dpkg --compare-versions » ; tout autre
        # usage de dpkg (installation, retrait, configuration) et tout apt restent interdits.
        lecture = ligne.startswith(('/usr/bin/dpkg-query -W ', '/usr/bin/dpkg --compare-versions '))
        assert lecture or not re.search(r'lighttpd|apache|nginx|dpkg', ligne), ligne
        assert not re.search(r'lighttpd|apache|nginx', ligne), ligne
        assert lecture or os.path.basename(appel[0]) not in ('apt', 'apt-get', 'dpkg')
    assert not installes.admin.existe('/etc/lighttpd')
    lignes = [l for l in code(ADMIN) if re.search(r'WEB_|web_', l)]
    assert lignes and not any(re.search(r'lighttpd|www-data|apt|dpkg', l) for l in lignes)


def test_etape_web_deja_en_place_a_la_seconde_passe(installes):
    faux = installes.admin
    faux.restaurer('installe')
    avant = len(faux.appels())
    r = faux.installation('--activer', *arguments_reinstallation(installes, 'admin'), '--jeu', installes.jeu['admin'])
    assert r.returncode == 0, r.stderr
    assert re.search(r'étape \d+/\d+ web : déjà en place', r.stderr)
    assert not [a for a in faux.appels()[avant:] if 'paresia/web' in ' '.join(a) and modifiant(a)]


def test_etape_web_dossier_different_refuse_sans_confirmation(installes):
    faux = installes.admin
    faux.restaurer('installe')
    faux.chemin(WEB + '/app.js').write_text('// modifié\n')
    r = faux.installation('--activer', *arguments_reinstallation(installes, 'admin'), '--jeu', installes.jeu['admin'])
    assert r.returncode == 78 and WEB in r.stderr
    assert faux.lire(WEB + '/app.js') == '// modifié\n'


def test_etape_web_index_refuse_aucun_index_laisse(faux_admin):
    faux = faux_admin
    greffon_dans_le_clone(faux, 'mauvais', {'ui_autre_t0': 'x'})
    r = faux.installation()
    assert r.returncode == 78, r.stderr
    assert 'pages_catalog_invalid mauvais' in r.stderr and str(faux.racine) not in r.stderr
    assert not faux.existe(WEB + '/greffons/index.json')


def test_etape_web_greffon_valide_dans_l_index(faux_admin):
    faux = faux_admin
    greffon_dans_le_clone(faux, 'exemple', {'ui_exemple_t0': 'Titre'}, scripts=('etat.js',))
    r = faux.installation()
    assert r.returncode == 0, r.stderr
    assert json.loads(faux.lire(WEB + '/greffons/index.json')) == {'format': 1, 'greffons': [{'nom': 'exemple', 'pages': [
        {'id': 'p0', 'titre_cle': 'ui_exemple_t0', 'script': 'etat.js'}]}]}
    assert faux.lire(WEB + '/greffons/exemple/etat.js') == '// page\n'
    assert WEB in r.stdout


# -- fonctions de Remus et contrôle du produit (backend-relais) ---------------------------------

FONCTIONS_INSTALLEES = '/usr/local/lib/paresia/remus/fonctions'
IMAGE_FACTICE = 'registry.example.org/strfry:%s sha256:' + 'b' * 64


def declarer_empreinte(faux, empreinte):
    dossier = faux.clone / 'deploy/backend-relais/usr/local/lib/paresia/remus/fonctions'
    for fichier in dossier.glob('*.toml'):
        fichier.write_text(fichier.read_text().replace('[produit]\n', '[produit]\nempreinte = "%s"\n' % empreinte))


def declarer_version(faux, version):
    dossier = faux.clone / 'deploy/backend-relais/usr/local/lib/paresia/remus/fonctions'
    for fichier in dossier.glob('*.toml'):
        fichier.write_text(re.sub(r'(?m)^version = ".*"$', 'version = "%s"' % version, fichier.read_text()))


def refus_produit(faux):
    resultat = faux.installation()
    assert resultat.returncode == 78, resultat.stderr
    assert [a for a in faux.appels() if modifiant(a)] == [] and faux.jeux() == []
    # nom, source et version déclarés sont cités ; aucune autre commande ne nomme Docker
    assert 'strfry' in resultat.stderr and 'https://github.com/hoytech/strfry' in resultat.stderr
    assert all(os.path.basename(a[0]) != 'docker' or a[1] == 'inspect' for a in faux.appels())
    return resultat


@pytest.mark.parametrize('lecture', ['registry.example.org/strfry:latest sha256:' + 'b' * 64,
                                     'registry.example.org/strfry:1.1.3 sha256:' + 'b' * 64,
                                     'registry.example.org/strfry sha256:' + 'b' * 64, 'illisible', ''])
def test_produit_en_desaccord_refuse_avant_toute_modification(faux_relais, lecture):
    faux_relais.regler(docker_inspect=lecture)
    resultat = refus_produit(faux_relais)
    assert '4cd3cf6' in resultat.stderr


def test_produit_conteneur_absent_refuse(faux_relais):
    faux_relais.regler(docker_absent=True)
    refus_produit(faux_relais)


def test_produit_empreinte_prevaut_sur_l_etiquette(faux_relais):
    declarer_empreinte(faux_relais, 'sha256:' + 'c' * 64)      # l'étiquette convient, l'empreinte diffère
    refus_produit(faux_relais)


def test_produit_empreinte_egale_passe_meme_si_etiquette_differente(faux_relais):
    declarer_empreinte(faux_relais, 'sha256:' + 'b' * 64)
    faux_relais.regler(docker_inspect='registry.example.org/strfry:autre sha256:' + 'b' * 64)
    assert faux_relais.installation('--sauter', 'sudoers').returncode == 0


@pytest.mark.parametrize('version,etiquette,passe', [('>=1.1.3,<2', '1.1.3', True), ('>=1.1.3,<2', 'v1.9.0', True),
                                                     ('>=1.1.3,<2', '2.0.0', False), ('>=1.1.3,<2', '1.1.2', False),
                                                     ('>1.1.3', '1.1.3', False), ('<=1.1.3', '1.1.3', True)])
def test_produit_intervalle_applique_a_l_etiquette(faux_relais, version, etiquette, passe):
    declarer_version(faux_relais, version)
    faux_relais.regler(docker_inspect='registry.example.org/strfry:%s sha256:%s' % (etiquette, 'b' * 64))
    if passe:
        assert faux_relais.installation('--sauter', 'sudoers').returncode == 0
    else:
        refus_produit(faux_relais)


def test_produit_etape_sautable(faux_relais):
    faux_relais.regler(docker_absent=True)
    resultat = faux_relais.installation('--sauter', 'produit', '--sauter', 'sudoers')
    assert resultat.returncode == 0, resultat.stderr
    assert not any(os.path.basename(a[0]) == 'docker' for a in faux_relais.appels())


def test_fonctions_posees_avant_sudoers_avec_les_droits_attendus(installe):
    faux, _ = installe
    if faux.machine != 'relais':
        pytest.skip('backend-relais seulement')
    dossier = faux.chemin(FONCTIONS_INSTALLEES)
    assert dossier.is_dir() and oct(dossier.stat().st_mode & 0o777) == '0o755'
    for fichier in dossier.iterdir():
        attendu = '0o644' if fichier.suffix == '.toml' else '0o755'
        assert oct(fichier.stat().st_mode & 0o777) == attendu, fichier
        assert not fichier.is_symlink()
    assert sorted(f.name for f in dossier.iterdir()) == sorted(
        f.name for f in (RACINE / 'deploy/backend-relais/usr/local/lib/paresia/remus/fonctions').iterdir())
    # le sudoers posé est le rendu des manifestes posés : trois règles exactes
    regles = [l for l in faux.lire('/etc/sudoers.d/paresia-remus').splitlines() if l and not l.startswith('#')]
    assert len(regles) == 3 and all(r.startswith('chef ALL=(root) NOPASSWD: /usr/bin/docker ') for r in regles)
    appels = [' '.join(a) for a in installes_appels(faux)]
    assert next(i for i, c in enumerate(appels) if FONCTIONS_INSTALLEES in c and ' mv ' in c or c.startswith('/usr/bin/mv')
                ) < next(i for i, c in enumerate(appels) if 'server.remus.sudoers' in c)


def installes_appels(faux):
    return faux.appels()


def test_fonctions_ecart_refuse_sans_modification(installe):
    faux, installes = installe
    if faux.machine != 'relais':
        pytest.skip('backend-relais seulement')
    cible = faux.chemin(FONCTIONS_INSTALLEES) / 'strfry_etat'
    cible.chmod(0o775)          # droits plus larges que ceux attendus
    nb, arbre = len(faux.appels()), faux.arbre()
    resultat = faux.installation('--activer', *arguments_reinstallation(installes, 'relais'))
    assert resultat.returncode == 78, resultat.stderr
    assert [a for a in faux.appels()[nb:] if modifiant(a)] == [] and faux.arbre() == arbre


def test_fonctions_differentes_remplacees_avec_confirmation(installe):
    faux, installes = installe
    if faux.machine != 'relais':
        pytest.skip('backend-relais seulement')
    cible = faux.chemin(FONCTIONS_INSTALLEES) / 'strfry_etat'
    cible.write_text('modifie')
    cible.chmod(0o755)
    resultat = faux.installation('--activer', '--code-remplacement-confirme', 'oui',
                                 *arguments_reinstallation(installes, 'relais'))
    assert resultat.returncode == 0, resultat.stderr
    assert cible.read_text() != 'modifie'


@pytest.mark.parametrize('reglage,code', [
    ({}, 0), ({'libssl_version': '3.5.6-1'}, 69),
    ({'libssl_version': '3.5.7-1~deb13u2'}, 69),
    ({'libssl_version': '3.5.7-1~deb13u3'}, 0),
    ({'libssl_version': '3.5.8-1~deb13u1'}, 0),
    ({'libssl_version': '3.6.0-1'}, 0),
    ({'libssl_absent': True}, 69),
    ({'libssl_statut': 'deinstall ok config-files'}, 69),
    ({'libssl_version': ''}, 69), ({'libssl_version': 'illisible'}, 69),
])
def test_prerequis_libssl(faux_admin, reglage, code):
    faux_admin.regler(**reglage)
    avant = faux_admin.arbre(exclure=())
    resultat = faux_admin.lancer('--verifier')
    assert resultat.returncode == code, resultat.stderr
    if code:
        assert 'libssl3t64-3.5.7-1~deb13u3' in resultat.stderr
        assert 'illisible' not in resultat.stderr
    assert faux_admin.arbre(exclure=()) == avant


@pytest.mark.parametrize('identite', [None, 'courante', 'uid_seul', 'gid_seul',
                                    '0', 'abc', '1;x', '01', '4294967295', ''])
def test_alpha_journal_proprietaire_sudo(faux, identite):
    env = {}
    if identite == 'courante':
        if not os.getuid() or not os.getgid():
            pytest.skip('identité non nulle requise')
        env = {'SUDO_UID': str(os.getuid()), 'SUDO_GID': str(os.getgid())}
    elif identite == 'uid_seul':
        env = {'SUDO_UID': '1000'}
    elif identite == 'gid_seul':
        env = {'SUDO_GID': '1000'}
    elif identite is not None:
        env = {'SUDO_UID': identite, 'SUDO_GID': identite}
    extra = ['--sauter', 'nftables', '--port-essai', str(faux.port)] if faux.machine == 'relais' else []
    code, sortie, _ = lancer_pty(faux, ['--alpha-test', '--session-secours', 'oui', *extra], env=env)
    assert code == 0, sortie[-3000:]
    journal, = journaux(faux)
    appels = [a for a in faux.appels() if a[0] == '/usr/bin/chown' and str(journal) in a]
    assert journal.stat().st_mode & 0o777 == 0o600
    if identite == 'courante':
        assert appels == [['/usr/bin/chown', '-h', '--', f'{os.getuid()}:{os.getgid()}', str(journal)]]
    else:
        assert appels == []


def test_alpha_journal_echec_chown(faux):
    faux.regler(echec_commande='chown')
    code, sortie, _ = lancer_pty(faux, ['--alpha-test'], env={'SUDO_UID': '1000', 'SUDO_GID': '1000'})
    assert code == 78 and 'Le dossier du journal' in sortie


def test_tunnel_activation_ancienne_retiree(installes):
    f = installes.admin
    f.restaurer('installe')
    try:
        p = f.etat / 'enabled.json'
        enabled = json.loads(p.read_text())
        enabled.append('paresia-tunnel.service')
        p.write_text(json.dumps(enabled))
        avant = len(f.appels())
        args = arguments_reinstallation(installes, 'admin')
        resultat = f.installation(*args)
        assert resultat.returncode == 0, resultat.stderr
        appels = f.appels()[avant:]
        assert [a for a in appels if a[:2] == ['/usr/bin/systemctl', 'disable']] == [
            ['/usr/bin/systemctl', 'disable', 'paresia-tunnel.service']]
        assert not any(a[:2] in (['/usr/bin/systemctl', 'stop'], ['/usr/bin/systemctl', 'restart'])
                       and 'paresia-tunnel.service' in a for a in appels)
        assert 'paresia-tunnel.service' not in json.loads(p.read_text())
        avant = len(f.appels())
        assert f.installation(*args).returncode == 0
        assert not any(a[:2] == ['/usr/bin/systemctl', 'disable'] for a in f.appels()[avant:])
        f.restaurer('passe1')
        avant = len(f.appels())
        assert f.installation().returncode == 0
        assert not any(a[:2] == ['/usr/bin/systemctl', 'disable'] for a in f.appels()[avant:])
    finally:
        f.restaurer('installe')
