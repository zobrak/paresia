# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests du mode --mise-a-jour des scripts d'installation (versions, unités de Paresia, empreintes de configuration,
# retour arrière automatique et manuel, migration de données, copie périmée sous /run, prérequis en une fois) en
# environnement factice : racine temporaire, systemctl et sudo simulés, aucun root, aucun réseau sortant.
# Dépendances : bibliothèque standard, pytest ; fixtures de test_scripts_installation.py.
# Suivi des versions
#   0.1.0  2026-11-08  Première version.
#   0.1.19  2026-11-08  Versions dérivées du fichier VERSION (installée = VERSION, livrée = suivante, ancienne = précédente).
import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

from tests.outils.installation_factice import Faux
from tests.test_scripts_installation import (ADMIN, INVITE, RELAIS, SENTINELLE, arguments_reinstallation,  # noqa: F401
                                             faux, faux_admin, faux_relais, installes, journaux, lancer_pty,
                                             machine, modele, modifiants)

ACTIONS = ('stop', 'start', 'restart', 'kill', 'enable', 'disable')
PROPRES = {'admin': ('pollux.service', 'romulus.service'), 'relais': ('remus.service', 'castor.service')}
ORDRE = {'admin': [('stop', 'pollux.service'), ('stop', 'romulus.service'),
                   ('start', 'romulus.service'), ('start', 'pollux.service')],
         'relais': [('stop', 'remus.service'), ('stop', 'castor.service'),
                    ('start', 'castor.service'), ('start', 'remus.service')]}
CONFIG = {'admin': ('/etc/paresia/paresia.conf', 'server/conf/paresia.conf'),
          'relais': ('/etc/paresia/paresia.conf', 'server/conf/paresia-relais.conf')}
CODE = '/usr/local/lib/paresia/server/commun/__init__.py'
EMPREINTES = '/usr/local/lib/paresia/empreintes-conf'

def _version_voisine(version, delta):
    """Version de même majeure.mineure dont le dernier numéro diffère de delta (jamais négatif)."""
    majeure, mineure, correctif = (int(n) for n in version.split('.'))
    return '%d.%d.%d' % (majeure, mineure, max(correctif + delta, 0))


# La version installée du jeu d'essai est celle du fichier VERSION du dépôt ; la livrée lui est strictement supérieure,
# l'ancienne strictement inférieure : aucun numéro n'est figé dans les tests.
INSTALLEE = (Path(__file__).resolve().parent.parent / 'VERSION').read_text().strip()
LIVREE = _version_voisine(INSTALLEE, 1)
ANCIENNE = _version_voisine(INSTALLEE, -1)
assert ANCIENNE != INSTALLEE, 'le dernier numéro de VERSION doit être au moins 1'
PIEGE = 'VALEUR-PIEGE-4242'
NOUVEAU = 'VALEUR-LIVREE-4242'


@pytest.fixture
def installe(installes, machine):
    """(Faux restauré à l'état installé, ensemble des installations) ; les fichiers du clone que les tests modifient
    (version livrée, code, configuration livrée) sont rétablis à la fin : le clone n'est pas dans l'instantané."""
    faux = getattr(installes, machine)
    faux.restaurer('installe')
    origines = {rel: (faux.clone / rel).read_bytes() for rel in ('VERSION', 'server/commun/__init__.py',
                                                                  'server/conf/paresia.conf', 'server/conf/paresia-relais.conf')}
    yield faux, installes
    for rel, octets in origines.items():
        (faux.clone / rel).write_bytes(octets)


def actions(faux, depuis=0):
    """[(sous-commande, unité)] des systemctl stop|start|restart|kill|enable|disable lancés depuis le numéro d'appel."""
    return [(a[1], a[2]) for a in faux.appels()[depuis:] if os.path.basename(a[0]) == 'systemctl' and a[1] in ACTIONS]


def actives(faux):
    return set(json.loads((faux.etat / 'actives.json').read_text()))


def preparer(faux, version=LIVREE, code=True):
    """Le clone livre une version plus récente (et, avec code, un fichier de code différent)."""
    (faux.clone / 'VERSION').write_text(version + '\n')
    if code:
        fichier = faux.clone / 'server/commun/__init__.py'
        fichier.write_text(fichier.read_text() + '# nouvelle version livrée\n')


