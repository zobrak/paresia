# SPDX-License-Identifier: AGPL-3.0-or-later
# Logique du poste client sans interface : ouverture, perte et fermeture de la session,
# cookie, ligne à remettre ; dépendances : bibliothèque standard et admin.app.
# Suivi des versions
#   0.1.14  2026-11-08  Contrôleur de la fenêtre principale : une seule session, cookie, perte ;
#                       fermeture : cookie et vue vidés même si la session échoue.
import threading
from urllib.parse import urlsplit

from .cles import ErreurCle, ligne_authorized_keys
from .presence import ErreurPresence, Etat
from .textes import afficher

NOM_COOKIE = 'admin_token'
PORT_HTTPS = 443


def origine(url):
    """(schéma, hôte, port) d'une adresse, ou None si elle est illisible."""
    try:
        parties = urlsplit(url)
        hote = parties.hostname
        port = parties.port
    except ValueError:
        return None
    if not parties.scheme or not hote:
        return None
    return (parties.scheme.lower(), hote.lower(), port if port is not None else PORT_HTTPS)


def navigation_autorisee(url, base):
    """Même schéma https, même hôte et même port que l'adresse de base."""
    try:
        if '@' in urlsplit(url).netloc:
            return False
    except ValueError:
        return False
    cible, reference = origine(url), origine(base)
    return (cible is not None and cible == reference and cible[0] == 'https')


