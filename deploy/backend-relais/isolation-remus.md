# Isolation de Remus : décisions

SPDX-License-Identifier: AGPL-3.0-or-later

Version du document : 0.1.16 · 2026-11-08 · public : administrateur.
Source : pages anglaises installées, systemd **257.13** (pied de systemd.exec(5)).
La version de la cible sera relevée à l’étape 1 de la procédure. Ce document
décrit l’isolation de l’unité remus.service, livrée avec lui. Les valeurs sont les
valeurs à éprouver sur la cible, pas une preuve d’exécution.

| Directive | Décision | Valeur dans remus.service | Citation (page, extrait) | Compensation |
| --- | --- | --- | --- | --- |
| LimitCORE | conservée | `0` | systemd.exec(5) : « Set soft and hard limits on various resources for executed processes. » | Pas de vidage mémoire. |
| NoNewPrivileges | retirée | `absente (défaut false)` | systemd.exec(5) : « Takes a boolean argument. If true, ensures that the service process and all its children can never gain new privileges through execve() (e.g. via setuid or setgid bits, or filesystem capabilities). This is the simplest and most effective » | Sudoers fermé ; chef sans shell, sans mot de passe, hors docker ; validation par gabarits ; NoNewPrivs=0 à contrôler. |
| CapabilityBoundingSet | adaptée | `CAP_SETUID CAP_SETGID CAP_AUDIT_WRITE` | systemd.exec(5) : « Capabilities listed will be included in the bounding set, all others are removed. » | Minimum proposé pour identité et audit, justifié ci-dessous ; à vérifier sur la cible (PAM, sockets Remus). Aucun CAP_SYS_ADMIN. |
| AmbientCapabilities | conservée | `` | systemd.exec(5) : « If the empty string is assigned to this option, the ambient capability set is reset to the empty capability set » | Aucune capacité ambiante à chef ; acquisition setuid bornée. |
| ProtectSystem | conservée | `strict` | systemd.exec(5) : « Takes a boolean argument or the special values "full" or "strict". If true, mounts the /usr/ and the boot loader directories (/boot and /efi) read-only for processes invoked by this unit. If set to "full", the /etc/ directory is mounted read-only, too. If set to "strict" the entire file system hierarchy is mounted read-only, except for the API file system subtrees /dev/, /proc/ and /sys/ » | Système en lecture seule ; seules les exceptions ReadWritePaths sont ouvertes. |
| ProtectHome | conservée | `yes` | systemd.exec(5) : « Takes a boolean argument or the special values "read-only" or "tmpfs". If true, the directories /home/, /root, and /run/user are made inaccessible and empty for processes invoked by this unit. If set to "read-only", the three directories » | à vérifier sur la cible : configuration Docker de root masquée ; aucune authentification au registre supposée. |
| PrivateTmp | conservée | `yes` | systemd.exec(5) : « Takes a boolean argument, or "disconnected". If enabled, a new file system namespace will be set up for the executed processes, and /tmp/ and /var/tmp/ directories inside it are not shared with processes outside of the namespace, plus all temporary files created by a service » | à vérifier sur la cible : /tmp privé, aucun échange de fichiers Docker supposé. |
| PrivateDevices | conservée | `yes` | systemd.exec(5) : « Takes a boolean argument. If true, sets up a new /dev/ mount for the executed processes and only adds API pseudo devices such as /dev/null, /dev/zero or /dev/random (as well as the pseudo TTY subsystem) to it, but no physical devices such as /dev/sda, system memory /dev/mem, system » | à vérifier sur la cible : pseudo-terminaux de sudo, API /dev ; le démon Docker reste extérieur. |
| ProtectKernelTunables | conservée | `yes` | systemd.exec(5) : « Takes a boolean argument. If true, kernel variables accessible through /proc/sys/, /sys/, /proc/sysrq-trigger, /proc/latency_stats, /proc/acpi, /proc/timer_stats, /proc/fs and /proc/irq will be made read-only and /proc/kallsyms as well as /proc/kcore will be inaccessible to all processes of the unit. Usually, tunable kernel variables should be » | Aucun réglage noyau requis par le client Docker. |
| ProtectKernelModules | conservée | `yes` | systemd.exec(5) : « Takes a boolean argument. If true, explicit module loading will be denied. This allows module load and unload operations to be turned » | Aucun module à charger par le client. |
| ProtectKernelLogs | conservée | `yes` | systemd.exec(5) : « Takes a boolean argument. If true, access to the kernel log ring buffer will be denied. It is recommended to turn this on » | chef ne lit pas le journal du noyau. |
| ProtectControlGroups | conservée | `yes` | systemd.exec(5) : « Takes a boolean argument or the special values "private" or "strict". If true, the Linux Control Groups (cgroups(7)) hierarchies accessible through /sys/fs/cgroup/ will be made read-only to all processes of the unit. If set to "private", the unit will run in a cgroup namespace with a » | Le démon Docker extérieur gère ses groupes ; à vérifier sur la cible. |
| ProtectClock | conservée | `yes` | systemd.exec(5) : « Takes a boolean argument. If set, writes to the hardware clock or system clock will be denied. Defaults to off. Enabling this option removes » | Aucun changement d’horloge requis. |
| ProtectHostname | conservée | `yes` | systemd.exec(5) : « Takes a boolean argument. When set, sets up a new UTS namespace for the executed processes. In addition, changing hostname or domainname is prevented. Defaults to off. Note that the » | Aucun changement de nom requis. |
| ProtectProc | conservée | `invisible` | systemd.exec(5) : « Takes one of "noaccess", "invisible", "ptraceable" or "default" (which it defaults to). When set, this controls the "hidepid=" mount option of the "procfs" instance for the unit that controls which directories with process metainformation (/proc/PID) are visible and accessible: when set to "noaccess" the ability to access most of other users' process metadata in /proc/ is taken » | à vérifier sur la cible : métadonnées sudo et surveillance par gabarits. |
| RestrictAddressFamilies | conservée | `AF_UNIX` | systemd.exec(5) : « Restricts the set of socket address families accessible to the processes of this unit. Takes "none", or a space-separated list of address family names to allow-list, such as AF_UNIX, AF_INET or AF_INET6. When "none" is specified, then all address families » | à vérifier sur la cible : audit PAM potentiellement AF_NETLINK ; ne pas l’ajouter sans constat et citation. |
| RestrictNamespaces | conservée | `yes` | systemd.exec(5) : « Restricts access to Linux namespace functionality for the processes of this unit. For details about Linux namespaces, see namespaces(7). Either takes a boolean argument, or a space-separated list of namespace type identifiers. If false (the default), no restrictions on namespace creation and switching are made. If true, access to any kind of namespacing is prohibited. Otherwise, a space-separated list of namespace » | à vérifier sur la cible : le client ne crée pas les conteneurs lui-même. |
| RestrictRealtime | conservée | `yes` | systemd.exec(5) : « Takes a boolean argument. If set, any attempts to enable realtime scheduling in a process of the unit are refused. This restricts access to realtime task scheduling policies such as SCHED_FIFO, SCHED_RR » | Aucune politique temps réel requise. |
| RestrictSUIDSGID | conservée | `yes` | systemd.exec(5) : « Takes a boolean argument. If set, any attempts to set the set-user-ID (SUID) or set-group-ID (SGID) bits on files or directories will be denied (for details on these bits see inode(7)). As the SUID/SGID bits are mechanisms to elevate privileges, and allow users to » | Interdit de poser les bits, pas d’exécuter un fichier setuid existant ; vérifier NoNewPrivs. |
| LockPersonality | conservée | `yes` | systemd.exec(5) : « Takes a boolean argument. If set, locks down the personality(2) system call so that the kernel execution domain may not be changed from the default or the personality selected with Personality= directive. This may be useful to improve security, because odd » | Personnalité native conservée. |
| SystemCallArchitectures | conservée | `native` | systemd.exec(5) : « Takes a space-separated list of architecture identifiers to include in the system call filter. The known architecture identifiers are the same as for ConditionArchitecture= described in systemd.unit(5), as well as x32, mips64-n32, mips64-le-n32, and the special identifier native. The special identifier native implicitly maps to the native architecture of the » | à vérifier sur la cible : sudo et Docker doivent être natifs. |
| SystemCallFilter | conservée | `@system-service` | systemd.exec(5) : « Takes a space-separated list of system call names or system call groups. If this setting is used, system calls executed by the unit processes except for the listed ones will result in the system call being denied (allow-listing). If the first character of the list » | à vérifier sur la cible : appels d’identité et PAM ; aucun ajout global de @privileged. |
| UMask | conservée | `0077` | systemd.exec(5) : « Controls the file mode creation mask. Takes an access mode in octal notation. See umask(2) for details. Defaults to 0022 » | Fichiers créés privés. |
| MemoryDenyWriteExecute | conservée | `absente (comme pollux.service)` | systemd.exec(5) : « Takes a boolean argument. If set, attempts to create memory mappings that are writable and executable at the same time, or to change existing memory mappings to become executable, or mapping shared memory segments as executable, are prohibited. Specifically, a system call filter is added (or preferably, an » | à vérifier sur la cible avant activation : bibliothèques Python et PAM ; aucun retrait nouveau. |
| PrivateUsers | retirée | `absente (défaut false)` | systemd.exec(5) : « If this mode is enabled, all unit processes are run without privileges in the host user namespace » | Sudo doit agir sur l’identité hôte ; capacités bornées, pas de namespace utilisateur privé ; sudoers fermé. |
| ReadWritePaths | adaptée | `/run/sudo (à valider)` | systemd.exec(5) : « Sets up a new file system namespace for executed processes. These options may be used to limit access a process has to the file system. Each setting takes a space-separated list of paths relative to the host's root directory (i.e. the system running the service » | Exception restreinte au timestampdir de sudo ; à vérifier sur la cible ; ne pas ouvrir tout /run ni /var/log. |
| ReadOnlyPaths | conservée | `/etc/paresia /usr/local/lib/paresia` | systemd.exec(5) : « Paths listed in ReadOnlyPaths= are accessible for reading only, writing will be refused even if the usual file access controls would permit this. » | Code et configuration root:root, non inscriptibles par chef. |
| DynamicUser | retirée | `absente (compte chef fixe)` | systemd.exec(5) : « NoNewPrivileges= and RestrictSUIDSGID= are implicitly enabled (and cannot be disabled) » | Identité fixe ; aucun mécanisme qui impose NoNewPrivileges. |

## Fondement et héritage

`prctl(2)` renvoie désormais à `PR_SET_NO_NEW_PRIVS(2const)` dans les pages
installées. Cette dernière dit : « With no_new_privs set to 1, execve(2) promises
not to grant privileges to do anything that could not have been done without the
execve(2) call » et « rendering the set-user-ID and set-group-ID mode bits, and
file capabilities non-functional ». `sudo(8)` : « It must be owned by the root
user and have the set-user-ID bit set. » Conclusion : retirer NoNewPrivileges.

La page systemd.exec(5) 257.13 ne donne pas l'ancienne liste de directives
impliquant NoNewPrivileges pour les unités sans CAP_SYS_ADMIN ; ne pas la
reconstituer par supposition. Elle l'impose explicitement à DynamicUser (citation
du tableau). Remus est une **unité système**, User=chef fixe, sans DynamicUser.
Il faut contrôler NoNewPrivs pour Remus **et ses fils sudo** ; une valeur 1
bloque la mise en service et impose d'identifier la directive effective.