def mise_a_jour(faux, installes, *args, env=None):
    return faux.installation('--mise-a-jour', *arguments_reinstallation(installes, faux.machine), *args, env=env)


def etat_installe(faux):
    """Code, configuration et unités installés (mode et contenu), pour comparer à l'octet."""
    return {k: v for k, v in faux.arbre().items()
            if k.startswith(('usr/local/lib/paresia', 'usr/local/bin', 'etc/paresia', 'etc/systemd/system', 'etc/sudoers.d'))}


def jeu_de(resultat):
    return re.search(r'(?m)^Jeu : (\d{8}-\d{6})$', resultat.stdout).group(1)


def sha(texte):
    return hashlib.sha256(texte if isinstance(texte, bytes) else texte.encode()).hexdigest()


# -- options -----------------------------------------------------------------------------------------------------------

def test_option_inconnue_et_incompatibilites(faux):
    avant = faux.arbre()
    assert faux.lancer('--interruption-confirmee').returncode == 64
    assert faux.lancer('--mise-a-jour', '--interruption-confirmee').returncode == 64
    assert faux.lancer('--mise-a-jour', '--verifier').returncode == 64
    assert faux.lancer('--mise-a-jour', '--retour-arriere', '--jeu', '20260101-000000', '--confirme').returncode == 64
    assert faux.lancer('--langue', 'fr-FR', env={'MISE_A_JOUR': 'peut-etre'}).returncode == 65
    assert faux.appels() == [] and faux.arbre() == avant and faux.jeux() == []


def test_mise_a_jour_sans_installation_refusee(faux):
    avant = faux.arbre()
    resultat = faux.installation('--mise-a-jour')
    assert resultat.returncode == 78 and 'aucune installation à mettre à jour' in resultat.stderr
    assert modifiants(faux, faux.appels()) == [] and faux.arbre() == avant and faux.jeux() == []


# -- versions ----------------------------------------------------------------------------------------------------------

def test_meme_version_deja_en_place(installe):
    faux, installes = installe
    arbre, comptes, jeux, nb = faux.arbre(), faux.comptes(), faux.jeux(), len(faux.appels())
    resultat = mise_a_jour(faux, installes)
    assert resultat.returncode == 0, resultat.stderr
    assert f'Version installée {INSTALLEE}, version livrée {INSTALLEE}' in resultat.stdout
    assert 'mise_a_jour_etat : déjà en place' in resultat.stderr
    assert modifiants(faux, faux.appels()[nb:]) == [] and actions(faux, nb) == []
    assert faux.arbre() == arbre and faux.comptes() == comptes and faux.jeux() == jeux


def test_version_livree_plus_ancienne_refusee(installe):
    faux, installes = installe
    preparer(faux, ANCIENNE, code=False)
    arbre, nb = faux.arbre(), len(faux.appels())
    resultat = mise_a_jour(faux, installes)
    assert resultat.returncode == 78 and 'plus ancienne' in resultat.stderr
    assert modifiants(faux, faux.appels()[nb:]) == [] and actions(faux, nb) == []
    assert faux.arbre() == arbre


@pytest.mark.parametrize('contenu', ['abc\n', '1.2\n', '1.2.3\n\n', '', '1.2.3 \n', 'x' * 300 + '\n', '1.2.3\x00\n'])
def test_version_installee_illisible_refusee(installe, contenu):
    faux, installes = installe
    preparer(faux)
    faux.chemin('/usr/local/lib/paresia/VERSION').write_bytes(contenu.encode())
    arbre, nb = faux.arbre(), len(faux.appels())
    resultat = mise_a_jour(faux, installes)
    assert resultat.returncode == 78 and 'ÉCART' in resultat.stderr
    assert modifiants(faux, faux.appels()[nb:]) == [] and actions(faux, nb) == []
    assert faux.arbre() == arbre


def test_version_installee_absente_avec_code_refusee(installe):
    faux, installes = installe
    preparer(faux)
    faux.chemin('/usr/local/lib/paresia/VERSION').unlink()
    arbre, nb = faux.arbre(), len(faux.appels())
    resultat = mise_a_jour(faux, installes)
    assert resultat.returncode == 78 and 'ÉCART' in resultat.stderr
    assert modifiants(faux, faux.appels()[nb:]) == [] and faux.arbre() == arbre


