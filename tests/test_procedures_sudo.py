# SPDX-License-Identifier: AGPL-3.0-or-later
# Garde des deux scripts d'installation et de la procédure d'essai : la liste de tête des commandes lancées
# par sudo est exacte face au code (rien d'oublié, rien en trop), chaque sudo est suivi d'un chemin absolu,
# chaque journalctl est lancé par sudo avec --no-pager, et les blocs de la procédure sont étiquetés bash.
# Dépendances : bibliothèque standard, pytest.
# Suivi des versions
#   0.1.2  2026-11-08  Mode --mise-a-jour : présence des exécutables testée sans sudo, liste des fichiers posés dans pose_complete.
#   0.1.1  2026-11-07  Installation tmpfiles du tunnel, contrôle des groupes et commandes sudo associées.
#   3.0.0-alpha.42  2026-11-07  Première version.
#   3.0.0-alpha.45  2026-11-07  Garde contre les formes `test … && action` qui ne s'arrêtent pas.
#   0.1.0  2026-11-07  Groupes des sondes de Castor et maintien des refus croisés.
#   0.1.0  2026-11-07  Sources : les deux scripts d'installation et l'essai de présence (les procédures pas à pas ne sont plus lues).
import re
import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
DEPLOY = RACINE / 'deploy'
ADMIN = DEPLOY / 'backend-admin' / 'installer-backend-admin.sh'
RELAIS = DEPLOY / 'backend-relais' / 'installer-backend-relais.sh'
ESSAI = DEPLOY / 'essai-presence.md'
QUATRE = [ADMIN, RELAIS, ESSAI]    # deux scripts et la procédure d'essai (qui reste une procédure séparée)
MARQUE = 'Commandes lancées par `sudo`'


def blocs(chemin):
    texte = chemin.read_text(encoding='utf-8')
    if chemin.suffix == '.sh':
        return [texte.replace('\\\n', ' ')]
    return [b.replace('\\\n', ' ') for b in re.findall(r'(?ms)^[ ]*```bash\n(.*?)^[ ]*```', texte)]


def lignes_code(chemin):
    return [l.strip() for b in blocs(chemin) for l in b.splitlines()
            if l.strip() and not l.strip().startswith('#') and not l.strip().startswith(('command "sudo"', 'if type -P'))]


def executables_sudo(ligne):
    """Exécutables lancés par chaque `sudo` de la ligne, wrappers (env, runuser, sudo, find -exec, nsenter) résolus."""
    trouves, erreurs = set(), []
    for m in re.finditer(r'(?<![\w/.-])sudo\s+(\S+)((?:\s+[^|;&)]*)?)', ligne):
        premier = m.group(1)
        if not re.fullmatch(r'/usr/s?bin/[\w.-]+', premier):
            erreurs.append(premier)
            continue
        jetons = (premier + ' ' + m.group(2)).split()
        trouves.add(premier)
        i = 0
        while i < len(jetons):
            j = jetons[i]
            suivant = None
            if j in ('/usr/bin/env', '/usr/bin/sudo', '/usr/sbin/runuser', '/usr/bin/nsenter'):
                k = i + 1
                if j in ('/usr/sbin/runuser', '/usr/bin/nsenter'):
                    while k < len(jetons) and jetons[k] != '--':
                        k += 1
                    k += 1
                else:
                    while k < len(jetons) and not jetons[k].startswith('/usr/') and jetons[k] != '--':
                        k += 1
                    if k < len(jetons) and jetons[k] == '--':
                        k = len(jetons)  # après `--` : argument refusé ou commande de l'essai, non lancé par ce sudo
                suivant = k
            elif j == '-exec':
                suivant = i + 1
            if suivant is not None and suivant < len(jetons) and re.fullmatch(r'/usr/s?bin/[\w.-]+', jetons[suivant]):
                trouves.add(jetons[suivant])
                i = suivant
                continue
            i += 1
    return trouves, erreurs


