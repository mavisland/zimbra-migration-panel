# Zimbra IMAP Aktarım Paneli

Lokal çalışan, CSV veya tekli form üzerinden imapsync aktarımlarını kuyruğa alan web arayüzü. Aynı anda en fazla üç hesap aktarılır.

## Kurulum

Bu proje Ubuntu üzerinde çalışacak şekilde hazırlanmıştır. Önce temel paketleri yükleyin:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip default-mysql-client
```

### imapsync kurulumu (zorunlu)

Dashboard yalnızca yönetim katmanıdır; gerçek aktarımı imapsync yapar. Bu nedenle imapsync olmadan yeni aktarım eklenemez. Projedeki Ubuntu kurulum betiğini çalıştırın:

```bash
sudo bash scripts/install-imapsync-ubuntu.sh
command -v imapsync
imapsync --version
```

Betik, imapsync'in resmi Ubuntu kurulum belgesindeki Perl bağımlılıklarını yükler ve imapsync betiğini resmi GitHub kopyasından `/usr/local/bin/imapsync` yoluna kurar. Üretim kurulumundan önce betiği ve indirilen kaynağı kendi güvenlik politikanıza göre inceleyin.

Proje klasöründe Python ortamını hazırlayın:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
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

Mevcut bir kurulum yükseltiliyorsa yeni başlangıç şeması yeniden çalıştırılmaz. Sıralı migration dosyalarını bir kez uygulayın:

```bash
mysql -h 127.0.0.1 -u zimbra_migrator -p zimbra_migration < migrations/001_active_job_lock.sql
mysql -h 127.0.0.1 -u zimbra_migrator -p zimbra_migration < migrations/002_transfer_verification.sql
```

`active_lock` alanındaki benzersiz indeks, aynı kaynak ve hedef mailbox çiftinin aynı anda iki kez kuyruğa alınmasını engeller. Tamamlanan, durdurulan veya hatalı işlerde kilit kaldırılır; böylece hesap daha sonra yeniden çalıştırılabilir.

Dashboard, imapsync'in her başarılı `msg ... copied to ...` satırından aktarılan ileti ve byte sayaçlarını en fazla saniyede bir günceller. İş ancak süreç sıfır koduyla sonlandığında, `Detected 0 errors`, `There is no unidentified message` ve başarılı bütünlük özeti görüldüğünde tamamlanmış sayılır. Bu doğrulamalardan biri eksikse iş loguyla birlikte hatalı duruma alınır.

`IMAPSYNC_PATH` değerini Ubuntu üzerindeki imapsync çalıştırılabilir dosyasına göre düzenleyin. Kurulumdan sonra yolu doğrulayın:

```bash
command -v imapsync
imapsync --version
```

Ubuntu sürümünüze uygun imapsync kurulumu için projenin resmi `INSTALL.Ubuntu.txt` belgesini kullanın.

## Hızlı yerel test

### 1. MySQL hazırlığı

MySQL sunucunuzda uygulamaya özel veritabanı ve kullanıcı oluşturun. Zimbra'nın kendi dahili veritabanını kullanmayın:

```sql
CREATE DATABASE zimbra_migration CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'zimbra_migrator'@'127.0.0.1' IDENTIFIED BY 'guclu-bir-parola';
GRANT ALL PRIVILEGES ON zimbra_migration.* TO 'zimbra_migrator'@'127.0.0.1';
FLUSH PRIVILEGES;
```

Şemayı içe aktarın:

```bash
mysql -h 127.0.0.1 -u zimbra_migrator -p zimbra_migration < migration_db.sql
```

### 2. Ortam ayarları

`.env` dosyasını düzenleyin:

```dotenv
IMAPSYNC_PATH=/usr/local/bin/imapsync
MAX_PARALLEL=3
APP_HOST=127.0.0.1
APP_PORT=8787
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_DATABASE=zimbra_migration
MYSQL_USER=zimbra_migrator
MYSQL_PASSWORD=guclu-bir-parola
```

`command -v imapsync` farklı bir yol döndürürse `IMAPSYNC_PATH` değerine o yolu yazın.

### 3. Uygulamayı geliştirme modunda çalıştırma

```bash
source .venv/bin/activate
python app.py
```

Aynı Ubuntu makinesindeki tarayıcıdan `http://127.0.0.1:8787` adresini açın. Sunucuya uzaktan bağlıysanız önce kendi bilgisayarınızda SSH tüneli açın:

