# SPDX-License-Identifier: AGPL-3.0-or-later
# Point d'entrée de l'application de bureau (python -m admin.app [--config <fichier>]) ;
# dépendances : PyQt6, QtWebEngine ; bibliothèque standard.
# Suivi des versions
#   0.1.19  2026-11-08  Installation des crochets d’exception avant la boucle graphique.
#   0.1.14  2026-11-08  Chargement de la configuration, du catalogue et lancement de la fenêtre.
from pathlib import Path
import sys

from server.commun.config import ErreurConfiguration

from .cles import lire_cle_publique
from .config import configuration
from .presence import SessionPresence
from .textes import Catalogue, afficher, charger

DOSSIER_I18N_SOURCES = Path(__file__).resolve().parents[2] / 'i18n'


def _catalogue_erreur():
    """Libellé de secours quand la configuration, donc la langue, est inconnue."""
    try:
        return charger('fr-FR', DOSSIER_I18N_SOURCES)
    except ValueError:
        return Catalogue({})


def _refuser(catalogue, detail=''):
    message = catalogue.libelle('ui_config_invalide')
    if detail:
        message = f'{message} : {afficher(detail)}'
    print(message, file=sys.stderr)
    return 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        config = configuration(argv)
    except ErreurConfiguration as erreur:
        return _refuser(_catalogue_erreur(),
                        '.'.join(p for p in (erreur.section, erreur.cle) if p))
    try:
        catalogue = charger(config['interface']['langue'], config['interface']['dossier_i18n'])
    except ValueError:
        return _refuser(_catalogue_erreur(), 'interface.dossier_i18n')

    from PyQt6.QtWidgets import QApplication

    from .fenetre import Fenetre

    connexion, cle, presence = config['connexion'], config['cle'], config['presence']

    def fabrique(admin, ecouteur):
        return SessionPresence(connexion['ssh'], connexion['hote_ssh'], connexion['compte_ssh'],
                               cle['cle_publique'], presence['ouverture_s'], admin=admin,
                               ssh_keygen=cle['ssh_keygen'], ecouteur=ecouteur)

    application = QApplication([sys.argv[0]])
    fenetre = Fenetre(config, catalogue, fabrique, lire_cle_publique)
    application.lastWindowClosed.connect(fenetre.controleur.quitter)
    fenetre.garder_exceptions()
    fenetre.show()
    return application.exec()


if __name__ == '__main__':
    sys.exit(main())