def reels(chemin):
    tous, erreurs = set(), []
    for ligne in lignes_code(chemin):
        t, e = executables_sudo(ligne)
        tous |= t
        erreurs += [(ligne, x) for x in e]
    return tous, erreurs


def annonces_script(chemin):
    """Exécutables de la liste descriptive du commentaire d'en-tête d'un script (puces « # - »)."""
    lignes = chemin.read_text(encoding='utf-8').splitlines()
    debut = next(i for i, l in enumerate(lignes) if MARQUE in l)
    puces, en_liste = [], False
    for ligne in lignes[debut + 1:]:
        if ligne.startswith('# - '):
            en_liste = True
            puces.append(ligne)
        elif en_liste:
            break
    return set(re.findall(r'/usr/s?bin/[\w.-]+', '\n'.join(puces)))


def annonces(chemin):
    if chemin.suffix == '.sh':
        return annonces_script(chemin)
    texte = chemin.read_text(encoding='utf-8')
    debut = texte.index(MARQUE)
    liste = []
    en_liste = False
    for ligne in texte[debut:].splitlines()[1:]:
        if ligne.startswith('- '):
            en_liste = True
            liste.append(ligne)
        elif en_liste and ligne.strip():
            break
        elif en_liste and not ligne.strip():
            break
    return set(re.findall(r'/usr/s?bin/[\w.-]+', '\n'.join(liste)))


@pytest.mark.parametrize('chemin', QUATRE, ids=lambda p: p.name)
def test_chaque_sudo_a_un_chemin_absolu(chemin):
    _, erreurs = reels(chemin)
    assert not erreurs, erreurs
    assert not re.search(r'sudo\s+(-i|-s|su\b|sh\b|bash\b)|sudo[^\n|]*\b(sh|bash)\s+-c', '\n'.join(lignes_code(chemin)))


@pytest.mark.parametrize('chemin', QUATRE, ids=lambda p: p.name)
def test_liste_sudo_exacte(chemin):
    attendu = set()
    for source in (QUATRE if chemin == ESSAI else [chemin]):
        attendu |= reels(source)[0]
    annonce = annonces(chemin)
    assert not (attendu - annonce), f'commandes sudo non listées : {sorted(attendu - annonce)}'
    assert not (annonce - attendu), f'commandes listées sans emploi : {sorted(annonce - attendu)}'


@pytest.mark.parametrize('chemin', QUATRE, ids=lambda p: p.name)
def test_journalctl_par_sudo_sans_pager(chemin):
    for ligne in lignes_code(chemin):
        if ligne.startswith('executables_requis '):
            continue    # contrôle de présence ([ -x ], sans sudo) : l'exécutable n'est pas lancé
        if re.search(r'(?<![\w/-])journalctl\b|/usr/bin/journalctl', ligne):
            assert 'sudo /usr/bin/journalctl' in ligne and '--no-pager' in ligne, ligne
    for ligne in chemin.read_text(encoding='utf-8').splitlines():
        for m in re.finditer(r'`((?:sudo /usr/bin/)?journalctl [^`]*)`', ligne):
            if '-u' in m.group(1) and '--no-pager' in m.group(1):
                assert m.group(1).startswith('sudo /usr/bin/journalctl'), ligne


@pytest.mark.parametrize('chemin', [ESSAI], ids=lambda p: p.name)
def test_blocs_etiquetes_bash(chemin):
    texte = chemin.read_text(encoding='utf-8')
    ouvertures = re.findall(r'(?m)^[ ]*```(\w*)$', texte)
    langages = ouvertures[0::2]
    assert langages and all(l in ('bash', 'text') for l in langages), set(langages)
    assert '```sh' not in texte and 'bash' in langages
    assert len(ouvertures) % 2 == 0


