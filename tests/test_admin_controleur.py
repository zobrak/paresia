# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests du contrôleur du poste client, de son point d'entrée et du noyau sans produit ;
# dépendances : bibliothèque standard, pytest ; aucun import Qt.
# Suivi des versions
#   0.1.14  2026-11-08  Ouverture, échecs, perte, fermeture (même si la session échoue), ligne à remettre, --config.
import ast
import json
from pathlib import Path
import re
import secrets
import threading
import time

import pytest

from admin.app import __main__ as principal
from admin.app.cles import ClePublique, ErreurCle
from admin.app.controleur import Controleur, navigation_autorisee
from admin.app.presence import ErreurPresence, Etat
from admin.app.textes import Catalogue, charger

RACINE = Path(__file__).resolve().parents[1]
URL = 'https://bunker.example.org'
CONFIG = {'connexion': {'url': URL},
          'cle': {'cle_publique': '/cle/admin.pub', 'commande_forcee': '/usr/local/bin/pollux'}}
CLE = ClePublique('ssh-ed25519', 'AAAA', 'essai')


class Surface:
    def __init__(self):
        self.appels = []

    def __getattr__(self, nom):
        def appel(*args):
            self.appels.append((nom,) + args)
        return appel

    def noms(self):
        return [a[0] for a in self.appels]

    def cherche(self, nom):
        return [a for a in self.appels if a[0] == nom]


class FausseSession:
    def __init__(self, ecouteur, erreur=None, attente=None):
        self.ecouteur = ecouteur
        self.erreur = erreur
        self.attente = attente
        self.etat = Etat.FERMEE
        self.fermetures = 0
        self._jeton = secrets.token_hex(32)
        self.commence = threading.Event()

    def ouvrir(self):
        self.commence.set()
        if self.attente is not None:
            self.attente.wait(5)
        if self.erreur is not None:
            raise ErreurPresence(self.erreur)
        if self.etat is Etat.FERMEE and self.fermetures:
            raise ErreurPresence('ui_presence_ssh_echec')
        self.etat = Etat.OUVERTE
        self.ecouteur(Etat.OUVERTE, None)

    def jeton(self):
        return self._jeton

    def fermer(self):
        self.fermetures += 1
        self.etat = Etat.FERMEE

    def perdre(self):
        self.etat = Etat.PERDUE
        self.ecouteur(Etat.PERDUE, 'ui_presence_perdue')


def monter(erreur=None, attente=None, lire=None, catalogue=None):
    surface, sessions = Surface(), []

    def fabrique(admin, ecouteur):
        assert admin == 'essai'
        sessions.append(FausseSession(ecouteur, erreur, attente))
        return sessions[-1]

    catalogue = catalogue or charger('fr-FR', RACINE / 'i18n')
    controleur = Controleur(CONFIG, catalogue, fabrique, lire or (lambda chemin: CLE),
                            surface=surface)
    return controleur, surface, sessions


def test_ouverture_reussie():
    controleur, surface, sessions = monter()
    assert controleur.ouvrir_administration() is True
    assert surface.cherche('deposer_cookie') == [('deposer_cookie', sessions[0].jeton())]
    assert surface.cherche('charger') == [('charger', URL + '/admin/')]
    assert surface.cherche('indiquer')[-1][1] is Etat.OUVERTE
    assert controleur.etat is Etat.OUVERTE
    assert surface.noms().index('deposer_cookie') < surface.noms().index('charger')


@pytest.mark.parametrize('code', ['session_limit', 'signature_invalid', 'ui_presence_defi_delai'])
def test_echec_ouverture(code):
    controleur, surface, _ = monter(erreur=code)
    catalogue = charger('fr-FR', RACINE / 'i18n')
    assert controleur.ouvrir_administration() is False
    assert not surface.cherche('deposer_cookie')
    assert not surface.cherche('charger')
    assert surface.cherche('erreur') == [('erreur', catalogue.erreur(code))]
    assert controleur.etat is Etat.FERMEE


def test_pas_de_detail_brut():
    secret = 'detail-brut-ssh-keygen'
    controleur, surface, _ = monter(erreur=secret)
    controleur.ouvrir_administration()
    assert secret not in repr(surface.appels)
    assert surface.cherche('erreur')[0][1] == charger('fr-FR', RACINE / 'i18n').erreur('internal_error')


