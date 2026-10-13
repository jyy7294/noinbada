#!/bin/bash
set -euo pipefail
# Only the TR ZIP namespace is touched. No global cleanup, no other services.
base=/srv/services/trzip
release=${1:?Pass the prepared release directory}
case "$release" in "$base"/releases/*) ;; *) echo 'Invalid release path'; exit 1;; esac
test -f "$release/src/trzip/runtime/api.py"
free=$(df --output=avail -B1 /srv | tail -1 | tr -d ' ')
test "$free" -gt 6000000000 || { echo 'TRZIP needs 6 GB free before installation'; exit 1; }
id trzip >/dev/null 2>&1 || useradd --system --home-dir "$base/state" --shell /usr/sbin/nologin trzip
# Parent is intentionally private on the shared VPS. Grant traversal only to
# this service identity, preserving every existing ACL entry.
getfacl -p /srv/services > "$base/parent-acl-before.txt"
setfacl -m u:trzip:--x /srv/services
find "$release" -type d -exec chmod 0755 {} +
find "$release" -type f -exec chmod 0644 {} +
install -d -o trzip -g trzip -m 0750 "$base/state" "$base/state/backups"
install -d -m 0755 "$base/acme" "$base/browser"
if [ ! -x "$base/venv/bin/python" ]; then python3 -m venv "$base/venv"; fi
"$base/venv/bin/python" -m pip install --disable-pip-version-check --no-cache-dir -r "$release/deploy/requirements.lock.txt"
PLAYWRIGHT_BROWSERS_PATH="$base/browser" "$base/venv/bin/python" -m playwright install chromium --only-shell
chmod -R a+rX "$base/browser"
if [ ! -f "$base/runtime.env" ]; then
cat > "$base/runtime.env" <<'ENV'
PYTHONPATH=/srv/services/trzip/current/src
TRZIP_RUNTIME_HOME=/srv/services/trzip/state
TRZIP_WEB_ROOT=/srv/services/trzip/current/web
TRZIP_RELEASE_MODE=candidate
TRZIP_GOOGLE_PAGE_ENABLED=true
PLAYWRIGHT_BROWSERS_PATH=/srv/services/trzip/browser
PYTHONDONTWRITEBYTECODE=1
ENV
chown root:trzip "$base/runtime.env"
chmod 0640 "$base/runtime.env"
fi
if [ -L "$base/current" ]; then readlink "$base/current" > "$base/previous-release"; fi
ln -sfn "$release" "$base/current.next"
mv -Tf "$base/current.next" "$base/current"
install -m 0644 "$release"/deploy/trzip-*.service "$release"/deploy/trzip-*.timer /etc/systemd/system/
install -m 0644 "$release/deploy/journald.conf" /etc/systemd/journald@trzip.conf
systemctl daemon-reload
systemctl start trzip-collect.service
systemctl enable --now trzip-api.service trzip-collect.timer trzip-enrich.timer trzip-maintain.timer
systemctl restart trzip-api.service
curl --fail --silent --retry 5 --retry-connrefused --retry-delay 1 http://127.0.0.1:8448/health/ready
if [ ! -f /etc/nginx/sites-available/trzip ]; then
    install -m 0644 "$release/deploy/nginx.conf" /etc/nginx/sites-available/trzip
    ln -s /etc/nginx/sites-available/trzip /etc/nginx/sites-enabled/trzip
fi
nginx -t
systemctl reload nginx
free=$(df --output=avail -B1 /srv | tail -1 | tr -d ' ')
test "$free" -gt 5368709120 || { echo 'Post-install space below 5 GiB'; exit 1; }
echo 'TR ZIP candidate installed; HTTPS must be validated before public handoff.'
