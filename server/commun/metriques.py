# SPDX-License-Identifier: AGPL-3.0-or-later
# Suivi des versions
#   0.1.1  2026-11-07  Référence au manuel sans ambiguïté avec un appel.
#   0.1.1  2026-11-07  Permissions du dossier appliquées au descripteur sécurisé.
#   0.1.1  2026-11-07  Refus des temporaires liés et nettoyage limité aux échecs.
#   0.1.1  2026-11-07  Registre et collecteur textfile.
"""Format texte Prometheus 0.0.4 ; STATE_DIRECTORY selon systemd.exec, section 5."""
import errno
import math
import os
import re
import stat
import threading
import time

from .config import ErreurConfiguration

_NOM = re.compile(r'[a-zA-Z_:][a-zA-Z0-9_:]*')
_LABEL = re.compile(r'[a-zA-Z_][a-zA-Z0-9_]*')


def _echapper(texte, etiquette=False):
    texte = texte.replace('\\', '\\\\').replace('\n', '\\n')
    return texte.replace('"', '\\"') if etiquette else texte


class Jauge:
    # Les appelants ne fournissent que des étiquettes techniques sans identité ni secret.
    genre = 'gauge'

    def __init__(self, nom, aide=''):
        if not isinstance(nom, str) or not _NOM.fullmatch(nom) or len(nom) > 128 or not isinstance(aide, str) or len(aide) > 4096:
            raise ValueError('invalid_metric_name')
        self.nom, self.aide = nom, aide
        self._valeurs = {}
        self._verrou = threading.Lock()

    def _modifier(self, valeur, etiquettes, ajouter):
        if type(valeur) not in (int, float) or not math.isfinite(valeur) or (self.genre == 'counter' and valeur < 0):
            raise ValueError('invalid_metric_value')
        etiquettes = {} if etiquettes is None else etiquettes
        if len(etiquettes) > 8:
            raise ValueError('invalid_metric_labels')
        for cle, texte in etiquettes.items():
            if not isinstance(cle, str) or not _LABEL.fullmatch(cle) or cle.startswith('__') or len(cle) > 64:
                raise ValueError('invalid_metric_labels')
            if not isinstance(texte, str) or len(texte) > 256 or any(ord(c) < 32 and c != '\n' for c in texte):
                raise ValueError('invalid_metric_labels')
        cle = tuple(sorted(etiquettes.items()))
        with self._verrou:
            if cle not in self._valeurs and len(self._valeurs) >= 1024:
                raise ValueError('metric_series_limit')
            self._valeurs[cle] = self._valeurs.get(cle, 0) + valeur if ajouter else valeur

    def definir(self, valeur, *, etiquettes=None):
        self._modifier(valeur, etiquettes, False)

    def incrementer(self, valeur=1, *, etiquettes=None):
        self._modifier(valeur, etiquettes, True)

    def rendre(self):
        with self._verrou:
            valeurs = sorted(self._valeurs.items())
        lignes = [f'# HELP {self.nom} {_echapper(self.aide)}', f'# TYPE {self.nom} {self.genre}']
        for etiquettes, valeur in valeurs:
            labels = ','.join(f'{k}="{_echapper(v, True)}"' for k, v in etiquettes)
            lignes.append(self.nom + ('{' + labels + '}' if labels else '') + ' ' + str(valeur))
        return '\n'.join(lignes) + '\n'


class Compteur(Jauge):
    genre = 'counter'

    def definir(self, valeur, *, etiquettes=None):
        raise ValueError('counter_assignment_forbidden')


class Registre:
    def __init__(self):
        self._series = {}
        self._verrou = threading.Lock()

    def enregistrer(self, serie):
        with self._verrou:
            if serie.nom in self._series or len(self._series) >= 256:
                raise ValueError('duplicate_or_excess_metric')
            self._series[serie.nom] = serie
        return serie

    def rendre(self):
        with self._verrou:
            series = sorted(self._series.items())
        return ''.join(serie.rendre() for _, serie in series)


