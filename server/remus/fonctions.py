# SPDX-License-Identifier: AGPL-3.0-or-later
# Remus enfiché : fonctions chargées par le chargeur du noyau ; dépendances : server.commun, server.remus.
# Suivi des versions
#   0.1.7  2026-11-07  Chargement des fonctions du côté yin, gabarits, privilèges, introspection (D148, D150, D153, D154).
"""Adaptation de Remus au chargeur de fonctions du noyau.

Une fonction est un script et un manifeste (côté `yin`) ; elle n'est jamais importée,
seulement lancée par `Executeur.lancer_script`. Le catalogue chargé est la liste fermée
des actions de Remus. Les noms de greffon, de domaine ou d'action viennent des
manifestes et de la configuration, jamais de ce module.

Dossiers par défaut (D148, remplaçables par `[remus.plugins]`) : fonctions livrées
sous /usr/local/lib/paresia/remus/fonctions, fonctions locales sous
/etc/paresia/remus/plugins.d.

Limite assumée (D153) : avec sudo, les droits sont ceux du compte de Remus, non de la
fonction ; le champ `privilege` est publié, non appliqué.
"""
from dataclasses import dataclass, field
import os
import re

from server.commun import plugins
from server.commun.catalogue import (CIBLE_DEFAUT, DOMAINES_RESERVES, MOTIF_CIBLE, Catalogue,
                                     creer_descripteur)
from server.commun.config import ErreurConfiguration
from server.commun.plugins import ErreurPlugin
from server.commun.privileges import vers_sudo
from server.remus import Action, ErreurOperation
from server.remus.executeur import (ELEMENT_MAX, Choix, Entier, Executeur, Hexadecimal, ListeEntiers,
                                    RenduSudo, Script, Texte, Variable)

COTE = 'yin'
DOSSIER_LIVRE = '/usr/local/lib/paresia/remus/fonctions'
DOSSIER_LOCAL = '/etc/paresia/remus/plugins.d'
CODES_CONNUS = frozenset({'command_failed', 'not_available'})
MOTIF_DOMAINE = re.compile(r'[a-z][a-z0-9_]{0,31}\Z')
COMPTE_ESSAI = 'essai'
NOMBRE_ELEMENTS_LISTE_MAX = 1024


@dataclass(frozen=True)
class Options:
    fonctions: str
    locales: str
    domaine: object
    cible: str


@dataclass(frozen=True, repr=False)
class Fonctions:
    """Résultat du chargement ; ne se décrit jamais par ses contenus."""
    actions: object
    catalogue: object
    cible: str

    def __repr__(self):
        return '<Fonctions>'


def options_plugins(configuration):
    """Lit `[remus.plugins]` (section absente admise) ; ErreurConfiguration sinon."""
    brut = configuration.get('plugins') or {}
    domaine, cible = brut.get('domaine'), brut.get('cible')
    if domaine is not None and (type(domaine) is not str or not MOTIF_DOMAINE.match(domaine)
                                or domaine in DOMAINES_RESERVES):
        raise ErreurConfiguration('config_invalid', 'plugins', 'domaine')
    if cible is None:
        cible = CIBLE_DEFAUT
    if type(cible) is not str or not MOTIF_CIBLE.match(cible):
        raise ErreurConfiguration('config_invalid', 'plugins', 'cible')
    return Options(brut.get('fonctions') or DOSSIER_LIVRE, brut.get('locales') or DOSSIER_LOCAL,
                   domaine, cible)


# --- Gabarits ----------------------------------------------------------------------------

def gabarit_de(parametre):
    """Gabarit de executeur.py pour un paramètre du descripteur ; ValueError sinon.

    Aucun nouveau validateur de valeur. Un type que les gabarits n'expriment pas
    (entier négatif, liste de plus de 1024 éléments, minimum de liste supérieur à 1)
    est refusé, jamais élargi.
    """
    type_, bornes = parametre.type, parametre.bornes
    if type_ == 'texte':
        return Texte(bornes['motif'], min(bornes['longueur_max'], ELEMENT_MAX), espace=True)
    if type_ == 'entier':
        return Entier(bornes['minimum'], bornes['maximum'])
    if type_ == 'choix':
        return Choix(*bornes['valeurs'], espace=True)
    if type_ == 'hexadecimal':
        return Hexadecimal(bornes['longueur'])
    if type_ == 'liste_entiers':
        if bornes['nombre_max'] > NOMBRE_ELEMENTS_LISTE_MAX or bornes.get('nombre_min', 0) > 1:
            raise ValueError('invalid_template')
        return ListeEntiers(bornes['minimum'], bornes['maximum'], bornes['nombre_max'])
    raise ValueError('invalid_template')


