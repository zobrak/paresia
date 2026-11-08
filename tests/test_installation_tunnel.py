# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests hors ligne du tunnel de production et de la procédure d'essai : bloc sshd du compte tunnel,
# configuration du client en couches, contrôles textuels des procédures. Aucun root, aucun sshd lancé.
# Dépendances : bibliothèque standard, pytest ; `ssh -G` seulement s'il existe.
# Suivi des versions
#   0.1.19  2026-11-08  Tunnel lié aux services, sans activation propre.
#   3.0.0-alpha.42  2026-11-07  Première version.
#   0.1.0  2026-11-07  Comptes hors /home et paramètres sans invite.
#   0.1.0  2026-11-07  Partie tunnel des deux scripts à la place de la procédure du tunnel ; rôle de lighttpd joué par www-data (uid_lighttpd) ; cas de validation de forme.
import ipaddress
import re
import shutil
import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
DEPLOY = RACINE / 'deploy'
SSHD = DEPLOY / 'backend-relais/etc/ssh/sshd_config.d/50-paresia-tunnel.conf'
TUNNEL = DEPLOY / 'backend-admin/etc/paresia/tunnel'
SSH_CONFIG = TUNNEL / 'ssh_config'
RELAIS = TUNNEL / 'ssh_config.d/10-relais.conf'
INSTALLATION = [DEPLOY / 'backend-admin/installer-backend-admin.sh', DEPLOY / 'backend-relais/installer-backend-relais.sh']
ESSAI = DEPLOY / 'essai-presence.md'
RFC5737 = [ipaddress.ip_network(n) for n in ('192.0.2.0/24', '198.51.100.0/24', '203.0.113.0/24')]


def lignes(chemin):
    """Lignes utiles, sans commentaire ni ligne vide."""
    return [l.rstrip() for l in chemin.read_text(encoding='utf-8').splitlines()
            if l.strip() and not l.lstrip().startswith('#')]


def test_sshd_mots_cles_exacts():
    attendu = ['StrictModes yes', 'PermitUserEnvironment no', 'Match User tunnel',
               '    AllowTcpForwarding local', '    AllowStreamLocalForwarding local', '    PermitListen none',
               '    PermitTTY no', '    X11Forwarding no', '    AllowAgentForwarding no',
               '    PasswordAuthentication no', '    AuthenticationMethods publickey']
    assert lignes(SSHD) == attendu


def test_sshd_match_en_dernier_sans_adresse():
    utiles = lignes(SSHD)
    assert sum(1 for l in utiles if l.startswith('Match ')) == 1
    # Tout ce qui suit Match est indenté : aucun mot-clé global après lui.
    apres = utiles[utiles.index('Match User tunnel') + 1:]
    assert apres and all(l.startswith('    ') for l in apres)
    assert not re.search(r'\d{1,3}(?:\.\d{1,3}){3}', '\n'.join(utiles))


def test_ssh_config_options():
    utiles = lignes(SSH_CONFIG)
    assert utiles[0] == 'Include /etc/paresia/tunnel/ssh_config.d/*.conf'
    assert utiles[1] == 'Host paresia-relais'
    options = [l.strip() for l in utiles[2:]]
    attendu = ['User tunnel', 'IdentityFile /etc/paresia/tunnel/id_ed25519', 'IdentitiesOnly yes',
               'StrictHostKeyChecking yes', 'UserKnownHostsFile /etc/paresia/tunnel/known_hosts',
               'BatchMode yes', 'ExitOnForwardFailure yes', 'StreamLocalBindUnlink yes',
               'StreamLocalBindMask 0111', 'ServerAliveInterval 15', 'ForwardAgent no', 'ForwardX11 no',
               'RequestTTY no', 'PasswordAuthentication no', 'PubkeyAuthentication yes',
               'LocalForward /run/paresia-tunnel/romulus/remus.sock /run/paresia-remus/remus.sock',
               'LocalForward /run/paresia-tunnel/pollux/castor.sock /run/paresia-castor/castor.sock']
    assert options == attendu
    assert 'ClearAllForwardings' not in SSH_CONFIG.read_text(encoding='utf-8')
    # Ni adresse ni clé dans la couche commune (D65).
    assert not re.search(r'\d{1,3}(?:\.\d{1,3}){3}|HostName', '\n'.join(utiles))


def test_couche_locale_adresse_rfc5737():
    assert [l.strip() for l in lignes(RELAIS)] == ['Host paresia-relais', 'HostName 192.0.2.200', 'Port 22']
    assert any(ipaddress.ip_address('192.0.2.200') in r for r in RFC5737)


