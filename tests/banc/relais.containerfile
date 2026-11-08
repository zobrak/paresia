# SPDX-License-Identifier: AGPL-3.0-or-later
# Image du banc de présence ; dépendances : paquets Debian 13 ci-dessous.
# Suivi des versions : 0.1.1 · 2026-11-07 · Montage des fichiers livrés.
#   0.1.1 · 2026-11-07 · Démarrage de SSH réservé à l'orchestrateur après création des clés.
#   0.1.5 · 2026-11-07 · Installation de la version à côté du paquet serveur.
FROM debian:trixie
ENV LANG=C.UTF-8
RUN apt-get update && apt-get install --yes --no-install-recommends systemd systemd-sysv dbus openssh-server openssh-client python3 python3-cryptography acl sudo curl procps iproute2 && rm -rf /var/lib/apt/lists/* && rm -f /etc/ssh/ssh_host_* && truncate -s 0 /etc/machine-id
# openssh-server.postinst (Debian 13) active ssh.service ; ssh.socket est une alternative.
# systemctl(1), disable : retrait des liens d'activation, sans modifier les unités.
RUN /usr/bin/systemctl --no-reload disable ssh.service ssh.socket
RUN /usr/sbin/groupadd --system --gid 970 paresia-castor && \
    /usr/sbin/groupadd --system --gid 971 chef && \
    /usr/sbin/groupadd --system --gid 972 tunnel && \
    /usr/sbin/groupadd --system --gid 973 paresia-castor-tunnel && \
    /usr/sbin/groupadd --system --gid 974 paresia-remus-tunnel && \
    /usr/sbin/groupadd --system --gid 975 paresia-castor-etat && \
    /usr/sbin/useradd --system --uid 970 --gid 970 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin paresia-castor && \
    /usr/sbin/useradd --system --uid 971 --gid 971 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin chef && \
    /usr/sbin/useradd --system --uid 972 --gid 972 --no-create-home --home-dir /var/lib/paresia-tunnel --shell /usr/sbin/nologin tunnel && \
    /usr/bin/install -d -o root -g root -m 0755 /etc/paresia /etc/paresia/conf.d /usr/local/lib/paresia && \
    /usr/sbin/usermod -aG paresia-castor-tunnel,paresia-remus-tunnel tunnel && \
    /usr/bin/install -d -o root -g root -m 0755 /var/lib/paresia-tunnel /var/lib/paresia-tunnel/.ssh && \
    /usr/bin/install -m 0755 /usr/bin/true /usr/bin/docker
COPY server/ /usr/local/lib/paresia/server/
COPY --chmod=0644 VERSION /usr/local/lib/paresia/VERSION
RUN /usr/bin/rm -rf /usr/local/lib/paresia/server/conf && /usr/bin/find /usr/local/lib/paresia/server -name __pycache__ -type d -exec /usr/bin/rm -rf {} + && /usr/bin/chown -R root:root /usr/local/lib/paresia/server && /usr/bin/find /usr/local/lib/paresia/server -type d -exec /usr/bin/chmod 0755 {} + && /usr/bin/find /usr/local/lib/paresia/server -type f -exec /usr/bin/chmod 0644 {} +
COPY --chmod=0644 server/conf/paresia-relais.conf /etc/paresia/paresia.conf
COPY --chmod=0644 deploy/backend-relais/etc/ssh/sshd_config.d/50-paresia-tunnel.conf /etc/ssh/sshd_config.d/50-paresia-tunnel.conf
COPY --chmod=0644 deploy/backend-relais/etc/systemd/system/castor.service deploy/backend-relais/etc/systemd/system/remus.service /etc/systemd/system/
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
