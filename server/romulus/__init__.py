# SPDX-License-Identifier: AGPL-3.0-or-later
# Assemblage de Romulus ; dépendances : bibliothèque standard et server.commun.
# Suivi des versions
#   0.1.15  2026-11-08  Domaine kernel, journal d'activité, sections activite et noyau.
#   0.1.8  2026-11-07  Schéma et aiguillage assemblés à partir des déclarations de services ; section plugins (D148, D150, D154).
#   0.1.1  2026-11-07  Sections journal et métriques transmises au chargeur.
#   3.0.0-alpha.41  2026-11-06  Option flux_max_simultanes (D85, D111).
#   3.0.0-alpha.41  2026-11-06  Sections bunker et relay, enregistrement de l'aiguillage (T038, D10, D57).
#   3.0.0-alpha.32  2026-11-06  Limites de taille et de concurrence des exports (T013).
#   3.0.0-alpha  2026-11-05  Configuration et cycle de vie des deux sockets.
#   3.0.0-alpha  2026-11-05  Options de plafonds : sessions, connexions HTTP, échéance, en-têtes.
import ipaddress
import os
import re

from server.commun import services
from server.commun.config import ErreurConfiguration, Option, lire
from server.commun.journal import Journal
from .activite import Activite, dossier_activite
from .aiguillage import Aiguillage
from .http import PREFIXE_API, FrontalHTTP
from .noyau import ACTIONS as ACTIONS_NOYAU, MARQUES, Noyau
from .presence import Presence
from .sessions import Sessions

SCHEMA = {
    ('presence', 'socket'): Option('chemin'),
    ('presence', 'uid_pollux'): Option('uid'),
    ('presence', 'gid'): Option('uid'),
    ('presence', 'timeout_s'): Option('duree', 30),
    ('presence', 'max_line'): Option('limite', 1048576),
    ('presence', 'max_connexions'): Option('limite', 64),
    ('presence', 'max_sessions'): Option('limite', 1024),
    ('http', 'socket'): Option('chemin'),
    ('http', 'uid_lighttpd'): Option('uid'),
    ('http', 'gid'): Option('uid'),
    ('http', 'timeout_s'): Option('duree', 30),
    ('http', 'max_body'): Option('limite', 65536),
    ('http', 'export_max_octets'): Option('limite', 8388608),
    ('http', 'export_max_simultanes'): Option('limite', 2),
    ('http', 'max_connexions'): Option('limite', 64),
    ('http', 'read_deadline_s'): Option('duree', 30),
    ('http', 'max_headers'): Option('limite', 100),
    ('http', 'max_header_bytes'): Option('limite', 16384),
    ('http', 'client_ip_header'): Option('texte'),
    ('http', 'fallback_ip'): Option('texte'),
    # Journal d'activité (qui fait quoi) et domaine d'administration du noyau.
    ('activite', 'detail'): Option('limite', 1),
    ('activite', 'taille_max'): Option('limite', 1048576),
    ('activite', 'dossier'): Option('chemin', facultatif=True),
    ('activite', 'regroupement_max'): Option('limite', 100000),
    ('activite', 'regroupements_simultanes'): Option('limite', 64),
    ('noyau', 'dossier_etat'): Option('chemin', facultatif=True),
    # Dossiers des déclarations de services : livrées et locales (valeurs par défaut documentées
    # dans server.commun.services). Les options de chaque service viennent de sa déclaration.
    ('plugins', 'livrees'): Option('chemin', facultatif=True),
    ('plugins', 'locales'): Option('chemin', facultatif=True),
}


SCHEMA_PLUGINS = {key: value for key, value in SCHEMA.items() if key[0] == 'plugins'}


def declarations(config, journal=None, chargeur=None):
    """Charge les déclarations de services selon `[romulus.plugins]` ; ErreurConfiguration sinon.

    chargeur : paramètres d'injection (livrees, locales, proprietaires, racine_confiance),
    utilisés seulement quand l'option correspondante n'est pas configurée. Une déclaration
    livrée défectueuse refuse le démarrage (code stable, sans nom de fichier).
    """
    chargeur = chargeur or {}
    brut = config.get('plugins') or {}
    livrees = brut.get('livrees') or chargeur.get('livrees') or services.DOSSIER_LIVRE
    locales = brut.get('locales') or chargeur.get('locales') or services.DOSSIER_LOCAL
    rappel = None
    if journal is not None:
        def rappel(evenement, niveau, **champs):
            journal.ecrire(niveau, evenement, **champs)
    try:
        return services.charger(
            livrees, locales, proprietaires=chargeur.get('proprietaires', frozenset({0})),
            racine_confiance=chargeur.get('racine_confiance', '/'), rappel=rappel)
    except services.ErreurService as erreur:
        raise ErreurConfiguration(erreur.code, 'plugins', 'livrees') from None


def schema_complet(declares):
    """Schéma du démon : socle, plus les sections de chaque service déclaré."""
    return {**SCHEMA, **declares.schema()}


