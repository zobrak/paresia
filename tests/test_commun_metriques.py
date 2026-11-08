# SPDX-License-Identifier: AGPL-3.0-or-later
# Suivi des versions
#   0.1.1  2026-11-07  Séries communes, écriture périodique, reprise et permissions.
#   0.1.1  2026-11-07  Format sans horodatage, interruptions et liens temporaires.
#   0.1.1  2026-11-07  Vérification du socle commun.
import errno
import io
import json
import os
import re
import secrets
import stat
import threading
import time
import pytest
from server.commun.metriques import Registre, Compteur, Jauge, Collecteur, dossier_configuration
from server.commun.journal import Journal
from server.commun.config import ErreurConfiguration

def test_rendu():
    registre = Registre()
    c = registre.enregistrer(Compteur('essais_total', 'a\nb'))
    c.incrementer(etiquettes={'type': 'a"b\nc'})
    c.incrementer(2, etiquettes={'type': 'a"b\nc'})
    texte = registre.rendre()
    assert texte.startswith('# HELP essais_total a\\nb\n# TYPE essais_total counter\n')
    assert texte.endswith(' 3\n')
    assert 'a\\"b\\nc' in texte
    with pytest.raises(ValueError):
        registre.enregistrer(Jauge('essais_total'))
    with pytest.raises(ValueError):
        c.incrementer(-1)

def test_collecteur(tmp_path, monkeypatch):
    journal = Journal('test', flux=io.StringIO())
    inactif = Collecteur('test', '0.1.1', journal, {}, {})
    inactif.ecrire()
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(ErreurConfiguration):
        dossier_configuration({'actif': True}, {})
    c = Collecteur('test', '0.1.1', journal, {'actif': True}, {'STATE_DIRECTORY': str(tmp_path)})
    c.ecrire()
    fichier = tmp_path / 'metriques' / 'test.prom'
    initial = fichier.read_text()
    assert 'paresia_up{daemon="test"} 1' in initial
    assert stat.S_IMODE(fichier.stat().st_mode) == 0o644
    assert stat.S_IMODE(fichier.parent.stat().st_mode) == 0o755
    def echec(*a, **kw):
        raise OSError(5, 'erreur')
    with monkeypatch.context() as m:
        m.setattr(os, 'rename', echec)
        c.ecrire()
    assert fichier.read_text() == initial
    assert not list(fichier.parent.glob('*.tmp'))
    c.arreter()
    assert 'paresia_up{daemon="test"} 0' in fichier.read_text()