def test_format_de_manifeste_different_refuse(installe):
    faux, installes = installe
    preparer(faux)
    module = faux.chemin('/usr/local/lib/paresia/server/sauvegarde/__init__.py')
    module.write_text(module.read_text().replace('VERSION_MANIFESTE = 3', 'VERSION_MANIFESTE = 2'))
    arbre, nb, jeux = faux.arbre(), len(faux.appels()), faux.jeux()
    resultat = mise_a_jour(faux, installes)
    assert resultat.returncode == 78 and 'format de manifeste' in resultat.stderr
    assert modifiants(faux, faux.appels()[nb:]) == [] and actions(faux, nb) == []
    assert faux.arbre() == arbre and faux.jeux() == jeux


# -- remplacement, ordre, unités -------------------------------------------------------------------------------------------

def test_mise_a_jour_remplace_arrete_et_reprend_dans_l_ordre(installe):
    faux, installes = installe
    preparer(faux)
    avant = {'enabled': (faux.etat / 'enabled.json').read_text(), 'actives': actives(faux), 'comptes': faux.comptes()}
    nb = len(faux.appels())
    resultat = mise_a_jour(faux, installes)
    assert resultat.returncode == 0, resultat.stderr
    assert f'Version installée {INSTALLEE}, version livrée {LIVREE}' in resultat.stdout
    jeu = jeu_de(resultat)
    # annonce avant tout arrêt : version, jeu, unités et effet
    annonce = resultat.stderr.index(f'Mise à jour de {INSTALLEE} vers {LIVREE} : jeu de sauvegarde ' + jeu)
    assert annonce < resultat.stderr.index('Arrêt de ')
    effet = 'sessions de présence' if faux.machine == 'admin' else 'feux de Castor'
    assert effet in resultat.stderr[annonce:resultat.stderr.index('Arrêt de ')]
    assert actions(faux, nb) == ORDRE[faux.machine]
    assert faux.lire('/usr/local/lib/paresia/VERSION') == LIVREE + '\n'
    assert faux.lire(CODE).endswith('# nouvelle version livrée\n')
    assert (faux.etat / 'enabled.json').read_text() == avant['enabled'] and actives(faux) == avant['actives']
    assert faux.comptes() == avant['comptes']
    for unite in PROPRES[faux.machine]:
        assert f'journalctl -u {unite} -n 30 --no-pager' in resultat.stdout
    releve = (faux.racine / 'var/backups/paresia' / faux.machine / jeu / 'releves/mise-a-jour').read_text()
    assert f'avant={INSTALLEE}' in releve and f'apres={LIVREE}' in releve and 'actives=' + ' '.join(PROPRES[faux.machine]) in releve
    # empreintes enregistrées au format « <empreinte>  <chemin> », sans clé privée ni valeur
    lignes = faux.lire(EMPREINTES).splitlines()
    assert lignes and all(re.fullmatch(r'[0-9a-f]{64}  /etc/paresia/[A-Za-z0-9._/-]+', l) for l in lignes)
    assert not faux.existe(CONFIG[faux.machine][0] + '.paresia-nouveau')
    assert SENTINELLE not in resultat.stdout + resultat.stderr


def test_unite_inactive_avant_reste_inactive(installe):
    faux, installes = installe
    preparer(faux)
    inactive = PROPRES[faux.machine][1] if faux.machine == 'admin' else PROPRES[faux.machine][0]
    (faux.etat / 'actives.json').write_text(json.dumps(sorted(actives(faux) - {inactive})))
    nb = len(faux.appels())
    resultat = mise_a_jour(faux, installes)
    assert resultat.returncode == 0, resultat.stderr
    attendu = [a for a in ORDRE[faux.machine] if a[1] != inactive]
    assert actions(faux, nb) == attendu
    assert inactive not in actives(faux)


