# SPDX-License-Identifier: AGPL-3.0-or-later
# Suivi des versions : 3.0.0-alpha — 2026-11-06, tests T023.
#   0.1.7  2026-11-07  Fichier attendu calculé par le chargeur de fonctions (dossiers vides).
#   0.1.0  2026-11-07  Confirmation préalable du remplacement du code ; Comptes hors /home et paramètres sans invite.
#   0.1.0  2026-11-07  Source des assertions de procédure : le script installer-backend-relais.sh (fonctions extraites et exécutées avec des commandes factices).
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

from remus_outils import Banc
from server.commun.config import lire
from server.remus import SCHEMA
from server.remus.fonctions import regles_sudoers
from server.remus.executeur import (Choix, Commande, Entier, Executeur, Hexadecimal,
                                   ListeEntiers, Param, ParamOption, RenduSudo, Texte, Variable,
                                   construire_table)
from server.remus.sudoers import (ENTETE, EXPRESSION_ENTIER_MAX, HEXADECIMAL_MAX,
                                 REGLES_MAX, _intervalle, generer_sudoers)

RACINE = Path(__file__).resolve().parents[1]
DEPLOY = RACINE / 'deploy/backend-relais'
LIVRE = DEPLOY / 'etc/sudoers.d/paresia-remus'
SCRIPT = DEPLOY / 'installer-backend-relais.sh'
P = ('sudo', '-n', '--', 'docker')
CONFIG = {'sudo': '/usr/bin/sudo', 'docker': '/opt/outils/docker', 'simultanes': 4}


def rendu(*elements):
    return (RenduSudo('essai', ('/opt/outils/docker',) + elements),)


def variable(gabarit):
    return Variable('v', gabarit)


def regles(texte):
    return [l for l in texte.splitlines() if l and not l.startswith('#')]


def motif(texte):
    # Décode le niveau de protection de sudoers, avant POSIX ERE.
    return regles(texte)[0].split('docker ', 1)[1].replace('\\\\', '\\')


def test_sudoers_generation():
    texte = generer_sudoers(rendu('restart', 'relais'), 'chef')
    assert regles(texte) == ['chef ALL=(root) NOPASSWD: /opt/outils/docker restart relais']
    choix = generer_sudoers(rendu('exec', 'relais', 'outil', variable(Choix('oui', 'non'))), 'chef')
    assert len(regles(choix)) == 2
    assert all('^' not in l for l in regles(choix))
    assert regles(choix)[0].endswith('outil oui')


def test_sudoers_gabarits_traduits():
    texte = generer_sudoers(rendu('exec', 'relais', '/bin/outil.v1+',
                                 variable(Hexadecimal(4)), variable(Entier(7, 113)),
                                 variable(Choix('oui', 'non'))), 'chef')
    assert len(regles(texte)) == 2
    m = motif(texte)
    for n in range(7, 114):
        assert re.fullmatch(m, f'exec relais /bin/outil.v1+ ab09 {n} oui')
    for n in ('6', '114', '007', '-7', '7 8', '7\n', '7x'):
        assert not re.fullmatch(m, f'exec relais /bin/outil.v1+ ab09 {n} oui')
    for h in ('AB09', 'ab0', 'ab099', 'ab 9', 'ab0g'):
        assert not re.fullmatch(m, f'exec relais /bin/outil.v1+ {h} 7 oui')
    assert not re.fullmatch(m, 'exec relais /bin/outilXv1+ ab09 7 oui')
    assert not re.fullmatch(m, 'exec relais /bin/outil.v1+ ab09 7 oui ajout')


@pytest.mark.parametrize('minimum,maximum', [(0, 0), (0, 9), (3, 17), (90, 120),
                                               (100, 999), (989, 1001), (2**63, 2**63)])
