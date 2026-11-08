# SPDX-License-Identifier: AGPL-3.0-or-later
# Fenêtre principale du poste client : vue web en profil privé, indicateur d'état,
# ligne à remettre ; dépendances : PyQt6, QtWebEngine ; bibliothèque standard.
# Suivi des versions
#   0.1.19  2026-11-08  Exceptions des slots : crochet différé, une seule boîte, cookie effacé.
#   0.1.14  2026-11-08  Fenêtre principale, cookie du jeton, navigation restreinte, indicateur ;
#                       fermeture toujours acceptée, une seule boîte de refus à la fois ;
#                       cookie lié à l'hôte, sans domaine.
import re
import sys
import threading

from PyQt6.QtCore import QObject, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PyQt6.QtNetwork import QNetworkCookie
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (QDialog, QLabel, QLineEdit, QMainWindow, QMessageBox,
                             QSystemTrayIcon, QVBoxLayout, QWidget)

from .controleur import NOM_COOKIE, Controleur, navigation_autorisee
from .presence import Etat
from .textes import afficher

COULEURS = {Etat.FERMEE: '#808080', Etat.OUVERTE: '#2e9e44', Etat.PERDUE: '#c0392b'}
TAILLE_ICONE = 32
ADRESSE_VIDE = 'about:blank'
PRIORITE_ERREUR = '<3>'


def icone(etat):
    """Pastille dessinée en mémoire, une couleur par état."""
    carte = QPixmap(TAILLE_ICONE, TAILLE_ICONE)
    carte.fill(QColor(0, 0, 0, 0))
    peintre = QPainter(carte)
    peintre.setRenderHint(QPainter.RenderHint.Antialiasing)
    peintre.setBrush(QColor(COULEURS[etat]))
    peintre.setPen(QColor('#202020'))
    peintre.drawEllipse(3, 3, TAILLE_ICONE - 6, TAILLE_ICONE - 6)
    peintre.end()
    return QIcon(carte)


def creer_cookie(jeton):
    """admin_token : lié au seul hôte de l'origine déposée (aucun domaine), Secure, HttpOnly,
    SameSite=Strict, chemin /, sans expiration."""
    cookie = QNetworkCookie(NOM_COOKIE.encode('ascii'), jeton.encode('ascii'))
    cookie.setSecure(True)
    cookie.setHttpOnly(True)
    cookie.setSameSitePolicy(QNetworkCookie.SameSite.Strict)
    cookie.setPath('/')
    return cookie


class PageRestreinte(QWebEnginePage):
    """N'accepte que l'origine configurée ; aucune surcharge de certificateError."""

    def __init__(self, profil, base, refus, parent=None):
        super().__init__(profil, parent)
        self._base = base
        self._refus = refus
        self._vide_attendu = False

    def attendre_vide(self):
        """Autorise une seule navigation principale vers l'adresse de vidage."""
        self._vide_attendu = True

    def acceptNavigationRequest(self, url, type_, est_principale):
        adresse = url.toString()
        if navigation_autorisee(adresse, self._base):
            return True
        if self._vide_attendu and est_principale and adresse == ADRESSE_VIDE:
            self._vide_attendu = False
            return True
        self._refus()
        return False


class Pont(QObject):
    """Surface du contrôleur : chaque appel devient un signal vers le fil de l'interface."""

    sig_cookie = pyqtSignal(str)
    sig_effacer = pyqtSignal()
    sig_exception = pyqtSignal()
    sig_charger = pyqtSignal(str)
    sig_vide = pyqtSignal()
    sig_etat = pyqtSignal(object, str)
    sig_rouvrir = pyqtSignal(str)
    sig_ligne = pyqtSignal(str)
    sig_erreur = pyqtSignal(str)

    def deposer_cookie(self, jeton):
        self.sig_cookie.emit(jeton)

    def effacer_cookie(self):
        self.sig_effacer.emit()

    def charger(self, url):
        self.sig_charger.emit(url)

    def charger_vide(self):
        self.sig_vide.emit()

    def indiquer(self, etat, texte):
        self.sig_etat.emit(etat, texte)

    def proposer_rouvrir(self, texte):
        self.sig_rouvrir.emit(texte)

    def montrer_ligne(self, texte):
        self.sig_ligne.emit(texte)

    def erreur(self, texte):
        self.sig_erreur.emit(texte)