class Controleur:
    """Une seule session à la fois ; la surface est fournie par la fenêtre.

    Les méthodes peuvent être appelées de n'importe quel fil ; la surface se charge
    du passage vers le fil de l'interface. Aucune méthode de la session n'est appelée
    sous le verrou du contrôleur (l'écouteur de la session le prend). Les séquences
    d'émission vers la surface sont sérialisées par un second verrou ; chacune
    revérifie, sous le premier, que son état est encore le courant.
    """

    def __init__(self, config, catalogue, fabrique_session, lire_cle, *, surface):
        self._config = config
        self._catalogue = catalogue
        self._fabrique = fabrique_session
        self._lire_cle = lire_cle
        self._surface = surface
        self._verrou = threading.Lock()
        self._emission = threading.Lock()
        self._session = None
        self._etat = Etat.FERMEE
        self._ouverture = False
        self._generation = 0
        self._quitte = False

    @property
    def etat(self):
        return self._etat

    def _url(self):
        return self._config['connexion']['url']

    def _signaler(self, etat, cle):
        self._surface.indiquer(etat, self._catalogue.libelle(cle))

    def _echec(self, code):
        self._surface.erreur(self._catalogue.erreur(code))
        self._signaler(Etat.FERMEE, 'ui_etat_fermee')

    # ---- ouverture -----------------------------------------------------

    def ouvrir_administration(self):
        """Bloquante (signature, accord de l'agent) ; vrai si la session est ouverte."""
        with self._verrou:
            if self._quitte or self._ouverture or self._etat is Etat.OUVERTE:
                return False
            self._ouverture = True
            generation = self._generation
            ancienne, self._session = self._session, None
        try:
            if ancienne is not None:
                ancienne.fermer()
            return self._ouvrir(generation)
        except Exception:  # noqa: BLE001 - aucun détail brut n'est affiché
            self._abandonner(generation)
            return False
        finally:
            with self._verrou:
                self._ouverture = False

    def _abandonner(self, generation):
        """Erreur inattendue : session fermée, erreur du catalogue, état libéré."""
        with self._verrou:
            courante = generation == self._generation
            session = self._session if courante else None
            if courante:
                self._session = None
                self._etat = Etat.FERMEE
        if session is not None:
            try:
                session.fermer()
            except Exception:  # noqa: BLE001
                pass
        if courante:
            try:
                with self._emission:
                    try:
                        self._surface.effacer_cookie()
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        self._surface.charger_vide()
                    except Exception:  # noqa: BLE001
                        pass
                    self._echec('internal_error')
            except Exception:  # noqa: BLE001
                pass

    def _ouvrir(self, generation):
        try:
            cle = self._lire_cle(self._config['cle']['cle_publique'])
        except ErreurCle as erreur:
            with self._emission:
                self._echec(erreur.code)
            return False
        try:
            session = self._fabrique(cle.commentaire, self.sur_etat)
        except (ErreurPresence, ValueError):
            with self._emission:
                self._echec('internal_error')
            return False
        with self._verrou:
            perimee = generation != self._generation
            if not perimee:
                self._session = session
        if perimee:
            session.fermer()
            return False
        try:
            session.ouvrir()
        except ErreurPresence as erreur:
            with self._verrou:
                courante = generation == self._generation
                if self._session is session:
                    self._session = None
            if courante:
                with self._emission:
                    with self._verrou:
                        courante = generation == self._generation
                    if courante:
                        self._echec(erreur.code)
            return False
        ouverte = session.etat is Etat.OUVERTE
        jeton = session.jeton() if ouverte else None
        with self._verrou:
            valide = generation == self._generation and self._session is session
            if valide and ouverte and jeton:
                self._etat = Etat.OUVERTE
        if not valide:
            session.fermer()
            return False
        if not (ouverte and jeton):
            self._perdre(session)
            return False
        # Une perte survenue entre la lecture et la pose de OUVERTE a été
        # ignorée par sur_etat : on la rattrape ici, hors verrou.
        if session.etat is not Etat.OUVERTE:
            self._perdre(session)
            return False
        with self._emission:
            with self._verrou:
                encore = (generation == self._generation and self._session is session
                          and self._etat is Etat.OUVERTE)
            if not encore:
                return False
            self._surface.deposer_cookie(jeton)
            self._surface.charger(self._url() + '/admin/')
            self._signaler(Etat.OUVERTE, 'ui_etat_ouverte')
        return True

    # ---- perte ---------------------------------------------------------

    def sur_etat(self, etat, code):
        """Écouteur de la session, appelé depuis son fil de lecture ou de battement."""
        if etat is not Etat.PERDUE:
            return
        with self._verrou:
            if self._etat is not Etat.OUVERTE:
                return
            session = self._session
        self._perdre(session)

    def _perdre(self, session):
        with self._verrou:
            if session is not None and self._session is not session:
                return
            self._etat = Etat.PERDUE
        with self._emission:
            with self._verrou:
                encore = self._etat is Etat.PERDUE and (
                    session is None or self._session is session)
            if not encore:
                return
            self._surface.effacer_cookie()
            self._surface.charger_vide()
            self._signaler(Etat.PERDUE, 'ui_etat_perdue')
            self._surface.proposer_rouvrir(self._catalogue.libelle('ui_proposer_rouvrir'))

    # ---- fermeture -----------------------------------------------------

    def fermer_administration(self):
        """Idempotente ; la session perdue ou en cours d'ouverture est aussi libérée."""
        with self._verrou:
            self._generation += 1
            session, self._session = self._session, None
            self._etat = Etat.FERMEE
        try:
            if session is not None:
                session.fermer()
        except Exception:  # noqa: BLE001 - non propagée : la fermeture de la fenêtre doit aboutir
            pass
        finally:
            with self._emission:
                self._surface.effacer_cookie()
                self._surface.charger_vide()
                self._signaler(Etat.FERMEE, 'ui_etat_fermee')

    def quitter(self):
        with self._verrou:
            self._quitte = True
        self.fermer_administration()

    # ---- ligne à remettre ---------------------------------------------

    def afficher_ligne_cle(self):
        try:
            cle = self._lire_cle(self._config['cle']['cle_publique'])
            ligne = ligne_authorized_keys(cle, self._config['cle']['commande_forcee'])
        except ErreurCle as erreur:
            self._surface.erreur(self._catalogue.erreur(erreur.code))
            return
        self._surface.montrer_ligne(afficher(ligne))
