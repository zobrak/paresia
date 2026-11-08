# Tests de la configuration en couches (T015, D29) ; dépendances : pytest, server.commun.config.
# Suivi des versions
#   0.1.15  2026-11-08  Repère X-Paresia-Client-IP dans les commentaires de l'exemple.
#   0.1.8  2026-11-07  Lecture partielle et uid facultatif ; schéma de Romulus assemblé à partir des déclarations.
#   0.1.1  2026-11-07  Sections journal et métriques du socle dans l'exemple.
#   0.1.1  2026-11-07  Refus des types incompatibles avec facultatif.
#   0.1.1  2026-11-07  Options communes facultatives.
#   3.0.0-alpha  2026-11-06  Section sauvegarde.stockage dans l'exemple paresia.conf (C36, D83).
#   3.0.0-alpha  2026-11-05  Cycle 1 : composant bunkerd ajouté à l'exemple paresia.conf.
#   3.0.0-alpha  2026-11-05  Première version : ordre des couches, sécurité des fichiers, exemple paresia.conf.
import os
from pathlib import Path
import re
import stat
import sys

import pytest

from server.commun.config import ErreurConfiguration, Option, lire
from server.bunkerd import SCHEMA as SCHEMA_BUNKERD
from server.pollux import SCHEMA as SCHEMA_POLLUX
from server.pollux.session import SCHEMA as SCHEMA_SESSION
from server.nisaba import SCHEMA_NISABA
from romulus_outils import schema_romulus
from server.sauvegarde import SCHEMA as SCHEMA_SAUVEGARDE

RACINE = Path(__file__).resolve().parents[1]
EXEMPLE = RACINE / 'server' / 'conf' / 'paresia.conf'
SCHEMA = {('general', 'nom'): Option('texte'), ('transport', 'socket'): Option('chemin'),
          ('transport', 'delai'): Option('duree', 30), ('auth', 'uid'): Option('uid')}
BASE = '[compo]\nnom = base\n[compo.transport]\nsocket = /run/base.sock\n[compo.auth]\nuid = 1\n'
COMPOSANTS = {'pollux': SCHEMA_POLLUX, 'pollux-session': SCHEMA_SESSION, 'romulus': schema_romulus(),
               'bunkerd': SCHEMA_BUNKERD, 'nisaba': SCHEMA_NISABA,
               'sauvegarde': SCHEMA_SAUVEGARDE}
# Démons qui lisent les sections journal et métriques du socle commun (exemple de backend-admin).
AVEC_SOCLE = ('pollux', 'romulus', 'nisaba')
ROOT = pytest.mark.skipif(os.geteuid() == 0, reason='les tests de propriétaire ne tournent pas en root')


def ecrire(chemin, texte, mode=0o600):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(texte, encoding='utf-8')
    chemin.chmod(mode)
    return chemin


@pytest.fixture
def racine(tmp_path):
    dossier = tmp_path / 'etc'
    dossier.mkdir(mode=0o755)
    ecrire(dossier / 'paresia.conf', BASE)
    return dossier


def charger(racine, **kw):
    kw.setdefault('environ', {})
    return lire('compo', SCHEMA, argv=[], racine_systeme=racine, **kw)


def test_couches_ordre(racine, tmp_path):
    utilisateur = tmp_path / 'xdg'
    ecrire(racine / 'conf.d' / '10-a.conf', '[compo.auth]\nuid = 2\n[compo.transport]\ndelai = 5\n')
    ecrire(utilisateur / 'paresia' / 'u.conf', '[compo.auth]\nuid = 3\n')
    env = {'XDG_CONFIG_HOME': str(utilisateur)}
    assert charger(racine)['auth']['uid'] == 2
    assert charger(racine)['transport']['delai'] == 5
    assert charger(racine, utilisateur=True, environ=env)['auth']['uid'] == 3
    env['PARESIA_COMPO_AUTH_UID'] = '4'
    assert charger(racine, utilisateur=True, environ=env)['auth']['uid'] == 4
    assert charger(racine, utilisateur=True, environ=env)['general']['nom'] == 'base'


