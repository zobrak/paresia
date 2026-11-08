# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests de l'outil de sauvegardes de procédure (C36, D83, D103) ; dépendances : pytest, bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha  2026-11-06  Création : configuration, copie, relevé, rotation, restauration, procédures.
#   3.0.0-alpha  2026-11-06  Procédures (-P, dépôt contrôlé, sous-shells), usage en code 2, chemins en //, page de manuel.
#   3.0.0-alpha.40  2026-11-06  Code 2 pour restaurer et retrouver (relatif, //) ; contrôle de tout le dépôt, PYTHONPATH après contrôle, SEE ALSO.
#   3.0.0-alpha.41  2026-11-06  Empreintes SHA-256 et refus à la restauration (D113) ; copie root de server/ avant lancement (D114).
#   3.0.0-alpha.41  2026-11-06  Manifeste en version 3, empreinte obligatoire, arbre complet, clé privée sur le fichier entier (D113).
#   3.0.0-alpha.41  2026-11-06  T066 cycle 2 : rejeu après échec du manifeste, journal du refus de clé en copie, contrôles de lien et de jeu robustes.
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys

import pytest

from server.commun.config import ErreurConfiguration, lire
from server.commun.journal import Journal
from server import sauvegarde
from server.sauvegarde import ErreurSauvegarde, SCHEMA, Stockage, rotation
from server.sauvegarde.__main__ import main

RACINE = Path(__file__).resolve().parents[1]
ROOT = pytest.mark.skipif(os.geteuid() == 0, reason='les tests de droits ne tournent pas en root')


def conf(tmp_path, actif='oui', taille='64', machine='essai'):
    base = tmp_path.resolve() / 'sauv'
    fichier = tmp_path.resolve() / 'paresia.conf'
    fichier.write_text(f'[sauvegarde.stockage]\nactif = {actif}\ntaille_max_mio = {taille}\n'
                       f'dossier = {base}\nmachine = {machine}\n', encoding='utf-8')
    fichier.chmod(0o644)
    return fichier, base


def cli(tmp_path, capsys, *args, entree=b'', **options):
    fichier, _ = conf(tmp_path, **options)
    sys.stdin = io.TextIOWrapper(io.BytesIO(entree))
    code = main(['--config', str(fichier), *args], environ={'LANG': 'fr.UTF-8'})
    sortie = capsys.readouterr()
    return code, sortie.out, sortie.err


@pytest.fixture
def stockage(tmp_path):
    fichier, base = conf(tmp_path)
    configuration = lire('sauvegarde', SCHEMA, argv=['--config', str(fichier)], environ={})
    return Stockage(configuration, Journal('sauvegarde', flux=io.StringIO()))


def fichier_source(tmp_path, nom, contenu=b'contenu', mode=0o640):
    chemin = tmp_path.resolve() / 'src' / nom
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(contenu)
    chemin.chmod(mode)
    return str(chemin)


def test_sauvegarde_configuration(tmp_path):
    fichier, base = conf(tmp_path)
    c = lire('sauvegarde', SCHEMA, argv=['--config', str(fichier)], environ={})
    assert c['stockage'] == {'actif': 'oui', 'taille_max_mio': 64, 'dossier': str(base), 'machine': 'essai'}
    c = lire('sauvegarde', SCHEMA, argv=['--config', str(fichier)],
             environ={'PARESIA_SAUVEGARDE_STOCKAGE_ACTIF': 'non', 'PARESIA_SAUVEGARDE_STOCKAGE_TAILLE_MAX_MIO': '3'})
    assert (c['stockage']['actif'], c['stockage']['taille_max_mio']) == ('non', 3)
    journal = Journal('sauvegarde', flux=io.StringIO())
    for cle, valeur in (('actif', 'peut-etre'), ('machine', 'Admin'), ('machine', '1x'), ('machine', 'a' * 33)):
        c = lire('sauvegarde', SCHEMA, argv=['--config', str(fichier)], environ={})
        c['stockage'][cle] = valeur
        with pytest.raises(ErreurSauvegarde) as e:
            Stockage(c, journal)
        assert e.value.message == 'backup_config_invalid'
    with pytest.raises(ErreurConfiguration):
        lire('sauvegarde', SCHEMA, argv=['--config', str(fichier)], environ={'PARESIA_SAUVEGARDE_STOCKAGE_DOSSIER': 'relatif'})
    # actif est obligatoire dans la configuration (aucun défaut dans le code)
    fichier.write_text('[sauvegarde.stockage]\ndossier = /x\nmachine = a\n')
    with pytest.raises(ErreurConfiguration):
        lire('sauvegarde', SCHEMA, argv=['--config', str(fichier)], environ={})


@pytest.mark.parametrize('nom', ['paresia.conf', 'paresia-relais.conf'])
def test_paresia_conf_sauvegarde(nom):
    c = lire('sauvegarde', SCHEMA, argv=['--config', str(RACINE / 'server/conf' / nom)], environ={})
    attendu = 'admin' if nom == 'paresia.conf' else 'relais'
    assert c['stockage'] == {'actif': 'oui', 'taille_max_mio': 64, 'dossier': '/var/backups/paresia',
                             'machine': attendu}