@pytest.mark.skipif(shutil.which('ssh') is None, reason='ssh absent : ssh -G ignoré')
def test_ssh_g_options_effectives(tmp_path):
    (tmp_path / 'couches').mkdir()
    (tmp_path / 'couches/10-relais.conf').write_bytes(RELAIS.read_bytes())
    copie = tmp_path / 'ssh_config'
    texte = SSH_CONFIG.read_text(encoding='utf-8').replace('/etc/paresia/tunnel/ssh_config.d/*.conf',
                                                           str(tmp_path / 'couches/*.conf'))
    copie.write_text(texte, encoding='utf-8')
    sortie = subprocess.run(['ssh', '-G', '-F', str(copie), 'paresia-relais'], capture_output=True,
                            text=True, timeout=10, check=True).stdout.splitlines()
    for ligne in ('stricthostkeychecking true', 'exitonforwardfailure yes', 'streamlocalbindunlink yes',
                  'serveraliveinterval 15', 'streamlocalbindmask 0111', 'hostname 192.0.2.200',
                  'user tunnel', 'port 22', 'identitiesonly yes', 'batchmode yes'):
        assert ligne in sortie, ligne
    assert sum(1 for l in sortie if l.startswith('localforward ')) == 2


def test_ordre_des_couches():
    # La première valeur obtenue l'emporte : l'Include précède le Host de la couche commune.
    texte = SSH_CONFIG.read_text(encoding='utf-8')
    assert texte.index('Include ') < texte.index('Host paresia-relais')


FICHIERS = [SSHD, SSH_CONFIG, RELAIS, *INSTALLATION, ESSAI]


@pytest.mark.parametrize('chemin', FICHIERS, ids=lambda p: p.name)
def test_noms_et_donnees(chemin):
    assert chemin.name == chemin.name.lower()
    texte = chemin.read_text(encoding='utf-8')
    assert 'SPDX-License-Identifier: AGPL-3.0-or-later' in texte
    assert not re.search('-----BEGIN [A-Z ]*PRIVATE KEY|nsec' + '1[0-9a-z]{20,}', texte)
    assert not re.search('fr' + '_FR|en' + '_US', texte)
    assert not re.findall(r'/home/[A-Za-z0-9_-]+', texte)
    for a in re.findall(r'(?<![\w.])\d{1,3}(?:\.\d{1,3}){3}(?![\w.])', texte):
        if a.count('.') == 3 and all(int(p) < 256 for p in a.split('.')):
            adresse = ipaddress.ip_address(a)
            assert (adresse.is_loopback or adresse.is_unspecified
                    or any(adresse in r for r in RFC5737)), a
    assert not re.search(r'(?i)\b(T0\d\d|fiche)\b', texte)


# -- Procédures --------------------------------------------------------------------------

def etapes(chemin, motif):
    texte = chemin.read_text(encoding='utf-8')
    parties = re.split(motif, texte)
    return dict(zip(parties[1::2], parties[2::2]))


def test_essai_etapes_a_f():
    par_lettre = etapes(ESSAI, r'(?m)^## Étape ([A-F]) — .*$')
    assert sorted(par_lettre) == list('ABCDEF')
    assert all('Retour arrière' in t or 'retour arrière' in t.lower() or l == 'E'
               for l, t in par_lettre.items())
    for lettre, corps in par_lettre.items():
        assert 'Machine' in corps or 'Machines' in corps or lettre == 'A' or lettre == 'F'


def test_essai_e1_a_e6_evenements():
    texte = ESSAI.read_text(encoding='utf-8')
    for sous_titre in ('E1', 'E2', 'E3', 'E4', 'E5', 'E6'):
        assert re.search(rf'(?m)^### {sous_titre} — ', texte)
    for evenement in ('challenge_issued', 'auth_ok', 'session_opened', 'action_routed', 'not_available',
                      'light_green', 'light_closed', 'session_closed', 'token_unknown',
                      'Accepted publickey for tunnel', 'Accepted publickey for app'):
        assert evenement in texte, evenement
    assert "read -r -s" in texte


def blocs_bash(chemin):
    return '\n'.join(re.findall(r'```bash\n(.*?)```', chemin.read_text(encoding='utf-8'), re.S))


def code_script(chemin):
    return '\n'.join(l for l in chemin.read_text(encoding='utf-8').splitlines() if not l.strip().startswith('#'))