def test_unites_tierces_jamais_touchees(installe):
    faux, installes = installe
    preparer(faux)
    tierces = {'ssh.service', 'lighttpd.service', 'strfry.service', 'docker.service', 'bunkerd.service', 'nisaba.service'}
    (faux.etat / 'actives.json').write_text(json.dumps(sorted(actives(faux) | tierces)))
    nb = len(faux.appels())
    resultat = mise_a_jour(faux, installes)
    assert resultat.returncode == 0, resultat.stderr
    assert actions(faux, nb) == ORDRE[faux.machine]
    assert not any(a[1] in tierces or a[0] in ('restart', 'kill', 'enable', 'disable') for a in actions(faux, nb))
    assert tierces <= actives(faux)


def test_relais_unite_hors_liste_active_refusee(installe):
    faux, installes = installe
    if faux.machine != 'relais':
        pytest.skip('propre à backend-relais')
    preparer(faux)
    (faux.etat / 'actives.json').write_text(json.dumps(sorted(actives(faux) | {'pollux.service'})))
    arbre, nb = faux.arbre(), len(faux.appels())
    resultat = mise_a_jour(faux, installes)
    assert resultat.returncode == 78 and 'pollux.service est active' in resultat.stderr
    assert actions(faux, nb) == [] and faux.arbre() == arbre


# -- configuration ---------------------------------------------------------------------------------------------------------

def livrer_option_nouvelle(faux):
    source = faux.clone / CONFIG[faux.machine][1]
    source.write_text(source.read_text() + f'\n[nouvelle_section]\nclef_nouvelle = {NOUVEAU}\n')
    return source


def test_configuration_non_modifiee_remplacee(installe):
    faux, installes = installe
    preparer(faux)
    livrer_option_nouvelle(faux)
    chemin = CONFIG[faux.machine][0]
    assert 'nouvelle_section' not in faux.lire(chemin)
    resultat = mise_a_jour(faux, installes)
    assert resultat.returncode == 0, resultat.stderr
    assert f'clef_nouvelle = {NOUVEAU}' in faux.lire(chemin)
    assert not faux.existe(chemin + '.paresia-nouveau')
    assert f'{sha(faux.chemin(chemin).read_bytes())}  {chemin}' in faux.lire(EMPREINTES).splitlines()
    assert NOUVEAU not in resultat.stdout + resultat.stderr


def configuration_modifiee(installe):
    faux, installes = installe
    preparer(faux)
    chemin = CONFIG[faux.machine][0]
    faux.ecrire(chemin, faux.lire(chemin) + f'\n[perso]\nmot_de_passe = {PIEGE}\n')
    livrer_option_nouvelle(faux)
    return faux, installes, chemin, faux.chemin(chemin).read_bytes()


def test_configuration_modifiee_conservee_et_options_signalees(installe):
    faux, installes, chemin, octets = configuration_modifiee(installe)
    resultat = mise_a_jour(faux, installes)
    assert resultat.returncode == 0, resultat.stderr
    assert faux.chemin(chemin).read_bytes() == octets
    nouveau = faux.chemin(chemin + '.paresia-nouveau')
    assert nouveau.exists() and f'clef_nouvelle = {NOUVEAU}' in nouveau.read_text() and PIEGE not in nouveau.read_text()
    assert stat.S_IMODE(nouveau.stat().st_mode) == 0o644
    assert json.loads((faux.etat / 'owners.json').read_text())[str(nouveau)] == 'root:root'
    assert f'Option nouvelle dans la version livrée de {chemin} : nouvelle_section.clef_nouvelle' in resultat.stdout
    assert f'Option nouvelle dans la version livrée de {chemin} : [nouvelle_section]' in resultat.stdout
    assert f'Option absente de la version livrée de {chemin} : perso.mot_de_passe' in resultat.stdout
    assert 'conservé tel quel' in resultat.stderr
    # aucune valeur n'est jamais affichée ni journalisée
    for sortie in (resultat.stdout, resultat.stderr):
        assert PIEGE not in sortie and NOUVEAU not in sortie
    # l'empreinte enregistrée est celle de la version livrée déposée à côté
    assert f'{sha(nouveau.read_bytes())}  {chemin}' in faux.lire(EMPREINTES).splitlines()
    # une seconde mise à jour est « déjà en place » (version livrée déjà à côté du fichier de l'administrateur)
    nb, arbre = len(faux.appels()), faux.arbre()
    encore = mise_a_jour(faux, installes)
    assert encore.returncode == 0, encore.stderr
    assert 'mise_a_jour_etat : déjà en place' in encore.stderr
    assert modifiants(faux, faux.appels()[nb:]) == [] and actions(faux, nb) == [] and faux.arbre() == arbre


