# SPDX-License-Identifier: AGPL-3.0-or-later
# Suivi des versions
#   0.1.18  2026-11-08  En-tête du fichier généré sans numéro de tâche.
#   0.1.7  2026-11-07  Alimenté par les manifestes des fonctions, sans exécuter de script (D148, D153).
#   0.1.1  2026-11-07  Lecture des sections journal et métriques de [remus] (exemple de configuration).
#   3.0.0-alpha  2026-11-06  Générateur fermé de sudoers (T023, D80 révisée).
"""Source unique : les commandes privilégiées des manifestes de fonctions, sans rien exécuter.

Citations : sudoers(5) installé (sudo 1.9.16p2), Cmnd, Wildcards,
Regular expressions, Including other files, Tag_Spec et sudoers_mode :
  "If a Cmnd has associated command line arguments, the arguments in the Cmnd
  must match those given by the user on the command line."
  "Command line arguments are matched as a single, concatenated string."
  "Wildcards in command line arguments should be used with care."
  "the following characters must be escaped with a '\\' if they are used in
  command arguments: ',', ':', '=', '\\'."
  "Starting with version 1.9.10, it is possible to use regular expressions"
  "supported by sudoers are POSIX extended regular expressions"
  "regular expressions must start with a `^' character and end with a `$'"
  "Regular expressions in sudoers are limited to 1024 characters."
  "skipping file names that end in `~' or contain a `.' character"
  "the default file mode is 0440 (readable by owner and group, writable by none)."
  "NOPASSWD:" ; "(root)" (exemples Runas_Spec).

La liste fermée évite les caractères de syntaxe et tout espace dans un élément.
Dans une expression, point et plus sont protégés par deux niveaux d'échappement
(sudoers puis POSIX ERE). Les espaces séparateurs sont produits ici uniquement.
Aucun Defaults n'est ajouté. Propriétaire d'installation : root:root.
Verbes : seuls `exec` et `restart` sont acceptés ; le lot 6 devra étendre le
générateur, en citant sudoers(5), pour toute autre forme.
Résidu accepté D80 : les arguments fixes fusionnés en un argument ne sont pas
 distingués par sudoers ; réexamen obligatoire pour chaque commande du lot 6.
"""
import itertools
import re
import sys

from server.commun.config import ErreurConfiguration, lire
from server.remus import SCHEMA
from server.remus.executeur import Choix, Entier, Hexadecimal, Variable

VERSION_FORMAT = '3.0.0-alpha'
# Bornes de ressources, indépendantes des valeurs de la configuration.
REGLES_MAX = 256
HEXADECIMAL_MAX = 128
EXPRESSION_ENTIER_MAX = 512
EXPRESSION_MAX = 1024  # Limite publiée de sudoers(5).
CARACTERES_FIXES = re.compile(r'[A-Za-z0-9/._+\-]{1,4096}', re.ASCII)
ENTETE = (f'# SPDX-License-Identifier: AGPL-3.0-or-later\n'
          f'# Suivi des versions : {VERSION_FORMAT} — 2026-11-06.\n'
          '# Remus : liste fermée des commandes privilégiées.\n'
          '# fichier généré, ne pas modifier à la main\n'
          '# Génération : python3 -m server.remus.sudoers\n')


def _fixe(element):
    if type(element) is not str or not CARACTERES_FIXES.fullmatch(element):
        raise ValueError('sudoers_unsafe_element')
    return element


def _intervalle(minimum, maximum):
    """Partition exacte en préfixes décimaux, sans zéro initial ni quantificateur libre."""
    if (type(minimum) is not int or type(maximum) is not int
            or minimum < 0 or maximum < minimum):
        raise ValueError('sudoers_unsafe_template')
    morceaux = []

    def visiter(prefixe, bas, haut, restants):
        if minimum <= bas and haut <= maximum:
            morceaux.append(prefixe + (f'[0-9]{{{restants}}}' if restants else ''))
            return
        if haut < minimum or bas > maximum:
            return
        pas = 10 ** (restants - 1)
        for chiffre in range(10):
            debut = bas + chiffre * pas
            visiter(prefixe + str(chiffre), debut, debut + pas - 1, restants - 1)

    if minimum == 0:
        morceaux.append('0')
    for longueur in range(1, len(str(maximum)) + 1):
        for premier in range(1, 10):
            pas = 10 ** (longueur - 1)
            visiter(str(premier), premier * pas, (premier + 1) * pas - 1, longueur - 1)
    motif = '(' + '|'.join(morceaux) + ')'
    if len(motif) > EXPRESSION_ENTIER_MAX:
        raise ValueError('sudoers_unsafe_template')
    return motif