def test_intervalle_exact(minimum, maximum):
    m = _intervalle(minimum, maximum)
    valeurs = set(range(max(0, minimum - 3), min(maximum + 4, minimum + 1200)))
    valeurs.update((minimum, maximum, maximum + 1))
    for n in valeurs:
        assert bool(re.fullmatch(m, str(n))) == (minimum <= n <= maximum)
        if n:
            assert not re.fullmatch(m, '0' + str(n))
    assert len(m) <= EXPRESSION_ENTIER_MAX


@pytest.mark.parametrize('element', ['a*b', 'a?b', '[a]', 'a\\b', 'a b', 'a,b', 'a:b',
                                    'a=b', 'a#b', 'a!b', 'a"b', 'a\nb', 'a\x7fb', 'é'])
def test_sudoers_refus_element(element):
    with pytest.raises(ValueError, match='^sudoers_unsafe_element$'):
        generer_sudoers(rendu('restart', element), 'chef')
    with pytest.raises(ValueError, match='^sudoers_unsafe_element$'):
        generer_sudoers((RenduSudo('a', (element, 'restart', 'relais')),), 'chef')


@pytest.mark.parametrize('gabarit', [Texte('a', 1), ListeEntiers(0, 9, 2), object(),
                                    Choix('a', espace=True), Hexadecimal(HEXADECIMAL_MAX + 1),
                                    Choix(*(str(n) for n in range(REGLES_MAX + 1)))])
def test_sudoers_refus(gabarit):
    with pytest.raises(ValueError, match='^sudoers_unsafe_template$'):
        generer_sudoers(rendu('exec', 'relais', 'outil', variable(gabarit)), 'chef')


def test_sudoers_refus_positions_et_plafonds():
    v = variable(Hexadecimal(4))
    for elements in [('restart', 'relais', v), ('exec', v, 'outil'),
                     ('exec', 'relais', v), ('exec', 'relais', 'outil', Variable('x', Entier(0, 1), '--x'))]:
        with pytest.raises(ValueError, match='^sudoers_unsafe_template$'):
            generer_sudoers(rendu(*elements), 'chef')
    v = variable(Choix(*(str(n) for n in range(17))))
    with pytest.raises(ValueError, match='^sudoers_unsafe_template$'):
        generer_sudoers(rendu('exec', 'relais', 'outil', v, v), 'chef')
    with pytest.raises(ValueError, match='^sudoers_unsafe_template$'):
        generer_sudoers(rendu('exec', 'relais', 'outil', variable(Entier(123456789012345678, 876543210987654321))), 'chef')
    for compte in ('chef ALL', 'root\n', 'a:b', '', 'A', 'a' * 33):
        with pytest.raises(ValueError, match='^sudoers_unsafe_element$'):
            generer_sudoers((), compte)


def test_sudoers_aucun_droit_large():
    for elements in [(), ('ps',), ('exec',), ('exec', 'relais'), ('-H', 'hote', 'exec', 'relais'),
                     ('run', 'image'), ('cp', 'a', 'b'), ('compose', 'up'),
                     ('exec', '-u', 'root', 'relais', 'outil'), ('restart', '--all')]:
        with pytest.raises(ValueError):
            generer_sudoers(rendu(*elements), 'chef')
    with pytest.raises(ValueError, match='^sudoers_unsafe_element$'):
        generer_sudoers((RenduSudo('a', ('/usr/bin/', 'restart', 'relais')),), 'chef')
    texte = generer_sudoers(rendu('exec', 'relais', 'outil', variable(Hexadecimal(64))), 'chef')
    assert 'NOPASSWD: ALL' not in texte and '(ALL)' not in texte
    assert not regles(texte)[0].endswith('*')


def test_sudoers_aucun_joker():
    def sans_joker(texte):
        for ligne in regles(texte):
            assert '*' not in ligne and '?' not in ligne
    # Règle fixe sans paramètre.
    sans_joker(generer_sudoers(rendu('restart', 'relais'), 'chef'))
    for g in [Choix('a', 'b'), Hexadecimal(128), Entier(0, 1000)]:
        texte = generer_sudoers(rendu('exec', 'relais', 'outil', variable(g)), 'chef')
        assert '*' not in texte and '?' not in texte
    # Combinaison Hexadecimal + Entier + Choix.
    sans_joker(generer_sudoers(rendu('exec', 'relais', 'outil', variable(Hexadecimal(8)),
                                    variable(Entier(0, 1000)), variable(Choix('a', 'b'))), 'chef'))
    # Fichier livré.
    sans_joker(LIVRE.read_text())


