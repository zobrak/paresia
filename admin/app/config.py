# SPDX-License-Identifier: AGPL-3.0-or-later
# Configuration du poste client ; dépendances : bibliothèque standard et server.commun.
# Suivi des versions
#   0.1.19  2026-11-08  Refus du caractère pour cent dans l’adresse HTTPS.
#   0.1.12  2026-11-08  Option ssh_keygen.
#   3.0.0-alpha.40  2026-11-06  Couches de configuration et validation du poste client.
import ipaddress
import re
from urllib.parse import urlsplit

from server.commun.config import ErreurConfiguration, Option, lire
from server.commun.texte import filtrer


SCHEMA = {
    ('connexion', 'url'): Option('texte'),
    ('connexion', 'hote_ssh'): Option('texte'),
    ('connexion', 'compte_ssh'): Option('compte'),
    ('connexion', 'ssh'): Option('chemin'),
    ('cle', 'cle_publique'): Option('chemin'),
    ('cle', 'commande_forcee'): Option('chemin'),
    ('cle', 'ssh_keygen'): Option('chemin'),
    ('presence', 'ouverture_s'): Option('duree', defaut=90),
    ('interface', 'langue'): Option('texte'),
    ('interface', 'dossier_i18n'): Option('chemin'),
}


def _hote_valide(hote):
    """Nom DNS ou adresse IP, sans résolution ni syntaxe d'option SSH."""
    if (not hote or not re.fullmatch(r'[A-Za-z0-9.:%_-]+', hote)
            or hote.startswith('-') or filtrer(hote) != hote
            or any(c.isspace() for c in hote)):
        return False
    try:
        ipaddress.ip_address(hote)
        return True
    except ValueError:
        return len(hote) <= 253 and all(
            re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', label)
            for label in hote.removesuffix('.').split('.')
        )


def _url_valide(url):
    """Adresse HTTPS de base uniquement ; aucun identifiant ni suffixe."""
    if (not url.startswith('https://') or filtrer(url) != url
            or any(c.isspace() for c in url) or '?' in url or '#' in url or '%' in url
            or not re.fullmatch(r'https://(?:\[[^\[\]]+\]|[A-Za-z0-9.-]+)(?::[0-9]+)?', url)):
        return False
    try:
        parties = urlsplit(url)
        return (parties.username is None and parties.password is None
                and not parties.path and _hote_valide(parties.hostname)
                and (parties.port is None or parties.port > 0)
                and not parties.netloc.endswith(':'))
    except ValueError:
        return False


def configuration(argv=None, *, environ=None, racine_systeme=None,
                  repertoire_utilisateur=None):
    """Charge les couches du composant admin et contrôle les valeurs finales."""
    resultat = lire('admin', SCHEMA, argv=argv, environ=environ, utilisateur=True,
                    racine_systeme=racine_systeme,
                    repertoire_utilisateur=repertoire_utilisateur)
    for domaine, cle, valide in (
        ('connexion', 'url', _url_valide(resultat['connexion']['url'])),
        ('connexion', 'hote_ssh', _hote_valide(resultat['connexion']['hote_ssh'])),
        ('interface', 'langue', re.fullmatch(r'[a-z]{2}-[A-Z]{2}',
                                          resultat['interface']['langue'])),
    ):
        if not valide:
            raise ErreurConfiguration('config_invalid', domaine, cle)
    return resultat