def test_commandes_interdites():
    blocs = blocs_bash(ESSAI)
    assert not re.search(r'systemctl\s+(?:enable|restart|reload-or-restart|try-restart)', blocs)
    assert not re.search(r'systemctl\s+(?:stop|restart|reload)\s+[^\n]*(?:docker|strfry|lighttpd|bunkerd|journal-legal)', blocs)
    assert 'rm -rf' not in ESSAI.read_text(encoding='utf-8') and 'rm -r ' not in blocs
    assert not re.search(r'(?m)^\s*(?:service|systemctl)\s+restart\s+ssh', blocs)
    assert 'shell=True' not in ESSAI.read_text(encoding='utf-8')
    for script in INSTALLATION:
        code = code_script(script)
        assert not re.search(r'systemctl\s+(?:restart|reload-or-restart|try-restart)', code)
        assert not re.search(r'systemctl\s+(?:stop|restart|reload)\s+[^\n]*(?:docker|strfry|lighttpd|bunkerd|journal-legal)', code)
        assert 'rm -rf' not in code and 'shell=True' not in code
        # systemctl enable seulement dans l'étape d'activation (option --activer), jamais pour l'unité du tunnel
        fonctions = {m.group(1): m.group(0) for m in re.finditer(r'(?ms)^(\w+)\(\) \{(?:[^\n]*\}$|[^\n]*\n.*?^\})', code)}
        assert [n for n, c in fonctions.items() if 'systemctl enable' in c] == ['etape_activation']
        assert 'paresia-tunnel.service' not in fonctions['etape_activation']
    for texte in (ESSAI.read_text(encoding='utf-8'), *(s.read_text(encoding='utf-8') for s in INSTALLATION)):
        assert 'ProtectHome=tmpfs' not in texte and 'BindReadOnlyPaths' not in texte and 'monté par son inode' not in texte


def test_sshd_t_precede_chaque_reload():
    for bloc in re.findall(r'```bash\n(.*?)```', ESSAI.read_text(encoding='utf-8'), re.S):
        if 'reload ssh' in bloc:
            assert 'sshd -t' in bloc[:bloc.index('reload ssh')], bloc
    for script in INSTALLATION:
        t = script.read_text(encoding='utf-8')
        corps = re.search(r'(?ms)^recharger_ssh\(\) \{.*?^\}', t).group()
        assert corps.index('sshd_t') < corps.index('systemctl reload ssh')
        assert len(re.findall(r'(?m)^[^#\n]*systemctl reload ssh', t)) == 1


def test_attention_devant_commandes_modifiantes():
    texte = ESSAI.read_text(encoding='utf-8')
    for bloc in re.finditer(r'(?:(?<=\n\n)|^)([^\n]*)\n\n```bash\n(.*?)```', texte, re.S):
        commande = bloc.group(2)
        if re.search(r'(?m)^\s*(?:sudo /usr/s?bin/)?(?:install|usermod|gpasswd|systemctl (?:start|stop|reload)|sed -i|rm |chown|chmod)', commande):
            debut = texte[:bloc.start(2)]
            dernier = debut.rfind('ATTENTION')
            assert dernier != -1 and bloc.start(2) - dernier < 1500, commande[:80]


def test_etape_f():
    f = etapes(ESSAI, r'(?m)^## Étape ([A-F]) — .*$')['F']
    assert 'systemctl stop' in f and 'systemctl enable' not in f
    assert 'www-data' not in f
    assert "sed -i 's/^restrict,/#restrict,/'" in f and "sed -i 's/^#restrict,/restrict,/'" in f
    assert 'paresia_relais' in f and 'PermitOpen' in f and 'AllowStreamLocalForwarding local' in f
    assert 'restaurer --jeu "$JEU_ESSAI" /var/lib/paresia-app/.ssh/authorized_keys' in f
    assert '40-paresia-tunnel-allowusers.conf' in f and 'déjà arrêtés' in f


def test_etape_c_sans_modifier_www_data():
    texte = ESSAI.read_text(encoding='utf-8')
    c = etapes(ESSAI, r'(?m)^## Étape ([A-F]) — .*$')['C']
    assert 'BindReadOnlyPaths' not in c and 'ProtectHome=yes' in c
    assert '/var/lib/paresia-app/.ssh/authorized_keys' in c
    assert '--sauter www-data' in c
    blocs = '\n'.join(re.findall(r'```bash\n(.*?)```', texte, re.S))
    assert 'gpasswd' not in blocs and 'usermod' not in blocs
    assert blocs.count('runuser -u www-data -g paresia-http -- /usr/bin/curl') == 2
    assert 'runuser -u nobody -g paresia-http' not in texte


def test_moindre_privilege_sans_shell_root():
    texte = ESSAI.read_text(encoding='utf-8')
    blocs = blocs_bash(ESSAI)
    assert not re.search(r'sudo\s+(-i|-s|su\b|sh\b|bash\b)|^\s*su\b|\bsu\s+-', blocs, re.M)
    assert not re.search(r'sudo[^\n|]*\b(sh|bash)\s+-c', blocs)
    assert not re.search(r'(?<![/\w-])sshd (-t|-T)', blocs), 'sshd doit être en chemin absolu'
    assert not re.search(r'(?m)^\s*(systemctl (?!--version)|journalctl|runuser|install|python3 -P)\b', blocs)
    assert 'Commandes lancées par `sudo`' in texte and 'pas un sudoers à recopier' in texte
    assert 'ne peuvent pas être restreintes' in texte and 'bash' in texte
    assert 'non couverts' not in texte and 'écrits pour root' not in texte
    # une garde `case` doit encadrer une condition (if), jamais seulement afficher un message
    assert not re.search(r"(?m)^case .*echo", blocs)
    for script in INSTALLATION:
        t = script.read_text(encoding='utf-8')
        assert 'pas un sudoers à recopier' in t and 'ne peuvent pas être restreintes' in t
        assert not re.search(r'sudo\s+(-i|-s|su\b|sh\b|bash\b)|sudo[^\n|]*\b(sh|bash)\s+-c', code_script(script))


