# Tips

Version du document : 0.1.19 · 2026-11-09 · [Accueil](Accueil.md)

Suivi, 2026-11-09 : première version de la page ; numéro du document inchangé (aucun numéro donné).

Cette page regroupe les petites aides d'ordre général : ce qu'un administrateur sait en principe faire, mais qu'il est utile d'avoir sous la main. Elle ne fait pas partie de l'installation. Les noms (`utilisateur`, `paresia-admin`) sont des exemples génériques.

## Sommaire

1. [Ajouter une clé à son agent SSH](#1-ajouter-une-clé-à-son-agent-ssh)

## 1. Ajouter une clé à son agent SSH

Un **agent SSH** est un petit programme de votre session qui garde vos clés privées en mémoire et signe à votre place. Les guides de ce wiki supposent que votre clé y est : ils vous renvoient ici si vous ne savez pas la lui confier.

Machine : votre poste, compte ordinaire. Faites tout dans **le même terminal** : l'agent n'existe que pour les programmes lancés depuis lui.

### À personnaliser

| Valeur | Où | Exemple du guide | Ce qu'il faut mettre |
| --- | --- | --- | --- |
| chemin de la clé privée | commande `ssh-add` | `~/.ssh/paresia-admin` | le fichier de votre clé privée (celui sans `.pub`) |

### a. Vérifier si un agent tourne

```
echo "$SSH_AUTH_SOCK"
```

Résultat attendu : un chemin de socket (sa forme dépend de votre bureau). Si rien ne s'affiche, aucun agent n'est actif dans ce terminal : passez à l'étape b. Sinon, passez à l'étape c.

Sous fish, cette commande affiche la même chose.

### b. Lancer un agent

Sous bash :

```
eval "$(ssh-agent -s)"
```

Sous fish :

```
eval (ssh-agent -c)
```

Résultat attendu, dans les deux cas : une ligne du type

```
Agent pid 12345
```

(le numéro varie). L'option `-s` fait écrire à `ssh-agent` des commandes pour un shell de type Bourne (bash), l'option `-c` pour un shell de type csh ; fish comprend cette seconde forme.

### c. Ajouter la clé

```
ssh-add ~/.ssh/paresia-admin
```

Résultat attendu, si la clé a une phrase secrète : le programme la demande, puis

```
Identity added: <chemin de la clé> (<nom de la clé>)
```

Le nom entre parenthèses est le commentaire de la clé (l'option `-C` de `ssh-keygen`).

**La phrase secrète demandée.** C'est celle que vous avez choisie en créant la clé avec `ssh-keygen` : elle protège le fichier de la clé privée. Tapez-la (rien ne s'affiche pendant la saisie) : elle n'est demandée qu'à l'ajout, puis l'agent garde la clé en mémoire jusqu'à la fin de la session de l'agent. Elle n'est enregistrée nulle part : si vous l'avez oubliée, il faut créer une nouvelle clé.

### d. Contrôler

```
ssh-add -l
```

Résultat attendu : une ligne par clé détenue par l'agent, de la forme

```
256 SHA256:EMPREINTE utilisateur (ED25519)
```

(taille, empreinte, nom de la clé, type). Si l'agent ne détient rien, la commande affiche `The agent has no identities.` : refaites l'étape c.

Pour voir la clé publique elle-même : `ssh-add -L` (une ligne qui commence par `ssh-ed25519 AAAA`).

### Réserves

La syntaxe fish (`eval (ssh-agent -c)`) et les sorties ci-dessus sont celles que donne l'usage courant d'OpenSSH ; elles n'ont pas été relues ici dans `man ssh-agent`, `man ssh-add` ni dans la documentation de fish : à confirmer à l'essai.