systemd.exec(5) : « Note that this setting only has an effect on the unit's
processes themselves (or any processes directly or indirectly forked off them). »
La portée des espaces de noms est indiquée par « Sets up a new file system
namespace for executed processes. » La page ne promet pas une isolation de
l'API Docker : son démon, extérieur à l'unité, n'hérite pas de ces restrictions.
capabilities(7) précise : « The bounding set is inherited at fork(2) from the
thread's parent, and is preserved across an execve(2). » Les filtres concernent
les « system calls executed by the unit processes » (systemd.exec(5)).
Les restrictions s'appliquent donc aux clients sudo/Docker fils de Remus,
pas aux opérations du démon Docker ; les règles sudoers restent déterminantes.

## Capacités et appels système

Minimum proposé, à éprouver avec le PAM installé ; aucune capacité ambiante :

- CAP_SETUID : capabilities(7), « Make arbitrary manipulations of process UIDs ».
- CAP_SETGID : capabilities(7), « Make arbitrary manipulations of process GIDs and
  supplementary GID list ».
- CAP_AUDIT_WRITE : capabilities(7), « Write records to kernel auditing log. »

Ce minimum couvre le changement d'identité et l'audit ; il ne prétend pas couvrir
toute configuration PAM. Toute capacité supplémentaire demande un constat et
une citation, aucun ensemble « toutes capacités ». CAP_SYS_ADMIN est exclue,
ainsi que tout accès direct de chef au socket Docker par groupe privilégié.