def test_sauvegarde_copier(stockage, tmp_path):
    f = fichier_source(tmp_path, 'etc/a.conf', b'abc', 0o640)
    os.utime(f, (1_000_000, 1_000_000))
    jeu, copies, depasse, _ = stockage.copier([f])
    assert (copies, depasse) == (1, False) and re.fullmatch(r'\d{8}-\d{6}', jeu)
    copie = stockage.chemin_copie(stockage.dossier_jeu(jeu), f)
    assert Path(copie).read_bytes() == b'abc'
    assert stat.S_IMODE(os.stat(copie).st_mode) == 0o640 and int(os.stat(copie).st_mtime) == 1_000_000
    assert not [p for p in Path(stockage.dossier_jeu(jeu)).rglob('.paresia-*')]
    # rejeu : la première sauvegarde est conservée
    Path(f).write_bytes(b'modifie')
    assert stockage.copier([f], jeu=jeu)[1] == 0
    assert Path(copie).read_bytes() == b'abc'
    # dossier refusé sans --arbre ; inexistant refusé sans --si-absent ; lien refusé
    with pytest.raises(ErreurSauvegarde) as e:
        stockage.copier([str(Path(f).parent)])
    assert e.value.message == 'backup_directory_refused'
    with pytest.raises(ErreurSauvegarde) as e:
        stockage.copier([f + '.absent'])
    assert e.value.message == 'backup_source_missing'
    lien = Path(f).parent / 'lien'
    lien.symlink_to(f)
    with pytest.raises(ErreurSauvegarde) as e:
        stockage.copier([str(lien)])
    assert e.value.message == 'backup_symlink_refused'
    for mauvais in ('relatif', '/a/../b', '/a//b', '/a/b/', '/', '/a\nb'):
        with pytest.raises(ErreurSauvegarde) as e:
            stockage.copier([mauvais])
        assert e.value.sortie == 2
    # arbre : arborescence, modes, liens non suivis
    racine = Path(f).parent / 'arbre'
    (racine / 'sous').mkdir(parents=True)
    (racine / 'sous' / 'x').write_bytes(b'x')
    (racine / 'sous' / 'x').chmod(0o755)
    (racine / 'l').symlink_to('sous/x')
    jeu2 = stockage.copier([str(racine)], arbre=True)[0]
    copie = Path(stockage.chemin_copie(stockage.dossier_jeu(jeu2), str(racine)))
    assert (copie / 'sous' / 'x').read_bytes() == b'x' and stat.S_IMODE((copie / 'sous' / 'x').stat().st_mode) == 0o755
    assert (copie / 'l').is_symlink() and os.readlink(copie / 'l') == 'sous/x'


def test_sauvegarde_releve(stockage, tmp_path, capsys):
    code, sortie, _ = cli(tmp_path, capsys, 'releve', 'nft-avant', entree=b'regles\n')
    assert code == 0
    jeu = Path(sortie.strip())
    assert (jeu / 'releves' / 'nft-avant').read_bytes() == b'regles\n'
    assert stat.S_IMODE(jeu.stat().st_mode) == 0o700
    for nom in ('../x', 'a/b', '', 'a b', 'x' * 65):
        assert cli(tmp_path, capsys, 'releve', nom)[0] == 2
    # relevé réécrit dans le même jeu, retrouvé par l'outil
    assert cli(tmp_path, capsys, 'releve', '--jeu', jeu.name, 'nft-avant', entree=b'autre')[0] == 0
    code, sortie, _ = cli(tmp_path, capsys, 'retrouver', '--releve', 'nft-avant')
    assert code == 0 and sortie.split('\t')[2].strip() == str(jeu / 'releves' / 'nft-avant')
    assert (jeu / 'releves' / 'nft-avant').read_bytes() == b'autre'


def jeux_fictifs(stockage, tailles, horodatages=None):
    machine = Path(stockage._preparer(True))
    noms = horodatages or [f'2026010{i + 1}-000000' for i in range(len(tailles))]
    for nom, taille in zip(noms, tailles):
        (machine / nom).mkdir(mode=0o700)
        (machine / nom / 'f').write_bytes(b'x' * taille)
    return machine, noms


def test_sauvegarde_rotation(stockage):
    machine, noms = jeux_fictifs(stockage, [10, 10, 10, 10])
    # limite exacte : rien de supprimé
    assert rotation(str(machine), 40) == (40, [])
    # un octet de moins : le plus ancien seulement
    assert rotation(str(machine), 39) == (30, [noms[0]])
    # jeu protégé et plus récent jamais supprimés
    taille, supprimes = rotation(str(machine), 0, protegés={noms[1]})
    assert supprimes == [noms[2]] and sorted(os.listdir(machine)) == [noms[1], noms[3]] and taille == 20
    # dossiers étrangers ignorés
    (machine / 'autre').mkdir()
    (machine / 'autre' / 'f').write_bytes(b'y' * 100)
    assert rotation(str(machine), 0, protegés={noms[1]})[1] == []
    assert (machine / 'autre').exists()


def test_sauvegarde_rotation_cli(tmp_path, capsys):
    # un jeu seul plus grand que la limite : écrit quand même, code 3, avertissement
    gros = fichier_source(tmp_path, 'gros', b'x' * (1024 * 1024 + 1))
    code, _, erreur = cli(tmp_path, capsys, 'copier', gros, taille='1')
    assert code == 3 and 'limite' in erreur
    _, base = conf(tmp_path, taille='1')
    jeux = list((base / 'essai').iterdir())
    assert len(jeux) == 1 and (Path(jeux[0]) / 'fichiers').exists()
    # le jeu suivant supprime l'ancien (le plus récent est conservé) : la limite est tenue, code 0
    petit = fichier_source(tmp_path, 'petit', b'x')
    code, _, _ = cli(tmp_path, capsys, 'copier', petit, taille='1')
    assert code == 0 and len(list((base / 'essai').iterdir())) == 1
    assert cli(tmp_path, capsys, 'nettoyer', taille='1')[0] == 0


def test_sauvegarde_desactivee(tmp_path, capsys):
    f = fichier_source(tmp_path, 'a')
    code, sortie, erreur = cli(tmp_path, capsys, 'copier', f, actif='non')
    _, base = conf(tmp_path)
    assert code == 0 and sortie == '' and 'désactivées' in erreur and not base.exists()
    assert cli(tmp_path, capsys, 'releve', 'x', entree=b'a', actif='non')[0] == 0 and not base.exists()
    code, sortie, _ = cli(tmp_path, capsys, 'jeu', actif='non')
    assert code == 0 and sortie.strip().startswith(str(base)) and not base.exists()
    # la restauration lit les sauvegardes existantes, même désactivées
    assert cli(tmp_path, capsys, 'copier', f)[0] == 0
    Path(f).write_bytes(b'change')
    assert cli(tmp_path, capsys, 'restaurer', f, actif='non')[0] == 0
    assert Path(f).read_bytes() == b'contenu'


