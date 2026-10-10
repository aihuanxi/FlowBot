#!/usr/bin/env bash
# Run on a dedicated Ubuntu/Debian server: sudo ./deploy.sh <public-ip> [device-id]
set -euo pipefail
[[ ${EUID} == 0 ]] || { echo 'Run as root on the target server' >&2; exit 1; }
flowbot_ip=${1:?public IPv4 required}
flowbot_device=${2:-oppo-test}
python3 - "$flowbot_ip" <<'PY'
import ipaddress, sys
ipaddress.IPv4Address(sys.argv[1])
assert sys.version_info >= (3, 10), 'Python 3.10+ required'
PY
flowbot_source=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
id flowbot >/dev/null 2>&1 || useradd --system --home /var/lib/flowbot --shell /usr/sbin/nologin flowbot
install -d -m 0755 /opt/flowbot
install -d -m 0700 -o flowbot -g flowbot /var/lib/flowbot
install -d -m 0750 -o root -g flowbot /etc/flowbot
install -m 0644 "$flowbot_source/server.py" /opt/flowbot/server.py
if [[ ! -f /etc/flowbot/config.json ]]; then
    python3 /opt/flowbot/server.py --config /etc/flowbot/config.json --init --device "$flowbot_device"
fi
if [[ ! -f /etc/flowbot/server.pem ]]; then
    umask 077
    openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 365 \
        -keyout /etc/flowbot/server.key -out /etc/flowbot/server.pem \
        -subj /CN=FlowBot-IP-Test -addext "subjectAltName=IP:$flowbot_ip" >/dev/null 2>&1
fi
openssl x509 -in /etc/flowbot/server.pem -noout -checkip "$flowbot_ip"
chown root:flowbot /etc/flowbot/config.json /etc/flowbot/server.key
chmod 0640 /etc/flowbot/config.json /etc/flowbot/server.key
chmod 0644 /etc/flowbot/server.pem
cat >/etc/systemd/system/flowbot.service <<'UNIT'
[Unit]
Description=FlowBot independent backend
After=network-online.target
Wants=network-online.target

[Service]
User=flowbot
Group=flowbot
WorkingDirectory=/var/lib/flowbot
ExecStart=/usr/bin/python3 /opt/flowbot/server.py --config /etc/flowbot/config.json --db /var/lib/flowbot/flowbot.sqlite3 --host 0.0.0.0 --port 443 --cert /etc/flowbot/server.pem --key /etc/flowbot/server.key
AmbientCapabilities=CAP_NET_BIND_SERVICE
Restart=on-failure
RestartSec=3
UMask=0077

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable flowbot
systemctl restart flowbot
systemctl is-active --quiet flowbot
echo 'FlowBot deployed; preserve /etc/flowbot and /var/lib/flowbot during upgrades'