def test_confd_ordre_lexical(racine):
    ecrire(racine / 'conf.d' / '20-b.conf', '[compo.auth]\nuid = 20\n')
    ecrire(racine / 'conf.d' / '05-a.conf', '[compo.auth]\nuid = 5\n')
    ecrire(racine / 'conf.d' / '10-c.conf', '[compo.auth]\nuid = 10\n')
    assert charger(racine)['auth']['uid'] == 20


def test_confd_nom_ignore(racine):
    # Noms hors de ^[0-9]{2}-[A-Za-z0-9._-]+\.conf$ : jamais lus (même invalides).
    for nom in ('a-sans-chiffres.conf', '1-un-chiffre.conf', '10-autre.ini', '10-x.conf.bak', '100-trois.conf'):
        ecrire(racine / 'conf.d' / nom, '[compo.auth]\nuid = 99\n[invalide')
    assert charger(racine)['auth']['uid'] == 1


def test_couche_utilisateur_desactivee_demon(racine, tmp_path):
    ecrire(tmp_path / 'xdg' / 'paresia' / 'u.conf', '[compo.auth]\nuid = 3\n')
    ecrire(tmp_path / 'home' / '.config' / 'paresia' / 'u.conf', '[compo.auth]\nuid = 3\n')
    env = {'XDG_CONFIG_HOME': str(tmp_path / 'xdg'), 'HOME': str(tmp_path / 'home')}
    assert charger(racine, environ=env)['auth']['uid'] == 1
    assert charger(racine, environ=env, environnement=False)['auth']['uid'] == 1


def test_couche_utilisateur_active(racine, tmp_path):
    ecrire(tmp_path / 'home' / '.config' / 'paresia' / 'u.conf', '[compo.auth]\nuid = 7\n')
    ecrire(tmp_path / 'home' / '.config' / 'paresia' / 'ignore.txt', '[invalide')
    # Défaut : $HOME/.config/paresia/
    assert charger(racine, utilisateur=True, environ={'HOME': str(tmp_path / 'home')})['auth']['uid'] == 7
    # Dossier injecté.
    assert charger(racine, utilisateur=True, repertoire_utilisateur=tmp_path / 'home' / '.config')['auth']['uid'] == 7
    # Ni HOME ni XDG_CONFIG_HOME : pas de couche 3, pas d'erreur.
    assert charger(racine, utilisateur=True)['auth']['uid'] == 1


def test_xdg_relatif_ignore(racine, tmp_path, monkeypatch):
    ecrire(tmp_path / 'rel' / 'paresia' / 'u.conf', '[compo.auth]\nuid = 8\n')
    ecrire(tmp_path / 'home' / '.config' / 'paresia' / 'u.conf', '[compo.auth]\nuid = 9\n')
    monkeypatch.chdir(tmp_path)
    for relatif in ('rel', ''):
        env = {'XDG_CONFIG_HOME': relatif, 'HOME': str(tmp_path / 'home')}
        assert charger(racine, utilisateur=True, environ=env)['auth']['uid'] == 9
    assert charger(racine, utilisateur=True, environ={'XDG_CONFIG_HOME': 'rel'})['auth']['uid'] == 1


def test_environnement_prioritaire(racine, tmp_path):
    ecrire(racine / 'conf.d' / '50-site.conf', '[compo.transport]\ndelai = 5\n')
    env = {'PARESIA_COMPO_TRANSPORT_DELAI': '7', 'PARESIA_COMPO_NOM': 'ignoree',
           'PARESIA_COMPO_GENERAL_NOM': 'env', 'PARESIA_AUTRE_AUTH_UID': '5'}
    config = charger(racine, environ=env)
    assert config['transport']['delai'] == 7 and config['general']['nom'] == 'env'
    assert config['auth']['uid'] == 1