def _gabarit_variable(element):
    """Gabarit d'un élément variable de la description neutre (copie des bornes)."""
    type_, bornes = element['type'], element['bornes']
    if type_ == 'choix':
        return Choix(*tuple(bornes['valeurs']))
    if type_ == 'hexadecimal':
        return Hexadecimal(bornes['longueur'])
    if type_ == 'entier':
        return Entier(bornes['minimum'], bornes['maximum'])
    raise ValueError('invalid_template')


# --- Privilèges --------------------------------------------------------------------------

def rendre(description, docker, nom):
    """Convertit la description de `vers_sudo` en objets du générateur de sudoers.

    Retourne des RenduSudo neufs ; l'objet reçu n'est jamais modifié.
    """
    rendus = []
    for indice, commande in enumerate(description):
        elements = [docker, commande['verbe']]
        for element in commande['elements']:
            elements.append(element if isinstance(element, str)
                            else Variable(element['nom'], _gabarit_variable(element)))
        rendus.append(RenduSudo(f'{nom}{indice}', tuple(elements)))
    return tuple(rendus)


def verificateur(docker):
    """Rappel `verifier_privileges` : rendu d'essai par le générateur, fail-closed.

    Retourne True seulement si le générateur produit le fichier ; tout refus ou toute
    exception donne False.
    """
    def verifier(description):
        if type(docker) is not str:
            return False
        try:
            from server.remus import sudoers
            sudoers.generer_sudoers(rendre(description, docker, COMPTE_ESSAI), COMPTE_ESSAI)
        except Exception:
            return False
        return True
    return verifier


# --- Chargement --------------------------------------------------------------------------

def _ecrire(journal, niveau, evenement, **champs):
    try:
        journal.ecrire(niveau, evenement, **champs)
    except Exception:
        pass


def _charger(domaine, options, docker, rappel, proprietaires, racine_confiance):
    """Seul appel du chargeur : le rappel de rendu d'essai y est toujours passé."""
    try:
        return plugins.charger(
            COTE, domaine, options.fonctions, options.locales, cible=options.cible,
            codes_connus=CODES_CONNUS, proprietaires=proprietaires,
            racine_confiance=racine_confiance, rappel=rappel,
            verifier_privileges=verificateur(docker))
    except ErreurPlugin as erreur:
        raise ErreurConfiguration(erreur.code, 'plugins', 'fonctions') from None
    except ValueError:
        raise ErreurConfiguration('config_invalid', 'plugins', 'domaine') from None
    except Exception:
        raise ErreurConfiguration('plugin_unreadable', 'plugins', 'fonctions') from None


def _docker(configuration):
    return (configuration.get('executor') or {}).get('docker')


def _livree(fonction, options):
    return (os.path.dirname(os.path.abspath(fonction.script))
            == os.path.abspath(os.fspath(options.fonctions)))


@dataclass(frozen=True)
class _Appelable:
    """Pont entre une Action de Remus et la voie « script » de l'exécuteur."""
    script: Script
    executeur: object = field(repr=False)

    def valider(self, params):
        if self.script.verifier(params) is not None:
            raise ErreurOperation('bad_request')
        return dict(params)

    def executer(self, contexte):
        resultat = self.executeur.lancer_script(
            self.script, contexte.params, session=contexte.session,
            identifiant=contexte.identifiant)
        if resultat.ok:
            return resultat.data
        raise ErreurOperation(resultat.code)


def _script(fonction):
    descripteur = fonction.descripteur
    gabarits = {p.nom: (gabarit_de(p), p.obligatoire) for p in descripteur.parametres}
    return Script(fonction.nom, fonction.script, descripteur.delai_s, fonction.sortie_max,
                  descripteur, fonction.journaliser, gabarits)


