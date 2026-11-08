# SPDX-License-Identifier: AGPL-3.0-or-later
# Journal JSON et syslog ; dépendances : bibliothèque standard, texte.
# Suivi des versions
#   0.1.1  2026-11-07  Détection du préfixe mémorisée pour chaque flux utilisé.
#   0.1.1  2026-11-07  Extensions du socle commun.
#   3.0.0-alpha  2026-11-05  Durcissement et corrections du cycle de revue 1.
#   3.0.0-alpha  2026-11-05  Format commun et masquage récursif.
import datetime
import json
import re
import sys
import syslog
import threading

from .texte import filtrer
from .systemd import flux_journal

_VERROU = threading.Lock()
# RFC 5424, § 6.2.1 : priorités numériques.
_NIVEAUX = {'debug': 7, 'notice': 5, 'critical': 2, 'info': syslog.LOG_INFO, 'warning': syslog.LOG_WARNING, 'error': syslog.LOG_ERR}
_SENSIBLES = ('token', 'passphrase', 'password', 'passwd', 'ncryptsec', 'nsec',
              'secret', 'privatekey', 'cleprivee', 'motdepasse', 'authorization',
              'cookie', 'credential', 'apikey', 'privkey', 'seed', 'mnemonic', 'bearer')


def _nettoyer(valeur):
    if isinstance(valeur, dict):
        resultat = {}
        for cle, contenu in valeur.items():
            if not isinstance(cle, str):
                raise ValueError('invalid_log_key')
            normalisee = re.sub('[^a-z0-9]', '', cle.lower())
            resultat[filtrer(cle)] = ('[REDACTED]' if any(m in normalisee for m in _SENSIBLES)
                                      else _nettoyer(contenu))
        return resultat
    if isinstance(valeur, (list, tuple)):
        return [_nettoyer(element) for element in valeur]
    if isinstance(valeur, str):
        return filtrer(valeur)
    if valeur is None or type(valeur) in (int, float, bool):
        return valeur
    # Ne jamais appeler str() sur une exception ou un objet arbitraire.
    raise ValueError('invalid_log_value')


class Journal:
    """Ne fournir que des métadonnées validées, jamais une requête ni ses params.

    destination vaut stdout ou syslog ; flux permet une capture en mémoire.
    Le masquage est une protection supplémentaire, pas une détection des secrets
    dans du texte libre.
    """

    def __init__(self, component, *, destination='stdout', flux=None, niveau='info', prefixe=None):
        if destination not in ('stdout', 'syslog'):
            raise ValueError('invalid_log_destination')
        self.component = component
        self.destination = destination
        self.flux = flux
        self.prefixe = prefixe
        self._flux_prefixe = None
        self._prefixe_detecte = False
        self.definir_niveau(niveau)
        self.compteur = None

    def definir_niveau(self, niveau):
        if niveau not in _NIVEAUX:
            raise ValueError('invalid_log_level')
        self.niveau = niveau

    def ecrire(self, level, event, **champs):
        if level not in _NIVEAUX or not re.fullmatch('[a-z][a-z0-9_]*', event):
            raise ValueError('invalid_log_event')
        if {'ts', 'level', 'component', 'event', 'params', 'requete', 'request'} & champs.keys():
            raise ValueError('reserved_log_field')
        if _NIVEAUX[level] > _NIVEAUX[self.niveau]:
            return
        objet = _nettoyer({
            'ts': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
            'level': level, 'component': self.component, 'event': event,
            **champs,
        })
        ligne = json.dumps(objet, ensure_ascii=True, allow_nan=False, separators=(',', ':'))
        if self.compteur is not None:
            self.compteur.incrementer(etiquettes={'daemon': self.component, 'level': level})
        with _VERROU:
            if self.destination == 'syslog':
                syslog.syslog(_NIVEAUX[level], ligne)
            else:
                flux = self.flux if self.flux is not None else sys.stdout
                if self.prefixe is None and flux is not self._flux_prefixe:
                    try:
                        self._prefixe_detecte = flux_journal(flux.fileno())
                    except (AttributeError, OSError, ValueError):
                        self._prefixe_detecte = False
                    self._flux_prefixe = flux
                if self.prefixe is True or (self.prefixe is None and self._prefixe_detecte):
                    ligne = f'<{_NIVEAUX[level]}>' + ligne
                print(ligne, file=flux, flush=True)