def test_environnement_desactive(racine, tmp_path):
    autre = ecrire(tmp_path / 'autre.conf', BASE.replace('base', 'autre'))
    env = {'PARESIA_COMPO_AUTH_UID': '4', 'PARESIA_COMPO_CONFIG': str(autre)}
    config = charger(racine, environ=env, environnement=False)
    assert config['auth']['uid'] == 1 and config['general']['nom'] == 'base'
    assert charger(racine, environ=env)['general']['nom'] == 'autre'


def test_sections_composant(racine):
    ecrire(racine / 'conf.d' / '10-x.conf',
           '[compo-bis.auth]\nuid = 50\ninconnue = 1\n[compo-bis]\nx = 1\n[autre.zzz]\ny = 1\n[compo2.auth]\nuid = 6\n')
    assert charger(racine)['auth']['uid'] == 1


def test_section_inconnue(racine):
    ecrire(racine / 'conf.d' / '10-x.conf', '[compo.inconnue]\nx = 1\n')
    with pytest.raises(ErreurConfiguration) as erreur:
        charger(racine)
    assert erreur.value.code == 'config_unknown_section' and erreur.value.fichier == '10-x.conf'
    ecrire(racine / 'conf.d' / '10-x.conf', '[compo.auth]\ninconnue = 1\n')
    with pytest.raises(ErreurConfiguration, match='config_unknown_option'):
        charger(racine)
    ecrire(racine / 'conf.d' / '10-x.conf', '[DEFAULT]\nuid = 1\n')
    with pytest.raises(ErreurConfiguration, match='config_defaults_forbidden'):
        charger(racine)
    ecrire(racine / 'conf.d' / '10-x.conf', '[compo.auth]\nuid = 1\nuid = 2\n')
    with pytest.raises(ErreurConfiguration, match='config_unreadable'):
        charger(racine)
    ecrire(racine / 'conf.d' / '10-x.conf', '[compo.auth]\nuid = %(x)s\n')
    with pytest.raises(ErreurConfiguration, match='config_invalid:auth:uid'):
        charger(racine)


def test_domaine_general(racine):
    assert charger(racine)['general'] == {'nom': 'base'}
    ecrire(racine / 'conf.d' / '10-x.conf', '[compo.general]\nnom = domaine\n')
    assert charger(racine)['general']['nom'] == 'domaine'


def test_config_sans_fichier(tmp_path):
    env = {'PARESIA_COMPO_GENERAL_NOM': 'n', 'PARESIA_COMPO_TRANSPORT_SOCKET': '/run/x.sock',
           'PARESIA_COMPO_AUTH_UID': '3'}
    config = lire('compo', SCHEMA, argv=[], environ=env, racine_systeme=tmp_path / 'absente')
    assert config == {'general': {'nom': 'n'}, 'transport': {'socket': '/run/x.sock', 'delai': 30.0},
                      'auth': {'uid': 3}}
    del env['PARESIA_COMPO_AUTH_UID']
    with pytest.raises(ErreurConfiguration, match='config_missing:auth:uid'):
        lire('compo', SCHEMA, argv=[], environ=env, racine_systeme=tmp_path / 'absente')


def test_fichier_explicite(racine, tmp_path):
    ecrire(racine / 'conf.d' / '10-x.conf', '[compo.auth]\nuid = 2\n')
    seul = ecrire(tmp_path / 'seul.conf', '[compo]\nnom = seul\n[compo.transport]\nsocket = /run/s\n[compo.auth]\nuid = 11\n')
    config = lire('compo', SCHEMA, argv=['--config', str(seul)], environ={}, racine_systeme=racine)
    assert config['auth']['uid'] == 11 and config['general']['nom'] == 'seul'
    env = {'PARESIA_COMPO_CONFIG': str(seul), 'PARESIA_COMPO_AUTH_UID': '12'}
    assert lire('compo', SCHEMA, argv=[], environ=env, racine_systeme=racine)['auth']['uid'] == 12
    del env['PARESIA_COMPO_AUTH_UID']
    assert lire('compo', SCHEMA, argv=[], environ=env, racine_systeme=racine)['auth']['uid'] == 11
    with pytest.raises(ErreurConfiguration, match='config_path_missing'):
        lire('compo', SCHEMA, argv=['--config', ''], environ={}, racine_systeme=racine)
    with pytest.raises(ErreurConfiguration, match='config_unreadable'):
        lire('compo', SCHEMA, argv=['--config', str(tmp_path / 'absent.conf')], environ={})