def configuration(*, argv=None, environ=None, chargeur=None, **options):
    options = {'journal': True, 'metriques': True, **options}
    communes = {cle: valeur for cle, valeur in options.items()
                if cle not in ('journal', 'metriques')}
    # Premier temps : seules les options des dossiers de déclarations, le reste est ignoré.
    base = lire('romulus', SCHEMA_PLUGINS, argv=argv, environ=environ, partielle=True, **communes)
    declares = declarations(base, None, chargeur)
    resultat = lire('romulus', schema_complet(declares), argv=argv, environ=environ, **options)
    http, presence = resultat['http'], resultat['presence']
    if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}", http['client_ip_header']):
        raise ErreurConfiguration('config_invalid', 'http', 'client_ip_header')
    try:
        http['fallback_ip'] = str(ipaddress.ip_address(http['fallback_ip']))
    except ValueError:
        raise ErreurConfiguration('config_invalid', 'http', 'fallback_ip') from None
    if presence['max_connexions'] > 1024:
        raise ErreurConfiguration('config_invalid', 'presence', 'max_connexions')
    if http['max_connexions'] > 1024:
        raise ErreurConfiguration('config_invalid', 'http', 'max_connexions')
    for cle, (minimum, maximum) in {'detail': (1, 3), 'taille_max': (65536, 16777216),
                                    'regroupement_max': (1, 1000000),
                                    'regroupements_simultanes': (1, 1024)}.items():
        if not minimum <= resultat['activite'][cle] <= maximum:
            raise ErreurConfiguration('config_invalid', 'activite', cle)
    services.verifier_options(declares, resultat)
    if presence['socket'] == http['socket']:
        raise ErreurConfiguration('config_invalid', 'http', 'socket')
    return resultat


class Romulus:
    def __init__(self, config, *, journal=None, chargeur=None, environ=None, confiance=None):
        """Les déclarations de services sont chargées avant toute écoute. chargeur : injection
        des dossiers et du contrôle de propriété (tests). confiance : injection pour le journal
        d'activité et le domaine kernel (proprietaires, racine_confiance, racine_systeme,
        horloge, monotone, version) ; environ remplace os.environ."""
        self.journal = journal if journal is not None else Journal('romulus')
        confiance = dict(confiance or {})
        environ = os.environ if environ is None else environ
        self.activite = None
        options = config.get('activite')
        if options is not None:
            dossier = dossier_activite(options, environ)
            if dossier is None:
                self.journal.ecrire('error', 'activity_unusable', code='activity_dir_missing')
            else:
                self.activite = Activite(
                    dossier, options, self.journal,
                    proprietaires=confiance.get('proprietaires'),
                    racine_confiance=confiance.get('racine_confiance', '/'),
                    **{c: confiance[c] for c in ('horloge', 'monotone') if c in confiance})
        self.sessions = Sessions(self.journal, config['presence']['max_sessions'], self.activite)
        presence = config['presence']
        self.presence = Presence(
            presence['socket'], {presence['uid_pollux']},
            {'presence/session/open', 'presence/session/close'}, self.sessions.traiter,
            gid=presence['gid'], max_line=presence['max_line'],
            delai=presence['timeout_s'], max_connexions=presence['max_connexions'],
            journal=self.journal, fermeture=self.sessions.fermeture)
        declares = declarations(config, self.journal, chargeur)
        self.http = FrontalHTTP(
            config['http'], self.sessions, self.journal,
            chemins={PREFIXE_API + a for a in declares.actions_routables() | ACTIONS_NOYAU},
            exports=declares.exports(), suivis=declares.suivis(), activite=self.activite)
        # Sans la section d'un service (appels directs, tests), aucune destination : 501.
        self.aiguillage = Aiguillage(config, declares, self.journal, activite=self.activite)
        self.http.actions.update(self.aiguillage.actions())
        self.noyau = Noyau(
            config, schema_complet(declares), declares, self.aiguillage, self.sessions,
            self.activite,
            **{c: confiance[c] for c in ('proprietaires', 'racine_confiance', 'racine_systeme',
                                         'horloge', 'monotone', 'version') if c in confiance})
        self.http.actions.update(self.noyau.actions())
        if self.activite is not None:
            self.activite.jumeaux = {
                **{a: s.destination for s in declares.services for a in s.actions_routables()},
                **{a: 'romulus' for a in ACTIONS_NOYAU}}
            self.activite.marques = dict(MARQUES)

    def demarrer(self):
        try:
            if self.activite is not None:
                self.activite.preparer()
            self.presence.demarrer()
            self.http.demarrer()
        except BaseException:
            self.arreter()
            raise
        return self

    def arreter(self):
        self.presence.arreter()
        self.http.arreter()
        if self.activite is not None:
            self.activite.fermer()

    def __enter__(self):
        return self.demarrer()

    def __exit__(self, *_):
        self.arreter()
