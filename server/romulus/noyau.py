# SPDX-License-Identifier: AGPL-3.0-or-later
# Domaine d'administration `kernel` servi par Romulus : état, services, métriques, configuration masquée, activité ; dépendances : bibliothèque standard, server.commun.
# Suivi des versions
#   0.1.15  2026-11-08  Première version : lecture seule, aucun secret, aucun privilège.
import math
import os
import re
import time

from server.commun.config import ErreurConfiguration, lire
from server.commun.jumeaux import ErreurProtocole, encoder
from server.commun.plugins import (ErreurPlugin, ouvrir_dossier_confiance,
                                   ouvrir_fichier_controle)
from server.commun.texte import filtrer
from server.commun.version import lire_version
from .activite import ActiviteInutilisable

DOMAINE = 'kernel'
ACTIONS = frozenset({'kernel/state/status', 'kernel/state/services', 'kernel/state/metrics',
                     'kernel/state/config', 'kernel/activity/list'})
# Paramètres dont la valeur peut être journalisée (niveau 3) : aucun n'est secret.
MARQUES = {
    'kernel/state/metrics': frozenset({'daemon'}),
    'kernel/state/config': frozenset({'daemon'}),
    'kernel/activity/list': frozenset({'limit', 'level', 'domain'}),
}
# Démons du noyau (liste fermée) et unité de chacun.
DEMONS = {'pollux': 'pollux.service', 'pollux-session': '', 'romulus': 'romulus.service'}
DOSSIER_ETAT_DEFAUT = '/var/lib'
METRIQUES_MAX_OCTETS = 256 * 1024
ECHANTILLONS_MAX = 500
ETIQUETTES_MAX = 16
TEXTE_MAX = 128
REPONSE_MAX = 1024 * 1024
TYPES_PUBLICS = frozenset({'duree', 'limite', 'niveau', 'booleen', 'uid'})
# Clés de type texte, chemin ou compte dont la valeur peut être publiée.
CLES_PUBLIQUES = frozenset({'client_ip_header', 'fallback_ip', 'namespace'})
FRAGMENTS_SECRETS = ('secret', 'passphrase', 'password', 'token', 'jeton', 'key', 'cle')
_NOM_METRIQUE = re.compile(r'[a-zA-Z_:][a-zA-Z0-9_:]{0,127}\Z')
_ECHANTILLON = re.compile(
    r'([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(.*)\})?[ \t]+([^ \t]+)(?:[ \t]+-?[0-9]+)?\Z')
_ETIQUETTE = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]{0,63})="((?:[^"\\]|\\.)*)"(?:,|\Z)')
_MOTIF_DOMAINE = re.compile(r'[a-z][a-z0-9_]{0,31}\Z')
_CATALOGUES = {'aucun': 'none', 'declaration': 'declaration', 'pair': 'pair'}


def _vide(params):
    if params != {}:
        raise ErreurProtocole('bad_request')


def _demon(params):
    if set(params) != {'daemon'} or params['daemon'] not in DEMONS:
        raise ErreurProtocole('bad_request')
    return params['daemon']


def _entier_borne(valeur, minimum, maximum):
    return type(valeur) is int and minimum <= valeur <= maximum


def _valeur_publiable(valeur):
    if isinstance(valeur, str):
        return filtrer(valeur)[:256]
    if isinstance(valeur, float) and not math.isfinite(valeur):
        return None
    return valeur


def masquee(cle, type_option):
    """Échec fermé : publiée seulement si le type est sûr ou la clé en liste blanche."""
    if any(fragment in cle.lower() for fragment in FRAGMENTS_SECRETS):
        return True
    return type_option not in TYPES_PUBLICS and cle not in CLES_PUBLIQUES