def test_empreinte_absente_traitee_comme_modifiee(installe):
    faux, installes = installe
    preparer(faux)
    livrer_option_nouvelle(faux)
    chemin = CONFIG[faux.machine][0]
    octets = faux.chemin(chemin).read_bytes()
    faux.chemin(EMPREINTES).unlink()          # installation faite avant le mécanisme des empreintes
    resultat = mise_a_jour(faux, installes)
    assert resultat.returncode == 0, resultat.stderr
    assert faux.chemin(chemin).read_bytes() == octets
    assert f'clef_nouvelle = {NOUVEAU}' in faux.lire(chemin + '.paresia-nouveau')
    assert f'Option nouvelle dans la version livrée de {chemin} : nouvelle_section.clef_nouvelle' in resultat.stdout
    assert f'{sha(faux.chemin(chemin + ".paresia-nouveau").read_bytes())}  {chemin}' in faux.lire(EMPREINTES).splitlines()


@pytest.mark.parametrize('ligne', ['pas une empreinte\n', 'A' * 64 + '  /etc/paresia/paresia.conf\n', '0' * 64 + ' /etc/paresia/paresia.conf\n',
                                   '0' * 64 + '  etc/relatif\n', '0' * 64 + '  /etc/paresia/a\n' + '1' * 64 + '  /etc/paresia/a\n',
                                   '\n', '0' * 64 + '  /etc/paresia/a b\n'])
def test_empreinte_mal_formee_refusee_sans_rien_modifier(installe, ligne):
    faux, installes = installe
    preparer(faux)
    faux.ecrire(EMPREINTES, ligne)
    arbre, nb, jeux = faux.arbre(), len(faux.appels()), faux.jeux()
    resultat = mise_a_jour(faux, installes)
    assert resultat.returncode == 78 and 'ÉCART' in resultat.stderr and 'empreintes-conf' in resultat.stderr
    assert modifiants(faux, faux.appels()[nb:]) == [] and actions(faux, nb) == []
    assert faux.arbre() == arbre and faux.jeux() == jeux


# -- échec après l'arrêt : retour arrière automatique, ou migration de données -----------------------------------------------

def test_echec_de_verification_retour_arriere_automatique(installe):
    faux, installes = installe
    preparer(faux)
    avant, unites, comptes, nb = etat_installe(faux), actives(faux), faux.comptes(), len(faux.appels())
    faux.regler(mode_socket='600')            # les sockets créées au démarrage ont de mauvais droits
    resultat = mise_a_jour(faux, installes)
    assert resultat.returncode == 78, resultat.stderr
    jeu = re.search(r'(?m)^Jeu : (\d{8}-\d{6})$', resultat.stdout).group(1)
    assert 'retour arrière automatique du jeu ' + jeu in resultat.stderr and 'Retour arrière automatique terminé' in resultat.stderr
    assert etat_installe(faux) == avant                 # code, VERSION, unités, configuration : restaurés à l'octet
    assert faux.lire('/usr/local/lib/paresia/VERSION') == INSTALLEE + '\n'
    assert actives(faux) == unites and faux.comptes() == comptes
    assert not any(os.path.basename(a[0]) in ('userdel', 'groupdel', 'useradd', 'groupadd') for a in faux.appels()[nb:])
    assert not any(a[0] in ('restart', 'kill', 'enable', 'disable') for a in actions(faux, nb))


def test_echec_de_demarrage_retour_arriere_automatique(installe):
    faux, installes = installe
    preparer(faux)
    avant, unites, nb = etat_installe(faux), actives(faux), len(faux.appels())
    en_echec = 'pollux.service' if faux.machine == 'admin' else 'castor.service'
    faux.regler(demarrage_echec={en_echec: LIVREE})     # le démarrage échoue avec le nouveau code seulement
    resultat = mise_a_jour(faux, installes)
    assert resultat.returncode == 78, resultat.stderr
    assert 'retour arrière automatique' in resultat.stderr and jeu_de(resultat) in resultat.stderr
    assert etat_installe(faux) == avant and actives(faux) == unites
    assert faux.lire('/usr/local/lib/paresia/VERSION') == INSTALLEE + '\n'