def _possibilites(variable):
    if variable.drapeau is not None:
        raise ValueError('sudoers_unsafe_template')
    gabarit = variable.gabarit
    if type(gabarit) is Choix:
        if gabarit.espace or len(gabarit.valeurs) > REGLES_MAX:
            raise ValueError('sudoers_unsafe_template')
        return tuple(_fixe(v) for v in gabarit.valeurs), False
    if type(gabarit) is Hexadecimal and gabarit.longueur <= HEXADECIMAL_MAX:
        return (f'[0-9a-f]{{{gabarit.longueur}}}',), True
    if type(gabarit) is Entier:
        return (_intervalle(gabarit.minimum, gabarit.maximum),), True
    raise ValueError('sudoers_unsafe_template')


def _ere(texte):
    # Deux antislashs dans le fichier sudoers donnent un antislash à regexec(3).
    return texte.replace('.', r'\\.').replace('+', r'\\+')


def generer_sudoers(commandes, compte):
    """Retourne un fichier complet ou un code stable, jamais un rendu partiel."""
    if type(compte) is not str or not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', compte):
        raise ValueError('sudoers_unsafe_element')
    lignes = [ENTETE]
    for commande in commandes:
        elements = commande.elements
        if len(elements) < 3:
            raise ValueError('sudoers_unsafe_element')
        docker = _fixe(elements[0])
        if not docker.startswith('/') or docker.endswith('/'):
            raise ValueError('sudoers_unsafe_element')
        variables = any(isinstance(e, Variable) for e in elements)
        if variables and (len(elements) < 5 or elements[1] != 'exec'
                          or any(type(e) is not str for e in elements[1:4])):
            raise ValueError('sudoers_unsafe_template')
        # Refuse les options Docker et les opérations hors de la liste de formes.
        if elements[1] != 'exec' and elements[1] != 'restart':
            raise ValueError('sudoers_unsafe_element')
        if elements[1] == 'exec' and len(elements) < 4:
            raise ValueError('sudoers_unsafe_element')
        # Le conteneur et le programme fixes ne doivent pas devenir des options Docker.
        for element in elements[2:4] if elements[1] == 'exec' else elements[2:3]:
            if type(element) is str and element.startswith('-'):
                raise ValueError('sudoers_unsafe_element')
        choix, motifs = [], []
        nombre = 1
        for element in elements[1:]:
            valeurs, motif = (_possibilites(element) if type(element) is Variable
                              else ((_fixe(element),), False))
            nombre *= len(valeurs)
            if nombre > REGLES_MAX:
                raise ValueError('sudoers_unsafe_template')
            choix.append(valeurs)
            motifs.append(motif)
        expression = any(motifs)
        for combinaison in itertools.product(*choix):
            arguments = ' '.join(v if m or not expression else _ere(v)
                                 for v, m in zip(combinaison, motifs))
            if expression:
                arguments = '^' + arguments + '$'
                if len(arguments) > EXPRESSION_MAX:
                    raise ValueError('sudoers_unsafe_template')
            lignes.append(f'{compte} ALL=(root) NOPASSWD: {docker} {arguments}\n')
    return ''.join(lignes)


def main(argv=None, *, proprietaires=frozenset({0}), racine_confiance='/'):
    """Charge les fonctions des deux dossiers (rendu d'essai compris) et écrit le fichier.

    Il ne lit que les manifestes et n'exécute aucun script. Limite : le chargeur écarte
    une fonction dont la condition de chargement n'est pas remplie ; ses règles ne sont
    alors pas produites.
    """
    from server.remus.fonctions import regles_sudoers
    try:
        configuration = lire('remus', SCHEMA, argv=argv, journal=True, metriques=True)
        texte = generer_sudoers(regles_sudoers(configuration, proprietaires=proprietaires,
                                               racine_confiance=racine_confiance), 'chef')
    except ErreurConfiguration as erreur:
        sys.stderr.write(erreur.code + '\n')
        return 1
    except ValueError as erreur:
        # Les seules ValueError attendues de la table et du générateur sont des codes.
        code = str(erreur)
        if not re.fullmatch('[a-z][a-z0-9_]{0,63}', code):
            code = 'sudoers_generation_failed'
        sys.stderr.write(code + '\n')
        return 1
    sys.stdout.write(texte)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
