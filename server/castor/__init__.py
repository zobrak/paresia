# SPDX-License-Identifier: AGPL-3.0-or-later
# Castor : un feu de circulation par session de présence ; dépendances : bibliothèque standard et server.commun.
# Suivi des versions
#   3.0.0-alpha  2026-11-05  Feux, deux sockets aux appelants distincts, journal d'audit (T020).
from collections import OrderedDict
import math
import os
import threading
import time

from server.commun.config import ErreurConfiguration, Option
from server.commun.journal import Journal
from server.commun.jumeaux import MAX_LINE, reponse
from server.commun.serveur import Serveur

SCHEMA = {
    ('tunnel', 'socket'): Option('chemin'),
    ('tunnel', 'uid'): Option('uid'),
    ('tunnel', 'gid'): Option('uid'),
    ('state', 'socket'): Option('chemin'),
    ('state', 'uid'): Option('uid'),
    ('state', 'gid'): Option('uid'),
    ('lights', 'heartbeat_s'): Option('duree', 30),
    ('lights', 'margin_s'): Option('duree', 5),
    ('lights', 'maximum'): Option('limite', 64),
    ('lights', 'closed_s'): Option('duree', 10),
    ('lights', 'verification_s'): Option('duree', 1),
    ('transport', 'delai_s'): Option('duree', 30),
    ('transport', 'max_line'): Option('limite', MAX_LINE),
    ('transport', 'max_connexions'): Option('limite', 64),
}

ACTIONS_TUNNEL = frozenset({'castor/light/ping', 'castor/light/close'})
ACTIONS_ETAT = frozenset({'castor/light/state'})


class Castor:
    """Un feu par session ; toutes les échéances viennent de l'horloge monotone injectée.

    Les transitions sont sérialisées par un verrou. Les événements de journal sont
    collectés sous le verrou et écrits après sa libération : un journal lent ne
    bloque jamais une requête. L'état renvoyé par state est calculé à la demande
    avec l'horloge, sans dépendre du fil de surveillance. En cas de doute, rouge.
    """

    def __init__(self, configuration, *, horloge=time.monotonic, journal=None):
        lumieres = configuration['lights']
        if lumieres['heartbeat_s'] + lumieres['margin_s'] > 3600:
            raise ErreurConfiguration('config_invalid', 'lights', 'margin_s')
        if os.fspath(configuration['tunnel']['socket']) == os.fspath(configuration['state']['socket']):
            raise ErreurConfiguration('config_invalid', 'state', 'socket')
        self.config = configuration
        self.horloge = horloge
        self.journal = journal if journal is not None else Journal('castor')
        self.vert_s = lumieres['heartbeat_s'] + lumieres['margin_s']
        self.maximum = lumieres['maximum']
        self.ferme_s = lumieres['closed_s']
        self.periode = lumieres['verification_s']
        self._verrou = threading.Lock()
        self._feux = {}                  # session -> échéance
        self._fermees = OrderedDict()    # session -> fin de la mémoire de fermeture
        self._arret = threading.Event()
        self._fil = None
        self._demarre = False
        transport = configuration['transport']
        self.serveurs = []
        for section, actions, traitement in (
            ('tunnel', ACTIONS_TUNNEL, self._tunnel),
            ('state', ACTIONS_ETAT, self._etat),
        ):
            options = configuration[section]
            self.serveurs.append(Serveur(
                options['socket'], {options['uid']}, actions, traitement,
                gid=options['gid'], max_line=transport['max_line'],
                delai=transport['delai_s'], max_connexions=transport['max_connexions'],
                journal=self.journal))

    # -- état (appeler sous verrou) -------------------------------------------------
    def _purger(self, maintenant, evenements):
        for numero in [n for n, e in self._feux.items() if maintenant >= e]:
            del self._feux[numero]
            evenements.append(('info', 'light_expired', {'session': numero}))
        for numero in [n for n, f in self._fermees.items() if maintenant >= f]:
            del self._fermees[numero]

    def _ecrire(self, evenements):
        for niveau, nom, champs in evenements:
            self.journal.ecrire(niveau, nom, **champs)

    @staticmethod
    def _refus(q, code, evenements):
        evenements.append(('warning', 'request_refused',
                           {'session': q['session'], 'reason': code}))
        return reponse(q['id'], code=code)

    # -- actions --------------------------------------------------------------------
    def _ping(self, q, evenements):
        numero = q['session']
        maintenant = self.horloge()
        self._purger(maintenant, evenements)
        if numero in self._fermees:
            return self._refus(q, 'session_closed', evenements)
        if numero not in self._feux:
            if len(self._feux) >= self.maximum:
                return self._refus(q, 'session_limit', evenements)
            evenements.append(('info', 'light_green', {'session': numero}))
        self._feux[numero] = maintenant + self.vert_s
        return reponse(q['id'])

    def _close(self, q, evenements):
        numero = q['session']
        maintenant = self.horloge()
        self._purger(maintenant, evenements)
        self._feux.pop(numero, None)
        self._fermees.pop(numero, None)
        self._fermees[numero] = maintenant + self.ferme_s
        while len(self._fermees) > self.maximum:
            self._fermees.popitem(last=False)
        evenements.append(('info', 'light_closed', {'session': numero, 'reason': 'close'}))
        return reponse(q['id'])

    def _state(self, q, evenements):
        numero = q['session']
        maintenant = self.horloge()
        fin = self._fermees.get(numero)
        if fin is not None and maintenant < fin:
            return self._refus(q, 'session_closed', evenements)
        echeance = self._feux.get(numero)
        if echeance is not None and maintenant < echeance:
            return reponse(q['id'], {'state': 'green',
                                     'remaining_s': max(1, math.ceil(echeance - maintenant))})
        return reponse(q['id'], {'state': 'red'})

    def _traiter(self, q, actions):
        evenements = []
        with self._verrou:
            if q['session'] < 1 or q['params']:
                resultat = self._refus(q, 'bad_request', evenements)
            else:
                resultat = actions[q['action']](q, evenements)
        self._ecrire(evenements)
        return resultat

    def _tunnel(self, q, _):
        return self._traiter(q, {'castor/light/ping': self._ping,
                                 'castor/light/close': self._close})

    def _etat(self, q, _):
        return self._traiter(q, {'castor/light/state': self._state})

    # -- surveillance et cycle de vie -----------------------------------------------
    def verifier(self):
        """Une passe de purge : journalise les expirations."""
        evenements = []
        with self._verrou:
            self._purger(self.horloge(), evenements)
        self._ecrire(evenements)

    def _surveiller(self):
        while not self._arret.wait(self.periode):
            try:
                self.verifier()
            except Exception:
                self.journal.ecrire('error', 'monitor_failed')

    def demarrer(self):
        try:
            for serveur in self.serveurs:
                ancien = os.umask(0o177)
                try:
                    serveur.demarrer()
                finally:
                    os.umask(ancien)
            self._arret.clear()
            self._fil = threading.Thread(target=self._surveiller, daemon=True)
            self._fil.start()
            self._demarre = True
        except BaseException:
            self.arreter()
            raise
        self.journal.ecrire('info', 'startup')
        return self

    def arreter(self):
        self._arret.set()
        for serveur in self.serveurs:
            serveur.arreter()
        if self._fil is not None:
            self._fil.join()
            self._fil = None
        with self._verrou:
            self._feux.clear()
            self._fermees.clear()
        if self._demarre:
            self._demarre = False
            self.journal.ecrire('info', 'shutdown')

    def __enter__(self):
        return self.demarrer()

    def __exit__(self, *_):
        self.arreter()