def test_sudoers_crochets_seulement_classes_attendues():
    # Le générateur n'émet « [ » que pour [0-9a-f] et [0-9] (classes ERE fermées).
    def verifier(texte):
        for ligne in regles(texte):
            assert '[' not in ligne.replace('[0-9a-f]', '').replace('[0-9]', ''), ligne
    verifier(generer_sudoers(rendu('exec', 'relais', 'outil', variable(Hexadecimal(8)),
                                   variable(Entier(0, 1000)), variable(Choix('a', 'b'))), 'chef'))
    verifier(LIVRE.read_text())


def test_sudoers_option_refusee_via_executeur(tmp_path):
    c = Commande('essai', P + ('exec', 'relais', 'outil', ParamOption('--delai', 'd', Entier(0, 9))))
    ex = Banc(tmp_path).executeur([c])
    with pytest.raises(ValueError, match='^sudoers_unsafe_template$'):
        generer_sudoers(ex.commandes_sudo(), 'chef')


@pytest.mark.parametrize('minimum,maximum', [(-1, 5), (5, 4), (-3, -1), (10, 2)])
def test_intervalle_refus_bornes(minimum, maximum):
    with pytest.raises(ValueError, match='^sudoers_unsafe_template$'):
        _intervalle(minimum, maximum)


def test_sudoers_erreur_sans_element():
    for element in ('a\nb\nsecret-x', 'a b\rsecret-y'):
        for elements in (('restart', element), (element, 'restart', 'relais')):
            with pytest.raises(ValueError) as erreur:
                generer_sudoers((RenduSudo('a', ('/opt/outils/docker',) + elements),), 'chef')
            assert str(erreur.value) == 'sudoers_unsafe_element'
            assert '\n' not in str(erreur.value) and 'secret' not in str(erreur.value)


def test_sudoers_table_vide():
    assert generer_sudoers(Executeur(CONFIG, construire_table()).commandes_sudo(), 'chef') == ENTETE
    assert regles(ENTETE) == []


def test_sudoers_source_unique(tmp_path):
    banc = Banc(tmp_path)
    c = Commande('essai', P + ('exec', 'relais', 'outil', Param('n', Entier(3, 8)),
                              Param('h', Hexadecimal(4))))
    ex = banc.executeur([c])
    assert ex.lancer('essai', {'n': 5, 'h': 'ab09'}).ok
    argv = banc.recu()['argv']
    r = ex.commandes_sudo()
    assert argv[:2] == ['-n', '--']
    assert argv[2] == r[0].elements[0] == ex.configuration['docker']
    texte = generer_sudoers(r, 'chef')
    arguments = regles(texte)[0].split(' NOPASSWD: ', 1)[1].split(' ', 1)[1].replace('\\\\', '\\')
    assert re.fullmatch(arguments, ' '.join(argv[3:]))


def configuration(tmp_path):
    f = tmp_path / 'paresia.conf'
    f.write_text((RACINE / 'server/conf/paresia-relais.conf').read_text())
    f.chmod(0o644)
    tmp_path.chmod(0o755)
    return f


def dossiers_vides(tmp_path):
    # Le dossier livré du dépôt est copié (propriétaire = uid effectif du test).
    shutil.copytree(DEPLOY / 'usr/local/lib/paresia/remus/fonctions', tmp_path / 'livre',
                    dirs_exist_ok=True)
    for dossier in (tmp_path / 'livre', tmp_path / 'local'):
        dossier.mkdir(mode=0o755, exist_ok=True)
        dossier.chmod(0o755)
        for fichier in dossier.iterdir():
            fichier.chmod(0o755 if fichier.suffix != '.toml' else 0o644)
    return {'proprietaires': {os.geteuid()}, 'racine_confiance': tmp_path}


