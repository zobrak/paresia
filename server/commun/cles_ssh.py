# SPDX-License-Identifier: AGPL-3.0-or-later
# Lecture sûre des clés SSH ; dépendances : bibliothèque standard, jumeaux et sshsig.
# Suivi des versions
#   3.0.0-alpha.41  2026-11-06  Analyse partagée et fichier de confiance root pour la présence ; lignes cert-authority ignorées (D20, D28).
import base64
import binascii
import hmac
import os
import re
import stat

from .jumeaux import MAX_LINE
from .sshsig import SignatureInvalide, TYPES

# Point d'injection des attributs pour les tests sans privilèges.
_attributs = os.fstat


def _lignes(chemin, proprietaires):
    """Lecture seule, régulière, bornée, sans lien final ; propriétaire contrôlé."""
    fd = os.open(chemin, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as fichier:
        attributs = _attributs(fichier.fileno())
        if (not stat.S_ISREG(attributs.st_mode) or attributs.st_uid not in proprietaires
                or attributs.st_mode & 0o022):
            raise ValueError()
        contenu = fichier.read(MAX_LINE + 1)
    if len(contenu) > MAX_LINE:
        raise ValueError()
    return contenu.decode('utf-8').split('\n')


def _champ(ligne):
    """Extrait un champ SSH ; dans des guillemets, seul \\" est un échappement (OpenSSH)."""
    ligne = ligne.lstrip(' \t')
    citation = False
    index = 0
    while index < len(ligne):
        caractere = ligne[index]
        if citation and caractere == '\\' and ligne[index + 1:index + 2] == '"':
            index += 1
        elif caractere == '"':
            citation = not citation
        elif caractere in ' \t' and not citation:
            return ligne[:index], ligne[index:].lstrip(' \t')
        index += 1
    if citation:
        raise ValueError()
    return ligne, ''


def _options_cert_authority(options):
    """Vrai si la liste d'options contient l'option cert-authority ; ValueError si mal formée.

    Les options sont séparées par des virgules hors guillemets ; dans une valeur citée,
    seul \\" est un échappement. Une valeur citée n'est donc jamais une option. Le nom est
    comparé sans tenir compte de la casse, et seule la forme exacte `cert-authority`
    (suivie d'une virgule ou de la fin) est reconnue.
    Source : OpenSSH, auth-options.c (sshauthopt_parse) et misc.c (opt_flag : strncasecmp ;
    opt_dequote : valeur entre guillemets lue, analyse reprise après le guillemet fermant),
    https://raw.githubusercontent.com/openssh/openssh-portable/master/auth-options.c et
    .../misc.c. Réserves : extraits établis par résumé, non copie intégrale ; la phase de
    repérage de la fin des options (sshkey_advance_past_options) n'a pas été lue.
    """
    elements = ['']
    citation = False
    index = 0
    while index < len(options):
        caractere = options[index]
        if citation and caractere == '\\' and options[index + 1:index + 2] == '"':
            elements[-1] += options[index:index + 2]
            index += 2
            continue
        if caractere == '"':
            citation = not citation
        if caractere == ',' and not citation:
            elements.append('')
        else:
            elements[-1] += caractere
        index += 1
    if citation:
        raise ValueError()
    return any(element.lower() == 'cert-authority' for element in elements)


def autorisee(chemin, admin, type_cle, publique, uid_app, journal):
    """Relit le fichier root à chaque preuve ; plusieurs clés par nom sont admises.

    Le refus des écritures groupe/autres exclut aussi une ACL effective en écriture
    (son masque est reflété dans les bits du groupe). L'uid app ne peut être root.
    """
    try:
        if uid_app == 0:
            raise ValueError()
        lignes = _lignes(chemin, {0})
        trouvee = False
        for ligne in lignes:
            if not ligne.strip() or ligne.lstrip().startswith('#'):
                continue
            genre, suite = _champ(ligne)
            options = ''
            if genre.encode('utf-8') not in TYPES:
                # Une liste d'options est un seul champ, y compris command="a b".
                candidat, reste = _champ(suite)
                if candidat.encode('utf-8') in TYPES:
                    options = genre
                    genre, suite = candidat, reste
                else:
                    journal.ecrire('info', 'key_ignored', reason='key_type')
                    continue
            # Seule l'option cert-authority est interprétée (la ligne désigne une autorité
            # de certification, non une clé d'admin). Les autres options (from=, restrict,
            # principals=) ne sont PAS appliquées par Pollux.
            # Une valeur citée contenant ce mot (ex. command="x,cert-authority") n'est pas
            # une option cert-authority. Options mal formées : ligne ignorée (biais sûr).
            try:
                autorite = _options_cert_authority(options)
            except ValueError:
                journal.ecrire('info', 'key_ignored', reason='options')
                continue
            if autorite:
                journal.ecrire('info', 'key_ignored', reason='cert_authority')
                continue
            valeur, commentaire = _champ(suite)
            commentaire = commentaire.rstrip(' \t')
            if re.fullmatch(r'[A-Za-z0-9._@-]{1,64}', commentaire) is None:
                continue
            try:
                blob = base64.b64decode(valeur, validate=True)
            except (ValueError, binascii.Error):
                continue
            if (commentaire == admin and genre.encode('ascii') == type_cle
                    and hmac.compare_digest(blob, publique)):
                trouvee = True
        return trouvee
    except (OSError, ValueError, UnicodeError):
        raise SignatureInvalide('keys_file') from None