def test_sauvegarde_refuse_cle_privee(stockage, tmp_path, capsys):
    cle = fichier_source(tmp_path, 'cle', b'-----BEGIN OPENSSH ' + b'PRIVATE KEY-----\nAAAA\n')
    code, _, erreur = cli(tmp_path, capsys, 'copier', cle)
    _, base = conf(tmp_path)
    assert code == 4 and 'clé privée' in erreur and not base.exists()
    pem = fichier_source(tmp_path, 'pem', b'x' * 100 + b'-----BEGIN RSA ' + b'PRIVATE KEY-----\n')
    assert cli(tmp_path, capsys, 'copier', pem)[0] == 4
    ok = fichier_source(tmp_path, 'ok', b'-----BEGIN CERTIFICATE-----\n')
    arbre = Path(ok).parent
    assert cli(tmp_path, capsys, 'copier', '--arbre', str(arbre))[0] == 4     # l'arbre contient une clé
    assert not base.exists()
    journal = io.StringIO()
    stockage.journal = Journal('sauvegarde', flux=journal)
    with pytest.raises(ErreurSauvegarde):
        stockage.copier([cle])
    assert 'backup_refused' in journal.getvalue() and 'PRIVATE' not in journal.getvalue() and cle not in journal.getvalue()


def test_sauvegarde_droits_chemins(tmp_path, stockage):
    stockage.copier([fichier_source(tmp_path, 'a')])
    for chemin in (stockage.base, stockage.dossier_machine):
        assert stat.S_IMODE(os.stat(chemin).st_mode) == 0o700
    jeu = stockage.jeux()[0]
    assert stat.S_IMODE(os.stat(stockage.dossier_jeu(jeu)).st_mode) == 0o700
    # composant lien symbolique refusé
    reel = tmp_path.resolve() / 'reel'
    reel.mkdir()
    (tmp_path / 'lien').symlink_to(reel)
    c = lire('sauvegarde', SCHEMA, argv=['--config', str(conf(tmp_path)[0])], environ={})
    c['stockage']['dossier'] = str(tmp_path.resolve() / 'lien' / 'sauv')
    with pytest.raises(ErreurSauvegarde) as e:
        Stockage(c, stockage.journal).copier([fichier_source(tmp_path, 'b')])
    assert e.value.message == 'backup_symlink_refused'
    assert not (reel / 'sauv').exists()
    # dossier de machine préexistant en lien ou ouvert à tous : refusé
    fichier, base = conf(tmp_path, machine='autre')
    (base / 'x').parent.mkdir(exist_ok=True)
    (base / 'autre').symlink_to(reel)
    s2 = Stockage(lire('sauvegarde', SCHEMA, argv=['--config', str(fichier)], environ={}), stockage.journal)
    with pytest.raises(ErreurSauvegarde):
        s2.copier([fichier_source(tmp_path, 'c')])


def test_sauvegarde_i18n():
    fr = json.loads((RACINE / 'i18n/fr-FR.json').read_text(encoding='utf-8'))
    en = json.loads((RACINE / 'i18n/en-US.json').read_text(encoding='utf-8'))
    assert fr.keys() == en.keys()
    source = (RACINE / 'server/sauvegarde/__init__.py').read_text() + (RACINE / 'server/sauvegarde/__main__.py').read_text()
    for cle in set(re.findall(r"'(backup_[a-z_]+)'", source)):
        if cle in ('backup_written', 'backup_rotated', 'backup_disabled', 'backup_refused', 'backup_restored'):
            continue
        assert cle in fr, cle
    for cle in fr:
        if cle.startswith('backup_'):
            assert fr[cle] and en[cle]


def test_sauvegarde_sortie_filtree(tmp_path, capsys):
    fichier, _ = conf(tmp_path)
    code = main(['--config', str(fichier), 'restaurer', '/tmp/a\x1b[31mb'], environ={'LANG': 'en.UTF-8'})
    sortie = capsys.readouterr()
    assert code == 2 and '\x1b' not in sortie.err
    code = main(['--config', str(fichier), 'retrouver', '--releve', 'x'], environ={})
    assert code == 5 and '\x1b' not in capsys.readouterr().err


def test_sauvegarde_hygiene():
    for p in (RACINE / 'server/sauvegarde').glob('*.py'):
        t = p.read_text()
        assert 'shell=True' not in t and 'os.system' not in t and 'subprocess' not in t and 'popen' not in t.lower()
    assert not list((RACINE / 'server/sauvegarde').glob('*.sh'))
    assert not [p for p in (RACINE / 'server').rglob('*.sh')]


def test_sauvegarde_retrouver(stockage, tmp_path, capsys):
    f = fichier_source(tmp_path, 'a', b'un')
    j1 = stockage.copier([f], jeu=None)[0]
    Path(f).write_bytes(b'deux')
    j2 = stockage.copier([f])[0]
    assert j1 < j2
    jeu, genre, copie, _ = stockage.retrouver(f)
    assert (jeu, genre) == (j2, 'fichier') and Path(copie).read_bytes() == b'deux'
    assert stockage.retrouver(f, jeu=j1)[0] == j1
    code, sortie, _ = cli(tmp_path, capsys, 'retrouver', f)
    assert code == 0 and sortie.split('\t')[0] == j2 and Path(f).read_bytes() == b'deux'
    assert cli(tmp_path, capsys, 'retrouver', f + 'x')[0] == 5
    assert cli(tmp_path, capsys, 'retrouver')[0] == 2
    assert cli(tmp_path, capsys, 'retrouver', f, '--releve', 'x')[0] == 2
    for chemin in ('relatif', '//etc/x', '///etc/x'):
        for commande in ('retrouver', 'restaurer'):
            assert cli(tmp_path, capsys, commande, chemin)[0] == 2, (commande, chemin)