def charger_fonctions(configuration, journal, *, proprietaires=frozenset({0}),
                      racine_confiance='/'):
    """Charge les fonctions (livrées puis locales) ; retourne Fonctions.

    Livré défectueux : ErreurConfiguration à code `plugin_*` (démarrage refusé). Local
    défectueux : ignoré et journalisé. Sans domaine configuré, rien n'est chargé.
    """
    options = options_plugins(configuration)
    if options.domaine is None:
        _ecrire(journal, 'info', 'plugins_loaded', functions=[], count=0, skipped=0)
        return Fonctions({}, None, options.cible)
    ecartees = []

    def rappel(evenement, niveau, **champs):
        if evenement == 'plugin_skipped':
            ecartees.append(1)
        _ecrire(journal, niveau, evenement, **champs)

    chargement = _charger(options.domaine, options, _docker(configuration), rappel,
                          proprietaires, racine_confiance)
    scripts = {}
    for action in sorted(chargement.fonctions):
        fonction = chargement.fonctions[action]
        try:
            scripts[action] = (fonction, _script(fonction))
        except ValueError:
            if _livree(fonction, options):
                raise ErreurConfiguration('plugin_manifest_invalid', 'plugins',
                                          'fonctions') from None
            _ecrire(journal, 'error', 'plugin_rejected', code='plugin_manifest_invalid',
                    scope='local', file=fonction.nom)
    executeur = None
    if scripts:
        if 'executor' not in configuration:
            raise ErreurConfiguration('config_missing', 'executor')
        executeur = Executeur(configuration['executor'], {}, journal=journal)
    actions = {}
    for action, (fonction, script) in scripts.items():
        appelable = _Appelable(script, executeur)
        actions[action] = Action(action, appelable.executer, appelable.valider,
                                 script.delai_s, False, tuple(script.journaliser))
    try:
        catalogue = Catalogue(options.cible, options.domaine,
                              [f.descripteur for f, _ in scripts.values()])
    except ValueError:
        raise ErreurConfiguration('plugin_manifest_invalid', 'plugins', 'fonctions') from None
    _ecrire(journal, 'info', 'plugins_loaded', functions=sorted(f.nom for f, _ in scripts.values()),
            count=len(scripts), skipped=len(ecartees))
    return Fonctions(actions, catalogue, options.cible)


def catalogue_injecte(cible, domaine, actions):
    """Catalogue minimal pour des actions fournies directement (descripteur sans paramètre).

    Remus ne sert qu'un domaine : actions de plusieurs domaines, ou d'un domaine autre que
    celui qui est configuré, sont refusées (`invalid_server_config`). Sans domaine, None.
    """
    domaines = {nom.split('/')[0] for nom in actions}
    if len(domaines) > 1 or (domaine is not None and domaines and domaines != {domaine}):
        raise ValueError('invalid_server_config')
    domaine = domaine if domaine is not None else next(iter(domaines), None)
    if domaine is None:
        return None
    try:
        return Catalogue(cible, domaine, [creer_descripteur(nom, delai_s=a.delai_max_s)
                                          for nom, a in sorted(actions.items())])
    except ValueError:
        raise ValueError('invalid_actions') from None


# --- Sudoers -----------------------------------------------------------------------------

def regles_sudoers(configuration, *, proprietaires=frozenset({0}), racine_confiance='/'):
    """Rendus pour le générateur de sudoers, à partir des seuls manifestes chargés.

    Aucun script n'est exécuté. Le chargeur reçoit le même rappel de rendu d'essai.
    """
    options = options_plugins(configuration)
    docker = _docker(configuration)
    if options.domaine is None:
        return ()
    chargement = _charger(options.domaine, options, docker, None, proprietaires, racine_confiance)
    rendus = []
    for action in sorted(chargement.fonctions):
        fonction = chargement.fonctions[action]
        if fonction.commandes:
            rendus.extend(rendre(vers_sudo(fonction.commandes), docker, fonction.nom))
    return tuple(rendus)
