# SPDX-License-Identifier: AGPL-3.0-or-later
# Commandes factices de l'environnement d'essai des scripts d'installation : sudo, id, getent, ss,
# ssh-keyscan, systemctl, ssh-keygen, curl. Aucun root, aucun systemd, aucun réseau : le « système »
# est une racine temporaire (FAUX_RACINE) ; l'état simulé (comptes, unités, propriétaires) est dans
# FAUX_ETAT. Les scripts testés ne contiennent aucun crochet : seul le PATH change.
# Dépendances : bibliothèque standard.
# Suivi des versions
#   0.1.19  2026-11-08  Simulation du paquet OpenSSL et comparaison Debian des versions.
#   0.1.0  2026-11-07  Création.
#   0.1.1  2026-11-07  Imports différés dans les fonctions (coût de chaque appel factice réduit).
#   0.1.3  2026-11-07  Dossiers d'état (StateDirectory=) créés au démarrage, conservés à l'arrêt, relevés par « show ».
#   0.1.2  2026-11-07  Réglages journal_extra_sudo et sorties_longues : sshd -T, ss et nft list ruleset suivis d'une sortie de plus de 200 000 octets ; clé publique factice de forme réelle.
#   0.1.3  2026-11-07  ss : liaison d'essai avec SO_REUSEADDR (un port en TIME_WAIT n'est pas en écoute).
#   0.1.5  2026-11-08  Commande server.romulus.pages : propriétaires et racine de confiance du système simulé.
#   0.1.4  2026-11-07  groupadd et useradd --system : premier numéro libre de la plage de login.defs en descendant, --gid par nom.
#   0.1.5  2026-11-08  Mise à jour : sha256sum, réglages demarrage_echec (start refusé pour une version du code installé) et mode_socket (droits des sockets créées au démarrage).
import os
import sys

ETAT = os.environ.get('FAUX_ETAT', '')
RACINE = os.environ.get('FAUX_RACINE', '')
DEPOT = os.environ.get('FAUX_DEPOT', '')
PREFIXES = ('/etc', '/var', '/run', '/usr/local', '/nonexistent')
HAUTS = ('etc', 'var', 'run', 'usr', 'nonexistent', 'proc', 'dev', 'tmp', 'home', 'bin', 'sbin', 'opt', 'srv',
         'root', 'lib', 'boot', 'sys', 'mnt', 'media')
INOFFENSIVES = ('install', 'tee', 'ls', 'cat', 'diff', 'grep', 'sed', 'find', 'tar', 'rm', 'rmdir', 'test', 'cp',
                'mv', 'chmod', 'awk', 'tail', 'sha256sum', 'dpkg')


def chemin_etat(nom):
    return os.path.join(ETAT, nom)