def test_fils_et_limites():
    import threading
    compteur = Compteur('parallel_total')
    fils = [threading.Thread(target=lambda: [compteur.incrementer() for _ in range(1000)]) for _ in range(4)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join()
    assert compteur.rendre().endswith(' 4000\n')
    with pytest.raises(ValueError):
        compteur.incrementer(etiquettes={'valeur': 'x' * 257})
    with pytest.raises(ValueError):
        Jauge('nom invalide')


def test_dossier_refuse(tmp_path):
    flux = io.StringIO()
    fichier = tmp_path / 'fichier'
    fichier.touch()
    c = Collecteur('test', '0.1.1', Journal('test', flux=flux),
                   {'actif': True, 'dossier': str(fichier)}, {})
    c.ecrire()
    assert 'metrics_write_failed' in flux.getvalue()


def test_series_regroupees_et_metadonnees_avant_echantillons():
    registre = Registre()
    compteur = registre.enregistrer(Compteur('essais_total', 'Nombre d’essais'))
    jauge = registre.enregistrer(Jauge('actifs', 'Activités'))
    compteur.incrementer(etiquettes={'etat': 'ok'})
    jauge.definir(2)
    compteur.incrementer(etiquettes={'etat': 'erreur'})
    jauge.definir(3)
    compteur.incrementer(etiquettes={'etat': 'ok'})
    assert registre.rendre().splitlines() == [
        '# HELP actifs Activités',
        '# TYPE actifs gauge',
        'actifs 3',
        '# HELP essais_total Nombre d’essais',
        '# TYPE essais_total counter',
        'essais_total{etat="erreur"} 1',
        'essais_total{etat="ok"} 2',
    ]


def test_fichier_sans_horodatage(tmp_path):
    collecteur = Collecteur('test', '0.1.1', Journal('test', flux=io.StringIO()),
                           {'actif': True, 'dossier': str(tmp_path)}, {})
    jauge = collecteur.registre.enregistrer(Jauge('essai', 'Mesure'))
    jauge.definir(1.25, etiquettes={'description': 'été avec espace, "citation" et\nligne'})
    collecteur.ecrire()
    contenu = (tmp_path / 'test.prom').read_bytes().decode('utf-8')
    etiquette = r'[a-zA-Z_][a-zA-Z0-9_]*="(?:[^"\\\r\n]|\\[\\"n])*"'
    nombre = r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?'
    echantillon = re.compile(
        r'[a-zA-Z_:][a-zA-Z0-9_:]*(?:\{' + etiquette + '(?:,' + etiquette + r')*\})? ' + nombre
    )
    lignes = [ligne for ligne in contenu.splitlines() if not ligne.startswith('#')]
    assert lignes
    # Une mesure comporte un nom (avec ses étiquettes) et une valeur, sans troisième champ.
    assert all(echantillon.fullmatch(ligne) for ligne in lignes)
    assert contenu.endswith('\n') and '\r' not in contenu


@pytest.mark.parametrize('existant', [False, True])
def test_exception_apres_fsync_preserve_publication(tmp_path, monkeypatch, existant):
    flux = io.StringIO()
    collecteur = Collecteur('test', '0.1.1', Journal('test', flux=flux),
                           {'actif': True, 'dossier': str(tmp_path)}, {})
    fichier = tmp_path / 'test.prom'
    temporaire = tmp_path / 'test.prom.tmp'
    if existant:
        collecteur.ecrire()
    precedent = fichier.read_bytes() if existant else None
    collecteur.up.definir(0, etiquettes={'daemon': 'test'})
    prochain = collecteur.registre.rendre().encode('utf-8')
    synchroniser = os.fsync
    synchronisations = []

    def interrompre(fd):
        synchroniser(fd)
        synchronisations.append(fd)
        assert temporaire.read_bytes() == prochain
        assert sorted(p.name for p in tmp_path.glob('*.prom')) == (['test.prom'] if existant else [])
        assert (fichier.read_bytes() if existant else None) == precedent
        raise OSError(errno.EIO, 'interruption après synchronisation')

    def renommer_interdit(*args, **kw):
        pytest.fail('rename exécuté malgré l’interruption')

    monkeypatch.setattr(os, 'fsync', interrompre)
    monkeypatch.setattr(os, 'rename', renommer_interdit)
    collecteur.ecrire()
    assert len(synchronisations) == 1
    assert not temporaire.exists()
    assert (fichier.read_bytes() if existant else None) == precedent
    assert fichier.exists() is existant
    evenement = json.loads(flux.getvalue())
    assert evenement['event'] == 'metrics_write_failed'
    assert evenement['errno'] == errno.EIO
    assert set(evenement) == {'ts', 'level', 'component', 'event', 'errno'}


@pytest.mark.parametrize('pendant_creation', [False, True])
def test_temporaire_symbolique_refuse(tmp_path, monkeypatch, pendant_creation):
    flux = io.StringIO()
    collecteur = Collecteur('test', '0.1.1', Journal('test', flux=flux),
                           {'actif': True, 'dossier': str(tmp_path)}, {})
    collecteur.ecrire()
    fichier = tmp_path / 'test.prom'
    precedent = fichier.read_bytes()
    cible = tmp_path / 'cible'
    cible.write_text('contenu à conserver', encoding='utf-8')
    temporaire = tmp_path / 'test.prom.tmp'
    ouverture = os.open
    creations = []

    def ouvrir(nom, drapeaux, *args, **kw):
        if nom == 'test.prom.tmp':
            creations.append(nom)
            assert drapeaux & os.O_NOFOLLOW
            assert drapeaux & os.O_EXCL
            assert drapeaux & os.O_CREAT
            # Simule un lien apparu entre le contrôle du résidu et la création.
            temporaire.symlink_to(cible)
        return ouverture(nom, drapeaux, *args, **kw)

    if pendant_creation:
        monkeypatch.setattr(os, 'open', ouvrir)
    else:
        temporaire.symlink_to(cible)
    collecteur.ecrire()
    assert creations == (['test.prom.tmp'] if pendant_creation else [])
    assert temporaire.is_symlink()
    assert cible.read_text(encoding='utf-8') == 'contenu à conserver'
    assert fichier.read_bytes() == precedent
    evenement = json.loads(flux.getvalue())
    assert evenement['event'] == 'metrics_write_failed'
    assert evenement['errno'] == (errno.EEXIST if pendant_creation else errno.ELOOP)


def test_temporaire_regulier_residuel_remplace(tmp_path):
    temporaire = tmp_path / 'test.prom.tmp'
    temporaire.write_text('ancienne écriture interrompue', encoding='utf-8')
    collecteur = Collecteur('test', '0.1.1', Journal('test', flux=io.StringIO()),
                           {'actif': True, 'dossier': str(tmp_path)}, {})
    collecteur.ecrire()
    assert (tmp_path / 'test.prom').read_text(encoding='utf-8') == collecteur.registre.rendre()
    assert not temporaire.exists()


def test_aucun_nettoyage_apres_rename_reussi(tmp_path, monkeypatch):
    collecteur = Collecteur('test', '0.1.1', Journal('test', flux=io.StringIO()),
                           {'actif': True, 'dossier': str(tmp_path)}, {})
    temporaire = tmp_path / 'test.prom.tmp'
    renommer = os.rename

    def renommer_et_recreer(*args, **kw):
        renommer(*args, **kw)
        temporaire.write_text('nouvelle écriture', encoding='utf-8')

    monkeypatch.setattr(os, 'rename', renommer_et_recreer)
    collecteur.ecrire()
    assert (tmp_path / 'test.prom').read_text(encoding='utf-8') == collecteur.registre.rendre()
    assert temporaire.read_text(encoding='utf-8') == 'nouvelle écriture'


def test_series_communes_et_compteur_journal(tmp_path):
    journal = Journal('test', flux=io.StringIO())
    debut = time.time()
    collecteur = Collecteur('test', '0.1.1', journal,
                           {'actif': True, 'dossier': str(tmp_path)}, {})
    fin = time.time()
    collecteur.ecrire()
    fichier = tmp_path / 'test.prom'

    def echantillons():
        return dict(ligne.rsplit(' ', 1) for ligne in fichier.read_text(encoding='utf-8').splitlines()
                    if not ligne.startswith('#'))

    initial = echantillons()
    assert initial['paresia_info{daemon="test",version="0.1.1"}'] == '1'
    assert debut <= float(initial['paresia_start_time_seconds{daemon="test"}']) <= fin
    for niveau in ('debug', 'info', 'notice', 'warning', 'error', 'critical'):
        assert initial[f'paresia_log_events_total{{daemon="test",level="{niveau}"}}'] == '0'
    journal.ecrire('info', 'premier')
    journal.ecrire('info', 'second')
    journal.ecrire('error', 'echec')
    journal.ecrire('debug', 'filtre')
    collecteur.ecrire()
    apres = echantillons()
    assert apres['paresia_log_events_total{daemon="test",level="info"}'] == '2'
    assert apres['paresia_log_events_total{daemon="test",level="error"}'] == '1'
    assert apres['paresia_log_events_total{daemon="test",level="debug"}'] == '0'
    assert apres['paresia_start_time_seconds{daemon="test"}'] == initial['paresia_start_time_seconds{daemon="test"}']


def test_ecritures_periodiques_et_arret_borne(tmp_path, monkeypatch):
    collecteur = Collecteur('test', '0.1.1', Journal('test', flux=io.StringIO()),
                           {'actif': True, 'dossier': str(tmp_path), 'periode_s': 0.02}, {})
    publications = []
    deux_publications = threading.Event()
    renommer = os.rename

    def observer_publication(*args, **kw):
        renommer(*args, **kw)
        publications.append((time.monotonic(), (tmp_path / 'test.prom').read_text(encoding='utf-8')))
        if len(publications) >= 2:
            deux_publications.set()

    monkeypatch.setattr(os, 'rename', observer_publication)
    collecteur.demarrer()
    try:
        assert deux_publications.wait(timeout=5)
        assert publications[1][0] > publications[0][0]
        assert all('paresia_up{daemon="test"} 1\n' in texte for _, texte in publications[:2])
    finally:
        debut_arret = time.monotonic()
        collecteur.arreter()
        duree_arret = time.monotonic() - debut_arret
    assert duree_arret < 3
    assert 'paresia_up{daemon="test"} 0\n' in (tmp_path / 'test.prom').read_text(encoding='utf-8')


def test_rename_echoue_sans_divulgation_puis_reussit(tmp_path, monkeypatch):
    flux = io.StringIO()
    collecteur = Collecteur('test', '0.1.1', Journal('test', flux=flux),
                           {'actif': True, 'dossier': str(tmp_path)}, {})
    fichier = tmp_path / 'test.prom'
    collecteur.ecrire()
    precedent = fichier.read_bytes()
    collecteur.up.definir(0, etiquettes={'daemon': 'test'})
    jetable = secrets.token_urlsafe(32)
    renommer = os.rename
    tentatives = []

    def renommer_une_fois_en_echec(*args, **kw):
        tentatives.append(True)
        if len(tentatives) == 1:
            raise OSError(errno.EIO, jetable, str(fichier))
        return renommer(*args, **kw)

    monkeypatch.setattr(os, 'rename', renommer_une_fois_en_echec)
    collecteur.ecrire()
    assert fichier.read_bytes() == precedent
    assert not (tmp_path / 'test.prom.tmp').exists()
    texte = flux.getvalue()
    assert jetable not in texte and str(tmp_path) not in texte
    evenement = json.loads(texte)
    assert evenement['event'] == 'metrics_write_failed'
    assert {k: v for k, v in evenement.items() if k not in {'ts', 'level', 'component', 'event'}} == {'errno': errno.EIO}
    collecteur.ecrire()
    assert len(tentatives) == 2
    assert 'paresia_up{daemon="test"} 0\n' in fichier.read_text(encoding='utf-8')
    assert not (tmp_path / 'test.prom.tmp').exists()
    assert flux.getvalue() == texte


def test_permissions_dossier_par_descripteur(tmp_path, monkeypatch):
    dossier = tmp_path / 'metriques'
    collecteur = Collecteur('test', '0.1.1', Journal('test', flux=io.StringIO()),
                           {'actif': True, 'dossier': str(dossier)}, {})
    creer = os.mkdir
    ouvrir = os.open
    changer_mode = os.fchmod
    descripteurs_dossiers = []
    modes_appliques = []

    def creer_restreint(chemin, mode):
        # Simule un masque restrictif sans modifier l'umask des autres fils.
        creer(chemin, 0o700)

    def ouvrir_dossier(chemin, drapeaux, *args, **kw):
        fd = ouvrir(chemin, drapeaux, *args, **kw)
        if chemin == str(dossier):
            assert drapeaux & os.O_NOFOLLOW
            assert drapeaux & os.O_DIRECTORY
            descripteurs_dossiers.append(fd)
        return fd

    def appliquer_mode(fd, mode):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            assert fd in descripteurs_dossiers
            modes_appliques.append(mode)
        changer_mode(fd, mode)

    def chmod_interdit(*args, **kw):
        pytest.fail('permissions appliquées par chemin au lieu du descripteur')

    monkeypatch.setattr(os, 'mkdir', creer_restreint)
    monkeypatch.setattr(os, 'open', ouvrir_dossier)
    monkeypatch.setattr(os, 'fchmod', appliquer_mode)
    monkeypatch.setattr(os, 'chmod', chmod_interdit)
    collecteur.ecrire()
    assert modes_appliques == [0o755]
    assert stat.S_IMODE(dossier.stat().st_mode) == 0o755
    assert (dossier / 'test.prom').is_file()


def test_dossier_remplace_par_lien_sans_changer_permissions(tmp_path, monkeypatch):
    dossier = tmp_path / 'metriques'
    cible = tmp_path / 'cible'
    cible.mkdir(mode=0o700)
    flux = io.StringIO()
    collecteur = Collecteur('test', '0.1.1', Journal('test', flux=flux),
                           {'actif': True, 'dossier': str(dossier)}, {})
    creer = os.mkdir

    def creer_puis_substituer(chemin, mode):
        creer(chemin, mode)
        dossier.rename(tmp_path / 'dossier_initial')
        dossier.symlink_to(cible, target_is_directory=True)

    monkeypatch.setattr(os, 'mkdir', creer_puis_substituer)
    collecteur.ecrire()
    assert stat.S_IMODE(cible.stat().st_mode) == 0o700
    assert not list(cible.iterdir())
    assert json.loads(flux.getvalue())['event'] == 'metrics_write_failed'