systemd.exec(5) décrit @privileged : « All system calls which need super-user »
et @system-service : « A reasonable set of system calls used by » (table des
groupes). Elle ne donne pas la liste exhaustive de leurs appels d'identité.
Le relevé local `systemd-analyze syscall-filter @system-service @privileged`
montre @setuid dans @system-service et setuid/setreuid/setresuid dans
@privileged ; cela ne signifie pas que les deux groupes sont disjoints.
Garder @system-service ; ne pas ajouter @privileged en bloc. Relever
`systemd-analyze syscall-filter @setuid` sur la cible et éprouver sudo.

ProtectSystem=strict est conservée. sudoers(5), timestampdir : « The directory
in which sudo stores its time stamp files. » Le chemin effectif doit être relevé
par root avec `sudo -V` ; `/run/sudo` est la proposition Debian à valider, pas
un chemin universel. sudoers(5), iolog_dir : « Only used if the log_input or
log_output options are enabled » ; aucune activation ici. Si la politique
hôte impose des journaux de session, arrêter et réexaminer l'exception de
chemin requise ; ne pas désactiver la journalisation de l'hôte.

ProtectHome, PrivateTmp, PrivateDevices sont conservées : tester la configuration
de root masquée, les fichiers temporaires et les pseudo-terminaux. Le client
Docker doit fonctionner via AF_UNIX ; unix(7) décrit cette famille comme
« sockets for local interprocess communication ». L'audit PAM peut nécessiter
une autre famille : essai obligatoire, aucun élargissement silencieux.
RestrictSUIDSGID porte sur la pose de bits ; PrivateUsers empêcherait les
capacités dans l'espace utilisateur hôte (citation du tableau), d'où son retrait.