def analyser_metriques(octets):
    """Échantillons du format texte Prometheus 0.0.4 ; toute ligne hors forme est ignorée."""
    resultat = []
    for ligne in octets.decode('utf-8', 'replace').split('\n'):
        ligne = ligne.rstrip('\r')
        if not ligne or ligne.startswith('#'):
            continue
        trouve = _ECHANTILLON.match(ligne)
        if trouve is None:
            continue
        nom, brutes, texte = trouve.groups()
        if not _NOM_METRIQUE.match(nom):
            continue
        etiquettes, reste = {}, brutes or ''
        valide = True
        while reste:
            une = _ETIQUETTE.match(reste)
            if une is None or len(etiquettes) >= ETIQUETTES_MAX:
                valide = False
                break
            valeur = (une.group(2).replace('\\n', '\n').replace('\\"', '"')
                      .replace('\\\\', '\\'))
            etiquettes[une.group(1)] = filtrer(valeur)[:TEXTE_MAX]
            reste = reste[une.end():]
        if not valide:
            continue
        try:
            nombre = float(texte)
        except ValueError:
            continue
        if not math.isfinite(nombre):
            continue
        if nombre.is_integer() and abs(nombre) < 2**53:
            nombre = int(nombre)
        resultat.append({'name': nom, 'labels': etiquettes, 'value': nombre})
        if len(resultat) >= ECHANTILLONS_MAX:
            break
    return resultat