```bash
ssh -L 8787:127.0.0.1:8787 kullanici@zimbra-sunucusu
```

Ardından kendi tarayıcınızda `http://127.0.0.1:8787` adresine gidin. API ve MySQL bağlantısını terminalden de kontrol edebilirsiniz:

```bash
curl http://127.0.0.1:8787/api/summary
```

JSON yanıtı alıyorsanız web uygulaması ve MySQL bağlantısı çalışıyor demektir.

### 4. Gerçek aktarımı kontrollü test etme

Önce iki geçici/test posta hesabı kullanın. Her iki hesapta da önemli veri bulunmadığından emin olun; formdan yalnızca bu hesapları ekleyin. Logu paneldeki **Log** bağlantısından veya sunucuda aşağıdaki komutla izleyin:

```bash
tail -f logs/job-1.log
```

Test sırasında şunları doğrulayın:

- Aynı anda en fazla üç hesabın `Aktarılıyor` durumuna geçtiğini,
- Dördüncü hesabın `Sırada Bekleyenler` altında kaldığını,
- Aktarım yüzdesi ve ileti sayılarının güncellendiğini,
- Tamamlanan hesabın `Biten Hesaplar` grubuna taşındığını,
- Aynı hesabı yeniden çalıştırdığınızda iletilerin çoğaltılmadığını.

Arayüz imapsync bulunamadığında üst bölümde kırmızı bir sistem uyarısı gösterir ve yeni aktarım eklemeyi engeller. Mevcut bekleyen işler de imapsync kurulana kadar başlatılmaz.

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

### Nginx zorunlu mu?

Hayır. Nginx uygulamanın çalışması için zorunlu değildir. Tercih sırası şöyledir:

1. **SSH tüneli:** En kolay ve güvenli test yöntemidir. Uygulama yalnızca `127.0.0.1` üzerinde kalır.
2. **VPN veya özel yönetim ağı:** Uvicorn özel ağ adresinde yayınlanabilir ve firewall ile yalnızca yönetici IP'lerine açılabilir.
3. **Nginx/reverse proxy:** İnternet üzerinden erişim gerekiyorsa TLS, Basic Auth, erişim logları ve IP kısıtlama için önerilir.

Nginx olmadan özel ağda yayınlamak için `.env` içinde:

```dotenv
APP_HOST=0.0.0.0
APP_PORT=8787
```

Ardından uygulamayı başlatın:

```bash
source .venv/bin/activate
python app.py
```

Ubuntu firewall üzerinde portu herkese açmayın. Örneğin yalnızca `192.168.10.50` yönetici bilgisayarına izin vermek için:

```bash
sudo ufw allow from 192.168.10.50 to any port 8787 proto tcp
sudo ufw status
```

Tarayıcıdan `http://ZIMBRA_SUNUCU_IP:8787` adresine erişebilirsiniz. Bu bağlantı HTTP'dir; ağdaki trafik şifrelenmez. Bu nedenle yalnızca güvenilir LAN/VPN ortamında kullanılmalıdır.

> Uvicorn'u `0.0.0.0` üzerinde açıp 8787 portunu doğrudan internete yönlendirmeyin. Mevcut sürümde uygulama seviyesinde oturum açma bulunmadığından paneli gören kişi kayıtlı aktarım süreçlerini yönetebilir. İnternet erişimi için Nginx veya başka bir reverse proxy üzerinden HTTPS ve kimlik doğrulama kullanın.

### 1. Servis kullanıcısı ve dosyalar

```bash
sudo useradd --system --home /opt/zimbra-migration --shell /usr/sbin/nologin zimbra-migrator
sudo mkdir -p /opt/zimbra-migration
sudo chown zimbra-migrator:zimbra-migrator /opt/zimbra-migration
sudo -u zimbra-migrator mkdir -p /opt/zimbra-migration/data/pids /opt/zimbra-migration/logs
sudo chmod 700 /opt/zimbra-migration/data /opt/zimbra-migration/data/pids /opt/zimbra-migration/logs
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

Her aktarım kendine ait `data/pids/job-ID.pid` dosyasını kullanır. Böylece `--pidfilelocking`, üç paralel imapsync sürecinin birbirini engellemesine neden olmaz. Uygulama başlangıçta yarım kalmış `starting`, `running` ve `stopping` kayıtlarını `interrupted` durumuna alır; artık geçici parola ve PID dosyalarını temizler.

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