def test_sauvegarde_restaurer(stockage, tmp_path):
    f = fichier_source(tmp_path, 'etc/a', b'origine', 0o600)
    jeu = stockage.copier([f])[0]
    Path(f).write_bytes(b'modifie')
    os.chmod(f, 0o644)
    stockage.restaurer(f)
    assert Path(f).read_bytes() == b'origine' and stat.S_IMODE(os.stat(f).st_mode) == 0o600
    assert not list(Path(f).parent.glob('.paresia-*'))
    # arbre : rétabli entièrement, l'ancien arbre disparaît après succès
    racine = Path(f).parent / 'arbre'
    (racine / 'd').mkdir(parents=True)
    (racine / 'd' / 'x').write_bytes(b'x')
    stockage.copier([str(racine)], arbre=True, jeu=jeu)
    (racine / 'd' / 'x').write_bytes(b'faux')
    (racine / 'intrus').write_bytes(b'i')
    stockage.restaurer(str(racine))
    assert (racine / 'd' / 'x').read_bytes() == b'x' and not (racine / 'intrus').exists()
    assert not list(racine.parent.glob('.paresia-*'))
    # chemin lien symbolique refusé, chemin non sauvegardé refusé
    lien = racine.parent / 'lien'
    lien.symlink_to(f)
    with pytest.raises(ErreurSauvegarde) as e:
        stockage.restaurer(str(lien))
    assert e.value.message == 'backup_symlink_refused'
    with pytest.raises(ErreurSauvegarde) as e:
        stockage.restaurer('relatif')
    assert e.value.sortie == 2
    # un chemin non sauvegardé ne peut pas être écrit, même sous un arbre sauvegardé
    with pytest.raises(ErreurSauvegarde) as e:
        stockage.restaurer(str(racine / 'd' / 'x'))
    assert e.value.sortie == 5


def test_sauvegarde_restaurer_absente(tmp_path, capsys):
    f = fichier_source(tmp_path, 'present', b'intact')
    _, base = conf(tmp_path)
    code, _, erreur = cli(tmp_path, capsys, 'restaurer', f)       # dossier de sauvegarde absent
    assert code == 5 and f in erreur and Path(f).read_bytes() == b'intact' and not base.exists()
    # jeu existant sans ce chemin
    autre = fichier_source(tmp_path, 'autre', b'a')
    assert cli(tmp_path, capsys, 'copier', autre)[0] == 0
    code, _, erreur = cli(tmp_path, capsys, 'restaurer', f)
    assert code == 5 and 'Aucune sauvegarde' in erreur and Path(f).read_bytes() == b'intact'
    assert Path(autre).exists()


def test_sauvegarde_restaurer_marque_absence(stockage, tmp_path):
    cible = tmp_path.resolve() / 'etc' / 'nouveau.conf'
    cible.parent.mkdir()
    jeu = stockage.copier([str(cible)], si_absent=True)[0]
    assert stockage.retrouver(str(cible))[1] == 'absent'
    cible.write_bytes(b'cree par la procedure')
    stockage.restaurer(str(cible))
    assert not cible.exists() and cible.parent.exists()
    stockage.restaurer(str(cible))          # déjà absent : sans effet
    # arbre créé : supprimé seulement si la marque l'autorise
    arbre = cible.parent / 'dossier'
    stockage.copier([str(arbre)], si_absent=True, arbre=True, jeu=jeu)
    (arbre / 'x').parent.mkdir()
    (arbre / 'x').write_bytes(b'x')
    stockage.restaurer(str(arbre))
    assert not arbre.exists()
    simple = cible.parent / 'simple'
    stockage.copier([str(simple)], si_absent=True, jeu=jeu)
    simple.mkdir()
    with pytest.raises(ErreurSauvegarde):
        stockage.restaurer(str(simple))
    assert simple.exists()


# -- procédures -------------------------------------------------------------------------------

PROCEDURES = [RACINE / 'deploy/backend-relais/installer-backend-relais.sh',
              RACINE / 'deploy/backend-admin/installer-backend-admin.sh']
FORMES_REMPLACEES = ('.bak-', 'cp -pn', '-avant"', '$SAUVEGARDE', 'server.bak')


def lignes_code_script(texte):
    return [l for l in texte.splitlines() if l.strip() and not l.strip().startswith('#')]


def corps_fonction(texte, nom):
    return re.search(rf'(?ms)^{nom}\(\) \{{.*?^\}}', texte).group()


def test_procedures_sauvegarde_par_outil():
    for procedure in PROCEDURES:
        texte = procedure.read_text(encoding='utf-8')
        code = lignes_code_script(texte)
        for forme in FORMES_REMPLACEES:
            assert forme not in texte, (procedure.name, forme)
        assert 'python3 -P -m server.sauvegarde' in texte and 'restaurer' in texte
        # une copie de sauvegarde à la main n'existe plus : toute écriture sous /var/backups passe par l'outil
        for ligne in code:
            if '/var/backups' in ligne:
                assert 'server.sauvegarde' in ligne, ligne
        # le retour arrière restaure par l'outil, sans repli ; un échec de restauration arrête le script (set -e)
        retour = corps_fonction(texte, 'retour_arriere')
        assert 'restaurer_si_pose' in retour and not re.search(r'(?m)^[^#\n]*sudo /usr/bin/(rm|cp|mv|install)\b', retour)
        # seule exception : le retrait du fichier d'index des pages de greffons (un fichier, jamais un dossier)
        sans_index = '\n'.join(l for l in code if 'greffons/index.json' not in l)
        assert 'rm -f' not in sans_index and 'rm -rf' not in sans_index
        restaurer = corps_fonction(texte, 'restaurer')
        assert 'outil_q restaurer --jeu "$JEU"' in restaurer and '||' not in restaurer
        assert 'set -euo pipefail' in texte.split('# DEBUT commun')[0]