def test_sudoers_fichier_genere(tmp_path):
    f = configuration(tmp_path)
    conf = lire('remus', SCHEMA, argv=[], environ={'PARESIA_REMUS_CONFIG': str(f)}, journal=True, metriques=True)
    options = dossiers_vides(tmp_path)
    conf['plugins'].update(fonctions=str(tmp_path / 'livre'), locales=str(tmp_path / 'local'))
    attendu = generer_sudoers(regles_sudoers(conf, **options), 'chef')
    assert LIVRE.read_text() == attendu


def test_sudoers_commande(tmp_path):
    f = configuration(tmp_path)
    env = {'PATH': os.environ.get('PATH', ''), 'PARESIA_REMUS_CONFIG': str(f)}
    def lancer():
        return subprocess.run([sys.executable, '-m', 'server.remus.sudoers'], cwd=RACINE,
                              env=env, capture_output=True, text=True, timeout=10)
    # Dossiers par défaut absents sur la machine d'essai : en-tête seul, sans règle, sans erreur.
    p = lancer()
    assert (p.returncode, p.stderr) == (0, '') and not regles(p.stdout)
    for texte in ('[remus.executor]\nsudo = relatif\n', '[remus.executor]\nsudo = /bin/sudo\n'):
        f.write_text(texte)
        p = lancer()
        assert p.returncode == 1 and not p.stdout
        assert re.fullmatch(r'config_[a-z_]+\n', p.stderr)
        assert 'relatif' not in p.stderr


def test_sudoers_visudo(tmp_path):
    outil = shutil.which('visudo', path=os.defpath + ':/usr/sbin')
    if not outil:
        pytest.skip('visudo absent')
    fichier = tmp_path / 'sudoers'
    fichier.write_text(generer_sudoers(rendu('exec', 'relais', 'outil.v1+',
                            variable(Hexadecimal(8)), variable(Entier(9, 12))), 'chef') +
                      generer_sudoers(rendu('restart', 'relais'), 'chef'))
    invalide = tmp_path / 'invalide'
    invalide.write_text('chef ALL=(root NOPASSWD: /bin/true\n')
    for chemin, valide in [(LIVRE, True), (fichier, True), (invalide, False)]:
        try:
            p = subprocess.run([outil, '-c', '-f', str(chemin)], capture_output=True, text=True, timeout=10)
        except PermissionError:
            pytest.skip('visudo non lançable dans le bac à sable (permission)')
        if p.returncode and any(t in p.stderr.lower() for t in ('permission denied', 'must be root', 'operation not permitted')):
            pytest.skip('visudo : droits insuffisants pour le contrôle')
        assert (p.returncode == 0) == valide, p.stderr


def test_procedure_sudoers():
    t = SCRIPT.read_text()
    assert 'env -i PYTHONPATH=/usr/local/lib/paresia /usr/sbin/runuser -u nobody -- /usr/bin/python3 -P -s -B -m server.remus.sudoers' in t
    assert t.index('diff --') < t.index('visudo -c -f "$temporaire"') < t.index('install -o root -g root -m 0440')
    for texte in ('sudo -n -l -U chef', 'sudo -u chef /usr/bin/sudo -n -- /usr/bin/docker ps',
                  'journalctl', 'session de secours', 'root:root 0440', '1.9.10', 'POSIX extended',
                  'NEWS.gz', 'DOCKER_CONFIG', 'DOCKER_HOST', 'env_reset', 'includedir'):
        assert texte in t
    assert 'mktemp' not in t and '$?" -eq 0' not in t
    assert t.index('includedir /etc/sudoers') < t.index('install -o root -g root -m 0440')
    assert t.index('sudo -V') < t.index('install -o root -g root -m 0440')
    assert 'Defaults' not in LIVRE.read_text()