def test_cle_illisible():
    def lire(chemin):
        raise ErreurCle('ui_cle_illisible')

    controleur, surface, sessions = monter(lire=lire)
    assert controleur.ouvrir_administration() is False
    assert not sessions and not surface.cherche('deposer_cookie')
    assert surface.cherche('erreur') == [
        ('erreur', charger('fr-FR', RACINE / 'i18n').libelle('ui_cle_illisible'))]


def test_perte_sans_reouverture_automatique():
    controleur, surface, sessions = monter()
    controleur.ouvrir_administration()
    surface.appels.clear()
    sessions[0].perdre()
    assert controleur.etat is Etat.PERDUE
    assert surface.noms()[:2] == ['effacer_cookie', 'charger_vide']
    assert surface.cherche('indiquer')[-1][1] is Etat.PERDUE
    assert len(surface.cherche('proposer_rouvrir')) == 1
    assert len(sessions) == 1 and not surface.cherche('deposer_cookie')
    # une seconde notification de la même perte ne répète rien d'ouvert
    assert controleur.ouvrir_administration() is True
    assert len(sessions) == 2 and sessions[0].fermetures == 1


def test_fermetures_equivalentes():
    for action in ('fermer_administration', 'quitter'):
        controleur, surface, sessions = monter()
        controleur.ouvrir_administration()
        surface.appels.clear()
        getattr(controleur, action)()
        getattr(controleur, action)()
        assert sessions[0].fermetures == 1
        assert surface.noms().count('effacer_cookie') == 2
        assert surface.noms().count('charger_vide') == 2
        assert surface.cherche('indiquer')[-1][1] is Etat.FERMEE
        assert controleur.etat is Etat.FERMEE


def test_fermeture_malgre_echec_de_la_session():
    for action in ('fermer_administration', 'quitter'):
        controleur, surface, sessions = monter()
        controleur.ouvrir_administration()

        def echec():
            raise RuntimeError('essai')
        sessions[0].fermer = echec
        surface.appels.clear()
        getattr(controleur, action)()
        assert 'effacer_cookie' in surface.noms()
        assert 'charger_vide' in surface.noms()
        assert surface.cherche('indiquer')[-1][1] is Etat.FERMEE
        assert controleur.etat is Etat.FERMEE


def test_quitter_interdit_reouverture():
    controleur, _, sessions = monter()
    controleur.quitter()
    assert controleur.ouvrir_administration() is False and not sessions


def test_une_seule_session():
    controleur, _, sessions = monter()
    assert controleur.ouvrir_administration() is True
    assert controleur.ouvrir_administration() is False
    assert len(sessions) == 1


def test_une_seule_ouverture_en_cours():
    attente = threading.Event()
    controleur, surface, sessions = monter(attente=attente)
    resultat = []
    fil = threading.Thread(target=lambda: resultat.append(controleur.ouvrir_administration()))
    fil.start()
    while not sessions or not sessions[0].commence.is_set():
        time.sleep(0.001)
    assert controleur.ouvrir_administration() is False
    attente.set()
    fil.join(5)
    assert resultat == [True] and len(sessions) == 1


def test_fermeture_pendant_ouverture():
    attente = threading.Event()
    controleur, surface, sessions = monter(attente=attente)
    resultat = []
    fil = threading.Thread(target=lambda: resultat.append(controleur.ouvrir_administration()))
    fil.start()
    while not sessions or not sessions[0].commence.is_set():
        time.sleep(0.001)
    controleur.fermer_administration()
    attente.set()
    fil.join(5)
    assert resultat == [False]
    assert not surface.cherche('deposer_cookie') and not surface.cherche('erreur')
    assert controleur.etat is Etat.FERMEE


class VerrouEspion:
    """Exécute une action une seule fois, juste avant la première prise du verrou d'émission."""

    def __init__(self, reel, action):
        self.reel, self.action, self.fait = reel, action, False

    def __enter__(self):
        if not self.fait:
            self.fait = True
            self.action()
        self.reel.acquire()

    def __exit__(self, *args):
        self.reel.release()


def test_fermeture_entre_validation_et_depot():
    controleur, surface, sessions = monter()
    controleur._emission = VerrouEspion(controleur._emission, controleur.fermer_administration)
    assert controleur.ouvrir_administration() is False
    assert not surface.cherche('deposer_cookie') and not surface.cherche('charger')
    assert surface.noms()[-3:] == ['effacer_cookie', 'charger_vide', 'indiquer']
    assert surface.cherche('indiquer')[-1][1] is Etat.FERMEE
    assert controleur.etat is Etat.FERMEE


