# SPDX-License-Identifier: AGPL-3.0-or-later
# Catalogue du noyau (actions presence/* et castor/*) ; dépendances : catalogue.
# Suivi des versions
#   0.1.17  2026-11-08  Descripteurs du noyau, source unique de la liste fermée (D154).
"""Descripteurs des actions du noyau, calculés une fois pour toutes.

Les paramètres et erreurs reprennent le § 5.3 de docs/protocole.md ; les bornes des
paramètres reprennent les contrôles de Pollux. Une action sans paramètre n'en déclare
aucun. Les actions de catalogue (`<domaine>/catalog/…`) ne figurent pas ici : elles sont
définies par leur suffixe. Chaque action est écrite en chaîne complète.
"""
from types import MappingProxyType

from .catalogue import CIBLE_DEFAUT, Catalogue, Parametre, creer_descripteur

_ADMIN = Parametre('admin', 'texte', {'motif': '[A-Za-z0-9._@-]{1,64}', 'longueur_max': 64})
_SOURCE = Parametre('source', 'texte', {'motif': '[0-9A-Fa-f:.]{2,45}', 'longueur_max': 45})
_SIGNATURE = Parametre('signature', 'texte', {'motif': '[A-Za-z0-9+/=]+', 'longueur_max': 2048})


def _d(action, parametres=(), erreurs=()):
    return creer_descripteur(action, parametres=parametres, erreurs=erreurs)


_PRESENCE = (
    _d('presence/session/challenge', (_ADMIN, _SOURCE),
       ('bad_request', 'challenge_required', 'auth_info_unavailable')),
    _d('presence/session/open', (_ADMIN, _SOURCE, _SIGNATURE),
       ('bad_request', 'challenge_required', 'challenge_expired', 'signature_invalid',
        'session_limit', 'auth_info_unavailable', 'not_available')),
    _d('presence/session/ping', erreurs=('bad_request', 'session_closed')),
    _d('presence/session/close', erreurs=('bad_request', 'session_closed')),
    _d('presence/relay/ping', erreurs=('bad_request', 'session_closed', 'peer_unavailable')),
)
_CASTOR = (
    _d('castor/light/ping', erreurs=('bad_request', 'session_closed', 'session_limit')),
    _d('castor/light/state', erreurs=('bad_request', 'session_closed')),
    _d('castor/light/close', erreurs=('bad_request',)),
)


class CatalogueNoyau:
    """Agrégat immuable des descripteurs du noyau (plusieurs domaines, sans catalog/*)."""
    __slots__ = ('_descripteurs',)

    def __init__(self, descripteurs):
        # Validation par la classe Catalogue : unicité des actions et des noms Varlink,
        # un domaine par instance (elle ajoute d'office ses actions de catalogue).
        par_domaine = {}
        for descripteur in descripteurs:
            par_domaine.setdefault(descripteur.action.split('/')[0], []).append(descripteur)
        for domaine, liste in par_domaine.items():
            Catalogue(CIBLE_DEFAUT, domaine, liste)
        object.__setattr__(self, '_descripteurs',
                           MappingProxyType({d.action: d for d in descripteurs}))

    def __setattr__(self, nom, valeur):
        raise AttributeError('immutable_catalog')

    @property
    def descripteurs(self):
        return self._descripteurs

    @property
    def actions(self):
        return frozenset(self._descripteurs)


CATALOGUE_NOYAU = CatalogueNoyau(_PRESENCE + _CASTOR)
