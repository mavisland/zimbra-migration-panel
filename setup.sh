#!/usr/bin/env bash
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/zimbra-migration}
APP_USER=zimbra-migrator
DB_NAME=zimbra_migration
DB_USER=zimbra_migrator
MIN_PYTHON_MINOR=8
SOURCE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# Prefer Ubuntu's system locale; fall back to the current session locale.
SYSTEM_LOCALE=""
if [[ -r /etc/default/locale ]]; then
  SYSTEM_LOCALE=$(sed -n 's/^LANG=["'"']\?\([^"'"']*\)["'"']\?$/\1/p' /etc/default/locale | head -n 1)
fi
SYSTEM_LOCALE=${SYSTEM_LOCALE:-${LC_ALL:-${LC_MESSAGES:-${LANG:-en}}}}
LANGUAGE_CODE=en
if [[ ${SYSTEM_LOCALE,,} == tr* ]]; then
  LANGUAGE_CODE=tr
fi
# shellcheck source=/dev/null
source "$SOURCE_DIR/scripts/locales/setup.${LANGUAGE_CODE}.sh"

python_requirement_error() {
  printf "$MSG_PYTHON_REQUIRED\n" "$MIN_PYTHON_MINOR" >&2
  echo "$MSG_CURRENT_UBUNTU_EXAMPLE" >&2
  echo "  sudo apt update" >&2
  echo "  sudo apt install -y python3 python3-venv python3-pip" >&2
  echo "$MSG_PYTHON_RETRY" >&2
  exit 1
}

python_venv_error() {
  echo "$MSG_VENV_REQUIRED" >&2
  echo "$MSG_INSTALL_EXAMPLE" >&2
  echo "  sudo apt update" >&2
  echo "  sudo apt install -y python3-venv python3-pip" >&2
  echo "$MSG_SETUP_RETRY" >&2
  exit 1
}

if [[ ${EUID} -ne 0 ]]; then
  echo "$MSG_ROOT_REQUIRED" >&2
  exit 1
fi

if [[ -f "$APP_DIR/.env" ]]; then
  printf "$MSG_EXISTING_INSTALLATION\n" "$APP_DIR" >&2
  exit 1
fi

echo "$MSG_STEP_REQUIREMENTS"
NEEDED_PACKAGES=(rsync)
if ! command -v python3 >/dev/null 2>&1 || ! python3 -c "import sys; raise SystemExit(sys.version_info < (3, ${MIN_PYTHON_MINOR}))"; then
  python_requirement_error
fi
if ! python3 -m venv --help >/dev/null 2>&1 || ! python3 -m pip --version >/dev/null 2>&1; then
  python_venv_error
fi

# Never touch Zimbra's embedded database under /opt/zimbra. Reuse an independent
# system MySQL/MariaDB service when available; otherwise install a local service.
if command -v mysql >/dev/null 2>&1 && mysql --protocol=socket -uroot -e "SELECT 1" >/dev/null 2>&1; then
  echo "$MSG_MYSQL_REUSE"
else
  NEEDED_PACKAGES+=(default-mysql-server default-mysql-client)
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y "${NEEDED_PACKAGES[@]}"

echo "$MSG_STEP_IMAPSYNC"
if command -v imapsync >/dev/null 2>&1; then
  echo "$MSG_IMAPSYNC_REUSE $(command -v imapsync)"
else
  bash "$SOURCE_DIR/scripts/install-imapsync-ubuntu.sh"
fi

echo "$MSG_STEP_FILES"
if ! getent passwd "$APP_USER" >/dev/null; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi
mkdir -p "$APP_DIR" "$APP_DIR/data/pids" "$APP_DIR/logs"
rsync -a --delete \
  --exclude='.git/' --exclude='.env' --exclude='.venv/' --exclude='data/' --exclude='logs/' \
  "$SOURCE_DIR/" "$APP_DIR/"

echo "$MSG_STEP_PYTHON"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "$MSG_STEP_DATABASE"
if systemctl list-unit-files mysql.service >/dev/null 2>&1; then
  systemctl enable --now mysql
elif systemctl list-unit-files mariadb.service >/dev/null 2>&1; then
  systemctl enable --now mariadb
fi
if ! mysql --protocol=socket -uroot -e "SELECT 1" >/dev/null 2>&1; then
  echo "$MSG_MYSQL_ACCESS_ERROR" >&2
  echo "$MSG_ZIMBRA_DB_UNUSED" >&2
  exit 1
fi
DB_PASSWORD=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
mysql --protocol=socket -uroot <<SQL
CREATE DATABASE ${DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER '${DB_USER}'@'127.0.0.1' IDENTIFIED BY '${DB_PASSWORD}';
GRANT SELECT, INSERT, UPDATE, DELETE ON ${DB_NAME}.* TO '${DB_USER}'@'127.0.0.1';
FLUSH PRIVILEGES;
SQL
mysql --protocol=socket -uroot "$DB_NAME" < "$APP_DIR/migration_db.sql"

echo "$MSG_STEP_CREDENTIALS"
read -r -p "$MSG_USERNAME_PROMPT" PANEL_USER
PANEL_USER=${PANEL_USER:-admin}
if [[ ! "$PANEL_USER" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "$MSG_USERNAME_INVALID" >&2
  exit 1
fi
PANEL_HASH=$(INSTALL_LANGUAGE="$LANGUAGE_CODE" "$APP_DIR/.venv/bin/python" "$APP_DIR/scripts/hash-password.py")
SESSION_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
SERVER_NAME=$(hostname -f 2>/dev/null || hostname)
SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
IMAPSYNC_PATH=$(command -v imapsync)

cat > "$APP_DIR/.env" <<ENV
IMAPSYNC_PATH=${IMAPSYNC_PATH}
MAX_PARALLEL=3
CSV_MAX_BYTES=5242880
CSV_MAX_ROWS=5000
CREDENTIAL_RETENTION_HOURS=24
APP_HOST=0.0.0.0
APP_PORT=8787
APP_USERNAME=${PANEL_USER}
APP_PASSWORD_HASH='${PANEL_HASH}'
SESSION_SECRET=${SESSION_SECRET}
SESSION_HTTPS_ONLY=false
ALLOWED_HOSTS=127.0.0.1,localhost,${SERVER_NAME},${SERVER_IP}
IMAPSYNC_SSL_VERIFY=true
TLS_CERTFILE=
TLS_KEYFILE=
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_DATABASE=${DB_NAME}
MYSQL_USER=${DB_USER}
MYSQL_PASSWORD='${DB_PASSWORD}'
ENV

echo "$MSG_STEP_PERMISSIONS"
chown -R root:root "$APP_DIR"
chown -R "$APP_USER:$APP_USER" "$APP_DIR/data" "$APP_DIR/logs"
chown root:"$APP_USER" "$APP_DIR/.env"
chmod 640 "$APP_DIR/.env"
chmod 700 "$APP_DIR/data" "$APP_DIR/data/pids" "$APP_DIR/logs"
cp "$APP_DIR/deploy/zimbra-migration.service" /etc/systemd/system/zimbra-migration.service

echo "$MSG_STEP_SERVICE"
systemctl daemon-reload
systemctl enable --now zimbra-migration
systemctl --no-pager --full status zimbra-migration || true

echo
echo "$MSG_COMPLETE"
echo "$MSG_PANEL http://${SERVER_IP:-127.0.0.1}:8787"
echo "$MSG_USERNAME $PANEL_USER"
echo "$MSG_PORT_SAFETY"