## Signaux et résidu de sudoers

sudo(8), Signal handling : « When the command is run as a child of the sudo
process, sudo will relay signals it receives to the command. » SIGTERM est donc
relayé dans ce cas. « Some signals, such as SIGSTOP and SIGKILL, cannot be caught
and thus will not be relayed to the command. » sudoers(5), use_pty : « If set, and
sudo is running in a terminal, the command will be run in a new pseudo-terminal ».
L'exécuteur peut fonctionner sans terminal ; ne pas supposer que use_pty crée
alors un moniteur. Aucun Defaults n'est ajouté.

Après SIGKILL de sudo, le devenir garanti de la commande root est **non confirmée**
par ces extraits. Compensation : arrêt par le contrôle de groupe de l'unité
(KillMode=mixed), avec vérification de l'absence de fils après arrêt.
L'arrêt du client Docker ne garantit pas l'arrêt d'une opération déjà reçue
par le démon : chaque commande réelle de la table doit être auditée à ce titre.

Le résidu accepté est celui des **arguments fixes fusionnés** : sudoers(5) compare une
chaîne concaténée, pas les frontières d'argv. Cela concerne aussi les règles
exactes. Aucune expression ne contient d'espace dans sa partie variable ; les
espaces fixes restent néanmoins ambigus. La validation par gabarits est conservée,
mais un appel direct de chef à sudo la contourne. **Réexamen à l'ajout de la première commande réelle**, par
un audit de sécurité, pour chaque programme et ses arguments ; aucun droit dans la table
vide actuelle, aucun programme intermédiaire setuid.

## Essais réels

Toutes les commandes ci-dessous sont exécutées par vous, en root, sur la
cible.
Ne pas ajouter de commande de diagnostic aux sudoers de production. Avec la
table vide, seul un refus est attendu ; l'essai positif attend une commande
réelle auditée de la table et passe par Remus sous sa véritable unité.

1. Relever `systemctl cat remus.service`, `systemctl show remus.service`,
   `sudo -V`, `systemd-analyze syscall-filter @system-service @privileged @setuid`.
   Attendu : valeurs du tableau, chemins effectifs connus, aucun NNP implicite.
2. Pour NoNewPrivileges, CapabilityBoundingSet, SystemCallFilter, RestrictSUIDSGID : relever
   `PID=$(systemctl show -p MainPID --value remus.service)` puis
   `cat /proc/"$PID"/status`. Attendu : NoNewPrivs 0, CapAmb nul, CapBnd limité
   aux trois capacités ; répéter sur le PID du fils sudo observé pendant une
   commande auditée. Contrôler ses identités et les refus seccomp dans
   `journalctl -u remus.service`. Un échec bloque l'installation.
3. Pour ProtectHome, PrivateTmp, PrivateDevices, ProtectControlGroups, RestrictNamespaces,
   ProtectProc, SystemCallArchitectures, MemoryDenyWriteExecute : lancer cette
   commande auditée par le client Remus, sous l'unité réelle. Attendu :
   succès et sortie attendue sans accès aux ressources masquées, pas de SIGSYS
   ni d'erreur de chargement de bibliothèque ; conserver les valeurs du tableau
   tant que cet essai n'est pas disponible. Contrôler avec root les vues
   `/proc/<pid>/root/root`, `/proc/<pid>/root/tmp`, `/proc/<pid>/root/dev`,
   `/proc/<pid>/root/sys/fs/cgroup` et `/proc/<pid>/root/proc`.
4. Pour RestrictAddressFamilies et les capacités d'audit/PAM : même appel,
   lecture par root de `journalctl -u remus.service` et du journal sudo ; attendu :
   accès Docker par socket Unix et audit sans erreur de permission. En cas
   d'échec, relever le besoin réel avant toute adaptation.
5. Pour ReadWritePaths : relever `sudo -V`, puis contrôler par root les modes du
   timestampdir et le résultat de la même commande ; attendu : aucune écriture
   nécessaire hors de l'exception validée, aucune erreur « read-only ».
6. Pour les signaux : commande auditée suffisamment longue, échéance de la validation,
   observer SIGTERM et l'absence de fils après l'arrêt de l'unité ; vérifier
   séparément le cas SIGKILL. Attendu : aucun processus root survivant dans le
   groupe de contrôle ; observer aussi le résultat côté démon Docker.