def test_migration_de_donnees_aucun_retour_arriere_automatique(installe):
    faux, installes = installe
    preparer(faux)
    faux.regler(mode_socket='600', journal_extra='info state_migrated source_format=0 target_format=1')
    nb = len(faux.appels())
    resultat = mise_a_jour(faux, installes)
    assert resultat.returncode == 78, resultat.stderr
    jeu = jeu_de(resultat)
    assert 'Migration de données constatée' in resultat.stderr and 'retour arrière automatique du jeu' not in resultat.stderr
    assert 'Retour arrière automatique terminé' not in resultat.stderr
    assert f'--retour-arriere --jeu {jeu} --confirme' in resultat.stderr and 'est à restaurer par l\'administrateur' in resultat.stderr
    assert faux.lire('/usr/local/lib/paresia/VERSION') == LIVREE + '\n'       # rien n'est restauré
    assert not (set(PROPRES[faux.machine]) & actives(faux))                # les unités redémarrées restent arrêtées
    assert not any(os.path.basename(a[0]) in ('userdel', 'groupdel') for a in faux.appels()[nb:])


def test_demarrage_en_echec_apres_migration_aucune_restauration(installe):
    faux, installes = installe
    preparer(faux)
    en_echec = 'pollux.service' if faux.machine == 'admin' else 'castor.service'
    faux.regler(demarrage_echec={en_echec: LIVREE}, journal_extra='info state_migrated source_format=0 target_format=1')
    resultat = mise_a_jour(faux, installes)
    assert resultat.returncode == 78, resultat.stderr
    assert 'Migration de données constatée' in resultat.stderr and 'Retour arrière automatique terminé' not in resultat.stderr
    assert faux.lire('/usr/local/lib/paresia/VERSION') == LIVREE + '\n'
    assert not (set(PROPRES[faux.machine]) & actives(faux))


# -- retour arrière manuel ------------------------------------------------------------------------------------------------------

def test_retour_arriere_manuel_d_un_jeu_de_mise_a_jour(installe):
    faux, installes = installe
    preparer(faux)
    avant, unites, comptes = etat_installe(faux), actives(faux), faux.comptes()
    enabled = (faux.etat / 'enabled.json').read_text()
    resultat = mise_a_jour(faux, installes)
    assert resultat.returncode == 0, resultat.stderr
    jeu, nb = jeu_de(resultat), len(faux.appels())
    assert etat_installe(faux) != avant
    retour = faux.lancer('--retour-arriere', '--jeu', jeu, '--confirme', '--session-secours', 'oui')
    assert retour.returncode == 0, retour.stderr
    assert etat_installe(faux) == avant and faux.lire('/usr/local/lib/paresia/VERSION') == INSTALLEE + '\n'
    assert actives(faux) == unites and faux.comptes() == comptes and (faux.etat / 'enabled.json').read_text() == enabled
    assert not any(os.path.basename(a[0]) in ('userdel', 'groupdel', 'useradd', 'groupadd', 'gpasswd') for a in faux.appels()[nb:])
    arrets = [a for a in actions(faux, nb) if a[0] == 'stop']
    assert arrets and all(a[1] in PROPRES[faux.machine] for a in arrets)
    assert not any(a[0] in ('restart', 'kill', 'enable', 'disable') for a in actions(faux, nb))
    assert 'Retour arrière terminé' in retour.stderr


def test_retour_arriere_d_un_jeu_ancien_echoue_sans_rien_modifier(installe):
    faux, installes = installe
    preparer(faux)
    resultat = mise_a_jour(faux, installes)
    assert resultat.returncode == 0, resultat.stderr
    jeu = jeu_de(resultat)
    manifeste = faux.racine / 'var/backups/paresia' / faux.machine / jeu / 'manifeste.json'
    donnees = json.loads(manifeste.read_text())
    donnees['version'] = 2                                  # format de manifeste que l'outil livré refuse
    manifeste.write_text(json.dumps(donnees))
    arbre, nb = faux.arbre(), len(faux.appels())
    retour = faux.lancer('--retour-arriere', '--jeu', jeu, '--confirme', '--session-secours', 'oui')
    assert retour.returncode == 74, retour.stderr
    assert faux.arbre() == arbre and actions(faux, nb) == []