def test_perte_entre_validation_et_depot():
    controleur, surface, sessions = monter()
    controleur._emission = VerrouEspion(controleur._emission, lambda: sessions[0].perdre())
    assert controleur.ouvrir_administration() is False
    assert not surface.cherche('deposer_cookie') and not surface.cherche('charger')
    assert all(a[1] is not Etat.OUVERTE for a in surface.cherche('indiquer'))
    assert surface.cherche('indiquer')[-1][1] is Etat.PERDUE
    assert controleur.etat is Etat.PERDUE


def test_perte_puis_fermeture_sans_proposition_tardive():
    controleur, surface, sessions = monter()
    controleur.ouvrir_administration()
    surface.appels.clear()
    controleur._emission = VerrouEspion(controleur._emission, controleur.fermer_administration)
    sessions[0].perdre()
    assert not surface.cherche('proposer_rouvrir')
    assert surface.cherche('indiquer')[-1][1] is Etat.FERMEE


def test_erreur_inattendue_a_l_ouverture():
    secret = 'trace-interne'
    controleur, surface, sessions = monter()

    def ouvrir_casse():
        raise RuntimeError(secret)

    controleur._fabrique_origine = controleur._fabrique

    def fabrique(admin, ecouteur):
        session = controleur._fabrique_origine(admin, ecouteur)
        session.ouvrir = ouvrir_casse
        return session

    controleur._fabrique = fabrique
    assert controleur.ouvrir_administration() is False
    assert sessions[0].fermetures == 1
    assert surface.cherche('erreur') == [
        ('erreur', charger('fr-FR', RACINE / 'i18n').erreur('internal_error'))]
    assert secret not in repr(surface.appels)
    assert controleur.etat is Etat.FERMEE
    # l'état ouvrant est libéré : une nouvelle tentative démarre
    controleur._fabrique = controleur._fabrique_origine
    assert controleur.ouvrir_administration() is True


def test_etat_et_jeton_lus_hors_verrou():
    controleur, surface, sessions = monter()
    lectures = []

    class SessionEspionne(FausseSession):
        @property
        def etat(self):
            lectures.append(controleur._verrou.locked())
            return self._etat_lu

        @etat.setter
        def etat(self, valeur):
            self._etat_lu = valeur

        def jeton(self):
            lectures.append(controleur._verrou.locked())
            return self._jeton

    controleur._fabrique = lambda admin, ecouteur: SessionEspionne(ecouteur)
    assert controleur.ouvrir_administration() is True
    assert lectures and not any(lectures)
    assert controleur.etat is Etat.OUVERTE


def test_perte_entre_lecture_et_pose_rattrapee():
    controleur, surface, sessions = monter()

    class SessionPerdante(FausseSession):
        def jeton(self):
            jeton = self._jeton
            # perte après la lecture de l'état, avant la pose de OUVERTE
            self.perdre()
            return jeton

    controleur._fabrique = lambda admin, ecouteur: SessionPerdante(ecouteur)
    assert controleur.ouvrir_administration() is False
    assert controleur.etat is Etat.PERDUE
    assert not surface.cherche('deposer_cookie')
    assert surface.cherche('indiquer')[-1][1] is Etat.PERDUE


def test_abandon_nettoie_cookie_et_page():
    controleur, surface, sessions = monter()
    catalogue = charger('fr-FR', RACINE / 'i18n')

    def charger_casse(*args):
        surface.appels.append(('charger',) + args)
        raise RuntimeError('charge')

    def effacer_casse(*args):
        surface.appels.append(('effacer_cookie',) + args)
        raise RuntimeError('efface')

    surface.charger = charger_casse
    surface.effacer_cookie = effacer_casse
    assert controleur.ouvrir_administration() is False
    noms = surface.noms()
    assert noms.index('deposer_cookie') < noms.index('charger') < noms.index('effacer_cookie')
    assert noms.index('effacer_cookie') < noms.index('charger_vide') < noms.index('erreur')
    assert surface.cherche('erreur') == [('erreur', catalogue.erreur('internal_error'))]
    assert sessions[0].fermetures == 1
    assert controleur.etat is Etat.FERMEE