def dossier_configuration(options, environ):
    if not options.get('actif', False):
        return None
    dossier = options.get('dossier')
    if dossier is None:
        base = environ.get('STATE_DIRECTORY', '').split(':')[0]
        dossier = os.path.join(base, 'metriques') if base else None
    if not dossier or not os.path.isabs(dossier) or '\0' in dossier:
        raise ErreurConfiguration('config_missing', 'metriques', 'dossier')
    return dossier


class Collecteur:
    def __init__(self, nom, version, journal, options, environ):
        if not re.fullmatch('[a-z][a-z0-9_-]{0,63}', nom):
            raise ValueError('invalid_metric_daemon')
        self.nom, self.journal = nom, journal
        self.dossier = dossier_configuration(options, environ)
        self.periode = options.get('periode_s', 15)
        if not isinstance(self.periode, (int, float)) or not math.isfinite(self.periode) or not 0 < self.periode <= 3600:
            raise ErreurConfiguration('config_invalid', 'metriques', 'periode_s')
        self.registre = Registre()
        labels = {'daemon': nom}
        self.up = self.registre.enregistrer(Jauge('paresia_up'))
        self.up.definir(1, etiquettes=labels)
        self.registre.enregistrer(Jauge('paresia_info')).definir(1, etiquettes={**labels, 'version': version})
        self.registre.enregistrer(Jauge('paresia_start_time_seconds')).definir(time.time(), etiquettes=labels)
        journal.compteur = self.registre.enregistrer(Compteur('paresia_log_events_total'))
        for niveau in ('debug', 'info', 'notice', 'warning', 'error', 'critical'):
            journal.compteur.incrementer(0, etiquettes={'daemon': nom, 'level': niveau})
        self._fin = threading.Event()
        self._ecriture = threading.Lock()
        self._fil = None

    def ecrire(self):
        if self.dossier is None:
            return
        with self._ecriture:
            temporaire = self.nom + '.prom.tmp'
            fd_dossier = None
            cree = False
            dossier_cree = False
            try:
                try:
                    os.mkdir(self.dossier, 0o755)
                    dossier_cree = True
                except FileExistsError:
                    pass
                fd_dossier = os.open(self.dossier, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                if not stat.S_ISDIR(os.fstat(fd_dossier).st_mode):
                    raise NotADirectoryError()
                if dossier_cree:
                    os.fchmod(fd_dossier, 0o755)
                try:
                    residuel = os.stat(temporaire, dir_fd=fd_dossier, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    if stat.S_ISLNK(residuel.st_mode):
                        raise OSError(errno.ELOOP, 'metrics_temporary_symlink')
                    if not stat.S_ISREG(residuel.st_mode):
                        raise OSError(errno.EINVAL, 'metrics_temporary_invalid')
                    os.unlink(temporaire, dir_fd=fd_dossier)
                fd = os.open(temporaire, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=fd_dossier)
                cree = True
                with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as sortie:
                    os.fchmod(sortie.fileno(), 0o644)
                    sortie.write(self.registre.rendre())
                    sortie.flush()
                    os.fsync(sortie.fileno())
                os.rename(temporaire, self.nom + '.prom', src_dir_fd=fd_dossier, dst_dir_fd=fd_dossier)
                cree = False
            except OSError as erreur:
                self.journal.ecrire('error', 'metrics_write_failed', errno=erreur.errno)
            finally:
                if fd_dossier is not None:
                    if cree:
                        try:
                            os.unlink(temporaire, dir_fd=fd_dossier)
                        except OSError as erreur:
                            if erreur.errno != errno.ENOENT:
                                self.journal.ecrire('error', 'metrics_write_failed', errno=erreur.errno)
                    os.close(fd_dossier)

    def demarrer(self):
        if self.dossier is not None:
            self._fil = threading.Thread(target=self._boucle, daemon=True)
            self._fil.start()

    def _boucle(self):
        while not self._fin.is_set():
            self.ecrire()
            self._fin.wait(self.periode)

    def arreter(self):
        self._fin.set()
        if self._fil is not None:
            self._fil.join(timeout=0.2)
        self.up.definir(0, etiquettes={'daemon': self.nom})
        if self.dossier is not None:
            # Le stockage peut être indisponible : aucune attente illimitée à l'arrêt.
            dernier = threading.Thread(target=self.ecrire, daemon=True)
            dernier.start()
            dernier.join(timeout=2)