def test_valeur_masquee_invalide(racine):
    ecrire(racine / 'conf.d' / '10-x.conf', '[compo.auth]\nuid = -4\n')
    ecrire(racine / 'conf.d' / '20-y.conf', '[compo.auth]\nuid = 4\n')
    with pytest.raises(ErreurConfiguration, match='config_invalid:auth:uid'):
        charger(racine)
    (racine / 'conf.d' / '10-x.conf').unlink()
    ecrire(racine / 'conf.d' / '10-x.conf', '[compo.auth]\nuid = 3\n')
    assert charger(racine, environ={'PARESIA_COMPO_AUTH_UID': '9'})['auth']['uid'] == 9
    with pytest.raises(ErreurConfiguration, match='config_invalid:auth:uid'):
        charger(racine, environ={'PARESIA_COMPO_AUTH_UID': 'x'})


@ROOT
def test_couches_securite(racine, tmp_path, monkeypatch):
    confd = racine / 'conf.d'
    fichier = ecrire(confd / '10-x.conf', '[compo.auth]\nuid = 2\n')
    assert charger(racine)['auth']['uid'] == 2

    def refuse(code='config_unsafe_permissions'):
        with pytest.raises(ErreurConfiguration, match=code):
            charger(racine, utilisateur=True, environ={'XDG_CONFIG_HOME': str(tmp_path / 'xdg')})

    for mode in (0o620, 0o602, 0o666):
        fichier.chmod(mode)
        refuse()
    fichier.chmod(0o600)
    for mode in (0o770, 0o707):
        confd.chmod(mode)
        refuse()
    confd.chmod(0o755)
    (racine / 'paresia.conf').chmod(0o666)
    refuse()
    (racine / 'paresia.conf').chmod(0o600)
    racine.chmod(0o777)
    refuse()
    racine.chmod(0o755)
    # Propriétaire non admis : ni root ni l'uid effectif (injecté).
    with monkeypatch.context() as ctx:
        ctx.setattr(os, 'geteuid', lambda: os.getuid() + 1)
        refuse()
    # Liens symboliques : fichier, conf.d, dossier utilisateur.
    cible = ecrire(tmp_path / 'cible.conf', '[compo.auth]\nuid = 9\n')
    (confd / '20-lien.conf').symlink_to(cible)
    refuse('config_unreadable')
    (confd / '20-lien.conf').unlink()
    ailleurs = tmp_path / 'ailleurs'
    confd.rename(ailleurs)
    confd.symlink_to(ailleurs)
    refuse('config_unreadable')
    confd.unlink()
    ailleurs.rename(confd)
    ecrire(tmp_path / 'vrai' / 'u.conf', '[compo.auth]\nuid = 9\n')
    (tmp_path / 'xdg').mkdir()
    (tmp_path / 'xdg' / 'paresia').symlink_to(tmp_path / 'vrai')
    refuse('config_unreadable')
    # Non régulier : un tube nommé portant un nom de fichier de couche.
    (tmp_path / 'xdg' / 'paresia').unlink()
    (tmp_path / 'xdg' / 'paresia').mkdir()
    os.mkfifo(tmp_path / 'xdg' / 'paresia' / 'f.conf')
    refuse()
    # Taille (> 1 Mio) et nombre de fichiers (> 64).
    os.unlink(tmp_path / 'xdg' / 'paresia' / 'f.conf')
    ecrire(tmp_path / 'xdg' / 'paresia' / 'gros.conf', '[compo.auth]\nuid = 1\n#' + 'x' * (1024 * 1024))
    refuse('config_too_large')
    os.unlink(tmp_path / 'xdg' / 'paresia' / 'gros.conf')
    for numero in range(65):
        ecrire(confd / f'{numero:02d}-n.conf', '[compo.auth]\nuid = 2\n')
    refuse('config_too_large')
    for numero in range(1, 65):
        (confd / f'{numero:02d}-n.conf').unlink()
    assert charger(racine)['auth']['uid'] == 2