def test_sauvegarde_page_manuel():
    page = RACINE / 'docs/man/paresia-sauvegarde.8'
    if not page.exists():
        pytest.fail('page de manuel docs/man/paresia-sauvegarde.8 absente (rédigée par le documentaliste)')
    texte = page.read_text(encoding='utf-8')
    for macro in ('.Dd', '.Dt', '.Os', '.Sh NAME', '.Sh SYNOPSIS', '.Sh DESCRIPTION', '.Sh ENVIRONMENT',
                  '.Sh FILES', '.Sh EXIT STATUS', '.Sh SECURITY', '.Sh SEE ALSO'):
        assert macro in texte, macro
    for commande in ('copier', 'releve', 'lister', 'taille', 'jeu', 'nettoyer', 'retrouver', 'restaurer'):
        assert commande in texte
    # options en macros d'enclosure (Oo/Oc), jamais des Op consécutifs sur une ligne d'entrée
    assert not re.search(r'(?m)^\.It .*\bOp\b', texte) and 'Oo Fl' in texte
    # ENVIRONMENT avant FILES ; aucun renvoi à paresia.conf(5)
    assert texte.index('.Sh ENVIRONMENT') < texte.index('.Sh FILES')
    assert 'paresia.conf 5' not in texte
    environnement = texte.split('.Sh ENVIRONMENT', 1)[1].split('.Sh FILES', 1)[0]
    for variable in ('PARESIA_SAUVEGARDE_CONFIG', 'PARESIA_SAUVEGARDE_STOCKAGE_ACTIF', 'PARESIA_SAUVEGARDE_STOCKAGE_DOSSIER'):
        assert variable in environnement, variable
    securite = texte.split('.Sh SECURITY', 1)[1]
    for phrase in ('peuvent contenir des données sensibles', '0700',
                   "n'est pas reconnue", 'consignés dans le\nmanifeste', 'La confiance repose sur le propriétaire', 'SHA-256'):
        assert phrase in securite, phrase
    plat = ' '.join(securite.split())
    assert 'lu en entier' in plat and 'PRIVATE KEY BLOCK' in plat
    mandoc = shutil.which('mandoc')
    if mandoc:
        resultat = subprocess.run([mandoc, '-T', 'lint', str(page)], capture_output=True, text=True)
        assert 'ERROR' not in resultat.stdout + resultat.stderr, resultat.stdout


def test_procedures_outil_et_depot_controle():
    catalogue = (RACINE / 'i18n/fr-FR.json').read_text(encoding='utf-8')
    for procedure in PROCEDURES:
        texte = procedure.read_text(encoding='utf-8')
        assert 'python3 -m server.sauvegarde' not in texte
        assert not re.search(r'python3 (?!-P -m server\.sauvegarde)\S* ?-?m? ?server\.sauvegarde', texte)
        copie = corps_fonction(texte, 'copier_code_outil')
        # D114 : copie de server/ dans un dossier root 0700 par install (sudo, chemin absolu), sans lien
        # symbolique ; aucun contrôle du clone par propriétaire ; la copie est gardée par de vrais if
        for forme in ('-L "$DEPOT/server"', 'find "$DEPOT/server" ! -type d ! -type f -print -quit',
                      'sudo /usr/bin/install -d -o root -g root -m 0700 "$TRAVAIL"',
                      'sudo /usr/bin/install -d -o root -g root -m 0755',
                      'sudo /usr/bin/install -o root -g root -m 0644 --'):
            assert forme in copie, forme
        assert re.search(r'(?m)^    if ', copie) and 'stat -c' not in copie and 'export PYTHONPATH="$DEPOT"' not in texte
        # la fonction outil fixe PYTHONPATH et la configuration ; elle n'est employée qu'après la copie réussie
        assert 'outil() { sudo /usr/bin/env PYTHONPATH=/run/paresia-installation' in texte
        assert 'PARESIA_SAUVEGARDE_CONFIG="$CONF_OUTIL"' in texte and 'CONF_OUTIL=/run/paresia-installation/server/conf/' in texte
        assert 'unset -f outil' not in texte
        jeu = corps_fonction(texte, 'jeu_pret')
        assert jeu.index('copier_code_outil') < jeu.index('outil_q jeu')
        for nom in ('sauvegarder', 'sauvegarder_arbre', 'releve'):
            assert 'jeu_pret' in corps_fonction(texte, nom), nom
        assert copie.index('install -d -o root -g root -m 0700') < copie.index('install -o root -g root -m 0644')
        assert 'Copie du code impossible' in catalogue and 'install_err_copie_code' in texte



def test_sauvegarde_usage_code_2(tmp_path, capsys):
    for args in (['--help'], ['--inconnue'], ['copier', '--inconnue', '/a'], ['lister', 'x'], ['copier']):
        code, sortie, erreur = cli(tmp_path, capsys, *args)
        assert code == 2 and sortie == '' and 'Usage invalide' in erreur, args
    fr = json.loads((RACINE / 'i18n/fr-FR.json').read_text(encoding='utf-8'))
    en = json.loads((RACINE / 'i18n/en-US.json').read_text(encoding='utf-8'))
    assert 'backup_usage' in fr and 'backup_usage' in en


def test_sauvegarde_refuse_double_barre(stockage, tmp_path):
    for chemin in ('//etc/x', '//', '///etc/x'):
        with pytest.raises(ErreurSauvegarde) as e:
            stockage.copier([chemin])
        assert e.value.message == 'backup_path_invalid' and e.value.sortie == 2, chemin
    fichier, _ = conf(tmp_path)
    configuration = lire('sauvegarde', SCHEMA, argv=['--config', str(fichier)], environ={})
    configuration['stockage']['dossier'] = '//var/backups/paresia'
    with pytest.raises(ErreurSauvegarde) as e:
        Stockage(configuration, Journal('sauvegarde', flux=io.StringIO()))
    assert e.value.message == 'backup_config_invalid'


# -- intégrité (D113) -------------------------------------------------------------------------
def _manifeste(stockage, jeu):
    return json.loads((Path(stockage.dossier_jeu(jeu)) / 'manifeste.json').read_text(encoding='utf-8'))


def test_sauvegarde_empreinte_inscrite(stockage, tmp_path):
    import hashlib
    source = Path(fichier_source(tmp_path, 'a.conf', b'abc'))
    arbre = tmp_path / 'arbre'
    (arbre / 'sous').mkdir(parents=True)
    (arbre / 'x').write_bytes(b'un')
    (arbre / 'sous' / 'y').write_bytes(b'deux')
    jeu, *_ = stockage.copier([str(source), str(arbre)], arbre=True)
    manifeste = _manifeste(stockage, jeu)
    assert manifeste['version'] == 3 == sauvegarde.VERSION_MANIFESTE
    assert manifeste['entrees'][str(source)]['sha256'] == hashlib.sha256(b'abc').hexdigest()
    assert manifeste['entrees'][str(arbre)]['empreintes'] == {
        'x': hashlib.sha256(b'un').hexdigest(), 'sous/y': hashlib.sha256(b'deux').hexdigest()}
    assert manifeste['entrees'][str(arbre)]['dossiers'] == ['sous'] and manifeste['entrees'][str(arbre)]['liens'] == {}
    stockage.releve('r1', io.BytesIO(b'releve'), jeu=jeu)
    assert _manifeste(stockage, jeu)['releves']['r1'] == hashlib.sha256(b'releve').hexdigest()
    assert stockage.retrouver(releve='r1', jeu=jeu)[1] == 'releve'