# -- copie périmée sous /run/paresia-installation ---------------------------------------------------------------------------------

def copie_perimee(faux):
    perimee = faux.chemin('/run/paresia-installation/server')
    perimee.mkdir(parents=True)
    (perimee / 'ancien.py').write_text('# copie d\'une version précédente\n')
    (faux.chemin('/run/paresia-installation')).chmod(0o700)
    return perimee


def test_copie_perimee_deplacee_sans_rm(faux):
    copie_perimee(faux)
    resultat = faux.installation()
    assert resultat.returncode == 0, resultat.stderr
    retirees = list(faux.chemin('/run/paresia-installation').glob('code-retire-*'))
    assert len(retirees) == 1 and (retirees[0] / 'server/ancien.py').exists()
    assert not (faux.chemin('/run/paresia-installation/server/ancien.py')).exists()
    assert (faux.chemin('/run/paresia-installation/server/sauvegarde/__init__.py')).exists()
    assert not any(os.path.basename(a[0]) == 'rm' and 'paresia-installation' in ' '.join(a) for a in faux.appels())
    assert any(os.path.basename(a[0]) == 'mv' for a in faux.appels())


@pytest.mark.parametrize('piege', ['lien', 'fifo'])
def test_copie_perimee_non_conforme_refusee(faux, piege):
    perimee = copie_perimee(faux)
    if piege == 'lien':
        (perimee / 'lien.py').symlink_to('/etc/passwd')
    else:
        os.mkfifo(perimee / 'tube')
    arbre = faux.arbre(exclure=())
    resultat = faux.installation()
    assert resultat.returncode == 78 and 'Copie du code impossible' in resultat.stderr
    assert not list(faux.chemin('/run/paresia-installation').glob('code-retire-*'))
    assert not any(os.path.basename(a[0]) == 'mv' for a in faux.appels())
    assert faux.arbre(exclure=()) == arbre


# -- prérequis en une fois ---------------------------------------------------------------------------------------------------------

def script_modifie(faux, remplacements):
    texte = faux.script.read_text(encoding='utf-8')
    for ancien, nouveau in remplacements:
        assert ancien in texte, ancien
        texte = texte.replace(ancien, nouveau)
    faux.script.write_text(texte, encoding='utf-8')


def test_prerequis_un_manque_un_seul_message(faux):
    script_modifie(faux, [('/usr/bin/tee ', '/usr/bin/tee-absent ')])
    resultat = faux.lancer('--verifier')
    assert resultat.returncode == 69, resultat.stderr
    assert resultat.stderr.strip().startswith('Prérequis manquants : /usr/bin/tee-absent. Installez-les'), resultat.stderr
    assert faux.appels() == [] or modifiants(faux, faux.appels()) == []


def test_prerequis_plusieurs_manques_accumules_en_un_message(faux):
    absent = [('/usr/bin/tee ', '/usr/bin/tee-absent '), ('/usr/bin/diff ', '/usr/bin/diff-absent '),
              ('command -v ss ', 'command -v ss-absent ')]
    script_modifie(faux, absent)
    faux.ecrire('/etc/os-release', 'ID=debian\nVERSION_ID="12"\n')
    resultat = faux.lancer('--verifier', env={'FAUX_SYSTEMD': 'abc'})
    assert resultat.returncode == 69, resultat.stderr
    lignes = [l for l in resultat.stderr.splitlines() if l.strip()]
    assert len(lignes) == 1 and lignes[0].startswith('Prérequis manquants : ')
    for element in ('/usr/bin/tee-absent', '/usr/bin/diff-absent', '/usr/bin/ss', 'debian-13', 'systemd'):
        assert element in lignes[0], (element, lignes[0])
    # la même vérification sert à l'étape prerequis : même message, même code, aucune modification
    etape = faux.installation(env={'FAUX_SYSTEMD': 'abc'})
    assert etape.returncode == 69 and lignes[0] in etape.stderr
    assert modifiants(faux, faux.appels()) == [] and faux.jeux() == []