def lire_json(nom, defaut):
    import json
    try:
        with open(chemin_etat(nom), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return defaut


def ecrire_json(nom, valeur):
    import json
    with open(chemin_etat(nom), 'w', encoding='utf-8') as f:
        json.dump(valeur, f)


def echec(message, code=1):
    print(message, file=sys.stderr)
    sys.exit(code)


def reel(chemin):
    """Chemin du système simulé -> chemin réel dans la racine temporaire."""
    return RACINE + chemin


def haut(argument):
    return argument.split('/')[1] if argument.startswith('/') else None


def reecrire(argument):
    """Réécrit un argument absolu vers la racine ; refuse tout autre chemin absolu inconnu."""
    import re
    if not argument.startswith('/'):
        valeur = None
        if '=' in argument:
            cle, _, valeur = argument.partition('=')
            if re.fullmatch(r'[A-Z_]+', cle) and valeur.startswith(PREFIXES):
                return cle + '=' + RACINE + valeur
        return argument
    if argument == '/dev/null' or argument in ('/bin/sh', '/bin/false', '/bin/bash'):
        return argument
    if argument.startswith((RACINE + '/', DEPOT + '/', ETAT + '/')) or argument in (RACINE, DEPOT, ETAT):
        return argument
    if haut(argument) not in HAUTS:
        return argument
    if argument.startswith(PREFIXES):
        return RACINE + argument
    if re.fullmatch(r'/usr/s?bin/[\w.-]+', argument) or argument == '/usr/bin/env':
        return argument
    if argument.startswith('/proc/'):
        return argument
    echec('chemin absolu refusé par le sudo factice : ' + argument, 97)


def journaliser(argv):
    import json
    with open(chemin_etat('appels.log'), 'a', encoding='utf-8') as f:
        f.write(json.dumps(argv) + '\n')


# -- comptes ---------------------------------------------------------------------------------
def lire_fichier(nom):
    try:
        with open(chemin_etat(nom), encoding='utf-8') as f:
            return [l.rstrip('\n') for l in f if l.strip()]
    except OSError:
        return []


def ecrire_fichier(nom, lignes):
    with open(chemin_etat(nom), 'w', encoding='utf-8') as f:
        f.write(''.join(l + '\n' for l in lignes))


def passwd():
    return [l.split(':') for l in lire_fichier('passwd')]


def groupes():
    return [l.split(':') for l in lire_fichier('group')]


def sauver_passwd(lignes):
    ecrire_fichier('passwd', [':'.join(l) for l in lignes])


def sauver_groupes(lignes):
    ecrire_fichier('group', [':'.join(l) for l in lignes])


def cmd_getent(args):
    base = args[0]
    table = passwd() if base == 'passwd' else groupes()
    manque = False
    for cle in args[1:]:
        trouve = [l for l in table if l[0] == cle or l[2] == cle]
        if not trouve:
            manque = True
        for ligne in trouve:
            print(':'.join(ligne))
    sys.exit(2 if manque else 0)


def groupes_de(nom):
    utilisateur = [l for l in passwd() if l[0] == nom]
    if not utilisateur:
        echec('id: « %s » : utilisateur inexistant' % nom)
    gid = utilisateur[0][3]
    resultat = [g[0] for g in groupes() if g[2] == gid]
    resultat += [g[0] for g in groupes() if g[2] != gid and nom in g[3].split(',')]
    return resultat


def cmd_id(args):
    nom = next((a for a in args if not a.startswith('-')), None)
    if nom is None:
        print(open(chemin_etat('uid')).read().strip())
        return
    utilisateur = [l for l in passwd() if l[0] == nom]
    if not utilisateur:
        echec('id: « %s » : utilisateur inexistant' % nom)
    if '-u' in args:
        print(utilisateur[0][2])
    elif '-g' in args:
        print(utilisateur[0][3])
    elif '-nG' in args:
        print(' '.join(groupes_de(nom)))
    else:
        print('uid=%s(%s) gid=%s' % (utilisateur[0][2], nom, utilisateur[0][3]))


def bourrage(modele):
    """Sortie longue (plus de 200 000 octets, plus que la capacité d'un tube) placée après la sortie réelle quand le
    réglage `sorties_longues` de knobs.json est posé : un `grep -q` ou un `head` derrière un tube recevrait SIGPIPE."""
    if lire_json('knobs.json', {}).get('sorties_longues'):
        for i in range(6000):
            print(modele % i)


def option(args, nom):
    return args[args.index(nom) + 1] if nom in args else None


def plage_systeme(type_):
    """Bornes SYS_<type_>_MIN et SYS_<type_>_MAX de l'etc/login.defs du système simulé (repli 100 et 999)."""
    import re
    valeurs = {}
    try:
        with open(reel('/etc/login.defs'), encoding='utf-8') as f:
            for ligne in f:
                m = re.match(r'\s*(SYS_%s_(?:MIN|MAX))\s*=?\s*(\d+)' % type_, ligne)
                if m:
                    valeurs[m.group(1)] = int(m.group(2))
    except OSError:
        pass
    return valeurs.get('SYS_%s_MIN' % type_, 100), valeurs.get('SYS_%s_MAX' % type_, 999)


def premier_libre(type_, pris):
    """Premier numéro libre de la plage système, en descendant depuis la borne haute (comme useradd(8) et groupadd(8)
    pour un compte ou un groupe système) ; échec si la plage est pleine."""
    bas, haut = plage_systeme(type_)
    for numero in range(haut, bas - 1, -1):
        if str(numero) not in pris:
            return str(numero)
    echec('plage système pleine', 4)


def cmd_groupadd(args):
    nom = args[-1]
    if '--system' not in args:
        echec('groupadd: --system est requis', 2)
    if any(g[0] == nom for g in groupes()):
        echec('groupadd: groupe déjà existant', 9)
    sauver_groupes(groupes() + [[nom, 'x', premier_libre('GID', {g[2] for g in groupes()}), '']])


def cmd_useradd(args):
    gid, home, shell, nom = option(args, '--gid'), option(args, '--home-dir'), option(args, '--shell'), args[-1]
    if '--system' not in args or '--uid' in args:
        echec('useradd: --system sans --uid est requis', 2)
    if any(l[0] == nom for l in passwd()):
        echec('useradd: utilisateur déjà existant', 9)
    groupe = [g for g in groupes() if g[0] == gid]       # --gid accepte un nom (le groupe doit exister)
    if not groupe:
        echec('useradd: le groupe %s n\'existe pas' % gid, 6)
    home = home[len(RACINE):] if home and home.startswith(RACINE) else home    # donnée, non chemin réel
    if '--no-create-home' not in args or home is None:
        echec('useradd: --no-create-home et --home-dir sont requis', 2)
    uid = premier_libre('UID', {l[2] for l in passwd()})
    sauver_passwd(passwd() + [[nom, 'x', uid, groupe[0][2], '', home, shell]])


def cmd_usermod(args):
    nom, liste = args[-1], args[args.index('-aG') + 1].split(',')
    if not any(l[0] == nom for l in passwd()):
        echec('usermod: utilisateur inexistant', 6)
    table = groupes()
    for g in table:
        if g[0] in liste and nom not in g[3].split(','):
            g[3] = ','.join(x for x in g[3].split(',') + [nom] if x)
    sauver_groupes(table)


def cmd_gpasswd(args):
    nom, groupe = args[-2], args[-1]
    table = groupes()
    for g in table:
        if g[0] == groupe:
            g[3] = ','.join(x for x in g[3].split(',') if x and x != nom)
    sauver_groupes(table)


def cmd_userdel(args):
    nom = args[-1]
    cible = [l for l in passwd() if l[0] == nom]
    sauver_passwd([l for l in passwd() if l[0] != nom])
    if cible:
        gid = cible[0][3]
        # userdel retire le groupe primaire de même nom, s'il est vide et n'est plus primaire d'un autre compte.
        if not any(l[3] == gid for l in passwd()):
            sauver_groupes([g for g in groupes() if not (g[2] == gid and g[0] == nom and not g[3])])


def cmd_groupdel(args):
    nom = args[-1]
    gid = next((g[2] for g in groupes() if g[0] == nom), None)
    if any(l[3] == gid for l in passwd()):
        echec('groupdel: impossible de retirer le groupe primaire', 8)
    sauver_groupes([g for g in groupes() if g[0] != nom])


# -- propriétaires, modes -------------------------------------------------------------------
def proprietaires():
    return lire_json('owners.json', {})


def poser_proprietaire(chemin, valeur):
    donnees = proprietaires()
    donnees[chemin] = valeur
    ecrire_json('owners.json', donnees)


def cmd_install(args):
    import subprocess
    propre, nouveau, i = [], {}, 0
    proprietaire = groupe = None
    while i < len(args):
        a = args[i]
        if a in ('-o', '-g'):
            if a == '-o':
                proprietaire = args[i + 1]
            else:
                groupe = args[i + 1]
            i += 2
            continue
        propre.append(a)
        i += 1
    repertoire = '-d' in propre
    cibles = [a for a in propre if not a.startswith('-') and a != '--']
    resultat = subprocess.run(['/usr/bin/install'] + propre)
    if resultat.returncode == 0:
        cibles = cibles if repertoire else cibles[-1:]
        for c in cibles:
            if c != '/dev/null' or not repertoire:
                poser_proprietaire(c, '%s:%s' % (proprietaire or 'root', groupe or 'root'))
    sys.exit(resultat.returncode)


def cmd_chown(args):
    spec = [a for a in args if not a.startswith('-')]
    for c in spec[1:]:
        poser_proprietaire(c, spec[0])


def cmd_stat(args):
    i = args.index('-c')
    modele, fichiers = args[i + 1], [a for a in args[i + 2:] if a != '--']
    code = 0
    for f in fichiers:
        if not os.path.lexists(f):
            print("stat: impossible d'exécuter statx '%s' : Aucun fichier ou dossier de ce type" % f, file=sys.stderr)
            code = 1
            continue
        proprietaire = proprietaires().get(f, 'root:root')
        mode = '%o' % (os.stat(f).st_mode & 0o7777)
        sortie = (modele.replace('%U:%G', proprietaire).replace('%a', mode).replace('%n', f).replace('%s', str(os.stat(f).st_size))
                  .replace('%U', proprietaire.split(':')[0]).replace('%G', proprietaire.split(':')[1]))
        print(sortie)
    sys.exit(code)


# -- clés ssh ---------------------------------------------------------------------------------
def empreinte_cle(texte):
    import base64
    import hashlib
    return 'SHA256:' + base64.b64encode(hashlib.sha256(texte.encode()).digest()).decode().rstrip('=')


def cmd_ssh_keygen(args):
    import base64
    import re
    if '-lf' in args:
        source = args[args.index('-lf') + 1]
        contenu = sys.stdin.read() if source == '-' else open(source, encoding='utf-8').read()
        for ligne in contenu.splitlines():
            m = re.search(r'ssh-ed25519 (\S+)', ligne)
            if m:
                commentaire = ligne.split(m.group(1), 1)[1].strip() or 'sans-commentaire'
                print('256 %s %s (ED25519)' % (empreinte_cle(m.group(1)), commentaire))
                return
        echec('%s is not a public key file.' % source)
    chemin = args[args.index('-f') + 1]
    sentinelle = open(chemin_etat('sentinelle')).read().strip() if os.path.exists(chemin_etat('sentinelle')) else 'x'
    corps = base64.b64encode(os.urandom(32)).decode()
    with open(chemin, 'w', encoding='utf-8') as f:
        f.write('-----BEGIN FAKE KEY-----\n%s\n-----END FAKE KEY-----\n' % sentinelle)
    os.chmod(chemin, 0o600)
    with open(chemin + '.pub', 'w', encoding='utf-8') as f:
        f.write('ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI%s paresia-tunnel\n' % corps.replace('=', ''))


# -- systemd -----------------------------------------------------------------------------------
SOCKETS = {
    'pollux.service': [('/run/paresia-pollux', 'paresia-pollux:paresia-pollux', 0o711),
                       ('/run/paresia-pollux/pollux.sock', 'paresia-pollux:paresia-sessions', 0o660),
                       ('/run/paresia-pollux/pollux-relay.sock', 'paresia-pollux:paresia-liaison', 0o660)],
    'romulus.service': [('/run/paresia-romulus', 'paresia-romulus:paresia-romulus', 0o711),
                        ('/run/paresia-romulus/romulus.sock', 'paresia-romulus:paresia-liaison', 0o660),
                        ('/run/paresia-romulus/romulus-http.sock', 'paresia-romulus:paresia-http', 0o660)],
    'castor.service': [('/run/paresia-castor', 'paresia-castor:paresia-castor', 0o711),
                       ('/run/paresia-castor/castor.sock', 'paresia-castor:paresia-castor-tunnel', 0o660),
                       ('/run/paresia-castor/castor-state.sock', 'paresia-castor:paresia-castor-etat', 0o660)],
    'remus.service': [('/run/paresia-remus', 'chef:chef', 0o711),
                      ('/run/paresia-remus/remus.sock', 'chef:paresia-remus-tunnel', 0o660)],
    # les dossiers du tunnel sont créés par tmpfiles.d (systemd-tmpfiles --create), pas par l'unité
    'paresia-tunnel.service': [('/run/paresia-tunnel/romulus/remus.sock', 'paresia-tunnel:paresia-tunnel', 0o666),
                               ('/run/paresia-tunnel/pollux/castor.sock', 'paresia-tunnel:paresia-tunnel', 0o666)],
}

# Dossiers d'état créés par StateDirectory= au démarrage de l'unité et conservés à son arrêt.
ETATS = {'pollux.service': ('/var/lib/paresia-pollux', 'paresia-pollux:paresia-pollux'),
         'romulus.service': ('/var/lib/paresia-romulus', 'paresia-romulus:paresia-romulus'),
         'castor.service': ('/var/lib/paresia-castor', 'paresia-castor:paresia-castor'),
         'remus.service': ('/var/lib/paresia-remus', 'chef:chef')}


def actives():
    return lire_json('actives.json', [])


def cmd_systemctl(args):
    import shutil
    args = [a for a in args if a not in ('--no-pager', '--quiet')]
    if args[0] == '--version':
        print('systemd %s (%s-1)' % (os.environ.get('FAUX_SYSTEMD', '257'), os.environ.get('FAUX_SYSTEMD', '257')))
        for i in range(int(lire_json('knobs.json', {}).get('version_longue', 0))):
            print('+PAM +AUDIT +SELINUX +APPARMOR +IMA +IPE +SMACK +SECCOMP +GCRYPT -GNUTLS +OPENSSL +ACL +BLKID %d' % i)
        return
    sous, unites = args[0], [a for a in args[1:] if not a.startswith('-')]
    actifs, actives_fichier = actives(), 'actives.json'
    if sous == 'reload':
        return
    if sous == 'list-units':
        for u in actifs:
            print('%s loaded active running %s' % (u, u))
        return
    if sous == 'daemon-reload':
        return
    if sous == 'start':
        for u in unites:
            if not os.path.exists(reel('/etc/systemd/system/' + u)):
                echec('Failed to start %s: Unit not found.' % u, 5)
            echec_si = lire_json('knobs.json', {}).get('demarrage_echec', {})    # {unité: version du code pour laquelle start échoue}
            if u in echec_si:
                try:
                    with open(reel('/usr/local/lib/paresia/VERSION'), encoding='utf-8') as f:
                        installee = f.read().strip()
                except OSError:
                    installee = ''
                if installee == echec_si[u]:
                    echec('Job for %s failed.' % u, 1)
            if u == 'paresia-tunnel.service' and not os.path.isdir(reel('/run/paresia-tunnel/romulus')):
                echec('ssh: impossible de créer la socket : dossier absent', 255)
            if u not in actifs:
                actifs.append(u)
            if u in ETATS:
                os.makedirs(reel(ETATS[u][0]), exist_ok=True)
                os.chmod(reel(ETATS[u][0]), 0o711)
                poser_proprietaire(reel(ETATS[u][0]), ETATS[u][1])
            for chemin, proprietaire, mode in SOCKETS.get(u, []):
                if chemin.endswith('.sock'):
                    os.makedirs(os.path.dirname(reel(chemin)), exist_ok=True)
                    open(reel(chemin), 'a').close()
                else:
                    os.makedirs(reel(chemin), exist_ok=True)
                if chemin.endswith('.sock') and 'mode_socket' in lire_json('knobs.json', {}):
                    mode = int(lire_json('knobs.json', {})['mode_socket'], 8)
                os.chmod(reel(chemin), mode)
                poser_proprietaire(reel(chemin), proprietaire)
            if u == 'paresia-nftables.service':
                open(chemin_etat('table_chargee'), 'w').close()
            if u == 'castor.service' and os.path.exists(chemin_etat('feu_ferme')):
                os.unlink(chemin_etat('feu_ferme'))    # Castor redémarré : feux au rouge, sessions oubliées
        ecrire_json(actives_fichier, actifs)
    elif sous == 'stop' or (sous == 'disable' and '--now' in args):
        for u in unites:
            if u in actifs:
                actifs.remove(u)
            for chemin, _, _ in reversed(SOCKETS.get(u, [])):
                if os.path.isdir(reel(chemin)):
                    shutil.rmtree(reel(chemin))
                elif os.path.exists(reel(chemin)):
                    os.unlink(reel(chemin))
            if u == 'paresia-nftables.service' and os.path.exists(chemin_etat('table_chargee')):
                os.unlink(chemin_etat('table_chargee'))
        ecrire_json(actives_fichier, actifs)
        if sous == 'disable':
            actives_enabled(unites, False)
    elif sous in ('enable', 'disable'):
        actives_enabled(unites, sous == 'enable')
    elif sous == 'is-active':
        for u in unites:
            print('active' if u in actifs else 'inactive')
        sys.exit(0 if all(u in actifs for u in unites) else 3)
    elif sous == 'is-enabled':
        etat = lire_json('enabled.json', [])
        for u in unites:
            print('enabled' if u in etat else 'disabled')
        sys.exit(0 if all(u in etat for u in unites) else 1)
    elif sous == 'status':
        for u in unites:
            print('● %s - %s\n     Active: %s' % (u, u, 'active (running)' if u in actifs else 'inactive (dead)'))
    elif sous == 'show':
        if '--value' in args:
            print('4242')
            return
        valeurs = {'KillMode': 'mixed', 'TimeoutStopUSec': '2min 30s', 'User': 'chef',
                   'CapabilityBoundingSet': 'cap_setgid cap_setuid cap_audit_write', 'ReadWritePaths': '/run/sudo',
                   'ReadOnlyPaths': '/etc/paresia /usr/local/lib/paresia'}
        for u in unites:
            if u in ETATS:
                valeurs['StateDirectory'] = ETATS[u][0].rsplit('/', 1)[1]
        for i, a in enumerate(args):
            if a == '-p':
                print('%s=%s' % (args[i + 1], valeurs.get(args[i + 1], '')))
    else:
        echec('systemctl factice : sous-commande inconnue ' + sous, 98)


def actives_enabled(unites, activer):
    etat = lire_json('enabled.json', [])
    for u in unites:
        if activer and u not in etat:
            etat.append(u)
        if not activer and u in etat:
            etat.remove(u)
    ecrire_json('enabled.json', etat)


def cmd_ss(args):
    import socket
    if '-xl' in args:
        for u in actives():
            for chemin, _, _ in SOCKETS.get(u, []):
                if chemin.endswith('.sock'):
                    print('u_str LISTEN 0 4096 %s 12345 * 0' % chemin)
        bourrage('u_str LISTEN 0 4096 /run/neutre/%05d.sock 12345 * 0')
        return
    port = args[-1].rsplit(':', 1)[-1]
    # Écoute détectée par un essai de liaison (une connexion consommerait l'unique accept du serveur d'essai).
    # SO_REUSEADDR : une connexion en TIME_WAIT n'est pas une écoute (comme pour ss -ltn) ; un socket en LISTEN fait toujours échouer la liaison.
    with socket.socket() as essai:
        essai.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            essai.bind(('127.0.0.1', int(port)))
        except OSError:
            print('LISTEN 0 1 127.0.0.1:%s 0.0.0.0:*' % port)
            bourrage('LISTEN 0 1 127.0.0.2:%05d 0.0.0.0:*')


# -- sshd, nft, sudo ----------------------------------------------------------------------------
def cmd_sshd(args):
    if '-t' in args:
        sys.exit(1 if lire_json('knobs.json', {}).get('sshd_t_echec') else 0)
    contexte = dict(p.split('=', 1) for p in args[args.index('-C') + 1].split(','))
    utilisateur = contexte['user']
    dossier = reel('/etc/ssh/sshd_config.d/')
    valeurs = {'usepam': 'yes', 'strictmodes': 'yes', 'permituserenvironment': 'no', 'exposeauthinfo': 'no',
               'clientaliveinterval': '0', 'passwordauthentication': 'yes', 'allowtcpforwarding': 'yes',
               'allowstreamlocalforwarding': 'yes', 'authorizedkeysfile': '.ssh/authorized_keys .ssh/authorized_keys2',
               'permittty': 'yes', 'x11forwarding': 'no', 'allowagentforwarding': 'yes', 'permitlisten': 'any'}
    if utilisateur == 'app' and os.path.exists(dossier + '50-paresia-app.conf'):
        valeurs.update({'exposeauthinfo': 'yes', 'clientaliveinterval': '15', 'clientalivecountmax': '3',
                        'passwordauthentication': 'no', 'authenticationmethods': 'publickey'})
    if utilisateur == 'tunnel' and os.path.exists(dossier + '50-paresia-tunnel.conf'):
        valeurs.update({'allowtcpforwarding': 'local', 'allowstreamlocalforwarding': 'local', 'permitlisten': 'none',
                        'permittty': 'no', 'x11forwarding': 'no', 'allowagentforwarding': 'no',
                        'passwordauthentication': 'no', 'authenticationmethods': 'publickey'})
    sortie = ['%s %s' % (k, v) for k, v in sorted(valeurs.items())]
    existants = lire_json('knobs.json', {}).get('allowusers')
    if existants:
        extra = ' tunnel@' + contexte['addr'] if os.path.exists(dossier + '40-paresia-tunnel-allowusers.conf') else ''
        sortie.append('allowusers ' + existants + extra)
    extra_ctrl = lire_json('knobs.json', {}).get('sshd_extra')
    if extra_ctrl:
        sortie.append(extra_ctrl)
    print('\n'.join(sortie))
    bourrage('zzneutre %05d valeur-neutre-valeur-neutre')


def cmd_nft(args):
    chargee = os.path.exists(chemin_etat('table_chargee'))
    if args[0] == '--version':
        print('nftables v1.1.3 (Commodore Bullmoose #4)')
    elif args[:2] == ['list', 'ruleset']:
        print('table inet filter { }')
        if chargee:
            print('table inet paresia_relais { chain output { meta skuid "tunnel" ct state new reject } }')
        bourrage('# neutre %05d valeur-neutre-valeur-neutre')
    elif args[:2] == ['list', 'table']:
        if not chargee:
            echec('Error: No such file or directory', 1)
        print('table inet paresia_relais { chain output { meta skuid "tunnel" ct state new reject } }')
    elif args[0] == 'delete':
        if chargee:
            os.unlink(chemin_etat('table_chargee'))
    elif args[0] == '-c':
        return
    else:
        echec('nft factice : ' + ' '.join(args), 98)


def cmd_sudo_reel(args):
    if args and args[0] in ('--version', '-V'):
        print('Sudo version 1.9.16p2')
        if args[0] == '-V':
            print('Timestamp type: tty\nsudoers file mode 0440')
        return
    if '-l' in args:
        print('Matching Defaults entries for chef on backend-relais:\n    env_reset, mail_badpass\n\n'
              'User chef is not allowed to run sudo on backend-relais.')
        sys.exit(1)
    sys.exit(1)    # sudo -u chef sudo -n -- docker ps : refusé


def etat_socket(code, args):
    """Décide du résultat d'une connexion simulée sous runuser."""
    import re
    utilisateur = args['utilisateur']
    sockets = [a for a in args['reste'] if a.startswith('/run/')] or re.findall(r"connect\('([^']+)'\)", code)
    chemin = sockets[0] if sockets else ''
    permis = {('paresia-romulus', '/run/paresia-tunnel/romulus/remus.sock'),
              ('paresia-pollux', '/run/paresia-tunnel/pollux/castor.sock'),
              ('tunnel', '/run/paresia-castor/castor.sock'), ('chef', '/run/paresia-castor/castor-state.sock')}
    if (utilisateur, chemin) not in permis:
        print('PermissionError: [Errno 13] Permission denied')
        sys.exit(1)
    if "print('connecte')" in code:
        print('connecte')
    elif 'jumeaux/1' in code:
        action = args['reste'][1] if len(args['reste']) > 1 else ''
        ferme = os.path.exists(chemin_etat('feu_ferme'))
        if action == 'castor/light/close':
            open(chemin_etat('feu_ferme'), 'w').close()
        if action == 'castor/light/state' and ferme:
            print('{"id": "a", "ok": false, "error": "session_closed"}')
        elif action == 'castor/light/state':
            print('{"id": "a", "ok": true, "data": {"state": "green"}}')
        else:
            print('{"id": "a", "ok": true, "data": {}}')


def cmd_runuser(args):
    import subprocess
    utilisateur = args[args.index('-u') + 1]
    reste = args[args.index('--') + 1:]
    if reste[0] == '/usr/bin/curl':
        methode = reste[reste.index('-X') + 1]
        print('{"ok": false, "error": "token_missing"} 403' if methode == 'POST' else ' 405')
        return
    code = reste[reste.index('-c') + 1] if '-c' in reste else ''
    arguments = [a[len(RACINE):] if a.startswith(RACINE + '/') else a for a in reste[reste.index('-c') + 2:]] if '-c' in reste else []
    if 'create_connection' in code:
        if utilisateur == 'tunnel':
            print('ConnectionRefusedError: [Errno 111] Connection refused')
            sys.exit(1)
        sys.exit(subprocess.run([sys.executable, '-c', code] + arguments).returncode)
    etat_socket(code, {'utilisateur': utilisateur, 'reste': arguments})


def cmd_docker(args):
    """Faux docker : seule la lecture `inspect --format` existe ; tout autre appel échoue (code 97)."""
    reglages = lire_json('knobs.json', {})
    if args[:2] != ['inspect', '--format'] or len(args) != 4:
        echec('docker factice : appel inattendu : ' + ' '.join(args), 97)
    if reglages.get('docker_absent'):
        echec('Error: No such object: ' + args[3], 1)
    print(reglages.get('docker_inspect', 'registry.example.org/%s:4cd3cf6 sha256:%s' % (args[3], 'b' * 64)))


def cmd_nsenter(args):
    fichier = args[-1]
    proprietaire = proprietaires().get(fichier, 'root:root').replace(':', ' ')
    if not os.path.exists(fichier):
        echec('ls: impossible d\'accéder à %s' % fichier, 2)
    print('-rw-r--r-- 1 %s 0 nov.   7 12:00 %s' % (proprietaire, fichier))


def cmd_env(args):
    import re
    import subprocess
    env, i = dict(os.environ), 0
    if args and args[0] == '-i':
        env, i = {}, 1
    while i < len(args) and re.fullmatch(r'[A-Za-z_]+=.*', args[i]):
        cle, _, valeur = args[i].partition('=')
        env[cle] = valeur
        i += 1
    commande = args[i:]
    if commande[:1] == ['/usr/bin/python3'] and 'server.sauvegarde' in commande:
        env['PARESIA_SAUVEGARDE_STOCKAGE_DOSSIER'] = reel('/var/backups/paresia')
        sys.exit(subprocess.run([sys.executable] + commande[1:], env={**os.environ, **env}).returncode)
    if commande[:1] == ['/usr/bin/python3'] and 'server.romulus.pages' in commande:
        # Propriétaires et racine de confiance du système simulé (le compte de l'essai tient lieu de root).
        code = ('import os, sys; from server.romulus import pages; '
                'racine, livre = sys.argv[1:3]; '
                'sys.exit(pages.main(sys.argv[3:], proprietaires=frozenset({os.geteuid()}), '
                'racine_confiance=racine, dossier_livre=livre))')
        reste = commande[commande.index('server.romulus.pages') + 1:]
        sys.exit(subprocess.run([sys.executable, '-P', '-s', '-B', '-c', code, RACINE,
                                 RACINE + '/usr/local/lib/paresia/romulus/services'] + reste,
                                env={**os.environ, **env}).returncode)
    if commande[:1] == ['/usr/sbin/runuser']:
        env['PARESIA_REMUS_CONFIG'] = reel('/etc/paresia/paresia.conf')
        env['PARESIA_REMUS_PLUGINS_FONCTIONS'] = reel('/usr/local/lib/paresia/remus/fonctions')
        env['PARESIA_REMUS_PLUGINS_LOCALES'] = reel('/etc/paresia/remus/plugins.d')
        arguments = commande_sudoers(commande)
        # Les fichiers de l'essai appartiennent au compte de l'essai, non à root : propriétaire et racine de
        # confiance sont donnés au générateur, qui contrôle sinon les fichiers comme en production.
        if arguments[-2:] == ['-m', 'server.remus.sudoers']:
            arguments = arguments[:-2] + ['-c', 'import sys; from server.remus import sudoers; sys.exit(sudoers.main('
                                          'proprietaires={%d}, racine_confiance=%r))' % (os.getuid(), RACINE)]
        sys.exit(subprocess.run([sys.executable] + arguments, env={**os.environ, **env}).returncode)
    os.environ.update(env)
    executer(commande, deja_reecrit=True)


def commande_sudoers(commande):
    return commande[commande.index('--') + 2:]


def executer(argv, deja_reecrit=False):
    import re
    import subprocess
    commande = argv[0]
    nom = os.path.basename(commande)
    args = argv[1:]
    if any(a.startswith('/proc/') for a in args) and nom in ('grep', 'ls'):
        if nom == 'grep':
            print('NoNewPrivs:\t0\nSeccomp:\t2\nCapBnd:\t00000000200000c0\nCapEff:\t0000000000000000\nCapAmb:\t0000000000000000')
        elif any(a.endswith('/dev') for a in args):
            print('null\nzero\nrandom')
        sys.exit(0)
    if nom in INOFFENSIVES and nom not in ('install', 'find'):
        sys.exit(subprocess.run([commande] + args).returncode)
    if nom == 'find':
        args = [os.environ.get('USER_REEL', os.environ.get('LOGNAME', 'root')) if a == 'root' and i and args[i - 1] == '-user'
                else a for i, a in enumerate(args)]
        sys.exit(subprocess.run([commande] + args).returncode)
    table = {'install': cmd_install, 'chown': cmd_chown, 'stat': cmd_stat, 'useradd': cmd_useradd,
             'groupadd': cmd_groupadd, 'usermod': cmd_usermod, 'gpasswd': cmd_gpasswd, 'userdel': cmd_userdel,
             'groupdel': cmd_groupdel, 'ssh-keygen': cmd_ssh_keygen, 'systemctl': cmd_systemctl, 'sshd': cmd_sshd, 'ssh-keyscan': cmd_ssh_keyscan, 'getent': cmd_getent,
             'nft': cmd_nft, 'sudo': cmd_sudo_reel, 'runuser': cmd_runuser, 'docker': cmd_docker, 'nsenter': cmd_nsenter, 'env': cmd_env}
    if nom in table:
        table[nom](args)
        sys.exit(0)
    if nom == 'dpkg-query':
        reglages = lire_json('knobs.json', {})
        if reglages.get('libssl_absent'):
            print('dpkg-query: aucun paquet ne correspond à libssl3t64', file=sys.stderr)
            sys.exit(1)
        print(reglages.get('libssl_statut', 'install ok installed') + '|' +
              reglages.get('libssl_version', '3.5.7-1~deb13u3'), end='')
    elif nom == 'visudo':
        print(args[-1] + ' : analyse correcte')
    elif nom in ('systemd-analyze', 'systemd-run'):
        if nom == 'systemd-run':
            print('Running as unit: run-r1.service\nSorry, a password is required to run sudo')
    elif nom == 'journalctl':
        print('nov. 07 12:00:00 hote service[1]: light_green session=1\nnov. 07 12:00:01 hote service[1]: light_closed reason=close')
        if lire_json('knobs.json', {}).get('journal_extra'):
            print(lire_json('knobs.json', {})['journal_extra'])
        if '_COMM=sudo' in args and lire_json('knobs.json', {}).get('journal_extra_sudo'):
            print(lire_json('knobs.json', {})['journal_extra_sudo'])     # seulement le relevé des appels à sudo
    elif nom == 'systemd-tmpfiles':
        for ligne in open(args[-1], encoding='utf-8'):
            champs = ligne.split()
            if len(champs) >= 5 and champs[0] == 'd':
                chemin = reel(champs[1])
                os.makedirs(chemin, exist_ok=True)
                os.chmod(chemin, int(champs[2], 8))
                poser_proprietaire(chemin, '%s:%s' % (champs[3], champs[4]))
    elif nom == 'namei':
        for chemin in [a for a in args if a.startswith('/')]:
            print('f: %s' % chemin)
    elif nom == 'passwd':
        print('%s L 2026-11-07 0 99999 7 -1' % args[-1])
    elif nom == 'getfacl':
        for chemin in [a for a in args if a.startswith('/')]:
            cible = 'paresia-romulus' if chemin.endswith('romulus') else 'paresia-pollux'
            print('# file: %s\nuser::rwx\nuser:%s:--x\nmask::--x' % (chemin, cible))
    elif nom == 'ssh':
        hote = ''
        fichier = reel('/etc/paresia/tunnel/ssh_config.d/10-relais.conf')
        if os.path.exists(fichier):
            hote = re.search(r'HostName (\S+)', open(fichier).read()).group(1)
        print('\n'.join(['hostname ' + hote, 'user tunnel', 'port 22', 'stricthostkeychecking true',
                         'exitonforwardfailure yes', 'streamlocalbindunlink yes', 'streamlocalbindmask 0111',
                         'serveraliveinterval 15', 'identitiesonly yes', 'batchmode yes',
                         'localforward /run/paresia-tunnel/romulus/remus.sock /run/paresia-remus/remus.sock',
                         'localforward /run/paresia-tunnel/pollux/castor.sock /run/paresia-castor/castor.sock']))
    elif nom == 'python3':
        sys.exit(subprocess.run([sys.executable] + args).returncode)
    else:
        echec('commande inconnue du sudo factice : ' + commande, 99)
    sys.exit(0)


def cmd_sudo(args):
    import re
    argv = [reecrire(a) for a in args]
    if not argv or not re.fullmatch(r'/usr/s?bin/[\w.-]+', argv[0]):
        echec('sudo factice : exécutable non absolu : %s' % (args[:1],), 96)
    journaliser(argv)
    if lire_json('knobs.json', {}).get('echec_commande') == os.path.basename(argv[0]):
        sys.exit(1)
    executer(argv)


def cmd_ssh_keyscan(args):
    for _ in range(int(lire_json('knobs.json', {}).get('keyscan_lignes', 1))):
        print('%s ssh-ed25519 %s' % (args[-1], open(chemin_etat('hostkey')).read().strip()))


def principal():
    nom = os.path.basename(sys.argv[1])
    args = sys.argv[2:]
    dispatch = {'sudo': cmd_sudo, 'id': cmd_id, 'getent': cmd_getent, 'ss': cmd_ss, 'ssh-keyscan': cmd_ssh_keyscan,
                'systemctl': cmd_systemctl, 'ssh-keygen': cmd_ssh_keygen}
    if nom == 'curl':
        return
    dispatch[nom](args)


if __name__ == '__main__':
    principal()
