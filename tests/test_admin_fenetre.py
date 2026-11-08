# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests de la fenêtre principale du poste client ; dépendances : PyQt6, QtWebEngine, pytest.
# Suivi des versions
#   0.1.19  2026-11-08  Exceptions différées des slots et des fils, fermeture sûre et restauration des crochets.
#   0.1.14  2026-11-08  Profil privé, navigation, cookie, indicateur, ligne à remettre ;
#                       boîte de refus unique, fermeture acceptée malgré une erreur ;
#                       cookie sans domaine, origine IPv6 littérale.
import faulthandler
import os
import sys
import threading
from pathlib import Path
import secrets

import pytest

pytest.importorskip('PyQt6.QtWebEngineWidgets')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtGui import QCloseEvent                                     # noqa: E402
from PyQt6.QtCore import Qt, QUrl                                           # noqa: E402
from PyQt6.QtNetwork import QNetworkCookie                              # noqa: E402
from PyQt6.QtTest import QTest                                          # noqa: E402
from PyQt6.QtWebEngineCore import QWebEnginePage                        # noqa: E402
from PyQt6.QtWidgets import QApplication, QLineEdit                     # noqa: E402

from admin.app.cles import ClePublique, ErreurCle                       # noqa: E402
from admin.app.fenetre import Fenetre, creer_cookie, icone             # noqa: E402
from admin.app.presence import Etat                                     # noqa: E402
from admin.app.textes import charger                                    # noqa: E402

RACINE = Path(__file__).resolve().parents[1]
URL = 'https://bunker.example.org'
CONFIG = {'connexion': {'url': URL},
          'cle': {'cle_publique': '/cle/admin.pub', 'commande_forcee': '/usr/local/bin/pollux'}}
CATALOGUE = charger('fr-FR', RACINE / 'i18n')


@pytest.fixture(scope='module')
def application():
    return QApplication.instance() or QApplication(['paresia-admin'])


def lire_ok(chemin):
    return ClePublique('ssh-ed25519', 'AAAA', 'essai')


@pytest.fixture
def fenetre(application):
    f = Fenetre(CONFIG, CATALOGUE, lambda admin, ecouteur: None, lire_ok, barre_taches=False)
    yield f
    f.close()


def navigation(page, url):
    return page.acceptNavigationRequest(
        QUrl(url), QWebEnginePage.NavigationType.NavigationTypeLinkClicked, True)


def navigation_secondaire(page, url):
    return page.acceptNavigationRequest(
        QUrl(url), QWebEnginePage.NavigationType.NavigationTypeLinkClicked, False)


def test_vidage_a_usage_unique(fenetre):
    page = fenetre.page
    assert navigation(page, 'about:blank') is False
    page.attendre_vide()
    assert navigation(page, 'data:text/html,x') is False
    assert navigation_secondaire(page, 'about:blank') is False
    assert navigation(page, 'about:blank') is True
    assert navigation(page, 'about:blank') is False


def test_vidage_malgre_chargement_en_cours(fenetre):
    page = fenetre.page
    page.attendre_vide()
    assert navigation(page, URL + '/admin/') is True
    assert navigation(page, 'about:blank') is True


def test_userinfo_refuse(fenetre):
    assert navigation(fenetre.page, 'https://user:mdp@bunker.example.org/') is False


def test_telechargement_annule(fenetre):
    # le signal n'accepte qu'une vraie requête : on vérifie le branchement de l'annulation
    assert fenetre.profil.receivers(fenetre.profil.downloadRequested) == 1


def test_texte_brut(fenetre):
    assert fenetre.etiquette.textFormat() == Qt.TextFormat.PlainText


def test_profil_prive(fenetre):
    assert fenetre.profil.isOffTheRecord() is True


def test_navigation_restreinte(fenetre):
    assert navigation(fenetre.page, URL + '/admin/') is True
    for refusee in ('http://bunker.example.org/', 'https://autre.example.org/',
                    'https://bunker.example.org:8443/', 'file:///etc/passwd'):
        fenetre.dernier_message = None
        assert navigation(fenetre.page, refusee) is False, refusee
        assert fenetre.dernier_message.text() == CATALOGUE.libelle('ui_navigation_refusee')
        fenetre.dernier_message.done(0)


def test_une_seule_boite_de_refus(fenetre):
    assert navigation(fenetre.page, 'https://autre.example.org/') is False
    premiere = fenetre.dernier_message
    assert navigation(fenetre.page, 'file:///etc/passwd') is False
    assert fenetre.dernier_message is premiere
    premiere.done(0)
    assert navigation(fenetre.page, 'https://autre.example.org/') is False
    assert fenetre.dernier_message is not premiere


