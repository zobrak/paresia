# SPDX-License-Identifier: AGPL-3.0-or-later
# Suivi des versions
#   0.1.1  2026-11-07  Arrêt de la préparation du tunnel si stop ou tmpfiles échoue.
#   0.1.0  2026-11-07  Contrôles en sous-shell, chemins normalisés et détection des invites dans while ; Paramétrage préalable et absence d'invite de déploiement.
#   0.1.0  2026-11-07  Les deux scripts d'installation s'ajoutent à l'essai de présence ; les procédures pas à pas ne sont plus lues.
"""Contrôle des blocs bash livrés, sans exécuter leurs commandes."""
import re
import shlex
import subprocess
from pathlib import Path

import pytest

HOME = '/ho' + 'me'
DEPLOY = Path(__file__).resolve().parents[1] / 'deploy'
ADMIN = DEPLOY / 'backend-admin' / 'installer-backend-admin.sh'
RELAIS = DEPLOY / 'backend-relais' / 'installer-backend-relais.sh'
SCRIPTS = [ADMIN, RELAIS]
ESSAI = DEPLOY / 'essai-presence.md'
PROCEDURES = [ESSAI]


def invites_interdites(texte):
    """Repère les lectures hors flux, sauf la saisie sans écho du jeton."""
    interdites = []
    for bloc in re.findall(r'^[ \t]*```bash\n(.*?)^[ \t]*```', texte, re.M | re.S):
        for ligne in bloc.splitlines():
            if not re.search(r'\bread\b', ligne) or ligne.lstrip().startswith('#'):
                continue
            if re.search(r'\bwhile\b[^;]*\bread\b', ligne):
                continue
            analyse = shlex.shlex(ligne, posix=True, punctuation_chars=';|&')
            analyse.whitespace_split = True
            mots = list(analyse)
            if 'read' not in mots:
                continue
            arguments = mots[mots.index('read') + 1:]
            if '-s' in arguments and 'JETON' in arguments and 'export' not in mots:
                continue
            interdites.append(ligne)
    return interdites


def test_detection_invite():
    assert invites_interdites("```bash\nread -r -p 'Chemin : ' CHEMIN\n```\n")


def test_detection_invite_dans_while():
    assert invites_interdites("```bash\nwhile true; do read -p 'Q' V; done\n```\n")


def test_lectures_autorisees():
    assert not invites_interdites("```bash\nread -r -s -p 'Jeton : ' JETON; echo\nwhile IFS= read -r -d '' d; do echo ok; done\n```\n")


@pytest.mark.parametrize('fichier', PROCEDURES, ids=lambda p: p.name)
def test_procedure_sans_invite(fichier):
    assert not invites_interdites(fichier.read_text())


def lectures_script(texte):
    """Lectures `read` d'un script qui ne sont ni des lectures de flux, ni du terminal, ni d'une variable."""
    fautes = []
    for ligne in texte.splitlines():
        code = ligne.strip()
        if code.startswith('#') or not re.search(r'\bread\b', code):
            continue
        if re.search(r'\bwhile\b[^;]*\bread\b|<<<|< <\(|<\s*/dev/tty|\bread -r -s\b', code):
            continue
        fautes.append(ligne)
    return fautes


@pytest.mark.parametrize('script', SCRIPTS, ids=lambda p: p.name)
def test_script_sans_invite(script):
    t = script.read_text(encoding='utf-8')
    assert lectures_script(t) == []
    # la seule lecture au terminal est la touche Entrée de --alpha-test, dans son bloc retirable
    lectures_tty = [m.start() for m in re.finditer(r'(?m)^[^#\n]*read [^\n]*/dev/tty', t)]
    assert len(lectures_tty) == 1
    assert t.index('# DEBUT alpha-test') < lectures_tty[0] < t.index('# FIN alpha-test')
    assert not re.search(r'(?m)^[^#\n]*\bread -p\b', t) and 'select ' not in t


@pytest.mark.parametrize(('nom', 'variables'), [
    ('essai-presence.md', ('DEPOT', 'CLE_PUBLIQUE', 'ADMIN')),
])
def test_variables_obligatoires(nom, variables):
    texte = (DEPLOY / nom).read_text()
    blocs = '\n'.join(re.findall(r'^[ \t]*```bash\n(.*?)^[ \t]*```', texte, re.M | re.S))
    for variable in variables:
        assert f'| `{variable}` |' in texte
        assert (re.search(r'\$\{' + variable + r':\?', blocs)
                or re.search(r'test -n "\$\{' + variable + r':-\}"\s*\|\|\s*exit 1', blocs))


@pytest.mark.parametrize(('script', 'obligatoires'), [
    (ADMIN, ('ADRESSE_RELAIS', 'EMPREINTE_HOTE_RELAIS')),
    (RELAIS, ('ADRESSE_ADMIN', 'CLE_PUBLIQUE_TUNNEL', 'EMPREINTE_CLE_TUNNEL')),
], ids=lambda x: getattr(x, 'name', ''))
def test_variables_obligatoires_des_scripts(script, obligatoires):
    # aucune variable n'est obligatoire seule : les paramètres du tunnel vont ensemble, chacun est refusé
    # (code 64) par un test -z explicite et figure dans la table de paramètres de l'en-tête
    t = script.read_text(encoding='utf-8')
    for variable in obligatoires:
        assert re.search(rf'(?m)^#   {variable}  +--', t), variable
        assert f'if [ -z "${variable}" ]; then' in t and f'install_err_param_absent "nom={variable}"' in t, variable
        assert f'{variable}="${{{variable}:-}}"' in t
    # DEPOT : défaut = racine du clone, jamais obligatoire
    assert 'DEPOT="${DEPOT:-$(racine_clone)}"' in t and re.search(r'(?m)^#   DEPOT  +--depot', t)