class Noyau:
    """Les cinq actions du domaine `kernel`, en lecture seule.

    config : configuration effective de Romulus ; schema : son schéma complet ; declares :
    déclarations de services ; aiguillage : destinations configurées ; activite : journal
    d'activité (ou None). Aucune action ne publie de chemin, de compte, de socket ni de secret.
    """

    def __init__(self, config, schema, declares, aiguillage, sessions, activite, *,
                 proprietaires=None, racine_confiance='/', racine_systeme=None,
                 horloge=time.time, monotone=time.monotonic, version=lire_version):
        self.config, self.schema, self.declares = config, schema, declares
        self.aiguillage, self.sessions, self.activite = aiguillage, sessions, activite
        self.dossier_etat = (config.get('noyau') or {}).get('dossier_etat') or DOSSIER_ETAT_DEFAUT
        pollux = (config.get('presence') or {}).get('uid_pollux')
        base = {0, os.geteuid()} if proprietaires is None else set(proprietaires)
        if pollux is not None and proprietaires is None:
            base.add(pollux)
        self.proprietaires = frozenset(base)
        self.racine_confiance, self.racine_systeme = racine_confiance, racine_systeme
        self.horloge, self.version = horloge, version
        self._debut = monotone()
        self._monotone = monotone

    def actions(self):
        return {'kernel/state/status': lambda p, s: self._status(p),
                'kernel/state/services': lambda p, s: self._services(p),
                'kernel/state/metrics': lambda p, s: self._metriques(p),
                'kernel/state/config': lambda p, s: self._configuration(p),
                'kernel/activity/list': lambda p, s: self._activite(p)}

    @staticmethod
    def _reponse(data):
        if len(encoder({'ok': True, 'data': data})) > REPONSE_MAX:
            raise ErreurProtocole('internal_error')
        return {'ok': True, 'data': data}

    # -- métriques ------------------------------------------------------------------------

    def _fichier_metriques(self, demon):
        """(état, octets, âge) ; état : enabled, disabled ou unreadable."""
        chemin = os.path.join(self.dossier_etat, 'paresia-' + demon, 'metriques')
        try:
            dossier = ouvrir_dossier_confiance(chemin, self.racine_confiance, self.proprietaires)
        except ErreurPlugin:
            return 'unreadable', b'', None
        if dossier is None:
            return 'disabled', b'', None
        try:
            try:
                fd = ouvrir_fichier_controle(demon + '.prom', dossier, self.proprietaires)
            except ErreurPlugin as erreur:
                return ('disabled' if erreur.code == 'plugin_incomplete' else 'unreadable'), b'', None
            try:
                attributs = os.fstat(fd)
                if attributs.st_size > METRIQUES_MAX_OCTETS:
                    return 'unreadable', b'', None
                donnees = b''
                while len(donnees) <= METRIQUES_MAX_OCTETS:
                    bloc = os.read(fd, METRIQUES_MAX_OCTETS + 1 - len(donnees))
                    if not bloc:
                        break
                    donnees += bloc
                if len(donnees) > METRIQUES_MAX_OCTETS:
                    return 'unreadable', b'', None
                age = max(0, int(self.horloge() - attributs.st_mtime))
                return 'enabled', donnees, age
            except OSError:
                return 'unreadable', b'', None
            finally:
                os.close(fd)
        finally:
            os.close(dossier)

    # -- actions --------------------------------------------------------------------------

    def _status(self, params):
        _vide(params)
        try:
            version = self.version()
        except RuntimeError:
            raise ErreurProtocole('internal_error') from None
        demons = []
        for nom, unite in DEMONS.items():
            etat, _, age = self._fichier_metriques(nom)
            entree = {'name': nom, 'unit': unite, 'metrics': etat}
            if age is not None:
                entree['sample_age_s'] = age
            demons.append(entree)
        return self._reponse({
            'version': version, 'uptime_s': max(0, int(self._monotone() - self._debut)),
            'sessions': self.sessions.nombre(),
            'activity_detail': self.activite.detail if self.activite is not None else 1,
            'daemons': demons})

    def _services(self, params):
        _vide(params)
        services = []
        for service in self.declares.services:
            services.append({
                'domain': service.domaine, 'greffon': service.greffon, 'target': service.cible,
                'catalog': _CATALOGUES.get(service.catalogue_mode, 'none'),
                'available': self.aiguillage.destination(service.cible, service.domaine)
                is not None})
        return self._reponse({'services': services})

    def _metriques(self, params):
        demon = _demon(params)
        etat, donnees, _ = self._fichier_metriques(demon)
        if etat == 'unreadable':
            raise ErreurProtocole('not_available')
        echantillons = analyser_metriques(donnees) if etat == 'enabled' else []
        return self._reponse({'daemon': demon, 'available': etat == 'enabled',
                              'samples': echantillons})

    def _options(self, demon):
        """({(section, clé): valeur}, schéma) de la configuration effective du démon."""
        if demon == 'romulus':
            return self.config, self.schema
        if demon == 'pollux':
            from server import pollux
            schema, socle = pollux.SCHEMA, {'journal': True, 'metriques': True}
        else:
            from server.pollux import session
            schema, socle = session.SCHEMA, {'journal': True}
        try:
            return lire(demon, schema, argv=[], environ={}, environnement=False,
                        racine_systeme=self.racine_systeme, **socle), schema
        except ErreurConfiguration:
            raise ErreurProtocole('not_available') from None

    def _configuration(self, params):
        demon = _demon(params)
        valeurs, schema = self._options(demon)
        types = {(s, c): o.type for (s, c), o in schema.items()}
        types.update({('journal', 'niveau'): 'niveau', ('metriques', 'actif'): 'booleen',
                      ('metriques', 'dossier'): 'chemin', ('metriques', 'periode_s'): 'duree'})
        options = []
        for section in sorted(valeurs):
            for cle in sorted(valeurs[section]):
                type_option = types.get((section, cle))
                if type_option is None:
                    continue
                cache = masquee(cle, type_option)
                options.append({'section': section, 'key': cle, 'type': type_option,
                                'value': None if cache else _valeur_publiable(
                                    valeurs[section][cle]),
                                'masked': cache})
        return self._reponse({'daemon': demon, 'options': options})

    def _activite(self, params):
        if set(params) - {'limit', 'level', 'domain'}:
            raise ErreurProtocole('bad_request')
        limite, niveau, domaine = params.get('limit', 50), params.get('level', 1), params.get('domain')
        if (not _entier_borne(limite, 1, 200) or not _entier_borne(niveau, 1, 3)
                or (domaine is not None and not (isinstance(domaine, str)
                                                 and _MOTIF_DOMAINE.match(domaine)))):
            raise ErreurProtocole('bad_request')
        if self.activite is None:
            raise ErreurProtocole('not_available')
        try:
            entrees, tronque = self.activite.lire(limite, niveau, domaine)
        except ActiviteInutilisable:
            raise ErreurProtocole('not_available') from None
        return self._reponse({'detail': self.activite.detail, 'entries': entrees,
                              'truncated': tronque})
