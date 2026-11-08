# SPDX-License-Identifier: AGPL-3.0-or-later
# Nisaba : métriques au format texte d'exposition Prometheus (C35) ; dépendances : bibliothèque standard.
# Format : « Exposition formats / Text-based format » de la documentation Prometheus : lignes
# « # HELP nom texte », « # TYPE nom type », échantillons « nom{etiquette="valeur"} nombre » ; HELP
# échappe « \ » et le saut de ligne ; une valeur d'étiquette échappe « \ », « " » et le saut de ligne.
# Suivi des versions
#   3.0.0-alpha.40  2026-11-06  Création (T031) : registre en mémoire et rendu texte (aucun serveur HTTP).
import re
import threading

_NOM = re.compile(r'[a-zA-Z_:][a-zA-Z0-9_:]*')


class Metriques:
    """Compteurs d'échecs et dernières réussites par tâche ; les jauges du journal viennent du relevé."""

    def __init__(self):
        self._verrou = threading.Lock()
        self._reussites = {}
        self._echecs = {}

    def succes(self, tache, instant):
        with self._verrou:
            self._reussites[tache] = instant

    def echec(self, tache, code):
        with self._verrou:
            self._echecs[(tache, code)] = self._echecs.get((tache, code), 0) + 1

    def instantane(self, releve):
        """Structure JSON des séries ; releve = résultat de etat.collecter()."""
        with self._verrou:
            return {'derniere_reussite': dict(self._reussites),
                    'echecs': [{'tache': t, 'code': c, 'n': n} for (t, c), n in sorted(self._echecs.items())],
                    'journees': releve['journees'], 'preuves': dict(releve['preuves']),
                    'age_plus_ancien_s': releve['age_plus_ancien_s']}


def _etiquette(valeur):
    return str(valeur).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')


def _nombre(valeur):
    return repr(float(valeur)) if isinstance(valeur, float) else str(int(valeur))


def rendre(instantane, aide):
    """Texte d'exposition ; aide[nom] = texte HELP (catalogue i18n, fourni par l'appelant)."""
    sortie = []

    def serie(nom, genre, echantillons):
        if not _NOM.fullmatch(nom):
            raise ValueError('invalid_metric_name')
        texte = str(aide.get(nom, nom)).replace('\\', '\\\\').replace('\n', '\\n')
        sortie.append(f'# HELP {nom} {texte}')
        sortie.append(f'# TYPE {nom} {genre}')
        for etiquettes, valeur in echantillons:
            marque = ''.join(f'{cle}="{_etiquette(v)}",' for cle, v in etiquettes)
            sortie.append(f'{nom}{{{marque[:-1]}}} {_nombre(valeur)}' if marque else f'{nom} {_nombre(valeur)}')

    serie('nisaba_last_success_timestamp_seconds', 'gauge',
          [((('tache', t),), v) for t, v in sorted(instantane['derniere_reussite'].items())])
    serie('nisaba_failures_total', 'counter',
          [((('tache', e['tache']), ('code', e['code'])), e['n']) for e in instantane['echecs']])
    serie('nisaba_manifest_days', 'gauge', [((), instantane['journees'])])
    serie('nisaba_proofs', 'gauge',
          [((('etat', k),), instantane['preuves'][k]) for k in ('ancrees', 'en_attente', 'non_soumises')])
    age = instantane['age_plus_ancien_s']
    serie('nisaba_oldest_journal_age_seconds', 'gauge', [] if age is None else [((), age)])
    return '\n'.join(sortie) + '\n'