def test_erreurs_sans_valeur(racine):
    secret = 'valeur-fautive-' + os.urandom(6).hex()
    for contenu in (f'[compo.auth]\nuid = {secret}\n', f'[compo.auth]\n{secret} = 1\n',
                    f'[compo.{secret}]\nx = 1\n', f'[compo.auth\nuid = {secret}\n',
                    f'[DEFAULT]\nuid = {secret}\n'):
        ecrire(racine / 'conf.d' / '10-x.conf', contenu)
        with pytest.raises(ErreurConfiguration) as erreur:
            charger(racine)
        assert secret not in str(erreur.value) and secret not in repr(erreur.value.__dict__)
        assert erreur.value.fichier == '10-x.conf' and '/' not in erreur.value.fichier
        assert erreur.value.__cause__ is None
    (racine / 'conf.d' / '10-x.conf').unlink()
    with pytest.raises(ErreurConfiguration) as erreur:
        charger(racine, environ={'PARESIA_COMPO_AUTH_UID': secret})
    assert erreur.value.code == 'config_invalid'
    assert secret not in str(erreur.value) and secret not in repr(erreur.value.__dict__)


def test_variables_sans_collision():
    vues = {}
    for composant, schema in COMPOSANTS.items():
        prefixe = 'PARESIA_' + composant.upper().replace('-', '_')
        for domaine, cle in schema:
            variable = f'{prefixe}_{domaine.upper()}_{cle.upper()}'
            assert variable not in vues, (variable, vues[variable], composant)
            vues[variable] = composant


def test_lire_compatible(tmp_path, monkeypatch):
    fichier = ecrire(tmp_path / 'c.conf', '[compo.auth]\nuid = 3\n[compo]\nnom = n\n[compo.transport]\nsocket = /run/s\n')
    config = lire('compo', SCHEMA, argv=['--config', str(fichier)], environ={})
    assert config == {'general': {'nom': 'n'}, 'transport': {'socket': '/run/s', 'delai': 30.0}, 'auth': {'uid': 3}}
    monkeypatch.setattr(sys, 'argv', ['programme'])
    assert lire('compo', SCHEMA, environ={'PARESIA_COMPO_CONFIG': str(fichier)}) == config
    with pytest.raises(ErreurConfiguration, match='config_invalid_arguments'):
        lire('compo', SCHEMA, argv=['--autre'], environ={})
    with pytest.raises(ValueError, match='config_default_forbidden'):
        Option('chemin', '/x')


@pytest.mark.parametrize('composant', sorted(COMPOSANTS))
def test_paresia_conf_exemple(composant, tmp_path):
    socle = {'journal': True, 'metriques': True} if composant in AVEC_SOCLE else {}
    config = lire(composant, COMPOSANTS[composant], argv=['--config', str(EXEMPLE)], environ={}, **socle)
    attendu = {d: {c for dd, c in COMPOSANTS[composant] if dd == d} for d in {d for d, _ in COMPOSANTS[composant]}}
    if socle:    # options du socle commun : niveau du journal et métriques
        attendu.setdefault('journal', set()).add('niveau')
        attendu['metriques'] = {'actif', 'dossier', 'periode_s'}
    assert {d: set(v) for d, v in config.items()} == attendu
    # Les couches (racine factice contenant une copie de l'exemple) donnent le même résultat.
    racine = tmp_path / 'etc'
    racine.mkdir(mode=0o755)
    ecrire(racine / 'paresia.conf', EXEMPLE.read_text(encoding='utf-8'))
    assert lire(composant, COMPOSANTS[composant], argv=[], environ={}, racine_systeme=racine, **socle) == config