def test_script_sans_arret_hors_fonctions_dediees():
    # exit ne figure que dans les fonctions d'arrêt et dans les sous-shells de l'essai TCP : jamais dans le flux principal
    t = SCRIPT.read_text()
    for nom, corps in {m.group(1): m.group(0) for m in re.finditer(r'(?ms)^(\w+)\(\) \{(?:[^\n]*\}$|[^\n]*\n.*?^\})', t)}.items():
        if re.search(r'(?m)^[^#\n]*(?<!sys\.)\bexit\b', corps):
            assert nom in ('arreter', 'sortie_script', 'principal'), nom
    assert 'set -euo pipefail' in t.split('# DEBUT commun')[0]


def _blocs_installation():
    return SCRIPT.read_text(), []


def test_confirmation_remplacement_code():
    texte = SCRIPT.read_text()
    assert 'CONFIRMATION_CODE' not in texte
    assert 'CODE_REMPLACEMENT_CONFIRME="${CODE_REMPLACEMENT_CONFIRME:-non}"' in texte
    garde = re.search(r'(?ms)^a_poser\(\) \{.*?^\}', texte).group()
    assert 'if [ "$CODE_REMPLACEMENT_CONFIRME" = oui ]; then' in garde and 'refuser_difference "$2"' in garde
    assert 'Arrêtez les démons' not in texte      # le script ne les arrête pas : refus et message du catalogue
    assert 'install_err_unite_active' in texte


def test_procedure_controle_environnement_sudo():
    t = SCRIPT.read_text()
    install = t.index('install -o root -g root -m 0440')
    controle = t.index('test -d /etc/sudoers.d')
    grep = t.index('Defaults[:!@>]?')
    assert controle < grep < install
    assert t.index('test -r /etc/sudoers.d') < grep
    assert 'env_keep|env_check|env_delete)|!env_reset|setenv|SETENV' in t
    assert '|| rc=$?' in t and '"$rc" -ne 1' in t
    assert 'nécessaire mais non suffisant' in t and "n'est pas facultative" in t
    apres = t[t.index('controle_sudoers_apres() {'):]
    assert 'Matching Defaults entries for chef' in apres
    assert 'LC_ALL=C /usr/bin/sudo -n -l -U chef' in apres and '[ -z "$defauts" ]' in apres
    assert 'sudoers(5)' in t


def test_procedure_retour_arriere_groupes_sans_et_logique():
    t = SCRIPT.read_text()
    bloc = re.search(r'(?ms)^supprimer_comptes_crees\(\) \{.*?^\}', t).group()
    assert not re.search(r'getent group \S+ (>/dev/null )?&& groupdel', bloc)
    assert 'if cree_par_installation groupe "$nom" && getent group "$nom" > /dev/null; then' in bloc
    assert not re.search(r'(?m)^[^#\n]*userdel -r', t)
    tables = t[t.index('TABLE_GROUPES_ARRIERE=('):t.index('ETAPES=(prerequis')]
    for g in ('tunnel', 'chef', 'paresia-castor'):
        assert g in tables


def test_procedure_port_essai_valide():
    t = SCRIPT.read_text()
    assert '^[0-9]{1,5}$' in t and t.index('valider_port PORT_ESSAI "$PORT_ESSAI"') > t.index('PORT_ESSAI="${PORT_ESSAI:-49152}"')


def test_procedure_blocs_bash_valides():
    p = subprocess.run(['bash', '-n', str(SCRIPT)], text=True, capture_output=True)
    assert p.returncode == 0, p.stderr


DEBIAN = """# This file MUST be edited with the 'visudo' command as root.
Defaults\tenv_reset
Defaults\tmail_badpass
Defaults\tsecure_path="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Defaults\tuse_pty
root\tALL=(ALL:ALL) ALL
%sudo\tALL=(ALL:ALL) ALL
@includedir /etc/sudoers.d
"""
FAUTIFS = ['Defaults env_keep += "DOCKER_HOST"', 'Defaults:chef !env_reset', 'Defaults!/usr/bin/docker env_check += "X"',
           'Defaults>root env_delete -= "X"', 'Defaults setenv', 'chef ALL=(root) SETENV: /usr/bin/docker']


