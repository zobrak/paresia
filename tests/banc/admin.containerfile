# SPDX-License-Identifier: AGPL-3.0-or-later
# Image du banc de présence ; dépendances : paquets Debian 13 ci-dessous.
# Suivi des versions : 0.1.1 · 2026-11-07 · Montage des fichiers livrés.
#   0.1.1 · 2026-11-07 · Fichier tmpfiles.d du tunnel installé tel quel.
#   0.1.1 · 2026-11-07 · Démarrage de SSH réservé à l'orchestrateur après création des clés.
#   0.1.5 · 2026-11-07 · Installation de la version à côté du paquet serveur.
FROM debian:trixie
ENV LANG=C.UTF-8
RUN apt-get update && apt-get install --yes --no-install-recommends systemd systemd-sysv dbus openssh-server openssh-client python3 python3-cryptography acl sudo curl procps iproute2 && rm -rf /var/lib/apt/lists/* && rm -f /etc/ssh/ssh_host_* && truncate -s 0 /etc/machine-id
# openssh-server.postinst (Debian 13) active ssh.service ; ssh.socket est une alternative.
# systemctl(1), disable : retrait des liens d'activation, sans modifier les unités.
RUN /usr/bin/systemctl --no-reload disable ssh.service ssh.socket
RUN /usr/sbin/groupadd --system --gid 984 paresia-sessions && \
    /usr/sbin/groupadd --system --gid 985 paresia-liaison && \
    /usr/sbin/groupadd --system --gid 986 paresia-http && \
    /usr/sbin/groupadd --system --gid 980 paresia-pollux && \
    /usr/sbin/groupadd --system --gid 981 paresia-romulus && \
    /usr/sbin/groupadd --system --gid 982 paresia-tunnel && \
    /usr/sbin/groupadd --system --gid 983 app && \
    /usr/sbin/useradd --system --uid 980 --gid 980 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin paresia-pollux && \
    /usr/sbin/useradd --system --uid 981 --gid 981 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin paresia-romulus && \
    /usr/sbin/useradd --system --uid 982 --gid 982 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin paresia-tunnel && \
    /usr/sbin/useradd --system --uid 983 --gid 983 --no-create-home --home-dir /var/lib/paresia-app --shell /bin/sh app && \
    /usr/bin/install -d -o root -g root -m 0755 /etc/paresia /etc/paresia/conf.d /usr/local/lib/paresia /usr/local/lib/paresia/romulus /usr/local/lib/paresia/romulus/services && \
    /usr/sbin/usermod -aG paresia-sessions app && \
    /usr/bin/install -d -o root -g root -m 0755 /var/lib/paresia-app /var/lib/paresia-app/.ssh /etc/paresia/tunnel /etc/paresia/tunnel/ssh_config.d && \
    /usr/bin/install -m 0644 -o root -g root /dev/null /var/lib/paresia-app/.ssh/authorized_keys
COPY server/ /usr/local/lib/paresia/server/
COPY --chmod=0644 VERSION /usr/local/lib/paresia/VERSION
RUN /usr/bin/rm -rf /usr/local/lib/paresia/server/conf && /usr/bin/find /usr/local/lib/paresia/server -name __pycache__ -type d -exec /usr/bin/rm -rf {} + && /usr/bin/chown -R root:root /usr/local/lib/paresia/server && /usr/bin/find /usr/local/lib/paresia/server -type d -exec /usr/bin/chmod 0755 {} + && /usr/bin/find /usr/local/lib/paresia/server -type f -exec /usr/bin/chmod 0644 {} +
COPY --chmod=0755 server/bin/pollux-session /usr/local/bin/pollux-session
COPY --chmod=0644 server/conf/paresia.conf /etc/paresia/paresia.conf
COPY --chmod=0644 deploy/backend-admin/usr/local/lib/paresia/romulus/services/paresia-yang-bunkerd.toml deploy/backend-admin/usr/local/lib/paresia/romulus/services/paresia-yang-journal-legal.toml deploy/backend-admin/usr/local/lib/paresia/romulus/services/paresia-yang-nisaba.toml deploy/backend-admin/usr/local/lib/paresia/romulus/services/paresia-yang-strfry.toml deploy/backend-admin/usr/local/lib/paresia/romulus/services/paresia-yang-webui.toml /usr/local/lib/paresia/romulus/services/
COPY --chmod=0644 deploy/backend-admin/etc/paresia/conf.d/10-backend-admin.conf /etc/paresia/conf.d/10-backend-admin.conf
COPY --chmod=0644 deploy/backend-admin/etc/paresia/tunnel/ssh_config /etc/paresia/tunnel/ssh_config
COPY --chmod=0644 deploy/backend-admin/etc/paresia/tunnel/ssh_config.d/10-relais.conf /etc/paresia/tunnel/ssh_config.d/10-relais.conf
COPY --chmod=0644 deploy/backend-admin/etc/ssh/sshd_config.d/50-paresia-app.conf /etc/ssh/sshd_config.d/50-paresia-app.conf
COPY --chmod=0644 deploy/backend-admin/etc/systemd/system/pollux.service deploy/backend-admin/etc/systemd/system/romulus.service deploy/backend-admin/etc/systemd/system/paresia-tunnel.service /etc/systemd/system/
COPY --chmod=0644 deploy/backend-admin/etc/tmpfiles.d/paresia-tunnel.conf /etc/tmpfiles.d/paresia-tunnel.conf
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