def test_paresia_conf_sections_connues():
    sections = re.findall(r'^\[([^\]]+)\]$', EXEMPLE.read_text(encoding='utf-8'), re.M)
    sections = [s if '.' in s else s + '.general' for s in sections]    # [bunkerd] = domaine general
    assert sections
    connues = {f'{c}.{d}' for c, schema in COMPOSANTS.items() for d, _ in schema}
    connues |= {f'{c}.{d}' for c in AVEC_SOCLE for d in ('journal', 'metriques')}
    assert set(sections) <= connues and len(sections) == len(set(sections))
    texte = EXEMPLE.read_text(encoding='utf-8')
    assert set(re.findall(r'\b\d{1,3}(?:\.\d{1,3}){3}\b', texte)) <= {'127.0.0.1'}
    assert not re.search(r'^\s*[A-Za-z_]+\s*=\s*\S+\.(?:com|org|net|fr)\b', texte, re.M)


def test_commentaires_repris():
    for ancien in ('pollux.ini', 'pollux-session.ini', 'romulus.ini', 'bunkerd.ini'):
        assert not (RACINE / 'server' / 'conf' / ancien).exists()
    texte = EXEMPLE.read_text(encoding='utf-8')
    for repere in ('maximum x pair_delai_s', 'StrictModes', 'AcceptEnv', 'PermitUserEnvironment',
                   'X-Forwarded-For', 'X-Paresia-Client-IP', 'read_deadline_s', 'verrou global', 'ExposeAuthInfo'):
        assert repere in texte, repere


def test_paresia_conf_sans_secret():
    texte = EXEMPLE.read_text(encoding='utf-8')
    assert not re.search(r'nsec1|ncryptsec1|BEGIN [A-Z ]*PRIVATE KEY|passphrase\s*=|password\s*=|token\s*=',
                         texte, re.I)
    mode = os.stat(EXEMPLE).st_mode
    assert stat.S_ISREG(mode) and not mode & 0o022


def test_docs_configuration():
    doc = (RACINE / 'docs' / 'configuration.md').read_text(encoding='utf-8')
    for repere in ('/etc/paresia/paresia.conf', 'conf.d', 'XDG_CONFIG_HOME', '50-site.conf',
                   'PARESIA_POLLUX_SESSION', 'pollux-session', 'ConfigurationDirectory=',
                   'RuntimeDirectory=', '/usr/local/share/paresia/i18n/', 'config_unknown_section',
                   'config_unsafe_permissions', 'config_too_large', '--config', 'Unités systemd'):
        assert repere in doc, repere
    protocole = (RACINE / 'docs' / 'protocole.md').read_text(encoding='utf-8')
    assert 'docs/configuration.md' in protocole and 'fichier INI. Ce fichier doit' not in protocole


def test_options_socle(racine):
    resultat = charger(racine, journal=True, metriques=True)
    assert resultat['journal'] == {'niveau': 'info'}
    assert resultat['metriques'] == {'actif': False, 'dossier': None, 'periode_s': 15}
    env = {'PARESIA_COMPO_JOURNAL_NIVEAU': 'debug', 'PARESIA_COMPO_METRIQUES_ACTIF': 'true'}
    assert charger(racine, journal=True, metriques=True, environ=env)['metriques']['actif'] is True
    env['PARESIA_COMPO_JOURNAL_NIVEAU'] = 'invalide'
    with pytest.raises(ErreurConfiguration) as erreur:
        charger(racine, journal=True, environ=env)
    assert (erreur.value.code, erreur.value.section, erreur.value.cle) == ('config_invalid', 'journal', 'niveau')


@pytest.mark.parametrize('type_option', ['duree', 'limite', 'niveau', 'booleen'])
def test_option_facultative_type_refuse(type_option):
    with pytest.raises(ValueError, match='^invalid_config_optional$'):
        Option(type_option, facultatif=True)