def _fonction(*noms):
    t = SCRIPT.read_text()
    return '\n'.join(re.search(rf'(?ms)^{n}\(\) \{{.*?^\}}', t).group() for n in noms)


STUBS = 'arreter() { echo "Arrêt : $*" >&2; exit 1; }\nEX_CONFIG=78\nreleve_info() { :; }\nfiltre_sortie() { cat; }\nformater() { echo "$*"; }\n'


def _bac(tmp_path, sudoers, sudoers_d=()):
    d = tmp_path / 'sudoers.d'
    d.mkdir()
    for i, c in enumerate(sudoers_d):
        (d / f'f{i}').write_text(c + '\n')
    f = tmp_path / 'sudoers'
    f.write_text(sudoers.replace('/etc/sudoers.d', str(d)))
    bin_ = tmp_path / 'bin'
    bin_.mkdir()
    sudo = bin_ / 'sudo'
    sudo.write_text('#!/bin/sh\nif test "$1" = /usr/bin/sudo; then echo "Sudo version 1.9"; exit 0; fi\nexec "$@"\n')
    sudo.chmod(0o755)
    b = _fonction('controle_politique_sudo')
    b = b.replace('/etc/sudoers\\.d', str(d).replace('.', '\\.')).replace('/etc/sudoers.d', str(d)).replace('/etc/sudoers', str(f))
    return STUBS + b + '\n(set -euo pipefail; controle_politique_sudo)\necho "Code de sortie : $?"\n', bin_


def _prealable(tmp_path, sudoers, sudoers_d=()):
    b, bin_ = _bac(tmp_path, sudoers, sudoers_d)
    p = subprocess.run(['bash', '-c', b], capture_output=True, text=True,
                       env={'PATH': f'{bin_}:/usr/bin:/bin'})
    return int(re.search(r'Code de sortie : (\d+)', p.stdout).group(1))


def test_prealable_sudoers_debian_defaut_passe(tmp_path):
    assert _prealable(tmp_path, DEBIAN) == 0


@pytest.mark.parametrize('ligne', FAUTIFS)
def test_prealable_entree_fautive_signalee(tmp_path, ligne):
    assert _prealable(tmp_path, DEBIAN, [ligne]) == 1
    (tmp_path / 'y').mkdir()
    assert _prealable(tmp_path / 'y', DEBIAN + ligne + '\n') == 1


SUDO_L = {
    'valide': "Matching Defaults entries for chef on h:\n    env_reset, mail_badpass, secure_path=/usr/bin, use_pty\n\n"
              "User chef may run the following commands on h:\n    (root) NOPASSWD: /usr/bin/docker ps\n",
    'francais': "Les entrées par défaut correspondantes pour chef sur h :\n    env_reset\n\nx\n",
    'vide': "",
    'aucun_droit': "User chef is not allowed to run sudo on h.\n",
    'env_keep': "Matching Defaults entries for chef on h:\n    env_reset, env_keep+=DOCKER_HOST\n\nx\n",
    'noreset': "Matching Defaults entries for chef on h:\n    !env_reset\n\nx\n",
    'setenv': "Matching Defaults entries for chef on h:\n    env_reset, setenv\n\nx\n",
    'env_check': "Matching Defaults entries for chef on h:\n    env_reset, env_check+=X\n\nx\n",
    'env_delete': "Matching Defaults entries for chef on h:\n    env_reset, env_delete-=X\n\nx\n",
    'runas': "Matching Defaults entries for chef on h:\n    env_reset\n\nRunas and Command-specific defaults for chef:\n"
             "    Defaults!/usr/bin/docker !env_reset\n\nx\n",
    'SETENV': "Matching Defaults entries for chef on h:\n    env_reset\n\nUser chef may run:\n    (root) SETENV: /usr/bin/docker\n",
    'docker': "Matching Defaults entries for chef on h:\n    env_reset\n\nUser chef may run:\n    DOCKER_HOST=x /usr/bin/docker\n",
}