def test_fermeture_acceptee_malgre_erreur(fenetre):
    def casse():
        raise RuntimeError('essai')
    reel = fenetre.controleur.quitter
    fenetre.controleur.quitter = casse
    evenement = QCloseEvent()
    evenement.ignore()
    try:
        with pytest.raises(RuntimeError):
            fenetre.closeEvent(evenement)
    finally:
        fenetre.controleur.quitter = reel
    assert evenement.isAccepted()


def test_cookie():
    jeton = secrets.token_hex(32)
    cookie = creer_cookie(jeton)
    assert cookie.name().data() == b'admin_token'
    assert cookie.value().data() == jeton.encode()
    assert cookie.isSecure() and cookie.isHttpOnly()
    assert cookie.sameSitePolicy() == QNetworkCookie.SameSite.Strict
    assert cookie.path() == '/' and cookie.domain() == ''
    assert cookie.isSessionCookie()


def test_trois_etats_distincts(fenetre):
    titres, etiquettes, images = set(), set(), set()
    for etat, cle in ((Etat.FERMEE, 'ui_etat_fermee'), (Etat.OUVERTE, 'ui_etat_ouverte'),
                      (Etat.PERDUE, 'ui_etat_perdue')):
        fenetre._pont.indiquer(etat, CATALOGUE.libelle(cle))
        titres.add(fenetre.windowTitle())
        etiquettes.add(fenetre.etiquette.text())
        pixel = icone(etat).pixmap(32, 32).toImage().pixelColor(16, 16).name()
        images.add(pixel)
        assert fenetre.etiquette.text() == CATALOGUE.libelle(cle)
    assert len(titres) == len(etiquettes) == len(images) == 3


def test_barre_des_taches(application):
    sans = Fenetre(CONFIG, CATALOGUE, None, lire_ok, barre_taches=False)
    assert sans._icone_barre is None
    avec = Fenetre(CONFIG, CATALOGUE, None, lire_ok, barre_taches=True)
    avec._pont.indiquer(Etat.OUVERTE, CATALOGUE.libelle('ui_etat_ouverte'))
    assert avec._icone_barre.toolTip() == CATALOGUE.libelle('ui_etat_ouverte')
    sans.close()
    avec.close()


def test_ligne_en_lecture_seule(fenetre):
    fenetre.controleur.afficher_ligne_cle()
    assert fenetre.dialogue_ligne is not None
    champ = fenetre.dialogue_ligne.findChild(QLineEdit)
    assert champ.isReadOnly()
    assert champ.text() == 'restrict,command="/usr/local/bin/pollux" ssh-ed25519 AAAA essai'
    assert fenetre.dialogue_ligne.windowTitle() == CATALOGUE.libelle('ui_ligne_cle_titre')


def test_erreur_de_cle_traduite(application):
    def lire(chemin):
        raise ErreurCle('ui_cle_illisible')

    f = Fenetre(CONFIG, CATALOGUE, None, lire, barre_taches=False)
    f.controleur.afficher_ligne_cle()
    assert f.dialogue_ligne is None
    assert f.dernier_message.text() == CATALOGUE.libelle('ui_cle_illisible')
    f.close()


def test_fermeture_de_la_fenetre(fenetre):
    fenetre.close()
    assert fenetre.controleur.etat is Etat.FERMEE
    fenetre.close()


URL_V6 = 'https://[2001:db8::1]:8443'


