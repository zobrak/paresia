#!/usr/bin/python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Simulacre des programmes externes de Nisaba (jamais les vrais) : rsync, chattr, lsattr, setfacl, getfacl, ots.
# Copié sous le nom de chaque programme dans un dossier de test ; l'état vit à côté (sous-dossier etat/ et relais/).
# Suivi des versions
#   3.0.0-alpha.41  2026-11-06  Création (T033) : état en JSON, échecs injectables par fichiers echec-<outil>.
import json
import os
import re
import shutil
import stat
import sys

NOM = os.path.basename(sys.argv[0])
BASE = os.path.dirname(os.path.abspath(sys.argv[0]))
ETAT = os.path.join(BASE, 'etat')
RELAIS = os.path.join(BASE, 'relais')


def journaliser(*mots):
    with open(os.path.join(ETAT, 'appels.log'), 'a') as f:
        f.write('\t'.join(mots) + '\n')


def charger(nom):
    try:
        with open(os.path.join(ETAT, nom)) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def enregistrer(nom, valeur):
    with open(os.path.join(ETAT, nom), 'w') as f:
        json.dump(valeur, f)


def echec_injecte(args):
    """echec-<outil> : vide = échec toujours ; sinon une ligne par motif, échec si un motif est dans les arguments."""
    chemin = os.path.join(ETAT, 'echec-' + NOM)
    if not os.path.exists(chemin):
        return False
    motifs = [m for m in open(chemin).read().split('\n') if m]
    return not motifs or any(m in ' '.join(args) for m in motifs)


def sortie_erreur_injectee():
    chemin = os.path.join(ETAT, 'stderr-' + NOM)
    return open(chemin).read() if os.path.exists(chemin) else 'echec simule\n'


def chemin_relais(arg):
    return arg.split(':/', 1)[1] if ':/' in arg else None


def attributs_de(chemin):
    return charger('attributs.json').get(chemin, '')


def rsync(args):
    options, positionnels, i = set(), [], 0
    while i < len(args):
        if args[i] == '-e':
            i += 2
            continue
        (options.add(args[i]) if args[i].startswith('--') else positionnels.append(args[i]))
        i += 1
    if os.path.exists(os.path.join(ETAT, 'injoignable')):
        sys.stderr.write('ssh: connexion impossible\n')
        return 255
    if echec_injecte(args):
        sys.stderr.write(sortie_erreur_injectee())
        return 12
    source = chemin_relais(positionnels[0])
    if '--list-only' in options:
        if source == '' or os.path.isfile(os.path.join(RELAIS, source)):
            return 0
        sys.stderr.write('rsync: fichier absent\n')
        return 23
    destination = positionnels[1]
    noms = ([n for n in sorted(os.listdir(RELAIS)) if re.fullmatch(r'journal-.*\.jsonl', n)]
            if source == '' else [source])
    for nom in noms:
        distant, local = os.path.join(RELAIS, nom), os.path.join(destination, nom)
        contenu = open(distant, 'rb').read()
        if '--dry-run' in options:
            if not os.path.exists(local) or open(local, 'rb').read() != contenu:
                print(f'>fc.t...... {nom}')
            continue
        existant = os.path.getsize(local) if os.path.exists(local) else -1
        if existant >= len(contenu):
            continue                                # --append : receveur égal ou plus long, fichier ignoré
        with open(local, 'ab') as f:
            f.write(contenu[max(existant, 0):])
    return 0


def chattr(args):
    pose = args[0]
    chemin = args[-1]
    if echec_injecte(args) or not os.path.exists(chemin):
        sys.stderr.write(sortie_erreur_injectee())
        return 1
    attrs = charger('attributs.json')
    lettres = set(attrs.get(chemin, ''))
    (lettres.add if pose[0] == '+' else lettres.discard)(pose[1])
    attrs[chemin] = ''.join(sorted(lettres))
    enregistrer('attributs.json', attrs)
    return 0


def lsattr(args):
    code = 0
    for chemin in args[2:]:
        if echec_injecte(args) or not os.path.exists(chemin):
            sys.stderr.write('lsattr: introuvable\n')
            code = 1
            continue
        lettres = attributs_de(chemin)
        print(('i' if 'i' in lettres else '-') + ('a' if 'a' in lettres else '-') + '---------e------- ' + chemin)
    return code


def perm3(p):
    return p if len(p) == 3 else ('r' if 'r' in p else '-') + ('w' if 'w' in p else '-') + ('x' if 'x' in p else '-')


