#!/bin/sh
# Install espyresso's systemd units and safety settings. Run on the Pi as root
# from the repo: sudo services/install.sh
set -eu
cd "$(dirname "$0")"

install -m 644 espyresso.service /etc/systemd/system/espyresso.service
install -d /etc/systemd/system.conf.d /etc/systemd/journald.conf.d
install -m 644 system-watchdog.conf /etc/systemd/system.conf.d/espyresso-watchdog.conf
install -m 644 journald-persistent.conf /etc/systemd/journald.conf.d/espyresso-persistent.conf

systemctl daemon-reload
systemctl daemon-reexec  # applies RuntimeWatchdogSec
systemctl restart systemd-journald
systemctl enable espyresso.service
echo "installed; apply with: sudo systemctl restart espyresso"
