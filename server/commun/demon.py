# SPDX-License-Identifier: AGPL-3.0-or-later
# Suivi des versions
#   0.1.5  2026-11-07  Réveil périodique du fil principal pour traiter les signaux.
#   0.1.5  2026-11-07  Diagnostic borné et résolution de cadres tolérante aux boucles.
#   0.1.5  2026-11-07  Diagnostic debug limité à la classe et aux cadres du paquet.
#   0.1.2  2026-11-07  Résolution différée de la version dans le démarrage contrôlé.
#   0.1.1  2026-11-07  Erreurs génériques, catalogue localisé et état de service.
#   0.1.1  2026-11-07  Options communes et cycle de vie.
"""Cycle Type=notify (systemd.service(5)), codes de sortie de sysexits.h."""
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path
import signal
import sys
import threading

from . import systemd
from .config import ErreurConfiguration, lire
from .journal import Journal
from .metriques import Collecteur, dossier_configuration
from .texte import filtrer

_INTERVALLE_ATTENTE_SIGNAUX_S = 0.1


def _charger_catalogue(environ):
    """Choisit le catalogue une fois par lancement ; repli sur le français."""
    langue = 'fr-FR'
    for nom in ('LC_ALL', 'LC_MESSAGES', 'LANG'):
        valeur = environ.get(nom)
        if valeur:
            langue = 'en-US' if valeur.lower().startswith('en') else 'fr-FR'
            break
    dossier = Path(__file__).resolve().parents[2] / 'i18n'
    for choix in dict.fromkeys((langue, 'fr-FR')):
        try:
            textes = json.loads((dossier / (choix + '.json')).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(textes, dict):
            return textes
    return {}


def _texte(textes, cle, **valeurs):
    return filtrer(textes.get(cle, cle).format(**valeurs))


def _pile_interne(erreur):
    """Ne lit ni lignes source, ni variables locales, ni messages d'exception.

    Les cadres hors du paquet server sont omis : leurs chemins et noms peuvent
    appartenir à l'installation ou à du code fourni par un appelant.
    """
    paquet = Path(__file__).resolve().parent.parent
    pile = deque(maxlen=16)
    cadre = erreur.__traceback__
    while cadre is not None:
        code = cadre.tb_frame.f_code
        try:
            fichier = Path(code.co_filename).resolve().relative_to(paquet)
        except (ValueError, OSError, RuntimeError):
            pass
        else:
            pile.append((fichier.as_posix(), cadre.tb_lineno, code.co_name))
        cadre = cadre.tb_next
    return list(pile)


class ErreurDonnees(ValueError):
    """Base des erreurs de données illisibles ; sortie EX_DATAERR (65).

    Les appelants peuvent en dériver leurs exceptions métier. Leur message
    n'est jamais publié par le socle.
    """


@dataclass(frozen=True)
class Demon:
    """La version peut être un lecteur sans argument, appelé par lancer()."""

    nom: str
    version: str | Callable[[], str]
    schema: dict
    corps: object
    configurer: object = None

    @staticmethod
    def depuis_contexte(Classe):
        def corps(config, journal, cycle):
            with Classe(config, journal=journal):
                cycle.pret()
                cycle.attendre()
            return 0
        return corps


class Cycle:
    def __init__(self, environ, journal, textes=None):
        self.arret = threading.Event()
        self.environ, self.journal = environ, journal
        self._textes = _charger_catalogue(environ) if textes is None else textes
        self.en_service = False

    def pret(self, statut=None):
        self.journal.ecrire('debug', 'notify_open')
        resultat = systemd.pret(_texte(self._textes, 'commun_status_ready') if statut is None else statut,
                                environ=self.environ)
        # Le service est prêt même sans gestionnaire systemd pour recevoir l'avis.
        self.en_service = True
        self.journal.ecrire('debug', 'notify_closed')
        return resultat

    def statut(self, texte):
        self.journal.ecrire('debug', 'notify_open')
        resultat = systemd.statut(texte, environ=self.environ)
        self.journal.ecrire('debug', 'notify_closed')
        return resultat

    def demander_arret(self, *_):
        systemd.arret(environ=self.environ)
        self.arret.set()
        # Le signal ne prend pas le verrou du journal : il peut interrompre ecrire().

    def attendre(self):
        # Un signal reçu par un autre fil ne réveille pas forcément le fil principal.
        while not self.arret.wait(timeout=_INTERVALLE_ATTENTE_SIGNAUX_S):
            pass
        self.journal.ecrire('debug', 'stop_requested')


def lancer(demon, argv=None, environ=None):
    """Lance le démon depuis le fil principal, où sont installés les signaux.

    argv est la liste des options du démon ; None équivaut à une liste vide.
    Le catalogue sélectionné dans environ est chargé une fois pour ce lancement.
    """
    env = os.environ if environ is None else environ
    textes = _charger_catalogue(env)
    arguments = list([] if argv is None else argv)
    config_argv, options = [], set()
    i = 0
    while i < len(arguments):
        arg = arguments[i]
        if arg == '--config' and i + 1 < len(arguments) and not config_argv and arguments[i + 1] and not arguments[i + 1].startswith('--'):
            config_argv = arguments[i:i + 2]
            i += 2
        elif arg in ('--help', '--version', '--check', '--debug'):
            options.add(arg)
            i += 1
        else:
            print(_texte(textes, 'commun_usage', daemon=demon.nom), file=sys.stderr)
            return os.EX_USAGE
    try:
        prefixe = systemd.flux_journal(sys.stdout.fileno(), env)
    except (AttributeError, OSError, ValueError):
        prefixe = False
    journal = Journal(demon.nom, niveau='debug' if '--debug' in options else 'info', prefixe=prefixe)
    collecteur = None
    cycle = None
    precedents = {}
    try:
        version = demon.version() if callable(demon.version) else demon.version
        if '--help' in options or '--version' in options:
            cle = 'commun_help' if '--help' in options else 'commun_version'
            print(_texte(textes, cle, daemon=demon.nom, version=version))
            return 0
        if demon.configurer is None:
            config = lire(demon.nom, demon.schema, argv=config_argv, environ=env, journal=True, metriques=True)
        else:
            config = demon.configurer(argv=config_argv, environ=env)
        journal.definir_niveau('debug' if '--debug' in options else config.get('journal', {}).get('niveau', 'info'))
        for section, valeurs in config.items():
            for option in valeurs:
                journal.ecrire('debug', 'config_read', section=section, option=option)
        metriques = config.get('metriques', {})
        dossier_configuration(metriques, env)
        if '--check' in options:
            return 0
        cycle = Cycle(env, journal, textes)
        for sig in (signal.SIGTERM, signal.SIGINT):
            precedents[sig] = signal.signal(sig, cycle.demander_arret)
        collecteur = Collecteur(demon.nom, version, journal, metriques, env)
        collecteur.demarrer()
        demon.corps(config, journal, cycle)
        return 0
    except Exception as erreur:
        # Ne jamais convertir une exception arbitraire en texte ni publier sa valeur.
        if isinstance(erreur, ErreurConfiguration):
            code, cause = os.EX_CONFIG, erreur.code
        elif isinstance(erreur, OSError):
            code, cause = os.EX_OSERR, 'os_error'
        elif isinstance(erreur, ErreurDonnees):
            code, cause = os.EX_DATAERR, 'data_unreadable'
        else:
            code, cause = os.EX_SOFTWARE, 'internal_error'
        evenement = 'service_failed' if cycle is not None and cycle.en_service else 'startup_failed'
        journal.ecrire('error', evenement, cause=cause,
                       section=erreur.section if isinstance(erreur, ErreurConfiguration) else None,
                       option=erreur.cle if isinstance(erreur, ErreurConfiguration) else None,
                       errno=erreur.errno if isinstance(erreur, OSError) else None)
        if journal.niveau == 'debug':
            journal.ecrire('debug', 'internal_error_detail',
                           classe=type(erreur).__name__[:64], pile=_pile_interne(erreur))
        if sys.stderr.isatty():
            print(_texte(textes, 'commun_' + evenement, daemon=demon.nom), file=sys.stderr)
        return code
    finally:
        if collecteur is not None:
            collecteur.arreter()
        for sig, precedent in precedents.items():
            signal.signal(sig, precedent)