def test_prerequis_ss_absent_signale_aussi_sur_backend_admin(faux):
    script_modifie(faux, [('command -v ss ', 'command -v ss-absent ')])
    resultat = faux.lancer('--verifier')
    assert resultat.returncode == 69 and '/usr/bin/ss' in resultat.stderr


def test_prerequis_sudo_absent_signale_avec_les_autres_sur_le_relais(faux_relais, tmp_path):
    f = faux_relais
    absent = tmp_path / 'sans-sudo'
    absent.mkdir()
    (absent / 'sudo').write_text('#!/bin/sh\necho SUDO-APPELE >&2\nexit 99\n')
    (absent / 'sudo').chmod(0o755)
    script_modifie(f, [('/usr/bin/sudo ', '/usr/bin/sudo-absent '), ('/usr/bin/tee ', '/usr/bin/tee-absent ')])
    env = {'PATH': f'{absent}:{f.bin}:/usr/bin:/bin'}
    resultat = f.lancer('--verifier', env=env)
    assert resultat.returncode == 69, resultat.stderr
    assert 'SUDO-APPELE' not in resultat.stderr
    assert resultat.stderr.count('Prérequis manquants') == 1
    assert '/usr/bin/sudo-absent' in resultat.stderr and '/usr/bin/tee-absent' in resultat.stderr


def test_prerequis_complets_aucun_manque(faux):
    resultat = faux.lancer('--verifier')
    assert resultat.returncode == 0, resultat.stderr


# -- --alpha-test ------------------------------------------------------------------------------------------------------------------------

def test_alpha_test_pause_avant_l_arret_et_apres_le_redemarrage(installe):
    faux, installes = installe
    preparer(faux)
    args = ['--alpha-test', '--session-secours', 'oui', '--mise-a-jour', *arguments_reinstallation(installes, faux.machine)]
    if faux.machine == 'relais':
        args += ['--port-essai', str(faux.port)]
    code_sortie, sortie, pauses = lancer_pty(faux, args)
    assert code_sortie == 0, sortie[-3000:]
    assert pauses >= 3
    # la pause suit l'annonce, avant le premier arrêt
    annonce = sortie.index('étape 2/')
    assert 'mise_a_jour_etat : faite' in sortie[annonce:annonce + 80]
    premiere_pause = sortie.index(INVITE.decode(), annonce)
    assert annonce < premiere_pause < sortie.index('Arrêt de ')
    # une pause suit le redémarrage de la dernière unité reprise
    dernier_demarrage = sortie.rindex('commande systemctl start')
    assert INVITE.decode() in sortie[dernier_demarrage:]
    fichiers = journaux(faux)
    assert len(fichiers) == 1
    contenu = fichiers[0].read_text(encoding='utf-8')
    assert SENTINELLE not in sortie and SENTINELLE not in contenu and '\x1b' not in contenu


# -- cohérence des deux scripts ---------------------------------------------------------------------------------------------------------

def test_partie_commune_identique_dans_les_deux_scripts():
    def commun(chemin):
        t = chemin.read_text(encoding='utf-8')
        return t[t.index('# DEBUT commun'):t.index('# FIN commun')]
    assert commun(ADMIN) == commun(RELAIS)


def test_listes_fermees_d_unites_ecrites_dans_les_scripts():
    admin, relais = ADMIN.read_text(encoding='utf-8'), RELAIS.read_text(encoding='utf-8')
    assert 'MAJ_POSSIBLES=(pollux.service romulus.service paresia-tunnel.service)' in admin
    assert 'MAJ_POSSIBLES=(remus.service castor.service)' in relais
    for texte in (admin, relais):
        assert 'systemctl restart' not in texte.replace('jamais restart', '')
        assert re.search(r'(?m)^MISE_A_JOUR="\$\{MISE_A_JOUR:-non\}"|^\s+MISE_A_JOUR="\$\{MISE_A_JOUR:-non\}"', texte)
        assert 'VERSION_SCRIPT=0.2.0' in texte
