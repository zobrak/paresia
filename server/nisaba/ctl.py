# SPDX-License-Identifier: AGPL-3.0-or-later
# Nisaba : ligne de commande (C34), socket de contrôle réservée à root ; python3 -m server.nisaba.ctl
# <status|verify|run TACHE [AAAA-MM-JJ]|metrics|acl check|acl apply> [--config FICHIER] ; dépendances : bibliothèque
# standard et server.commun. Codes de sortie : 0 succès, 1 échec, 2 usage, 3 Nisaba injoignable.
# Suivi des versions
#   0.1.1  2026-11-07  --help et --version (code 0) ; journal à niveaux sur la sortie d'erreur.
#   3.0.0-alpha.40  2026-11-06  Création (T031) : status, verify, run, metrics ; acl par T033.
#   3.0.0-alpha.41  2026-11-06  T033 (C34) : acl check|apply (lignes et code de sortie), run scellement AAAA-MM-JJ.
import json
import os
import re
import secrets
import sys
from pathlib import Path

from server.commun.client import PairIndisponible, appeler
from server.commun.config import ErreurConfiguration
from server.commun.jumeaux import ErreurProtocole
from server.commun.journal import Journal
from server.commun.texte import filtrer
from server.commun.version import lire_version
from . import TACHES, configuration
from .metriques import rendre

ACTIONS_CTL = frozenset({'nisaba/state/status', 'nisaba/state/verify', 'nisaba/job/run',
                         'nisaba/acl/check', 'nisaba/acl/apply'})
AIDE_METRIQUES = {
    'nisaba_last_success_timestamp_seconds': 'nisaba_metric_help_last_success',
    'nisaba_failures_total': 'nisaba_metric_help_failures',
    'nisaba_manifest_days': 'nisaba_metric_help_manifest_days',
    'nisaba_proofs': 'nisaba_metric_help_proofs',
    'nisaba_oldest_journal_age_seconds': 'nisaba_metric_help_oldest_age',
}


def catalogue():
    """Catalogue français (comme bunkerd) ; une clé introuvable s'affiche telle quelle."""
    try:
        chemin = Path(__file__).resolve().parents[2] / 'i18n' / 'fr-FR.json'
        donnees = json.loads(chemin.read_text(encoding='utf-8'))
        return donnees if isinstance(donnees, dict) else {}
    except (OSError, ValueError):
        return {}


class _Sortie:
    def __init__(self, flux, textes):
        self.flux, self.textes = flux, textes

    def dire(self, cle, **champs):
        modele = self.textes.get(cle, cle)
        valeurs = {k: filtrer(str(v)) for k, v in champs.items()}
        try:
            texte = modele.format(**valeurs)
        except (KeyError, IndexError, ValueError):
            texte = modele
        print(filtrer(texte), file=self.flux)

    def brut(self, texte):
        print('\n'.join(filtrer(ligne) for ligne in texte.split('\n')), file=self.flux, end='')


def _analyser(argv):
    """(commande, arguments, fichier de configuration) ou None si l'usage est incorrect."""
    reste, config, i = [], None, 0
    while i < len(argv):
        if argv[i] == '--config':
            if config is not None or i + 1 >= len(argv) or not argv[i + 1]:
                return None
            config, i = argv[i + 1], i + 2
        else:
            reste.append(argv[i])
            i += 1
    if not reste:
        return None
    commande, arguments = reste[0], reste[1:]
    if commande in ('status', 'verify', 'metrics') and not arguments:
        return commande, arguments, config
    if commande == 'run' and len(arguments) == 1 and arguments[0] in TACHES:
        return commande, arguments, config
    if commande == 'run' and len(arguments) == 2 and arguments[0] == 'scellement' \
            and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', arguments[1]):
        return commande, arguments, config
    if commande == 'acl' and len(arguments) == 1 and arguments[0] in ('check', 'apply'):
        return commande, arguments, config
    return None


def _requete(action, params):
    return {'proto': 'jumeaux/1', 'id': secrets.token_hex(8), 'session': 0,
            'action': action, 'params': params}