def test_sauvegarde_fichier_altere_refuse(stockage, tmp_path):
    source = Path(fichier_source(tmp_path, 'a.conf', b'avant'))
    jeu, *_ = stockage.copier([str(source)])
    source.write_bytes(b'apres')
    copie = Path(Stockage.chemin_copie(stockage.dossier_jeu(jeu), str(source)))
    copie.write_bytes(b'altere')
    for appel in (lambda: stockage.restaurer(str(source)), lambda: stockage.retrouver(str(source))):
        with pytest.raises(ErreurSauvegarde) as e:
            appel()
        assert e.value.message == 'backup_integrity_failed' and e.value.sortie == 1
    assert source.read_bytes() == b'apres'
    copie.unlink()    # copie manquante : refus aussi
    with pytest.raises(ErreurSauvegarde) as e:
        stockage.restaurer(str(source))
    assert e.value.message == 'backup_integrity_failed' and source.read_bytes() == b'apres'


def test_sauvegarde_empreinte_absente_refusee(stockage, tmp_path):
    source = Path(fichier_source(tmp_path, 'a.conf', b'avant'))
    jeu, *_ = stockage.copier([str(source)])
    chemin = Path(stockage.dossier_jeu(jeu)) / 'manifeste.json'
    manifeste = json.loads(chemin.read_text(encoding='utf-8'))
    del manifeste['entrees'][str(source)]['sha256']
    chemin.write_text(json.dumps(manifeste), encoding='utf-8')
    source.write_bytes(b'apres')
    with pytest.raises(ErreurSauvegarde) as e:
        stockage.restaurer(str(source))
    assert e.value.message == 'backup_integrity_failed' and source.read_bytes() == b'apres'
    # manifeste d'ancienne version (sans empreinte) refusé
    manifeste['version'] = 1
    chemin.write_text(json.dumps(manifeste), encoding='utf-8')
    with pytest.raises(ErreurSauvegarde) as e:
        stockage.restaurer(str(source))
    assert e.value.message == 'backup_integrity_failed' and source.read_bytes() == b'apres'


def test_sauvegarde_arbre_un_fichier_altere_rien_restaure(stockage, tmp_path):
    arbre = tmp_path / 'arbre'
    arbre.mkdir()
    for nom in ('a', 'b', 'c'):
        (arbre / nom).write_bytes(nom.encode())
    jeu, *_ = stockage.copier([str(arbre)], arbre=True)
    (arbre / 'a').write_bytes(b'modifie')
    (arbre / 'b').unlink()
    copie = Path(Stockage.chemin_copie(stockage.dossier_jeu(jeu), str(arbre)))
    (copie / 'c').write_bytes(b'altere')
    with pytest.raises(ErreurSauvegarde) as e:
        stockage.restaurer(str(arbre))
    assert e.value.message == 'backup_integrity_failed'
    assert (arbre / 'a').read_bytes() == b'modifie' and not (arbre / 'b').exists()
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.startswith('.paresia')) == []
    (copie / 'c').write_bytes(b'c')    # copie rétablie : la restauration réussit
    (copie / 'intrus').write_bytes(b'x')    # fichier ajouté à la copie : refus
    with pytest.raises(ErreurSauvegarde):
        stockage.restaurer(str(arbre))


def test_sauvegarde_integrite_cli_et_catalogues(tmp_path, capsys):
    fichier, _ = conf(tmp_path)
    source = Path(fichier_source(tmp_path, 'a.conf', b'avant'))
    code, sortie, _ = cli(tmp_path, capsys, 'copier', str(source))
    assert code == 0
    copie = next((Path(sortie.strip()) / 'fichiers').rglob('a.conf'))
    copie.write_bytes(b'altere')
    code, _, erreur = cli(tmp_path, capsys, 'restaurer', str(source))
    assert code == 1 and 'Intégrité refusée' in erreur
    fr = json.loads((RACINE / 'i18n/fr-FR.json').read_text(encoding='utf-8'))
    en = json.loads((RACINE / 'i18n/en-US.json').read_text(encoding='utf-8'))
    assert 'backup_integrity_failed' in fr and 'backup_integrity_failed' in en


# -- compléments d'intégrité et de détection de clé privée ------------------------------------
def _en_tete(nom='OPENSSH '):
    return b'-----BEGIN ' + nom.encode() + b'PRIVATE KEY-----'


def _residus(*dossiers):
    return [p for d in dossiers for p in Path(d).rglob('.paresia-*')]


def _arbre_complet(tmp_path):
    arbre = tmp_path / 'arbre'
    (arbre / 'sous' / 'vide').mkdir(parents=True)
    (arbre / 'x').write_bytes(b'un')
    (arbre / 'sous' / 'y').write_bytes(b'deux')
    os.symlink('sous/y', arbre / 'l1')
    os.symlink(os.fsdecode(b'cible-\xff'), arbre / 'l2')
    return arbre


def _modifier_manifeste(stockage, jeu, fonction):
    chemin = Path(stockage.dossier_jeu(jeu)) / 'manifeste.json'
    manifeste = json.loads(chemin.read_text(encoding='utf-8'))
    fonction(manifeste)
    chemin.write_text(json.dumps(manifeste), encoding='utf-8')