def entrees(spec):
    """{(genre, nom): perm sur 3 caractères} des entrées d'accès, et liste des entrées par défaut."""
    acces, defaut = {}, []
    for entree in spec.split(','):
        parties = entree.split(':')
        if parties[0] == 'd':
            defaut.append(parties[1:])
        else:
            acces[(parties[0], parties[1])] = perm3(parties[2])
    return acces, defaut


def bits(perm):
    return (4 if perm[0] == 'r' else 0) | (2 if perm[1] == 'w' else 0) | (1 if perm[2] == 'x' else 0)


def setfacl(args):
    chemin = args[-1]
    journaliser('MODE', chemin, oct(stat.S_IMODE(os.stat(chemin).st_mode)) if os.path.exists(chemin) else '?')
    if echec_injecte(args) or not os.path.exists(chemin):
        sys.stderr.write(sortie_erreur_injectee())
        return 1
    if set(attributs_de(chemin)) & {'i', 'a'}:
        sys.stderr.write('setfacl: operation non permise (attribut i ou a)\n')
        return 1
    acl = charger('acl.json')
    if args[0] == '-b':
        acl.pop(chemin, None)
    else:
        acl[chemin] = args[1]
        # Comme le noyau : les bits de mode suivent l'ACL (propriétaire, masque = groupe, autres).
        acces, _ = entrees(args[1])
        nommes = [bits(p) for (genre, nom), p in acces.items() if genre == 'u' and nom]
        masque = 0
        for valeur in nommes + [bits(acces[('g', '')])]:
            masque |= valeur
        courant = stat.S_IMODE(os.stat(chemin).st_mode)
        proprio = bits(acces[('u', '')]) if ('u', '') in acces else courant >> 6 & 7
        autres = bits(acces[('o', '')]) if ('o', '') in acces else courant & 7
        os.chmod(chemin, proprio << 6 | masque << 3 | autres)
    enregistrer('acl.json', acl)
    return 0


def getfacl(args):
    chemin = args[-1]
    if echec_injecte(args) or not os.path.exists(chemin):
        sys.stderr.write('getfacl: introuvable\n')
        return 1
    mode = stat.S_IMODE(os.stat(chemin).st_mode)
    spec = charger('acl.json').get(chemin)
    brut = lambda b: ''.join(c if b & m else '-' for c, m in (('r', 4), ('w', 2), ('x', 1)))     # noqa: E731
    sortie = [f'user::{brut(mode >> 6 & 7)}']
    if spec is None:
        sortie += [f'group::{brut(mode >> 3 & 7)}', f'other::{brut(mode & 7)}']
    else:
        acces, defaut = entrees(spec)
        sortie += [f'user:{nom}:{perm}' for (genre, nom), perm in acces.items() if genre == 'u' and nom]
        sortie += [f"group::{acces.get(('g', ''), brut(mode >> 3 & 7))}", f'mask::{brut(mode >> 3 & 7)}',
                   f'other::{brut(mode & 7)}']
        etiquettes = {'u': 'user', 'g': 'group', 'o': 'other'}
        sortie += [f'default:{etiquettes[g]}:{n}:{perm3(p)}' for g, n, p in defaut]
        if defaut:
            sortie.append('default:mask::r-x')
    for ligne in sortie:
        print(ligne)
    return 0


def ots(args):
    if echec_injecte(args):
        sys.stderr.write(sortie_erreur_injectee())
        return 1
    chemin = args[-1]
    if args[0] == 'stamp':
        with open(chemin + '.ots', 'w') as f:
            f.write('EN-ATTENTE\n')
        return 0
    if not os.path.exists(os.path.join(ETAT, 'ancrage')):
        sys.stderr.write('preuve en attente\n')
        return 1
    shutil.copyfile(chemin, chemin + '.bak')
    os.unlink(chemin)
    with open(chemin, 'w') as f:
        f.write('ANCREE\n')
    return 0


if __name__ == '__main__':
    os.makedirs(ETAT, exist_ok=True)
    journaliser('ENV', ','.join(sorted(os.environ)))
    journaliser(NOM, *sys.argv[1:])
    sys.exit({'rsync': rsync, 'chattr': chattr, 'lsattr': lsattr, 'setfacl': setfacl, 'getfacl': getfacl,
              'ots': ots}[NOM](sys.argv[1:]))