def test_installation_valeur_du_masque_et_arret():
    admin, relais = (p.read_text(encoding='utf-8') for p in INSTALLATION)
    assert 'StreamLocalBindMask' in admin and '0111' in admin and 'streamlocalbindmask 0111' in admin
    assert 'install_ecart' in admin and 'ecart "' in admin          # tout écart bloque et s'affiche « attendu / relevé »
    assert 'passwd -S tunnel' in relais


def test_validations_de_forme_de_l_essai():
    texte = ESSAI.read_text(encoding='utf-8')
    garde_admin = re.search(r"case \"\$ADMIN\" in [^\n]*? esac", texte).group()
    garde_cle = re.search(r"case \"\$CLE_PUBLIQUE\" in [^\n]*? esac", texte).group()
    def verdict(garde, variable, valeur):
        r = subprocess.run(['bash', '--noprofile', '--norc', '-c', f'{variable}="$1"; {garde}', '_', valeur],
                           capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    for valide in ('alice', 'a.b_c@d-e', 'Admin1'):
        assert verdict(garde_admin, 'ADMIN', valide), valide
    for interdit in ('', 'a b', 'x;y', 'a$(id)', 'a/b', "a'b", 'a\nb', 'é'):
        assert not verdict(garde_admin, 'ADMIN', interdit), interdit
    assert verdict(garde_cle, 'CLE_PUBLIQUE', 'ssh-ed25519 AAAA admin')
    for interdite in ('', 'ssh-rsa AAAA x', 'AAAA ssh-ed25519', 'ssh-ed25519AAAA'):
        assert not verdict(garde_cle, 'CLE_PUBLIQUE', interdite), interdite


def test_nsenter_attend_root_root_644():
    admin = INSTALLATION[0].read_text(encoding='utf-8')
    corps = re.search(r'(?ms)^attributs_vus_par_pollux\(\) \{.*?^\}', admin).group()
    assert 'nsenter -t "$pid" -m -- /usr/bin/ls -l /var/lib/paresia-app/.ssh/authorized_keys' in corps
    assert 'verifie "nsenter:pollux:authorized_keys" "root:root 644"' in admin
    essai = ESSAI.read_text(encoding='utf-8')
    assert 'nsenter -t "$(systemctl show -p MainPID --value pollux.service)" -m -- /usr/bin/ls -l /var/lib/paresia-app/.ssh/authorized_keys' in essai
    assert 'listé, `root:root 644`' in essai


def lire_uid_lighttpd():
    import configparser
    ini = configparser.ConfigParser(interpolation=None)
    ini.read_string((RACINE / 'server/conf/paresia.conf').read_text(encoding='utf-8'))
    return int(ini['romulus.http']['uid_lighttpd'])


def test_essai_emploie_le_compte_uid_lighttpd():
    """Romulus n'accepte comme pair HTTP que uid_lighttpd : l'essai joue lighttpd avec le compte de cet UID (www-data)."""
    uid = lire_uid_lighttpd()
    assert uid == 33
    essai = ESSAI.read_text(encoding='utf-8')
    commandes = re.findall(r'runuser -u (\S+) -g paresia-http -- /usr/bin/curl', essai)
    assert commandes and set(commandes) == {'www-data'}
    admin = INSTALLATION[0].read_text(encoding='utf-8')
    assert f'"www-data:{uid}"' in admin        # le script contrôle l'UID de www-data (D42)
    assert 'runuser -u nobody -g paresia-http' not in essai
    # nobody reste employé pour les refus et pour la génération du sudoers (visudo)
    assert 'nobody' in essai and 'génération du sudoers' in essai


def test_tunnel_dependances_services():
    chemin = Path(__file__).resolve().parents[1] / 'deploy/backend-admin/etc/systemd/system/paresia-tunnel.service'
    texte = chemin.read_text(encoding='utf-8')
    assert '[Install]' not in texte and 'WantedBy=' not in texte
    directives = dict(re.findall(r'(?m)^(PartOf|After|Wants)=(.*)$', texte))
    assert directives == {'PartOf': 'pollux.service romulus.service',
                          'After': 'network-online.target', 'Wants': 'network-online.target'}
