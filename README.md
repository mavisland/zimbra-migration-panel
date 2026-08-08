# Zimbra IMAP Aktarım Paneli

Lokal çalışan, CSV veya tekli form üzerinden imapsync aktarımlarını kuyruğa alan web arayüzü. Aynı anda en fazla üç hesap aktarılır.

## Kurulum

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python app.py
```

Arayüz: `http://127.0.0.1:8787`

Önce bir MySQL veritabanı ve yalnızca bu veritabanına yetkili kullanıcı oluşturun:

```sql
CREATE DATABASE zimbra_migration CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

Ardından uygulama şemasını bir defa içe aktarın. Uygulama kendi başına tablo oluşturmaz veya şema değiştirmez:

```bash
mysql -u root -p zimbra_migration < migration_db.sql
```

`IMAPSYNC_PATH` değerini Windows'ta `imapsync.exe`, Linux'ta `imapsync` çalıştırılabilir dosyasına göre düzenleyin.

## CSV biçimi

```csv
source_host,source_port,source_security,source_email,source_password,target_host,target_port,target_security,target_email,target_password,start_date,end_date
imap.example.com,993,ssl,old@example.com,old-secret,mail.example.com,993,ssl,new@example.com,new-secret,,
```

Tarih alanları isteğe bağlıdır ve `YYYY-MM-DD` biçimindedir. CSV yalnızca içe aktarılırken okunur; parolalar CSV'den uygulamanın şifreli veritabanına alınır. CSV dosyasının güvenli biçimde silinmesi operatörün sorumluluğundadır.

## Güvenlik

- Web sunucusu varsayılan olarak yalnızca `127.0.0.1` üzerinde dinler.
- Parolalar MySQL içinde Fernet ile şifrelenir; anahtar `data/secret.key` dosyasındadır.
- imapsync parolaları işlem argümanlarına koyulmaz; aktarım süresince izinleri kısıtlanmış geçici passfile kullanılır.
- Paneli ağ üzerinde yayınlamadan önce kimlik doğrulama ve HTTPS ekleyin.

## Zimbra sunucusunda yayınlama

Uygulamayı doğrudan internete açmayın. Uvicorn yalnızca `127.0.0.1:8787` üzerinde çalışmalı; tarayıcı erişimi TLS ve kimlik doğrulamalı bir ters vekil üzerinden sağlanmalıdır.

### 1. Servis kullanıcısı ve dosyalar

```bash
sudo useradd --system --home /opt/zimbra-migration --shell /usr/sbin/nologin zimbra-migrator
sudo mkdir -p /opt/zimbra-migration
sudo chown zimbra-migrator:zimbra-migrator /opt/zimbra-migration
sudo -u zimbra-migrator python3 -m venv /opt/zimbra-migration/.venv
sudo -u zimbra-migrator /opt/zimbra-migration/.venv/bin/pip install -r /opt/zimbra-migration/requirements.txt
```

`.env` dosyasındaki MySQL hesabına yalnızca uygulama veritabanı için yetki verin. `data/secret.key` şifreleme anahtarını ayrıca yedekleyin; bu anahtar kaybolursa kayıtlı parolalar çözülemez.

### 2. systemd

Örnek servis dosyası: [`deploy/zimbra-migration.service`](deploy/zimbra-migration.service)

```bash
sudo cp deploy/zimbra-migration.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now zimbra-migration
sudo systemctl status zimbra-migration
```

Güvenlik nedeniyle örnek servis tek Uvicorn worker kullanır. Kuyruk yöneticisi uygulama içi olduğundan birden fazla web worker aynı aktarımı başlatabilir.

### 3. Nginx, TLS ve parola koruması

Örnek yapılandırma: [`deploy/nginx-zimbra-migration.conf`](deploy/nginx-zimbra-migration.conf)

```bash
sudo apt install apache2-utils
sudo htpasswd -c /etc/nginx/.htpasswd-zimbra-migration paneladmin
sudo cp deploy/nginx-zimbra-migration.conf /etc/nginx/conf.d/zimbra-migration.conf
sudo nginx -t
sudo systemctl reload nginx
```

`migration.example.com` ve sertifika yollarını kendi alan adınıza göre değiştirin. Mümkünse ayrıca firewall/VPN üzerinden yönetici IP'leriyle sınırlayın.

> **Zimbra Proxy uyarısı:** Zimbra'nın kendi Nginx proxy servisi 80/443 portlarını kullanıyorsa ikinci bir sistem Nginx'i aynı portlarda başlatamazsınız. Zimbra tarafından üretilen Nginx dosyalarını elle değiştirmek güncelleme veya servis yeniden yapılandırmasında kaybolabilir. Bu durumda önerilen kurulum, `migration.example.com` ters vekilini ayrı bir yönetim/reverse-proxy sunucusunda çalıştırıp `127.0.0.1:8787` yerine yalnızca özel ağdan erişilebilen Zimbra sunucusu adresine yönlendirmektir. Alternatif olarak paneli VPN/SSH tüneli üzerinden lokal portta kullanın.

SSH tüneli alternatifi:

```bash
ssh -L 8787:127.0.0.1:8787 admin@zimbra.example.com
```

Ardından yerel tarayıcıda `http://127.0.0.1:8787` adresini açın.