def test_sauvegarde_empreinte_attendue_obligatoire(stockage, tmp_path):
    source = Path(fichier_source(tmp_path, 'a.conf', b'avant'))
    jeu, *_ = stockage.copier([str(source)])
    cible = tmp_path / 'cible'
    cible.write_bytes(b'intact')
    copie = Stockage.chemin_copie(stockage.dossier_jeu(jeu), str(source))
    for attendu in (None, 5, 'a' * 63, 'a' * 65, 'A' * 64, 'g' * 64, 'a' * 64):
        with pytest.raises(ErreurSauvegarde) as e:
            sauvegarde._copier_fichier(copie, str(cible), attendu=attendu, verifier=True)
        assert e.value.message == 'backup_integrity_failed' and e.value.sortie == 1
        assert cible.read_bytes() == b'intact' and not _residus(tmp_path)
    # par restaurer : empreinte absente, invalide ou nulle
    for valeur in ('supprimee', None, 'A' * 64, 'abc', 'g' * 64):
        def changer(m, valeur=valeur):
            entree = m['entrees'][str(source)]
            if valeur == 'supprimee':
                entree.pop('sha256', None)
            else:
                entree['sha256'] = valeur
        _modifier_manifeste(stockage, jeu, changer)
        source.write_bytes(b'actuel')
        with pytest.raises(ErreurSauvegarde) as e:
            stockage.restaurer(str(source))
        assert e.value.message == 'backup_integrity_failed' and source.read_bytes() == b'actuel'
        assert not _residus(tmp_path)
    # arbre : un fichier de la copie absent du dictionnaire attendu
    arbre = _arbre_complet(tmp_path)
    jeu2, *_ = stockage.copier([str(arbre)], arbre=True)
    entree = dict(_manifeste(stockage, jeu2)['entrees'][str(arbre)])
    del entree['empreintes']['x']
    copie_arbre = Stockage.chemin_copie(stockage.dossier_jeu(jeu2), str(arbre))
    neuf = tmp_path / 'neuf'
    with pytest.raises(ErreurSauvegarde) as e:
        sauvegarde._copier_arbre(copie_arbre, str(neuf), restauration=entree)
    assert e.value.message == 'backup_integrity_failed'


def test_sauvegarde_manifeste_arbre_complet(stockage, tmp_path):
    import hashlib
    arbre = _arbre_complet(tmp_path)
    jeu, *_ = stockage.copier([str(arbre)], arbre=True)
    entree = _manifeste(stockage, jeu)['entrees'][str(arbre)]
    assert entree['empreintes'] == {'x': hashlib.sha256(b'un').hexdigest(), 'sous/y': hashlib.sha256(b'deux').hexdigest()}
    assert entree['dossiers'] == ['sous', 'sous/vide']
    assert entree['liens'] == {'l1': 'sous/y', 'l2': os.fsdecode(b'cible-\xff')}
    shutil.rmtree(arbre)
    stockage.restaurer(str(arbre))
    assert (arbre / 'x').read_bytes() == b'un' and (arbre / 'sous' / 'y').read_bytes() == b'deux'
    assert (arbre / 'sous' / 'vide').is_dir()
    assert os.readlink(arbre / 'l1') == 'sous/y' and os.readlink(os.fsencode(arbre / 'l2')) == b'cible-\xff'
    assert not _residus(tmp_path)


def test_sauvegarde_arbre_ecarts_de_structure_refuses(stockage, tmp_path):
    arbre = _arbre_complet(tmp_path)
    jeu, *_ = stockage.copier([str(arbre)], arbre=True)
    copie = Path(Stockage.chemin_copie(stockage.dossier_jeu(jeu), str(arbre)))
    (arbre / 'x').write_bytes(b'actuel')

    def ajouter_lien():
        os.symlink('x', copie / 'l3')

    def retirer_lien():
        (copie / 'l1').unlink()

    def changer_cible():
        (copie / 'l1').unlink()
        os.symlink('x', copie / 'l1')

    def ajouter_dossier():
        (copie / 'neuf').mkdir()

    def retirer_dossier():
        (copie / 'sous' / 'vide').rmdir()

    def ajouter_fichier():
        (copie / 'intrus').write_bytes(b'x')

    for ecart in (ajouter_lien, retirer_lien, changer_cible, ajouter_dossier, retirer_dossier, ajouter_fichier):
        ecart()
        with pytest.raises(ErreurSauvegarde) as e:
            stockage.restaurer(str(arbre))
        assert e.value.message == 'backup_integrity_failed', ecart.__name__
        assert (arbre / 'x').read_bytes() == b'actuel' and not _residus(tmp_path)
        shutil.rmtree(copie)    # copie rétablie à l'identique depuis la source d'origine
        shutil.copytree(arbre, copie, symlinks=True)
        (copie / 'x').write_bytes(b'un')
    # le manifeste est la référence : champs absents ou de mauvais type
    for cle, valeur in (('liens', 'supprimee'), ('dossiers', 'supprimee'), ('liens', []), ('dossiers', {}), ('liens', {'a': 1})):
        def changer(m, cle=cle, valeur=valeur):
            if valeur == 'supprimee':
                del m['entrees'][str(arbre)][cle]
            else:
                m['entrees'][str(arbre)][cle] = valeur
        _modifier_manifeste(stockage, jeu, changer)
        with pytest.raises(ErreurSauvegarde) as e:
            stockage.restaurer(str(arbre))
        assert e.value.message == 'backup_integrity_failed' and (arbre / 'x').read_bytes() == b'actuel'
        assert not _residus(tmp_path)


def test_sauvegarde_copie_restauration_refuse_entree_hors_manifeste(stockage, tmp_path, monkeypatch):
    arbre = _arbre_complet(tmp_path)
    jeu, *_ = stockage.copier([str(arbre)], arbre=True)
    copie = Path(Stockage.chemin_copie(stockage.dossier_jeu(jeu), str(arbre)))
    os.symlink('/etc/hostname', copie / 'glisse')
    monkeypatch.setattr(sauvegarde, '_structure_conforme', lambda copie, entree: sauvegarde._entrees_arbre(copie))
    entree = _manifeste(stockage, jeu)['entrees'][str(arbre)]
    neuf = tmp_path / 'neuf'
    with pytest.raises(ErreurSauvegarde) as e:
        sauvegarde._copier_arbre(str(copie), str(neuf), restauration=entree)
    assert e.value.message == 'backup_integrity_failed'
    with pytest.raises(ErreurSauvegarde):
        stockage.restaurer(str(arbre))
    assert not os.path.lexists(arbre / 'glisse')


def test_sauvegarde_manifeste_version_2_refuse(stockage, tmp_path):
    source = Path(fichier_source(tmp_path, 'a.conf', b'avant'))
    jeu, *_ = stockage.copier([str(source)])
    _modifier_manifeste(stockage, jeu, lambda m: m.__setitem__('version', 2))
    for appel in (lambda: stockage.retrouver(str(source)), lambda: stockage.restaurer(str(source))):
        with pytest.raises(ErreurSauvegarde) as e:
            appel()
        assert e.value.message == 'backup_integrity_failed'