# -- lecture partielle et uid facultatif ----------------------------------------------

AVEC_INCONNU = ('[compo.autre]\nx = 1\n[compo.transport]\nsocket = /run/s\ninconnue = 1\n'
                '[compo.auth]\nuid = 3\n')


def test_lecture_partielle_ignore_inconnu(tmp_path):
    fichier = ecrire(tmp_path / 'c.conf', AVEC_INCONNU)
    schema = {('transport', 'socket'): Option('chemin'), ('auth', 'uid'): Option('uid')}
    config = lire('compo', schema, argv=['--config', str(fichier)], environ={}, partielle=True)
    assert config == {'transport': {'socket': '/run/s'}, 'auth': {'uid': 3}}
    # Par défaut, la lecture reste stricte : section inconnue, puis option inconnue.
    with pytest.raises(ErreurConfiguration) as erreur:
        lire('compo', schema, argv=['--config', str(fichier)], environ={})
    assert erreur.value.code == 'config_unknown_section'
    fichier = ecrire(tmp_path / 'd.conf', AVEC_INCONNU.replace('[compo.autre]\nx = 1\n', ''))
    with pytest.raises(ErreurConfiguration) as erreur:
        lire('compo', schema, argv=['--config', str(fichier)], environ={})
    assert erreur.value.code == 'config_unknown_option'


def test_lecture_partielle_valide_les_options_connues(tmp_path):
    fichier = ecrire(tmp_path / 'c.conf', '[compo.autre]\nx = 1\n[compo.auth]\nuid = pas-un-entier\n')
    schema = {('auth', 'uid'): Option('uid')}
    codes = []
    for partielle in (False, True):
        with pytest.raises(ErreurConfiguration) as erreur:
            lire('compo', schema, argv=['--config', str(fichier)], environ={}, partielle=partielle)
        codes.append((erreur.value.code, erreur.value.section, erreur.value.cle))
    assert codes[0][0] == 'config_unknown_section' and codes[1] == ('config_invalid', 'auth', 'uid')
    # Valeur invalide par variable d'environnement : même code en lecture partielle.
    with pytest.raises(ErreurConfiguration) as erreur:
        lire('compo', schema, argv=[], environ={'PARESIA_COMPO_AUTH_UID': 'x'}, partielle=True,
             racine_systeme=tmp_path / 'absent')
    assert erreur.value.code == 'config_invalid'


def test_uid_facultatif(tmp_path):
    schema = {('transport', 'socket'): Option('chemin'), ('auth', 'uid'): Option('uid', facultatif=True)}
    fichier = ecrire(tmp_path / 'c.conf', '[compo.transport]\nsocket = /run/s\n')
    config = lire('compo', schema, argv=['--config', str(fichier)], environ={})
    assert config['auth'] == {'uid': None}
    fichier = ecrire(tmp_path / 'd.conf', '[compo.transport]\nsocket = /run/s\n[compo.auth]\nuid = 7\n')
    assert lire('compo', schema, argv=['--config', str(fichier)], environ={})['auth']['uid'] == 7
    fichier = ecrire(tmp_path / 'e.conf', '[compo.transport]\nsocket = /run/s\n[compo.auth]\nuid = -1\n')
    with pytest.raises(ErreurConfiguration) as erreur:
        lire('compo', schema, argv=['--config', str(fichier)], environ={})
    assert (erreur.value.code, erreur.value.section, erreur.value.cle) == ('config_invalid', 'auth', 'uid')
    with pytest.raises(ValueError):    # un uid n'a jamais de défaut
        Option('uid', 5, facultatif=True)
    # Sans facultatif, l'uid reste obligatoire.
    obligatoire = {('auth', 'uid'): Option('uid')}
    fichier = ecrire(tmp_path / 'f.conf', '[compo.auth]\n')
    with pytest.raises(ErreurConfiguration) as erreur:
        lire('compo', obligatoire, argv=['--config', str(fichier)], environ={})
    assert erreur.value.code == 'config_missing'