def test_outils_sbin_testes_sans_command_v():
    # /usr/sbin n'est pas dans le PATH d'un compte ordinaire : `command -v` y échouerait
    for chemin in (ADMIN, RELAIS):
        for ligne in lignes_code(chemin):
            if ligne.startswith('command -v') or 'command -v' in ligne:
                assert not re.search(r'\b(nft|visudo|runuser|sshd)\b', ligne), ligne
    # la présence des exécutables est testée sans sudo ([ -x ], accumulée) : l'absence de sudo est ainsi signalée avec les autres
    relais = RELAIS.read_text(encoding='utf-8')
    assert 'executables_requis /usr/bin/python3 /usr/bin/env /usr/bin/sudo /usr/sbin/visudo /usr/sbin/nft /usr/sbin/runuser' in relais
    assert 'if [ ! -x "$chemin" ]; then' in relais
    assert '/usr/sbin/sshd' in ADMIN.read_text(encoding='utf-8').split('controle_prerequis() {')[1].split('controle_manques')[0]
    for chemin in (ADMIN, RELAIS):
        corps = chemin.read_text(encoding='utf-8').split('controle_prerequis() {')[1].split('\n}\n')[0]
        assert 'sudo /usr/bin/test -x' not in corps


def test_variable_de_stockage_traverse_outil():
    for chemin in (ADMIN, RELAIS):
        texte = chemin.read_text(encoding='utf-8')
        definition = next(l for l in texte.splitlines() if l.strip().startswith('outil() {'))
        assert 'PYTHONPATH=/run/paresia-installation' in definition
        assert '${PARESIA_SAUVEGARDE_STOCKAGE_ACTIF:+PARESIA_SAUVEGARDE_STOCKAGE_ACTIF=' in definition


def test_sudo_dans_boucle_while_read_sans_entree_standard():
    # un sudo lancé dans une boucle `while read` ne doit pas consommer l'entrée de la boucle
    for chemin in (ADMIN, RELAIS):
        lignes = lignes_code(chemin)
        for i, ligne in enumerate(lignes):
            if ligne.startswith('while IFS= read'):
                corps = lignes[i + 1:lignes.index(next(l for l in lignes[i + 1:] if l.startswith('done')), i + 1)]
                assert corps and all('< /dev/null' in l for l in corps if 'sudo' in l), (chemin.name, corps)


def appels_sudo_simules(chemin, fonction, appels):
    """Exécute la fonction livrée avec sudo remplacé : aucun changement d'identité ni accès aux sockets."""
    texte = chemin.read_text(encoding='utf-8')
    definition = re.search(r'(?ms)^' + fonction + r'\(\) \{.*?^\}', texte).group()
    script = ('sudo() { printf \'%s\\0\' "$@" __fin_appel__; }\nfiltre_sortie() { cat; }\n'
              + definition + '\n' + appels)
    resultat = subprocess.run(['bash', '--noprofile', '--norc'], input=script,
                              text=True, capture_output=True, timeout=10)
    assert resultat.returncode == 0, resultat.stderr
    return [appel.split('\0') for appel in resultat.stdout.split('\0__fin_appel__\0') if appel]


def test_jumeaux_groupes_et_refus_croises():
    texte = RELAIS.read_text(encoding='utf-8')
    etape = texte[texte.index('etape_refus_castor() {'):texte.index('# Étape isolation_remus') if '# Étape isolation_remus' in texte else None]
    appels = '\n'.join('jumeaux ' + ' '.join(m) for m in re.findall(r'\bjumeaux (\w+) (/run/\S+) (castor/light/\w+)', etape))
    commandes = appels_sudo_simules(RELAIS, 'jumeaux', appels)
    attendus = [
        ('tunnel', [], 'castor.sock', 'ping'),
        ('chef', ['-g', 'chef', '-G', 'paresia-castor-etat'], 'castor-state.sock', 'state'),
        ('tunnel', [], 'castor.sock', 'close'),
        ('chef', ['-g', 'chef', '-G', 'paresia-castor-etat'], 'castor-state.sock', 'state'),
        ('chef', [], 'castor.sock', 'ping'),
        ('tunnel', [], 'castor-state.sock', 'state'),
    ]
    assert len(commandes) == len(attendus)
    for commande, (compte, groupes, socket, action) in zip(commandes, attendus):
        separateur = commande.index('--')
        assert commande[:separateur] == ['/usr/sbin/runuser', '-u', compte, *groupes]
        assert commande[separateur + 1:separateur + 4] == ['/usr/bin/python3', '-I', '-c']
        assert commande[-2:] == ['/run/paresia-castor/' + socket, 'castor/light/' + action]


