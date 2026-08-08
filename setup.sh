#!/usr/bin/env bash
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/zimbra-migration}
APP_USER=zimbra-migrator
DB_NAME=zimbra_migration
DB_USER=zimbra_migrator
MIN_PYTHON_MINOR=10
SOURCE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

if [[ ${EUID} -ne 0 ]]; then
  echo "Kurulumu sudo ile çalıştırın: sudo bash setup.sh" >&2
  exit 1
fi

if [[ -f "$APP_DIR/.env" ]]; then
  echo "$APP_DIR/.env zaten var. setup.sh yalnızca ilk kurulum içindir." >&2
  exit 1
fi

echo "[1/8] Sistem gereksinimleri denetleniyor..."
NEEDED_PACKAGES=(rsync)
if ! command -v python3 >/dev/null 2>&1 || ! python3 -c "import sys; raise SystemExit(sys.version_info < (3, ${MIN_PYTHON_MINOR}))"; then
  NEEDED_PACKAGES+=(python3 python3-venv python3-pip)
elif ! python3 -m venv --help >/dev/null 2>&1; then
  NEEDED_PACKAGES+=(python3-venv python3-pip)
fi

# Zimbra'nın /opt/zimbra altındaki gömülü veritabanına dokunulmaz. Sistemde ayrı
# bir MySQL/MariaDB hizmeti varsa yeniden kurulmaz; yoksa yerel hizmet kurulur.
if command -v mysql >/dev/null 2>&1 && mysql --protocol=socket -uroot -e "SELECT 1" >/dev/null 2>&1; then
  echo "Mevcut sistem MySQL/MariaDB hizmeti kullanılacak."
else
  NEEDED_PACKAGES+=(default-mysql-server default-mysql-client)
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y "${NEEDED_PACKAGES[@]}"
if ! python3 -c "import sys; raise SystemExit(sys.version_info < (3, ${MIN_PYTHON_MINOR}))"; then
  echo "Python 3.${MIN_PYTHON_MINOR} veya üzeri gerekli. Dağıtımınızın güncel Python paketini kurun." >&2
  exit 1
fi

echo "[2/8] imapsync denetleniyor..."
if command -v imapsync >/dev/null 2>&1; then
  echo "Mevcut imapsync kullanılacak: $(command -v imapsync)"
else
  bash "$SOURCE_DIR/scripts/install-imapsync-ubuntu.sh"
fi

echo "[3/8] Servis kullanıcısı ve uygulama dizini hazırlanıyor..."
if ! getent passwd "$APP_USER" >/dev/null; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi
mkdir -p "$APP_DIR" "$APP_DIR/data/pids" "$APP_DIR/logs"
rsync -a --delete \
  --exclude='.git/' --exclude='.env' --exclude='.venv/' --exclude='data/' --exclude='logs/' \
  "$SOURCE_DIR/" "$APP_DIR/"

echo "[4/8] Python ortamı kuruluyor..."
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "[5/8] Uygulama veritabanı hazırlanıyor..."
if systemctl list-unit-files mysql.service >/dev/null 2>&1; then
  systemctl enable --now mysql
elif systemctl list-unit-files mariadb.service >/dev/null 2>&1; then
  systemctl enable --now mariadb
fi
if ! mysql --protocol=socket -uroot -e "SELECT 1" >/dev/null 2>&1; then
  echo "Sistem MySQL/MariaDB root socket erişimi kurulamadı." >&2
  echo "Zimbra'nın gömülü veritabanı güvenlik nedeniyle kullanılmaz." >&2
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

echo "[6/8] Panel kimlik bilgileri oluşturuluyor..."
read -r -p "Panel kullanıcı adı [admin]: " PANEL_USER
PANEL_USER=${PANEL_USER:-admin}
if [[ ! "$PANEL_USER" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Kullanıcı adı yalnızca harf, rakam, nokta, alt çizgi ve tire içerebilir." >&2
  exit 1
fi
PANEL_HASH=$("$APP_DIR/.venv/bin/python" "$APP_DIR/scripts/hash-password.py")
SESSION_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
SERVER_NAME=$(hostname -f 2>/dev/null || hostname)
SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
IMAPSYNC_PATH=$(command -v imapsync)

cat > "$APP_DIR/.env" <<ENV
IMAPSYNC_PATH=${IMAPSYNC_PATH}
MAX_PARALLEL=3
CSV_MAX_BYTES=5242880
CSV_MAX_ROWS=5000
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

echo "[7/8] Dosya izinleri ve systemd servisi ayarlanıyor..."
chown -R root:root "$APP_DIR"
chown -R "$APP_USER:$APP_USER" "$APP_DIR/data" "$APP_DIR/logs"
chown root:"$APP_USER" "$APP_DIR/.env"
chmod 640 "$APP_DIR/.env"
chmod 700 "$APP_DIR/data" "$APP_DIR/data/pids" "$APP_DIR/logs"
cp "$APP_DIR/deploy/zimbra-migration.service" /etc/systemd/system/zimbra-migration.service

echo "[8/8] Servis başlatılıyor..."
systemctl daemon-reload
systemctl enable --now zimbra-migration
systemctl --no-pager --full status zimbra-migration || true

echo
echo "Kurulum tamamlandı."
echo "Panel: http://${SERVER_IP:-127.0.0.1}:8787"
echo "Kullanıcı: $PANEL_USER"
echo "Port 8787'yi yalnızca yönetici IP/VPN ağına açın."