@pytest.mark.parametrize('nom', ['essai-presence.md'])
def test_syntaxe_bash(nom):
    for bloc in re.findall(r'^[ \t]*```bash\n(.*?)^[ \t]*```', (DEPLOY / nom).read_text(), re.M | re.S):
        resultat = subprocess.run(['bash', '-n'], input=bloc, text=True, capture_output=True)
        assert resultat.returncode == 0, resultat.stderr


@pytest.mark.parametrize('script', SCRIPTS, ids=lambda p: p.name)
def test_syntaxe_bash_des_scripts(script):
    resultat = subprocess.run(['bash', '-n', str(script)], text=True, capture_output=True)
    assert resultat.returncode == 0, resultat.stderr


def arrets_hors_sous_shell(bloc):
    """Contrôle les exit et expansions obligatoires, sans compter les motifs de case comme des sous-shells."""
    profondeur, cas, fautes = 0, [], []
    fin_document = None
    for numero, ligne in enumerate(bloc.splitlines(), 1):
        if fin_document:
            if ligne.strip() == fin_document:
                fin_document = None
            continue
        document = re.search(r"<<-?\s*['\"]?(\w+)", ligne)
        if document:
            fin_document = document[1]
        # Masquer les arguments cités (notamment le Python embarqué et les substitutions
        # de commandes), mais conserver la présence des expansions obligatoires actives.
        def masquer(m):
            if m[0].startswith('"') and re.search(r'\$\{\w+:\?', m[0]):
                return ' EXPANSION_OBLIGATOIRE '
            return ' '
        code = re.sub(r"'[^']*'|\"(?:\\.|[^\"\\])*\"|(?<!\S)#.*", masquer, ligne)
        mots = re.findall(r';;|[()]|[^\s();]+', code)
        for mot in mots:
            if mot == 'case':
                cas.append('attente')
            elif mot == 'in' and cas and cas[-1] == 'attente':
                cas[-1] = 'motif'
            elif mot == 'esac' and cas:
                cas.pop()
            elif mot == ';;' and cas:
                cas[-1] = 'motif'
            elif mot == '(':
                if not (cas and cas[-1] == 'motif'):
                    profondeur += 1
            elif mot == ')':
                if cas and cas[-1] == 'motif':
                    cas[-1] = 'corps'
                else:
                    profondeur -= 1
            elif profondeur == 0 and mot in ('exit', 'EXPANSION_OBLIGATOIRE'):
                fautes.append(numero)
    return fautes


@pytest.mark.parametrize('bloc', [
    'exit 1\n',
    '( exit 1 ); exit 2\n',
    'case "$x" in /*) exit 1 ;; esac\n',
    'controle() { exit 1; }\n',
    ': "${DEPOT:?Fixez DEPOT}"\necho suite\n',
])
def test_detecte_arret_de_la_session(bloc):
    assert arrets_hors_sous_shell(bloc)


@pytest.mark.parametrize('bloc', [
    '(\nset -euo pipefail\n: "${DEPOT:?Fixez DEPOT}"\nexit 1\n)\n',
    'true && (cd /tmp && false || exit 1)\n',
    '(\ncase "$x" in ' + HOME + '|' + HOME + '/*) exit 1 ;; esac\n)\n',
    'echo "exit 1"\n# exit 1\n',
    'if test -z "$(find "$DEPOT/server" -type f)"; then (exit 1); fi\n',
])
def test_accepte_arret_du_sous_shell(bloc):
    assert not arrets_hors_sous_shell(bloc)


@pytest.mark.parametrize('fichier', PROCEDURES, ids=lambda p: p.name)
def test_aucun_arret_hors_sous_shell(fichier):
    for bloc in re.findall(r'^[ \t]*```bash\n(.*?)^[ \t]*```', fichier.read_text(), re.M | re.S):
        assert not arrets_hors_sous_shell(bloc), (fichier, bloc)


def garde_chemin():
    """La garde de normalisation des répertoires (chemin absolu, sans /home), extraite du script de backend-relais."""
    t = RELAIS.read_text(encoding='utf-8')
    return re.search(r'(?ms)^chemin_normalise\(\) \{.*?^\}', t).group()


@pytest.mark.parametrize(('chemin', 'code'), [
    (HOME, 65), (HOME + '/tunnel', 65), ('/' + HOME + '/tunnel', 65),
    ('/var/..' + HOME + '/tunnel', 65), ('/.' + HOME + '/tunnel', 65), (HOME + '/./tunnel', 65),
    ('relatif', 65), ('', 65), ('/var/lib/paresia-tunnel', 0),
])
def test_refus_home_apres_normalisation(chemin, code):
    resultat = subprocess.run(['bash', '--noprofile', '--norc', '-s', chemin],
                              input='arreter() { echo "arret:$2" >&2; exit "$1"; }\nEX_DATAERR=65\n' + garde_chemin()
                              + '\n(set -euo pipefail; chemin_normalise REPERTOIRE_TUNNEL "$1" > /dev/null)\nprintf "parent:%s" "$?"\n',
                              env={'PATH': '/usr/bin:/bin'}, text=True, capture_output=True, timeout=10)
    assert resultat.returncode == 0
    assert resultat.stdout == f'parent:{code}', resultat.stderr