def test_sonde_groupes_de_lecture_remus():
    commandes = appels_sudo_simules(ESSAI, 'sonde', 'sonde 1\n')
    assert len(commandes) == 1
    commande = commandes[0]
    assert commande[:10] == ['/usr/sbin/runuser', '-u', 'chef', '-g', 'chef', '-G',
                             'paresia-castor-etat', '--', '/usr/bin/python3', '-c']
    assert "s.connect('/run/paresia-castor/castor-state.sock')" in commande[10]
    assert commande[11:] == ['1']


@pytest.mark.parametrize('chemin', [RELAIS, ESSAI], ids=lambda p: p.name)
def test_groupes_sonde_annonces_et_documentes(chemin):
    texte = chemin.read_text(encoding='utf-8')
    liste = '\n'.join(l.removeprefix('# ') for l in texte.splitlines() if l.removeprefix('# ').startswith('- essais :'))
    assert '/usr/sbin/runuser -u chef -g chef -G paresia-castor-etat --' in liste
    assert 'runuser(1)' in texte and '`-g, --group`' in texte and '`-G, --supp-group`' in texte
    assert 'This option is allowed for the root user only.' in texte
    assert 'This option is available to the root user only.' in texte


def test_sous_etape_allowusers_et_diff_sshd():
    texte = RELAIS.read_text(encoding='utf-8')
    etape = texte[texte.index('etape_tunnel_sshd() {'):texte.index('verifier_tunnel_sshd()')]
    assert 'ordinaire-avant.txt' in etape and 'ordinaire-apres.txt' in etape and 'diff /run' in etape
    assert etape.index('ordinaire-avant.txt') < etape.index('poser_fichier "$DEPOT/$SRC/ssh/sshd_config.d/50-paresia-tunnel.conf"')
    # sous-étape AllowUsers : seulement si une liste existe déjà, sauvegardée avant, sshd -t puis reload
    sous = etape[etape.index('utilisateurs=$(sshd_tunnel'):]
    assert '[ -n "$utilisateurs" ]' in sous and 'sauvegarder "$SSH_ALLOWUSERS"' in sous
    assert sous.index('sauvegarder') < sous.index('tee /etc/ssh/sshd_config.d/40-paresia-tunnel-allowusers.conf')
    assert sous.index('sshd_t') < sous.index('recharger_ssh')
    assert "Sous-étape AllowUsers" in sous and 'N\'ajoutez' not in sous
    assert 'sans objet' in texte.lower() or 'seulement si une liste existe déjà' in texte
    assert 'exiger_session_secours' in etape.split('sudo /usr/sbin/sshd -T')[0]


def test_convention_aussi_dans_les_scripts():
    admin, relais = ADMIN.read_text(encoding='utf-8'), RELAIS.read_text(encoding='utf-8')
    assert 'pas un sudoers à recopier' in admin and 'pas un sudoers à recopier' in relais
    assert 'ne peuvent pas être restreintes' in admin and 'ne peuvent pas être restreintes' in relais
    assert 'Aucun shell root' in relais and 'refuse de s\'exécuter en root' in relais
    assert 'sans sudo' in admin and 's\'exécute en root' in admin and 'sans `sudo`' in admin