def _apres(tmp_path, sortie):
    b = STUBS + _fonction('controle_sudoers_apres') + '\n(set -euo pipefail; controle_sudoers_apres)\necho "Code de sortie : $?"\n'
    bin_ = tmp_path / 'bin'
    bin_.mkdir()
    (tmp_path / 'sortie').write_text(sortie)
    sudo = bin_ / 'sudo'
    # Sortie en anglais seulement si LC_ALL=C ; sinon section introuvable. -l : liste ; autre appel : refus.
    sudo.write_text('#!/bin/sh\ncase " $* " in *journalctl*) exit 0;; *" -l "*) case " $* " in *" LC_ALL=C "*) cat "%s";; *) echo "Entrées par défaut";; esac; exit 0;; esac\nexit 1\n'
                    % (tmp_path / 'sortie'))
    sudo.chmod(0o755)
    return subprocess.run(['bash', '-c', b], capture_output=True, text=True, env={'PATH': f'{bin_}:/usr/bin:/bin'})


@pytest.mark.parametrize('cle', ['valide', 'aucun_droit'])    # chef sans aucun droit : rien à contrôler, pas un échec
def test_apres_sortie_valide(tmp_path, cle):
    p = _apres(tmp_path, SUDO_L[cle])
    assert 'Code de sortie : 0' in p.stdout and 'Arrêt' not in p.stderr


@pytest.mark.parametrize('cle', [k for k in SUDO_L if k not in ('valide', 'aucun_droit')])
def test_apres_sortie_fautive_ou_absente(tmp_path, cle):
    p = _apres(tmp_path, SUDO_L[cle])
    assert 'Arrêt' in p.stderr, (cle, p.stderr)


def test_apres_langue_forcee(tmp_path):
    t = SCRIPT.read_text()
    assert 'LC_ALL=C /usr/bin/sudo -n -l -U chef' in t


# Contrôle de l'environnement sudo : le motif du grep -P de la procédure, appliqué au contenu réel
# du fichier d'exemple du paquet Debian sudo et à des cas qui doivent être détectés.
SUDOERS_DIST = Path('/usr/share/doc/sudo/examples/sudoers.dist')


def _motif_controle_environnement():
    t = SCRIPT.read_text()
    m = re.search(r"grep -r -n -P '(.*)' /etc/sudoers /etc/sudoers\.d", t)
    assert m
    return m.group(1)


def _grep_p(contenu, tmp_path):
    f = tmp_path / 'sudoers'
    f.write_text(contenu)
    if not shutil.which('grep'):
        pytest.skip('grep absent')
    return subprocess.run(['grep', '-n', '-P', _motif_controle_environnement(), str(f)],
                          capture_output=True, text=True).returncode


@pytest.mark.skipif(not SUDOERS_DIST.is_file(), reason='sudoers.dist du paquet sudo absent')
def test_controle_environnement_hote_debian_intact(tmp_path):
    # Hôte intact : aucune ligne détectée (code 1 de grep), y compris la ligne visudo env_keep.
    assert 'Defaults!/usr/sbin/visudo env_keep' in SUDOERS_DIST.read_text()
    assert _grep_p(SUDOERS_DIST.read_text(), tmp_path) == 1


@pytest.mark.parametrize('ligne', [
    'Defaults !env_reset',
    'Defaults env_keep += "DOCKER_HOST"',
    'Defaults:chef env_keep += "DOCKER_CONFIG"',
    'Defaults!/usr/bin/docker env_keep += "DOCKER_HOST"',
    'Defaults!/usr/sbin/visudo env_keep += "SUDO_EDITOR EDITOR VISUAL DOCKER_HOST"',
    'Defaults setenv',
    'chef ALL = SETENV: /usr/bin/docker',
])
def test_controle_environnement_detecte(ligne, tmp_path):
    assert _grep_p('Defaults secure_path="/usr/bin"\n' + ligne + '\n', tmp_path) == 0
