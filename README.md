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

### MySQL veritabanı ve uygulama kullanıcısı

Zimbra'nın kendi dahili MariaDB/MySQL veritabanını kullanmayın. Ayrı bir MySQL 8 sunucusu veya mevcut bağımsız MySQL hizmeti kullanın. Aynı Ubuntu sunucusuna kurulacaksa:

```bash
sudo apt update
sudo apt install -y mysql-server default-mysql-client
sudo systemctl enable --now mysql
sudo mysql
```

MySQL konsolunda veritabanını ve çalışma zamanı kullanıcısını oluşturun. Örnek parolayı güçlü ve benzersiz bir değerle değiştirin:

```sql
CREATE DATABASE zimbra_migration
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

CREATE USER 'zimbra_migrator'@'127.0.0.1'
    IDENTIFIED BY 'guclu-ve-benzersiz-bir-parola';

GRANT SELECT, INSERT, UPDATE, DELETE
    ON zimbra_migration.*
    TO 'zimbra_migrator'@'127.0.0.1';

FLUSH PRIVILEGES;
EXIT;
```

Başlangıç şemasını yönetici hesabıyla bir kez içe aktarın. Uygulama çalışma anında tablo oluşturmaz veya şema değiştirmez:

```bash
sudo mysql zimbra_migration < migration_db.sql
```

Uygulama kullanıcısının bağlantısını test edin:

```bash
mysql -h 127.0.0.1 -u zimbra_migrator -p \
  -e "SELECT COUNT(*) AS job_count FROM zimbra_migration.jobs;"
```

MySQL farklı bir sunucudaysa kullanıcı host bölümünü Zimbra sunucusunun özel IP adresiyle sınırlandırın; `%` kullanmayın. MySQL firewall portunu da yalnızca Zimbra sunucusunun IP adresine açın.

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

Yukarıdaki **MySQL veritabanı ve uygulama kullanıcısı** adımlarını tamamlayın. Bütün güncel tablo yapısı tek bir `migration_db.sql` dosyasındadır ve temiz kurulumda yalnızca bir kez içe aktarılır:

```bash
sudo mysql zimbra_migration < migration_db.sql
```

### 2. Ortam ayarları

Önce parola özeti ve oturum sırrı üretin:

```bash
source .venv/bin/activate
python scripts/hash-password.py
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

`.env` dosyasını düzenleyip bu iki çıktıyı ilgili alanlara yazın:

```dotenv
IMAPSYNC_PATH=/usr/local/bin/imapsync
MAX_PARALLEL=3
CSV_MAX_BYTES=5242880
CSV_MAX_ROWS=5000
APP_HOST=127.0.0.1
APP_PORT=8787
APP_USERNAME=admin
APP_PASSWORD_HASH=$scrypt$...
SESSION_SECRET=en-az-32-karakter-rastgele-deger
SESSION_HTTPS_ONLY=false
ALLOWED_HOSTS=127.0.0.1,localhost
IMAPSYNC_SSL_VERIFY=true
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

Ardından kendi tarayıcınızda `http://127.0.0.1:8787` adresine gidip oluşturduğunuz kullanıcıyla oturum açın. Web servisinin cevap verdiğini terminalden kontrol edebilirsiniz:

```bash
curl -I http://127.0.0.1:8787/login
```

`HTTP/1.1 200 OK` yanıtı alıyorsanız web servisi çalışıyor demektir. MySQL bağlantısı uygulama başlangıcında doğrulanır; bağlantı kurulamazsa servis başlamaz.

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

Tekli formdaki **Bağlantıyı Test Et** düğmesi imapsync `--justlogin` ile iki sunucuya oturum açmayı dener; aktarım başlatmaz. Tekli aktarım eklenirken bu kontrol sunucu tarafında zorunlu olarak bir kez daha uygulanır. CSV yüklemeleri UTF-8, zorunlu başlıklar, 5 MiB dosya boyutu ve varsayılan 5.000 hesap sınırıyla doğrulanır. Bu sınırlar `.env` üzerinden değiştirilebilir.

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
- Panel, scrypt parola özeti kullanan uygulama oturumu ve tüm durum değiştiren API çağrılarında CSRF kontrolü uygular.
- `ALLOWED_HOSTS` dışındaki Host başlıkları reddedilir.
- imapsync TLS bağlantılarında sertifika zinciri ve sunucu adı doğrulaması varsayılan olarak açıktır.

## Zimbra sunucusunda yayınlama

Bu kurulum Nginx kullanmaz. Uvicorn doğrudan systemd tarafından çalıştırılır. Önerilen erişim sırası:

1. SSH tüneli üzerinden `127.0.0.1` — test ve az sayıda yönetici için en güvenli yöntem.
2. VPN veya özel yönetim ağı — UFW ile yalnızca yönetici IP'lerine açık.
3. Doğrudan Uvicorn TLS — sertifika ve özel anahtar uygulamaya tanımlanır.

Önce panel parolası ve oturum sırrı oluşturun:

```bash
source .venv/bin/activate
python scripts/hash-password.py
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Çıktıları `.env` dosyasına yazın. Özel ağ örneği:

```dotenv
APP_HOST=0.0.0.0
APP_PORT=8787
APP_USERNAME=admin
APP_PASSWORD_HASH=$scrypt$...
SESSION_SECRET=en-az-32-karakter-rastgele-deger
SESSION_HTTPS_ONLY=false
ALLOWED_HOSTS=192.168.10.20,migration.example.com
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

Tarayıcıdan `http://ZIMBRA_SUNUCU_IP:8787` adresine erişebilirsiniz. HTTP yalnızca güvenilir LAN/VPN üzerinde kullanılmalıdır.

Doğrudan HTTPS için sertifika dosyalarını uygulama servis kullanıcısının okuyabildiği güvenli bir dizine yerleştirip aşağıdaki ayarları kullanın:

```dotenv
SESSION_HTTPS_ONLY=true
TLS_CERTFILE=/opt/zimbra-migration/certs/fullchain.pem
TLS_KEYFILE=/opt/zimbra-migration/certs/privkey.pem
```

Bu durumda adres `https://ZIMBRA_SUNUCU_IP:8787` olur. Sertifikadaki alan adıyla erişin. 8787 portunu yine yalnızca yönetici IP'lerine açın; uygulamayı genel internete yayınlamayın.

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

Güvenlik nedeniyle örnek servis `app.py` üzerinden tek Uvicorn worker kullanır. Kuyruk yöneticisi uygulama içi olduğundan birden fazla web worker çalıştırmayın.

Her aktarım kendine ait `data/pids/job-ID.pid` dosyasını kullanır. Böylece `--pidfilelocking`, üç paralel imapsync sürecinin birbirini engellemesine neden olmaz. Uygulama başlangıçta yarım kalmış `starting`, `running` ve `stopping` kayıtlarını `interrupted` durumuna alır; artık geçici parola ve PID dosyalarını temizler.

SSH tüneli alternatifi:

```bash
ssh -L 8787:127.0.0.1:8787 admin@zimbra.example.com
```

Ardından yerel tarayıcıda `http://127.0.0.1:8787` adresini açın.