class Fenetre(QMainWindow):
    def __init__(self, config, catalogue, fabrique_session, lire_cle, *, barre_taches=None):
        super().__init__()
        self._catalogue = catalogue
        self._url = config['connexion']['url']
        self._titre = catalogue.libelle('ui_app_titre')
        self.dialogue_ligne = None
        self.champ_ligne = None
        self.etat_affiche = Etat.FERMEE
        self.dernier_message = None
        self._icone_barre = None
        self._refus_ouvert = False
        self._exception_en_attente = False
        self._verrou_exception = threading.Lock()
        self._crochets = None
        self._erreur_interne_ouverte = False
        self._pont = Pont(self)
        self._pont.sig_exception.connect(self._apres_exception, Qt.ConnectionType.QueuedConnection)
        self.controleur = Controleur(config, catalogue, fabrique_session, lire_cle,
                                     surface=self._pont)

        self.profil = QWebEngineProfile()
        self.profil.downloadRequested.connect(lambda requete: requete.cancel())
        self.page = PageRestreinte(self.profil, self._url, self._navigation_refusee, self)
        self.vue = QWebEngineView(self)
        self.vue.setPage(self.page)
        self.etiquette = QLabel(self)
        self.etiquette.setTextFormat(Qt.TextFormat.PlainText)
        centre = QWidget(self)
        disposition = QVBoxLayout(centre)
        disposition.addWidget(self.etiquette)
        disposition.addWidget(self.vue)
        self.setCentralWidget(centre)

        menu = self.menuBar().addMenu(self._titre)
        self.action_ouvrir = self._action(menu, 'ui_menu_ouvrir', self._lancer_ouverture)
        self.action_fermer = self._action(menu, 'ui_menu_fermer',
                                          self.controleur.fermer_administration)
        self.action_ligne = self._action(menu, 'ui_menu_ligne_cle',
                                         self.controleur.afficher_ligne_cle)
        self.action_quitter = self._action(menu, 'ui_menu_quitter', self.close)

        pont = self._pont
        pont.sig_cookie.connect(self._deposer_cookie)
        pont.sig_effacer.connect(self._effacer_cookie)
        pont.sig_charger.connect(self._charger)
        pont.sig_vide.connect(self._charger_vide)
        pont.sig_etat.connect(self._indiquer)
        pont.sig_rouvrir.connect(self._proposer_rouvrir)
        pont.sig_ligne.connect(self._montrer_ligne)
        pont.sig_erreur.connect(self._montrer_erreur)

        if barre_taches is None:
            barre_taches = QSystemTrayIcon.isSystemTrayAvailable()
        if barre_taches:
            self._icone_barre = QSystemTrayIcon(self)
            self._icone_barre.show()
        self._indiquer(Etat.FERMEE, catalogue.libelle('ui_etat_fermee'))

    def _action(self, menu, cle, rappel):
        action = QAction(self._catalogue.libelle(cle), self)
        action.triggered.connect(lambda _coche=False: rappel())
        menu.addAction(action)
        return action

    # ---- actions -------------------------------------------------------

    def _lancer_ouverture(self):
        """L'ouverture est bloquante : elle se fait hors du fil de l'interface."""
        threading.Thread(target=self.controleur.ouvrir_administration, daemon=True).start()

    def closeEvent(self, evenement):
        try:
            self.controleur.quitter()
            if self._icone_barre is not None:
                self._icone_barre.hide()
        finally:
            self.restaurer_exceptions()
            super().closeEvent(evenement)

    def garder_exceptions(self):
        """Installer les crochets une seule fois, en conservant ceux de l'appelant."""
        if self._crochets is None:
            self._crochets = sys.excepthook, threading.excepthook
            sys.excepthook = self._crochet
            threading.excepthook = self._crochet_fil

    def restaurer_exceptions(self):
        if self._crochets is not None:
            sys.excepthook, threading.excepthook = self._crochets
            self._crochets = None

    def _crochet(self, type_, valeur, trace):
        if issubclass(type_, (KeyboardInterrupt, SystemExit)):
            if self._crochets is not None:
                self._crochets[0](type_, valeur, trace)
            return
        self._signaler_exception(type_)

    def _crochet_fil(self, args):
        if issubclass(args.exc_type, (KeyboardInterrupt, SystemExit)):
            if self._crochets is not None:
                self._crochets[1](args)
            return
        self._signaler_exception(args.exc_type)

    def _signaler_exception(self, type_):
        nom = type_.__name__
        if not re.fullmatch(r'[A-Za-z0-9_]{1,64}', nom):
            nom = '?'
        try:
            print(f'{PRIORITE_ERREUR}{nom}', file=sys.stderr)
        except (OSError, ValueError):
            pass  # Un diagnostic indisponible ne doit pas empêcher la fermeture sûre.
        with self._verrou_exception:
            if self._exception_en_attente:
                return
            self._exception_en_attente = True
        try:
            self._pont.sig_exception.emit()
        except RuntimeError:
            pass  # Le destinataire peut avoir été détruit pendant la fermeture.

    def _apres_exception(self):
        try:
            try:
                self.controleur.fermer_administration()
            except Exception:
                # La fermeture sûre ne dépend pas d'un contrôleur qui peut lever.
                try:
                    self._effacer_cookie()
                except Exception:
                    pass
            try:
                if not self._erreur_interne_ouverte:
                    self._erreur_interne_ouverte = True
                    boite = self._montrer_erreur(self._catalogue.erreur('internal_error'))
                    boite.finished.connect(self._liberer_erreur_interne)
            except Exception:
                # Une panne de l'affichage ne doit pas sortir du slot de secours.
                self._erreur_interne_ouverte = False
        finally:
            with self._verrou_exception:
                self._exception_en_attente = False

    def _liberer_erreur_interne(self, _code=0):
        self._erreur_interne_ouverte = False

    # ---- surface (fil de l'interface) -----------------------------------

    def _deposer_cookie(self, jeton):
        self.profil.cookieStore().setCookie(creer_cookie(jeton), QUrl(self._url))

    def _effacer_cookie(self):
        self.profil.cookieStore().deleteAllCookies()

    def _charger(self, url):
        self.vue.setUrl(QUrl(url))

    def _charger_vide(self):
        self.page.attendre_vide()
        self.vue.setUrl(QUrl(ADRESSE_VIDE))

    def _indiquer(self, etat, texte):
        texte = afficher(texte)
        self.setWindowTitle(f'{self._titre} : {texte}')
        self.etiquette.setText(texte)
        self.etat_affiche = etat
        pastille = icone(etat)
        self.setWindowIcon(pastille)
        if self._icone_barre is not None:
            self._icone_barre.setIcon(pastille)
            self._icone_barre.setToolTip(texte)

    def _navigation_refusee(self):
        """Une seule boîte de refus à la fois ; la navigation reste refusée."""
        if self._refus_ouvert:
            return
        self._refus_ouvert = True
        boite = self._montrer_erreur(self._catalogue.libelle('ui_navigation_refusee'))
        boite.finished.connect(lambda _code=0: self._liberer_refus())

    def _liberer_refus(self):
        self._refus_ouvert = False

    def _message(self, texte):
        boite = QMessageBox(self)
        boite.setWindowTitle(self._titre)
        boite.setTextFormat(Qt.TextFormat.PlainText)
        boite.setText(afficher(texte))
        return boite

    def _montrer_erreur(self, texte):
        boite = self._message(texte)
        boite.setIcon(QMessageBox.Icon.Warning)
        self.dernier_message = boite
        boite.open()
        return boite

    def _proposer_rouvrir(self, texte):
        boite = self._message(texte)
        boite.setIcon(QMessageBox.Icon.Question)
        ouvrir = boite.addButton(self._catalogue.libelle('ui_menu_ouvrir'),
                                 QMessageBox.ButtonRole.AcceptRole)
        ouvrir.clicked.connect(lambda _coche=False: self._lancer_ouverture())
        boite.addButton(QMessageBox.StandardButton.Close)
        self.dernier_message = boite
        boite.open()

    def _montrer_ligne(self, texte):
        dialogue = QDialog(self)
        dialogue.setWindowTitle(self._catalogue.libelle('ui_ligne_cle_titre'))
        champ = QLineEdit(afficher(texte), dialogue)
        champ.setReadOnly(True)
        champ.setMinimumWidth(640)
        disposition = QVBoxLayout(dialogue)
        disposition.addWidget(champ)
        self.dialogue_ligne = dialogue
        self.champ_ligne = champ
        dialogue.show()