def test_sauvegarde_refuse_cle_privee_fichier_entier(stockage, tmp_path, capsys):
    _, base = conf(tmp_path)
    bloc = 65536
    cas = {
        'loin': b'x' * 10000 + _en_tete(),
        'mio': b'\n' * (1024 * 1024) + _en_tete('RSA '),
        'limite': b'y' * 100 + _en_tete('A' * 64),
    }
    for decalage in (-1, 0, 1):
        cas[f'frontiere{decalage}'] = b'z' * (bloc + decalage) + _en_tete()
        cas[f'coupe{decalage}'] = b'z' * (bloc - 10 + decalage) + _en_tete()
    assert len(_en_tete('A' * 64)) == 91
    for nom, contenu in cas.items():
        source = fichier_source(tmp_path, nom, contenu)
        code, _, erreur = cli(tmp_path, capsys, 'copier', source)
        assert code == 4 and 'clé privée' in erreur and not base.exists(), nom
    # hors périmètre de la détection : nom trop long, nom ne se terminant pas par PRIVATE KEY
    for nom, contenu in (('long', _en_tete('A' * 65)), ('bloc', b'-----BEGIN PRIVATE KEY BLOCK-----'),
                         ('cert', b'-----BEGIN CERTIFICATE-----\n')):
        source = fichier_source(tmp_path, nom, contenu)
        assert cli(tmp_path, capsys, 'copier', source)[0] == 0, nom
    # arbre : clé loin du début d'un des fichiers
    arbre = tmp_path / 'arbre-cle'
    arbre.mkdir()
    (arbre / 'a').write_bytes(b'ok')
    (arbre / 'b').write_bytes(b'q' * 200000 + _en_tete())
    shutil.rmtree(base, ignore_errors=True)
    code, _, _ = cli(tmp_path, capsys, 'copier', '--arbre', str(arbre))
    assert code == 4 and not base.exists()


def test_sauvegarde_cle_detectee_pendant_la_copie(stockage, tmp_path, monkeypatch):
    monkeypatch.setattr(sauvegarde, '_verifier_sans_cle', lambda chemin, arbre: None)
    sortie = io.StringIO()
    stockage.journal = Journal('sauvegarde', flux=sortie)
    source = Path(fichier_source(tmp_path, 'cle', b'w' * 70000 + _en_tete()))
    with pytest.raises(ErreurSauvegarde) as e:
        stockage.copier([str(source)])
    assert e.value.message == 'backup_key_refused' and e.value.sortie == 4
    assert 'backup_refused' in sortie.getvalue() and 'backup_key_refused' in sortie.getvalue()
    assert str(source) not in sortie.getvalue()
    assert not _residus(stockage.base)
    jeux = stockage.jeux()
    jeu = jeux[0] if jeux else stockage.nouveau_jeu()
    assert 'cle' not in _manifeste_ou_vide(stockage, jeu)
    assert not list(Path(stockage.dossier_jeu(jeu)).rglob('cle'))
    arbre = tmp_path / 'arbre'
    (arbre / 'sous').mkdir(parents=True)
    (arbre / 'a').write_bytes(b'ok')
    (arbre / 'sous' / 'cle').write_bytes(b'v' * 130000 + _en_tete())
    with pytest.raises(ErreurSauvegarde) as e:
        stockage.copier([str(arbre)], arbre=True, jeu=jeu)
    assert e.value.sortie == 4 and not _residus(stockage.base)
    assert not os.path.lexists(Stockage.chemin_copie(stockage.dossier_jeu(jeu), str(arbre)))


def _manifeste_ou_vide(stockage, jeu):
    try:
        return _manifeste(stockage, jeu)['entrees']
    except FileNotFoundError:
        return {}


def test_sauvegarde_manifeste_taille_bornee(stockage, tmp_path, monkeypatch):
    a = Path(fichier_source(tmp_path, 'a.conf', b'a'))
    b = Path(fichier_source(tmp_path, 'b.conf', b'b'))
    jeu, *_ = stockage.copier([str(a)])
    avant = (Path(stockage.dossier_jeu(jeu)) / 'manifeste.json').read_bytes()
    monkeypatch.setattr(sauvegarde, '_MANIFESTE_MAX', len(avant) + 10)
    with pytest.raises(ErreurSauvegarde) as e:
        stockage.copier([str(b)], jeu=jeu)
    assert e.value.message == 'backup_failed' and e.value.sortie == 1
    assert (Path(stockage.dossier_jeu(jeu)) / 'manifeste.json').read_bytes() == avant
    assert not _residus(stockage.base)
    assert stockage.retrouver(str(a), jeu=jeu)[1] == 'fichier'


def test_sauvegarde_manifeste_echec_laisse_rejeu_possible(stockage, tmp_path, monkeypatch):
    a = Path(fichier_source(tmp_path, 'a.conf', b'a'))
    arbre = tmp_path / 'arbre'
    (arbre / 'sous').mkdir(parents=True)
    (arbre / 'sous' / 'f').write_bytes(b'x')
    fichier_neuf = Path(fichier_source(tmp_path, 'b.conf', b'b'))
    jeu, *_ = stockage.copier([str(a)])
    avant = (Path(stockage.dossier_jeu(jeu)) / 'manifeste.json').read_bytes()
    with monkeypatch.context() as m:
        m.setattr(sauvegarde, '_MANIFESTE_MAX', len(avant) + 10)
        for chemin, option in ((fichier_neuf, False), (arbre, True)):
            with pytest.raises(ErreurSauvegarde):
                stockage.copier([str(chemin)], arbre=option, jeu=jeu)
            assert not os.path.lexists(Stockage.chemin_copie(stockage.dossier_jeu(jeu), str(chemin)))
            assert (Path(stockage.dossier_jeu(jeu)) / 'manifeste.json').read_bytes() == avant
    assert not _residus(stockage.base)
    stockage.copier([str(fichier_neuf)], jeu=jeu)
    stockage.copier([str(arbre)], arbre=True, jeu=jeu)
    assert stockage.retrouver(str(arbre), jeu=jeu)[1] == 'arbre'
    assert stockage.retrouver(str(fichier_neuf), jeu=jeu)[1] == 'fichier'
