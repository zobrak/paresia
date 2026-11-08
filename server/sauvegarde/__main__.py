# SPDX-License-Identifier: AGPL-3.0-or-later
# CLI des sauvegardes de procédure : python3 -m server.sauvegarde (C34, C36, D83, D103) ;
# dépendances : bibliothèque standard et server.commun.
# Suivi des versions
#   0.1.1  2026-11-07  --help et --version (code 0, sortie standard) ; niveau de journal par [sauvegarde.journal].
#   3.0.0-alpha  2026-11-06  Création : copier, releve, lister, taille, jeu, nettoyer, retrouver, restaurer.
#   3.0.0-alpha  2026-11-06  Option inconnue ou --help : usage (code 2) ; -P dans le nom du programme.
import argparse
import json
import os
from pathlib import Path
import sys

from server.commun.config import ErreurConfiguration, lire
from server.commun.journal import Journal
from server.commun.texte import filtrer
from server.commun.version import lire_version
from . import (SCHEMA, SORTIE_ECHEC, SORTIE_LIMITE, SORTIE_OK, SORTIE_USAGE, ErreurSauvegarde, Stockage)

CATALOGUES = Path(__file__).resolve().parents[2] / 'i18n'


def langue(environ):
    for nom in ('LC_ALL', 'LC_MESSAGES', 'LANG'):
        valeur = environ.get(nom)
        if valeur:
            return 'fr-FR' if valeur.lower().startswith('fr') else 'en-US'
    return 'en-US'


def charger_catalogue(environ):
    try:
        contenu = json.loads((CATALOGUES / (langue(environ) + '.json')).read_text(encoding='utf-8'))
        return contenu if isinstance(contenu, dict) else {}
    except (OSError, ValueError):
        return {}


class Analyseur(argparse.ArgumentParser):
    def error(self, message):
        raise ErreurSauvegarde('backup_usage', SORTIE_USAGE)


def analyseur():
    principal = Analyseur(add_help=False, prog='python3 -P -m server.sauvegarde')
    principal.add_argument('--config')
    sous = principal.add_subparsers(dest='commande', parser_class=Analyseur)
    copier = sous.add_parser('copier', add_help=False)
    copier.add_argument('--arbre', action='store_true')
    copier.add_argument('--si-absent', dest='si_absent', action='store_true')
    copier.add_argument('--jeu')
    copier.add_argument('chemins', nargs='+')
    releve = sous.add_parser('releve', add_help=False)
    releve.add_argument('--jeu')
    releve.add_argument('nom')
    for nom in ('lister', 'taille', 'jeu', 'nettoyer'):
        sous.add_parser(nom, add_help=False)
    for nom in ('retrouver', 'restaurer'):
        commande = sous.add_parser(nom, add_help=False)
        commande.add_argument('--jeu', dest='jeu_choisi')
        if nom == 'retrouver':
            commande.add_argument('--releve')
            commande.add_argument('chemin', nargs='?')
        else:
            commande.add_argument('chemin')
    return principal


class Sortie:
    def __init__(self, catalogue):
        self.catalogue = catalogue

    def message(self, cle, **valeurs):
        modele = self.catalogue.get(cle, cle)
        propres = {k: filtrer(str(v)) for k, v in valeurs.items()}
        try:
            texte = modele.format(**propres)
        except (KeyError, IndexError, ValueError):
            texte = modele
        print(filtrer(texte), file=sys.stderr)

    @staticmethod
    def donnee(*champs):
        print('\t'.join(filtrer(str(c)) for c in champs))


def executer(args, stockage, sortie):
    commande = args.commande
    if commande in ('copier', 'releve', 'jeu') and not stockage.actif:
        stockage.journal.ecrire('warning', 'backup_disabled')
        sortie.message('backup_disabled')
        if commande == 'jeu':
            sortie.donnee(stockage.dossier_jeu(stockage.nom_prochain_jeu()))
        return SORTIE_OK
    code = SORTIE_OK
    if commande == 'copier':
        jeu, copies, depasse, taille = stockage.copier(args.chemins, arbre=args.arbre,
                                                       si_absent=args.si_absent, jeu=args.jeu)
        sortie.donnee(stockage.dossier_jeu(jeu))
        if copies < len(args.chemins):
            sortie.message('backup_already_saved')
    elif commande == 'releve':
        jeu, _, depasse, taille = stockage.releve(args.nom, sys.stdin.buffer, jeu=args.jeu)
        sortie.donnee(stockage.dossier_jeu(jeu))
    elif commande == 'jeu':
        sortie.donnee(stockage.dossier_jeu(stockage.nouveau_jeu()))
        return SORTIE_OK
    elif commande == 'lister':
        for nom in stockage.jeux():
            sortie.donnee(nom, stockage.taille_jeu(nom))
        return SORTIE_OK
    elif commande == 'taille':
        sortie.donnee(stockage.taille())
        return SORTIE_OK
    elif commande == 'nettoyer':
        supprimes, taille, depasse = stockage.nettoyer()
        for nom in supprimes:
            sortie.message('backup_rotated', jeu=nom)
    elif commande == 'retrouver':
        jeu, genre, copie, _ = stockage.retrouver(args.chemin, releve=args.releve, jeu=args.jeu_choisi)
        sortie.donnee(jeu, genre, copie if copie else '-')
        return SORTIE_OK
    else:   # restaurer
        jeu, genre = stockage.restaurer(args.chemin, jeu=args.jeu_choisi)
        sortie.message('backup_removed' if genre == 'absent' else 'backup_restored', chemin=args.chemin)
        return SORTIE_OK
    if depasse:
        sortie.message('backup_limit_exceeded', taille=taille, limite=stockage.limite_octets)
        code = SORTIE_LIMITE
    return code


def main(argv=None, environ=None):
    environ = os.environ if environ is None else environ
    os.umask(0o077)
    sortie = Sortie(charger_catalogue(environ))
    journal = Journal('sauvegarde', flux=sys.stderr)    # stdout reste réservé aux données (capture par $(...))
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments in (['--help'], ['--version']):
        cle = 'commun_help' if arguments == ['--help'] else 'commun_version'
        modele = sortie.catalogue.get(cle, cle)
        print(filtrer(modele.format(daemon='sauvegarde', version=lire_version())))
        return SORTIE_OK
    try:
        args = analyseur().parse_args(arguments)
        if args.commande is None:
            raise ErreurSauvegarde('backup_usage', SORTIE_USAGE)
        if args.commande == 'retrouver' and (args.chemin is None) == (args.releve is None):
            raise ErreurSauvegarde('backup_usage', SORTIE_USAGE)
        try:
            configuration = lire('sauvegarde', SCHEMA, argv=['--config', args.config] if args.config else [],
                                 environ=environ, journal=True)
            journal.definir_niveau(configuration['journal']['niveau'])
        except ErreurConfiguration as erreur:
            journal.ecrire('error', 'configuration_failed', code=erreur.code)
            raise ErreurSauvegarde('backup_config_invalid', SORTIE_ECHEC, code=erreur.code) from None
        return executer(args, Stockage(configuration, journal), sortie)
    except ErreurSauvegarde as erreur:
        sortie.message(erreur.message, **erreur.valeurs)
        return erreur.sortie
    except (OSError, ValueError, argparse.ArgumentError) as erreur:
        journal.ecrire('error', 'backup_failed', reason=type(erreur).__name__)
        sortie.message('backup_failed', code=type(erreur).__name__)
        return SORTIE_ECHEC


if __name__ == '__main__':
    raise SystemExit(main())