def _afficher_etat(sortie, data):
    inconnu = sortie.textes.get('nisaba_unknown', 'nisaba_unknown')
    jamais = sortie.textes.get('nisaba_never', 'nisaba_never')
    sortie.dire('nisaba_status_started', demarrage=data['demarrage'])
    for nom, tache in data['taches'].items():
        sortie.dire('nisaba_task_line', tache=nom, derniere=tache['derniere'] or jamais,
                    resultat=sortie.textes.get('nisaba_result_' + str(tache['resultat']), inconnu),
                    prochaine=tache['prochaine'] or inconnu)
        for echec in tache['echecs']:
            sortie.dire('nisaba_failure_line', heure=echec['heure'], code=echec['code'], texte=echec['texte'])
    journal = data['journal']
    sortie.dire('nisaba_journal_line',
                publications=inconnu if journal['publications_jour'] is None else journal['publications_jour'],
                journees=journal['journees'], derniere=journal['derniere_journee'] or inconnu)
    if journal['age_plus_ancien_s'] is not None:
        sortie.dire('nisaba_journal_age', jours=journal['age_plus_ancien_s'] // 86400)
    sortie.dire('nisaba_proofs_line', **journal['preuves'])


def main(argv=None, *, sortie=None, erreur=None):
    textes = catalogue()
    sortie_std = _Sortie(sortie if sortie is not None else sys.stdout, textes)
    sortie_err = _Sortie(erreur if erreur is not None else sys.stderr, textes)
    arguments_bruts = list(sys.argv[1:] if argv is None else argv)
    if arguments_bruts in (['--help'], ['--version']):
        cle = 'commun_help' if arguments_bruts == ['--help'] else 'commun_version'
        sortie_std.dire(cle, daemon='nisaba-ctl', version=lire_version())
        return 0
    analyse = _analyser(arguments_bruts)
    if analyse is None:
        sortie_err.dire('nisaba_usage')
        return 2
    commande, arguments, fichier = analyse
    journal = Journal('nisaba-ctl', flux=erreur if erreur is not None else sys.stderr)
    try:
        config = configuration(argv=['--config', fichier] if fichier else [])
    except ErreurConfiguration as e:
        sortie_err.dire('nisaba_config_failed', code=e.code)
        return 2
    journal.definir_niveau(config.get('journal', {}).get('niveau', 'info'))
    for section, valeurs in config.items():
        for option in valeurs:
            journal.ecrire('debug', 'config_read', section=section, option=option)
    if commande == 'status' or commande == 'metrics':
        requete = _requete('nisaba/state/status', {})
    elif commande == 'verify':
        requete = _requete('nisaba/state/verify', {})
    elif commande == 'run':
        requete = _requete('nisaba/job/run', {'task': arguments[0]} if len(arguments) == 1
                           else {'task': arguments[0], 'day': arguments[1]})
    else:
        requete = _requete('nisaba/acl/' + arguments[0], {})
    try:
        resultat = appeler(os.fspath(config['ctl']['socket']), requete, config['socket']['delai_s'],
                           actions=ACTIONS_CTL)
    except (PairIndisponible, ErreurProtocole, OSError, ValueError):
        sortie_err.dire('nisaba_unreachable')
        return 3
    if not resultat['ok']:
        code = resultat['error']['code']
        sortie_err.dire('nisaba_error', detail=textes.get(code, code))
        return 1
    data = resultat.get('data')
    try:
        if commande == 'status':
            _afficher_etat(sortie_std, data)
            return 0
        if commande == 'metrics':
            aide = {nom: textes.get(cle, cle) for nom, cle in AIDE_METRIQUES.items()}
            sortie_std.brut(rendre(data['metriques'], aide))
            return 0
        if commande == 'verify':
            for ligne in data['lignes']:
                sortie_std.brut(ligne + '\n')
            return 0 if data['code'] == 0 else 1
        if commande == 'run':
            if data['resultat'] == 'ok':
                sortie_std.dire('nisaba_run_ok', tache=data['tache'])
                return 0
            sortie_std.dire('nisaba_run_failed', tache=data['tache'], echecs=data['echecs'])
            return 1
        for ligne in data['lignes']:
            sortie_std.brut(ligne + '\n')
        if data['code'] == 0:
            sortie_std.dire('nisaba_acl_done', operation=arguments[0])
            return 0
        return 1
    except (KeyError, TypeError, AttributeError):
        sortie_err.dire('nisaba_unreachable')
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