def test_tunnel_tmpfiles_installe_avant_demarrage():
    texte = ADMIN.read_text(encoding='utf-8')
    etape = texte[texte.index('etape_tunnel_unite() {'):texte.index('verifier_tunnel_unite() {')]
    configuration = '/etc/tmpfiles.d/paresia-tunnel.conf'
    creation = f'sudo /usr/bin/systemd-tmpfiles --create {configuration}'
    sauvegarde = 'sauvegarder "$TMPFILES_TUNNEL"'
    installation = ('sudo /usr/bin/install -D -m 0644 -o root -g root '
                    '"$DEPOT/deploy/backend-admin/etc/tmpfiles.d/paresia-tunnel.conf" ' + configuration)
    assert etape.index(sauvegarde) < etape.index(installation) < etape.index(creation)
    assert etape.index(creation) < etape.index('sudo /usr/bin/systemctl start paresia-tunnel.service')
    assert 'refuser_si_active paresia-tunnel.service' in etape.split(installation)[0]   # jamais d'arrêt par le script
    assert configuration in texte[texte.index('pose_complete() {'):]       # restauré par le retour arrière
    for chemin in (ADMIN, ESSAI):
        assert {'/usr/bin/systemd-tmpfiles', '/usr/bin/namei'} <= annonces(chemin)
    controle = texte[texte.index('etape_tunnel_sockets() {'):texte.index('verifier_tunnel_sockets() {')]
    assert 'sudo /usr/bin/namei -l /run/paresia-tunnel/romulus/remus.sock' in controle
    assert 'getfacl' not in texte and 'setfacl' not in texte
    verif = texte[texte.index('verifier_tunnel_unite() {'):texte.index('jumeaux() {')]
    assert 'paresia-tunnel:paresia-romulus 710' in verif and 'paresia-tunnel:paresia-pollux 710' in verif
    assert 'root:root 711' in verif


def test_tunnel_releve_groupes_sans_membre_supplementaire():
    texte = ADMIN.read_text(encoding='utf-8')
    verif = texte[texte.index('verifier_tunnel_sockets() {'):texte.index('# Étape activation')]
    commande = 'sudo /usr/bin/getent group paresia-romulus paresia-pollux'
    assert commande in '\n'.join(lignes_code(ADMIN))
    assert verif.index('controle_groupes_tunnel') < verif.index('connecte ')
    assert 'quatrième champ vide' in texte and 'aucun membre supplémentaire' in texte
    for chemin in (ADMIN, ESSAI):
        assert '/usr/bin/getent' in annonces(chemin)
    liste = '\n'.join(l.removeprefix('# ') for l in ESSAI.read_text(encoding='utf-8').splitlines() if l.startswith('- comptes et'))
    assert '`/usr/bin/getent group paresia-romulus paresia-pollux`' in liste


    for chemin in (ADMIN, RELAIS):
        assert not any('${PYTHONPATH:?}' in l for l in lignes_code(chemin))


# Premiers mots d'un segment qui modifie le système ; un segment `echo` ou `printf` n'en fait pas partie.
ACTIONS = ('sudo', 'install', 'tar', 'cp', 'mv', 'rm', 'chown', 'chmod', 'tee', 'sed', 'systemctl', 'useradd',
           'groupadd', 'usermod', 'nft', 'outil', 'ssh-keygen', 'mkdir', 'ln', 'export', 'unset', 'cd')
# Actions en lecture seule, permises après une garde (empreinte d'une clé, sans rien écrire).
LECTURES = ('sudo /usr/bin/ssh-keygen -lf ',)
GARDE = re.compile(r'^(?:!\s*)?(?:test |sudo /usr/bin/test |\[ )')


@pytest.mark.parametrize('chemin', QUATRE, ids=lambda c: c.name)
def test_aucune_garde_test_et_action(chemin):
    """Une garde `test … && action` ne s'arrête pas en cas d'échec : elle doit être un `if … then … else … fi`."""
    fautes = []
    for ligne in lignes_code(chemin):
        if ligne.startswith('if '):
            continue
        segments = [x.strip() for x in ligne.split('&&')]
        for avant, segment in zip(segments, segments[1:]):
            if not GARDE.match(avant):
                continue
            mots = segment.split()
            if mots and mots[0] in ACTIONS and not segment.startswith(LECTURES):
                fautes.append(ligne)
    assert not fautes, fautes