def attendre(liste, delai_ms=5000):
    for _ in range(delai_ms // 50):
        if liste:
            return
        QTest.qWait(50)


def fenetre_pour(url):
    config = {'connexion': {'url': url}, 'cle': CONFIG['cle']}
    return Fenetre(config, CATALOGUE, lambda admin, ecouteur: None, lire_ok, barre_taches=False)


def test_cookie_sans_domaine_autres_attributs():
    cookie = creer_cookie('jeton-d-essai')
    assert cookie.domain() == ''
    assert cookie.isSecure() and cookie.isHttpOnly() and cookie.path() == '/'
    assert cookie.sameSitePolicy() == QNetworkCookie.SameSite.Strict
    assert cookie.isSessionCookie()


def test_ipv6_litterale(application):
    f = fenetre_pour(URL_V6)
    try:
        assert navigation(f.page, URL_V6 + '/admin/') is True
        for refusee in ('https://[2001:db8::2]:8443/', 'https://[2001:db8::1]:9443/',
                        'https://[2001:db8::1]/', 'http://[2001:db8::1]:8443/'):
            f.dernier_message = None
            assert navigation(f.page, refusee) is False, refusee
            f.dernier_message.done(0)
    finally:
        f.close()


def test_depot_et_effacement_du_cookie(application):
    f = fenetre_pour(URL_V6)
    magasin = f.profil.cookieStore()
    ajoutes, retires = [], []
    magasin.cookieAdded.connect(lambda c: ajoutes.append((c.name().data(), c.domain())))
    magasin.cookieRemoved.connect(lambda c: retires.append(c.name().data()))
    f.page.setHtml('<p></p>')
    QTest.qWait(1500)
    magasin.loadAllCookies()
    QTest.qWait(500)
    try:
        f._deposer_cookie('jeton-d-essai')
        attendre(ajoutes)
        assert ajoutes, 'cookie non déposé'
        assert ajoutes[0][0] == b'admin_token'
        # lié à l'hôte de l'origine : valeur sans point initial
        assert ajoutes[0][1] == '[2001:db8::1]'
        f._effacer_cookie()
        attendre(retires)
        assert retires, 'cookie non effacé'
    finally:
        f.close()


@pytest.fixture
def protection_exceptions(fenetre):
    anciens = sys.excepthook, threading.excepthook
    faulthandler.dump_traceback_later(30, exit=True)
    try:
        yield fenetre
    finally:
        fenetre.restaurer_exceptions()
        sys.excepthook, threading.excepthook = anciens
        faulthandler.cancel_dump_traceback_later()


@pytest.mark.parametrize('permanente', [False, True])
def test_exception_slot_differee(protection_exceptions, permanente, monkeypatch):
    f = protection_exceptions
    effacements, traitements, boites = [], [], []
    montrer = f._montrer_erreur
    def montrer_comptee(texte):
        boites.append(texte)
        return montrer(texte)
    monkeypatch.setattr(f, '_montrer_erreur', montrer_comptee)
    def panne():
        if permanente or not effacements:
            raise RuntimeError('message confidentiel')
    f._pont.sig_effacer.connect(panne)
    f._pont.sig_effacer.connect(lambda: effacements.append(True))
    f._pont.sig_exception.connect(lambda: traitements.append(True), Qt.ConnectionType.QueuedConnection)
    f.garder_exceptions()
    try:
        f.controleur.fermer_administration()
        QTest.qWait(200)
        assert effacements
        assert f.dernier_message.text() == CATALOGUE.erreur('internal_error')
        assert f.etat_affiche == Etat.FERMEE
        assert f._exception_en_attente is False
        assert len(traitements) == len(boites) == 1
        # Une seconde exception pendant la boîte ne crée pas une autre boîte.
        f._crochet(RuntimeError, RuntimeError('autre'), None)
        QTest.qWait(100)
        assert len(boites) == 1
        f.dernier_message.done(0)
        assert f._erreur_interne_ouverte is False
    finally:
        f._pont.sig_effacer.disconnect(panne)


def test_exception_controleur_efface_cookie(protection_exceptions, monkeypatch):
    f = protection_exceptions
    effacements = []
    def panne():
        raise RuntimeError('message confidentiel')
    monkeypatch.setattr(f.controleur, 'fermer_administration', panne)
    monkeypatch.setattr(f, '_effacer_cookie', lambda: effacements.append(True))
    f.garder_exceptions()
    f._crochet(RuntimeError, RuntimeError('message confidentiel'), None)
    QTest.qWait(100)
    assert effacements == [True]
    assert f.dernier_message.text() == CATALOGUE.erreur('internal_error')
    assert not f._exception_en_attente


def test_exception_autre_fil(protection_exceptions):
    f = protection_exceptions
    arrivees = []
    f._pont.sig_exception.connect(lambda: arrivees.append(True), Qt.ConnectionType.QueuedConnection)
    def panne():
        raise RuntimeError('message confidentiel')
    f.garder_exceptions()
    fil = threading.Thread(target=panne)
    fil.start()
    fil.join(timeout=2)
    assert not fil.is_alive()
    attendre(arrivees)
    assert arrivees
    assert f.dernier_message.text() == CATALOGUE.erreur('internal_error')
    assert not f._exception_en_attente


def test_exception_diagnostic_sans_valeur(protection_exceptions, capsys):
    f = protection_exceptions
    f.garder_exceptions()
    f._crochet(RuntimeError, RuntimeError('message confidentiel'), None)
    assert capsys.readouterr().err == '<3>RuntimeError\n'
    QTest.qWait(100)


@pytest.mark.parametrize('type_', [KeyboardInterrupt, SystemExit])
def test_exception_interruption_deleguee(protection_exceptions, monkeypatch, type_):
    f = protection_exceptions
    appels = []
    monkeypatch.setattr(sys, 'excepthook', lambda *args: appels.append(args))
    f.garder_exceptions()
    valeur = type_()
    f._crochet(type_, valeur, None)
    QTest.qWait(100)
    assert appels == [(type_, valeur, None)]
    assert f.dernier_message is None


def test_restauration_crochets(protection_exceptions):
    f = protection_exceptions
    anciens = sys.excepthook, threading.excepthook
    f.restaurer_exceptions()
    assert (sys.excepthook, threading.excepthook) == anciens
    f.garder_exceptions()
    f.garder_exceptions()
    f.restaurer_exceptions()
    assert (sys.excepthook, threading.excepthook) == anciens
    f.garder_exceptions()
    f.close()
    assert (sys.excepthook, threading.excepthook) == anciens