def test_session_fabriquee_apres_fermeture_est_fermee():
    controleur, surface, sessions = monter()
    fabrique_origine = controleur._fabrique

    def fabrique(admin, ecouteur):
        session = fabrique_origine(admin, ecouteur)
        controleur.fermer_administration()
        return session

    controleur._fabrique = fabrique
    assert controleur.ouvrir_administration() is False
    assert sessions[0].fermetures == 1
    assert not surface.cherche('deposer_cookie') and not surface.cherche('charger')
    assert controleur.etat is Etat.FERMEE


def test_ligne_cle(tmp_path, monkeypatch):
    surface = Surface()
    catalogue = Catalogue({'ui_cle_illisible': 'illisible'})
    controleur = Controleur(CONFIG, catalogue, None, lambda chemin: CLE, surface=surface)
    controleur.afficher_ligne_cle()
    assert surface.appels == [('montrer_ligne',
                               'restrict,command="/usr/local/bin/pollux" ssh-ed25519 AAAA essai')]

    def lire(chemin):
        raise ErreurCle('ui_cle_illisible')

    surface = Surface()
    Controleur(CONFIG, catalogue, None, lire, surface=surface).afficher_ligne_cle()
    assert surface.appels == [('erreur', 'illisible')]


def test_ligne_cle_filtree():
    surface = Surface()
    cle = ClePublique('ssh-ed25519', 'AAAA', 'ess\x1b[31mai')
    Controleur(CONFIG, Catalogue({}), None, lambda chemin: cle, surface=surface).afficher_ligne_cle()
    assert '\x1b' not in surface.appels[0][1]


@pytest.mark.parametrize('url, attendu', [
    (URL + '/admin/', True), (URL + ':443/x', True), ('https://BUNKER.example.org/', True),
    ('http://bunker.example.org/', False), ('https://autre.example.org/', False),
    ('https://bunker.example.org:8443/', False), ('https://bunker.example.org.evil/', False),
    ('about:blank', False), ('', False), ('file:///etc/passwd', False),
    ('https://user@bunker.example.org@evil/', False),
    ('https://user@bunker.example.org/', False), ('https://user:mdp@bunker.example.org/', False),
    ('https://@bunker.example.org/', False),
])
def test_navigation(url, attendu):
    assert navigation_autorisee(url, URL) is attendu


def test_config_invalide(tmp_path, capsys):
    fichier = tmp_path / 'paresia.conf'
    fichier.write_text('[admin.connexion]\nurl = http://valeur-fautive.example.org\n')
    fichier.chmod(0o600)
    assert principal.main(['--config', str(fichier)]) == 1
    sortie = capsys.readouterr()
    assert 'valeur-fautive' not in sortie.err + sortie.out
    attendu = json.loads((RACINE / 'i18n/fr-FR.json').read_text('utf-8'))['ui_config_invalide']
    assert sortie.err.startswith(attendu) and sortie.out == ''
    assert principal.main(['--inconnue']) == 1


FICHIERS_NOYAU = ('controleur.py', 'fenetre.py', '__main__.py')


def test_noyau_sans_produit():
    motif = re.compile(r'bunker|relay|legal|nisaba|strfry', re.IGNORECASE)
    for nom in FICHIERS_NOYAU:
        assert not motif.search((RACINE / 'admin/app' / nom).read_text('utf-8')), nom


APPELS_AFFICHES = {'setText', 'setWindowTitle', 'setToolTip', 'addAction', 'addMenu',
                   'setPlaceholderText', 'QLabel', 'QAction', 'print', 'showMessage',
                   'addButton', 'libelle', 'erreur'}


def test_aucun_texte_en_dur():
    for nom in FICHIERS_NOYAU:
        arbre = ast.parse((RACINE / 'admin/app' / nom).read_text('utf-8'))
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.Call):
                continue
            fonction = noeud.func
            appelee = getattr(fonction, 'attr', getattr(fonction, 'id', ''))
            if appelee in {'libelle', 'erreur'}:
                continue  # clés de catalogue
            if appelee in APPELS_AFFICHES:
                for argument in noeud.args:
                    assert not (isinstance(argument, ast.Constant)
                                and isinstance(argument.value, str) and argument.value), (
                        nom, noeud.lineno)
                    if isinstance(argument, ast.JoinedStr):
                        assert not any(isinstance(v, ast.Constant) and re.search(r'\w', v.value)
                                       for v in argument.values), (nom, noeud.lineno)
