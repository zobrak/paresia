# SPDX-License-Identifier: AGPL-3.0-or-later
# Banc de test de la copie, du scellement, de l'horodatage et des droits de Nisaba (T033) : simulacres des
# programmes externes (outil.py), relais simulé, état injectable ; dépendances : bibliothèque standard.
# Suivi des versions
#   3.0.0-alpha.41  2026-11-06  Création (T033).
import io
import json
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nisaba_outils import Horloge, configuration, journal_capture  # noqa: E402
from server.nisaba import Nisaba  # noqa: E402

OUTIL = Path(__file__).resolve().parent / 'outil.py'
PROGRAMMES = ('rsync', 'chattr', 'lsattr', 'setfacl', 'getfacl', 'ots', 'ssh')
SOURCE = 'journalpull@backend-relais:/'
CLE = '/etc/paresia/cle-de-test'
COMPTE = 'compte-test'


class BancJournal:
    """Nisaba non démarré, simulacres copiés dans bin/, relais simulé dans bin/relais/."""

    def __init__(self, tmp_path, dossier_socket=None, **horaire):
        self.base = Path(tmp_path)
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        for nom in PROGRAMMES:
            shutil.copy(OUTIL, self.bin / nom)
            (self.bin / nom).chmod(0o755)
        self.relais = self.bin / 'relais'
        self.relais.mkdir()
        self.etat_outils = self.bin / 'etat'
        self.etat_outils.mkdir()
        self.racine = self.base / 'racine'
        self.journal = self.racine / 'journal-legal'
        self.journal.mkdir(parents=True)
        self.etat = self.base / 'etat-nisaba'
        self.etat.mkdir()
        self.horloge = Horloge()
        self.journal_json, self.flux = journal_capture()
        self.sortie = io.StringIO()
        config = configuration(dossier_socket or self.base, self.journal, self.etat, **horaire)
        config['journal'].update(lsattr=str(self.bin / 'lsattr'), chattr=str(self.bin / 'chattr'),
                                 compte_acl=COMPTE)
        config['source'] = {'source': SOURCE, 'cle_ssh': CLE, 'rsync': str(self.bin / 'rsync'),
                            'ssh': str(self.bin / 'ssh'), 'connexion_s': 20, 'rsync_s': 50}
        config['ots'] = {'ots': str(self.bin / 'ots'), 'attente_max_jours': 3, 'delai_s': 30}
        config['droits'] = {'chattr': str(self.bin / 'chattr'), 'setfacl': str(self.bin / 'setfacl'),
                            'getfacl': str(self.bin / 'getfacl'), 'compte': COMPTE}
        self.config = config
        self.nisaba = Nisaba(config, horloge=self.horloge, journal=self.journal_json, sortie=self.sortie)

    # -- relais et état simulés -------------------------------------------------------
    def relais_ecrire(self, nom, texte):
        (self.relais / nom).write_text(texte)

    def journal_ecrire(self, jour, texte, mode=0o644):
        chemin = self.journal / f'journal-{jour}.jsonl'
        chemin.write_text(texte)
        chemin.chmod(mode)
        return chemin

    def appels(self):
        """[(programme, [arguments])] dans l'ordre ; les lignes ENV et MODE sont rendues à part."""
        fichier = self.etat_outils / 'appels.log'
        if not fichier.exists():
            return []
        return [(m[0], m[1:]) for m in (ligne.split('\t') for ligne in fichier.read_text().splitlines())]

    def appels_de(self, programme):
        return [args for nom, args in self.appels() if nom == programme]

    def vider_appels(self):
        (self.etat_outils / 'appels.log').unlink(missing_ok=True)

    def _json(self, nom):
        fichier = self.etat_outils / nom
        return json.loads(fichier.read_text()) if fichier.exists() else {}

    def attributs(self, chemin):
        return self._json('attributs.json').get(str(chemin), '')

    def poser_attributs(self, chemin, lettres):
        donnees = self._json('attributs.json')
        donnees[str(chemin)] = lettres
        (self.etat_outils / 'attributs.json').write_text(json.dumps(donnees))

    def acl(self, chemin):
        return self._json('acl.json').get(str(chemin))

    def poser_acl(self, chemin, spec):
        donnees = self._json('acl.json')
        donnees[str(chemin)] = spec
        (self.etat_outils / 'acl.json').write_text(json.dumps(donnees))

    def echec(self, programme, *motifs, erreur=None):
        (self.etat_outils / f'echec-{programme}').write_text('\n'.join(motifs))
        if erreur is not None:
            (self.etat_outils / f'stderr-{programme}').write_text(erreur)

    def drapeau(self, nom, present=True):
        fichier = self.etat_outils / nom
        fichier.touch() if present else fichier.unlink(missing_ok=True)

    def sortie_lignes(self):
        return self.sortie.getvalue().splitlines()

    def evenements(self):
        return [json.loads(ligne) for ligne in self.flux.getvalue().splitlines()]
