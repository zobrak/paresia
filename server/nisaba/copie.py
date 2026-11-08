# SPDX-License-Identifier: AGPL-3.0-or-later
# Nisaba : copie du journal légal depuis backend-relais (reprend journal-legal-pull.sh 1.2.1, D87, C38, T012) ;
# dépendances : bibliothèque standard et server.nisaba.droits. rsync est lancé par argv (N8) ; la clé SSH est
# donnée à ssh par son chemin et n'est jamais lue, copiée ni affichée.
# Suivi des versions
#   3.0.0-alpha.41  2026-11-06  Création (T033) : même commande rsync que pull 1.2.1, droits après copie.
import math
import os
import re
import stat

_JOURNAL = re.compile(r'journal-[0-9]{4}-[0-9]{2}-[0-9]{2}\.jsonl')
PLAFOND_PROCESSUS = 3600.0      # durée maximale d'un rsync lancé, secondes (rsync --timeout borne l'inactivité)


def secondes(valeur):
    """Entier de secondes pour --timeout et ConnectTimeout (arrondi par excès, au moins 1)."""
    return max(1, int(math.ceil(valeur)))


def commande_ssh(config_source):
    """Argument de rsync -e : ssh, clé par son chemin, options des scripts (jamais d'invite)."""
    return (f"{config_source['ssh']} -i {config_source['cle_ssh']} -o IdentitiesOnly=yes -o BatchMode=yes "
            f"-o ConnectTimeout={secondes(config_source['connexion_s'])}")


def masquer(texte, config_source):
    """Retire le chemin de la clé d'un texte d'erreur (jamais affiché)."""
    return texte.replace(os.fspath(config_source['cle_ssh']), '[cle]')


def copier(config_source, dossier, droits, lancer, echec_copie, echec_acl):
    """Copie rsync puis droits ; renvoie le nombre d'échecs (copie : 1 et arrêt ; droits : un par élément).

    echec_copie(texte) et echec_acl(texte) sont des rappels (ECHEC_COPIE, ECHEC_ACL).
    """
    dossier = os.fspath(dossier)
    argv = [os.fspath(config_source['rsync']), '--recursive', '--times', '--append',
            '--include=journal-*.jsonl', '--exclude=*', f"--timeout={secondes(config_source['rsync_s'])}",
            '-e', commande_ssh(config_source), config_source['source'], dossier.rstrip('/') + '/']
    resultat = lancer(argv, PLAFOND_PROCESSUS)
    if resultat.code != 0:
        echec_copie(masquer(resultat.erreur, config_source) or f'rsync_failed: {resultat.code}')
        return 1
    echecs = 0
    erreur = droits.poser(dossier, 'journal-dir')
    if erreur:
        echec_acl(erreur)
        echecs += 1
    try:
        noms = sorted(os.listdir(dossier))
    except OSError:
        return echecs
    for nom in noms:
        if _JOURNAL.fullmatch(nom) is None:
            continue
        chemin = os.path.join(dossier, nom)
        try:
            mode = os.lstat(chemin).st_mode
        except OSError:
            continue
        if not stat.S_ISREG(mode):                     # lstat : ni lien, ni autre type
            continue
        if droits.immuable(chemin) == 0:               # scellé : on ne le retouche pas
            continue
        erreur = droits.poser(chemin, 'file640')
        if erreur:
            echec_acl(erreur)
            echecs += 1
    return echecs
