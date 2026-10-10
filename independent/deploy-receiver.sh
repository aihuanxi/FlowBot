#!/usr/bin/env bash
# Optional durable Agent inbox; run after deploy.sh on the dedicated server.
set -euo pipefail
[[ ${EUID} == 0 ]] || { echo 'Run as root on the target server' >&2; exit 1; }
flowbot_ip=${1:?public IPv4 required}
flowbot_port=${2:-8443}
python3 - "$flowbot_ip" "$flowbot_port" <<'PY'
import ipaddress, sys
ipaddress.IPv4Address(sys.argv[1])
assert 1024 <= int(sys.argv[2]) <= 65535, 'port must be in 1024..65535'
PY
flowbot_source=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
test -f /etc/flowbot/server.key
openssl x509 -in /etc/flowbot/server.pem -noout -checkip "$flowbot_ip"
install -m 0644 "$flowbot_source/examples/webhook_receiver.py" /opt/flowbot/webhook_receiver.py
if [[ ! -f /etc/flowbot/webhook-example.token ]]; then
    python3 - <<'PY'
import os, secrets
with open('/etc/flowbot/webhook-example.token', 'x', opener=lambda p, f: os.open(p, f, 0o600)) as file:
    file.write(secrets.token_urlsafe(32))
PY
fi
chown root:flowbot /etc/flowbot/webhook-example.token
chmod 0640 /etc/flowbot/webhook-example.token
cat >/etc/systemd/system/flowbot-webhook-example.service <<UNIT
[Unit]
Description=FlowBot durable webhook inbox example
After=network-online.target
Wants=network-online.target

[Service]
User=flowbot
Group=flowbot
ExecStart=/usr/bin/python3 /opt/flowbot/webhook_receiver.py --host 0.0.0.0 --port ${flowbot_port} --db /var/lib/flowbot/agent-inbox.sqlite3 --token-file /etc/flowbot/webhook-example.token --cert /etc/flowbot/server.pem --key /etc/flowbot/server.key
Restart=on-failure
RestartSec=3
UMask=0077

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable flowbot-webhook-example
systemctl restart flowbot-webhook-example
systemctl is-active --quiet flowbot-webhook-example
echo "Webhook inbox deployed on HTTPS ${flowbot_port}; preserve its token and database"
