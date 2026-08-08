# Zimbra IMAP Migration Panel

[Türkçe](#türkçe) · [English](#english)

Browser-based, MySQL-backed queue and monitoring panel for parallel `imapsync` migrations. It supports single-account and CSV imports, three concurrent transfers by default, live progress, status/domain grouping, encrypted credentials, retries, and transfer logs.

> This is an independent community project. It is not affiliated with or endorsed by Zimbra or the imapsync project.

## Türkçe

### Başlamadan önce

Bu panel, eski bir IMAP posta sunucusundaki hesapları Zimbra'ya kopyalamak içindir. Taşıma işlemini `imapsync` yapar; bu proje işlemleri sıraya koyar ve tarayıcıdan izlemenizi sağlar.

Şunlara ihtiyacınız vardır:

- Ubuntu çalıştıran Zimbra sunucusuna `sudo` yetkili SSH erişimi,
- kaynak ve hedef posta hesaplarının adresleri ile parolaları,
- yönetici bilgisayarınızdan sunucunun 8787 portuna erişim veya SSH tüneli,
- kurulum sırasında paket indirebilmek için internet bağlantısı.

Komutlardaki `SUNUCU_IP`, `YONETICI_IP` ve `kullanici` örnek değerlerdir; kendi bilgilerinizle değiştirin. Başında `$` işareti gösterilen bir terminal satırı varsa `$` işaretini yazmayın.

### İlk kurulum

Önce bilgisayarınızda Terminal/PowerShell açıp sunucuya bağlanın:

```bash
ssh kullanici@SUNUCU_IP
```

Sunucuda aşağıdaki komutları sırayla çalıştırın. İlk komut Git yüklü değilse kurar; son komut tüm panel kurulumunu yapar:

```bash
sudo apt update
sudo apt install -y git
git clone https://github.com/mavisland/zimbra-migration-panel.git
cd zimbra-migration-panel
sudo bash setup.sh
```

`sudo` sizden Ubuntu kullanıcı parolanızı isteyebilir. Kurulum daha sonra panel için bir kullanıcı adı ve parola sorar. Bu panel parolası Ubuntu parolasından farklıdır ve tarayıcıda oturum açmak için kullanılır. Parola yazılırken ekranda karakter görünmemesi normaldir.

`setup.sh` ilk kurulumun tamamını yürütür:

- Python 3.10+, `venv`, imapsync ve MySQL/MariaDB bileşenlerini denetler; eksikleri kurar.
- `/opt/zimbra-migration` dizini ile kısıtlı `zimbra-migrator` servis kullanıcısını oluşturur.
- `zimbra_migration` veritabanını ve yalnızca bu veritabanında CRUD yetkili kullanıcıyı oluşturur.
- Tek şema dosyası olan `migration_db.sql` dosyasını içe aktarır.
- Panel kullanıcı adı/parolasını alır; uygulama sırlarını ve `.env` dosyasını üretir.
- systemd servisini etkinleştirip başlatır.

Betik yalnızca ilk kurulum içindir. `/opt/zimbra-migration/.env` zaten varsa veri kaybını önlemek için durur.

#### Neden Zimbra'nın MySQL/MariaDB hizmeti kullanılmıyor?

Zimbra'nın `/opt/zimbra` altındaki gömülü veritabanı, Zimbra'nın kendi şema, izin ve yükseltme yaşam döngüsüne aittir. Panel tablolarını buraya eklemek destek ve güncelleme riski oluşturur. `setup.sh`, işletim sisteminde bağımsız bir MySQL/MariaDB hizmeti varsa onu kullanır; yoksa `default-mysql-server` kurar. Zimbra veritabanına ve kimlik bilgilerine dokunmaz.

Kurulum tamamlandığında terminalde `Kurulum tamamlandı` mesajı ve panel adresi görünür. Yönetici bilgisayarınızdaki tarayıcıda `http://SUNUCU_IP:8787` adresini açıp kurulum sırasında belirlediğiniz panel hesabıyla giriş yapın.

Sayfa açılmıyorsa sunucunun güvenlik duvarında yalnızca kendi sabit IP adresinize izin verin. `YONETICI_IP` yerine kendi genel/özel yönetim IP adresinizi yazın:

```bash
sudo ufw allow from YONETICI_IP to any port 8787 proto tcp
```

### Kontrol ve günlükler

```bash
sudo systemctl status zimbra-migration
sudo journalctl -u zimbra-migration -f
command -v imapsync
imapsync --version
curl -I http://127.0.0.1:8787/login
```

Beklenen sonuçlar: servis durumunda `active (running)`, `command -v` çıktısında bir imapsync yolu ve `curl` çıktısında bir HTTP yanıtı görülmesidir. Sorun varsa son 100 günlük satırını alın:

```bash
sudo journalctl -u zimbra-migration -n 100 --no-pager
```

MySQL parolası `/opt/zimbra-migration/.env` içinde otomatik üretilir. İlk başlangıçta oluşan `/opt/zimbra-migration/data/secret.key` dosyasını güvenli biçimde yedekleyin; bu anahtar kaybolursa kayıtlı posta parolaları çözülemez.

### Güvenli erişim

Panel oturum açma, scrypt parola özeti, imzalı oturum çerezi, CSRF koruması ve güvenilir Host denetimi içerir. HTTP'yi yalnızca güvenilir LAN/VPN üzerinde kullanın. Nginx zorunlu değildir.

SSH tüneli için `.env` dosyasında `APP_HOST=127.0.0.1` kullanın ve yönetici bilgisayarınızda çalıştırın:

```bash
ssh -L 8787:127.0.0.1:8787 kullanici@zimbra-sunucusu
```

Ardından `http://127.0.0.1:8787` adresini açın. Doğrudan Uvicorn TLS kullanmak isterseniz:

```dotenv
SESSION_HTTPS_ONLY=true
TLS_CERTFILE=/opt/zimbra-migration/certs/fullchain.pem
TLS_KEYFILE=/opt/zimbra-migration/certs/privkey.pem
```

### CSV biçimi

```csv
source_host,source_port,source_security,source_email,source_password,target_host,target_port,target_security,target_email,target_password,start_date,end_date
imap.example.com,993,ssl,old@example.com,old-secret,mail.example.com,993,ssl,new@example.com,new-secret,,
```

CSV UTF-8 olmalıdır. Varsayılan sınırlar 5 MiB ve 5.000 hesaptır. Tarihler isteğe bağlı ve `YYYY-MM-DD` biçimindedir. Tekli formdaki **Bağlantıyı Test Et** işlemi imapsync `--justlogin` çalıştırır; posta taşımaz.

İlk denemede gerçek kullanıcılar yerine iki test posta hesabı kullanın. Panelde **Tekli** sekmesini açın, kaynak/eski ve hedef/yeni hesap bilgilerini girin, önce **Bağlantıyı Test Et** düğmesine basın. Test başarılıysa aktarımı ekleyin. Birden fazla hesap için örnek başlıklarla hazırlanmış CSV dosyasını **Toplu (CSV)** sekmesinden yükleyin.

### Sık karşılaşılan sorunlar

- **Panel açılmıyor:** `systemctl status` ve `journalctl` komutlarıyla servisi kontrol edin; firewall kuralını ve doğru sunucu IP'sini doğrulayın.
- **imapsync bulunamadı:** `sudo bash scripts/install-imapsync-ubuntu.sh` çalıştırıp servisi `sudo systemctl restart zimbra-migration` ile yeniden başlatın.
- **Bağlantı testi başarısız:** IMAP sunucu adı, 993 portu, SSL seçimi, posta adresi ve parolayı kontrol edin. Kaynak sunucunun uzak IMAP erişimine izin verdiğinden emin olun.
- **Sertifika hatası:** Doğru alan adını kullanın ve sunucunun geçerli sertifika zincirini düzeltin. TLS doğrulamasını kapatmak yalnızca geçici tanılama için düşünülmelidir.
- **Kurulumu tekrar çalıştırmak istiyorum:** Çalışan sistemde `setup.sh` dosyasını tekrar çalıştırmayın; `.env`, `data/secret.key` ve MySQL veritabanını yedeklemeden dosya silmeyin.

### Çalışma biçimi

- Parolalar MySQL'de Fernet ile şifreli tutulur ve imapsync'e `0600` izinli geçici passfile üzerinden verilir.
- Tamamlanan veya duran işlerin şifreli parolaları varsayılan olarak 24 saat sonra silinir. Süre `CREDENTIAL_RETENTION_HOURS` ile değiştirilebilir; sonrasında yeniden denemek için hesap tekrar eklenmelidir.
- Aynı kaynak/hedef posta kutusu çifti eş zamanlı olarak ikinci kez başlatılamaz.
- Her aktarım ayrı PID ve log dosyası kullanır; varsayılan paralellik üç hesaptır.
- İş, imapsync başarılı çıkış ve bütünlük özeti verdiğinde tamamlanmış sayılır.
- Servis yeniden başlarsa yarım kalan işler `interrupted` olur ve yeniden denenebilir.
- imapsync bulunamazsa yeni aktarım kabul edilmez.
- `migration_db.sql` temiz kurulum için gereken bütün tabloları içeren tek şema dosyasıdır.
- Kuyruğu duraklatma seçimi servis yeniden başlatıldığında korunur; parola içermeyen CSV raporu sol menüden indirilebilir. Dashboard son 500 işi gösterir, rapor bütün işleri içerir.

Kuyruk yöneticisi uygulama içinde çalıştığından yalnızca tek Uvicorn worker kullanın. Güncelleme sırasında `setup.sh` veya `migration_db.sql` dosyasını canlı sisteme yeniden uygulamayın; sürüme ait güncelleme notlarını izleyin.

### Geliştirici testleri

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q
```

GitHub Actions her push ve pull request'te Python testlerini, JavaScript sözdizimini ve Ubuntu kurulum betiklerini doğrular.

---

## English

### Before you begin

This panel copies accounts from an old IMAP mail server to Zimbra. `imapsync` performs the transfer; this project queues the jobs and lets you monitor them in a browser.

You need:

- SSH access with `sudo` permission to the Ubuntu server running Zimbra,
- addresses and passwords for the source and target mail accounts,
- access from the administrator workstation to server port 8787, or an SSH tunnel,
- internet access during installation so packages can be downloaded.

Values such as `SERVER_IP`, `ADMIN_IP`, and `user` are placeholders; replace them with your own details. If an example terminal line begins with `$`, do not type the `$` character.

### First-time installation

Open Terminal/PowerShell on your computer and connect to the server:

```bash
ssh user@SERVER_IP
```

Run these commands on the server in order. The first two install Git if necessary; the last command performs the complete panel installation:

```bash
sudo apt update
sudo apt install -y git
git clone https://github.com/mavisland/zimbra-migration-panel.git
cd zimbra-migration-panel
sudo bash setup.sh
```

`sudo` may ask for your Ubuntu account password. The installer then asks for a panel username and password. The panel password is separate from the Ubuntu password and is used to sign in through the browser. It is normal for no characters to appear while typing a password.

`setup.sh` performs the complete first-time installation:

- Checks for Python 3.10+, `venv`, imapsync, and MySQL/MariaDB, installing only missing components.
- Creates `/opt/zimbra-migration` and the restricted `zimbra-migrator` service account.
- Creates the `zimbra_migration` database and a user limited to CRUD access on that database.
- Imports the single schema file, `migration_db.sql`.
- Prompts for the panel username/password and generates application secrets and `.env`.
- Enables and starts the systemd service.

The script is intended for first installation only. It stops if `/opt/zimbra-migration/.env` already exists to protect existing data.

#### Why not use Zimbra's MySQL/MariaDB service?

The embedded database under `/opt/zimbra` belongs to Zimbra's schema, permission, and upgrade lifecycle. Adding panel tables creates support and upgrade risks. `setup.sh` reuses an independent system MySQL/MariaDB service when available, or installs `default-mysql-server` otherwise. It never touches Zimbra's database or credentials.

When the terminal prints `Kurulum tamamlandı` (installation complete), open the displayed `http://SERVER_IP:8787` address on the administrator workstation and sign in with the panel account you created.

If the page does not open, allow only your fixed administrator IP through the server firewall. Replace `ADMIN_IP` with your actual public/private administration IP:

```bash
sudo ufw allow from ADMIN_IP to any port 8787 proto tcp
```

### Status and logs

```bash
sudo systemctl status zimbra-migration
sudo journalctl -u zimbra-migration -f
command -v imapsync
imapsync --version
curl -I http://127.0.0.1:8787/login
```

Expected results are `active (running)` for the service, an imapsync path from `command -v`, and an HTTP response from `curl`. If something fails, display the latest 100 service log lines:

```bash
sudo journalctl -u zimbra-migration -n 100 --no-pager
```

The MySQL password is generated in `/opt/zimbra-migration/.env`. Securely back up `/opt/zimbra-migration/data/secret.key`, which is created on first start. Stored mail passwords cannot be decrypted if this key is lost.

### Secure access

The panel provides login protection, scrypt password hashing, signed session cookies, CSRF protection, and trusted Host validation. Use plain HTTP only on a trusted LAN/VPN. Nginx is not required.

For an SSH tunnel, set `APP_HOST=127.0.0.1` in `.env`, then run this on the administrator workstation:

```bash
ssh -L 8787:127.0.0.1:8787 user@zimbra-server
```

Open `http://127.0.0.1:8787`. To use Uvicorn's built-in TLS directly:

```dotenv
SESSION_HTTPS_ONLY=true
TLS_CERTFILE=/opt/zimbra-migration/certs/fullchain.pem
TLS_KEYFILE=/opt/zimbra-migration/certs/privkey.pem
```

### CSV format

```csv
source_host,source_port,source_security,source_email,source_password,target_host,target_port,target_security,target_email,target_password,start_date,end_date
imap.example.com,993,ssl,old@example.com,old-secret,mail.example.com,993,ssl,new@example.com,new-secret,,
```

CSV files must be UTF-8. Default limits are 5 MiB and 5,000 accounts. Dates are optional and use `YYYY-MM-DD`. **Test Connection** runs imapsync with `--justlogin` and does not transfer mail.

For the first attempt, use two test mailboxes rather than real users. Open the **Single** tab, enter the source/old and target/new account details, and click **Test Connection** first. Add the migration after the test succeeds. For multiple accounts, prepare a CSV with the example headers and upload it from **Bulk (CSV)**.

### Common problems

- **The panel does not open:** Check the service with `systemctl status` and `journalctl`; verify the firewall rule and server IP.
- **imapsync is missing:** Run `sudo bash scripts/install-imapsync-ubuntu.sh`, then `sudo systemctl restart zimbra-migration`.
- **Connection test fails:** Verify the IMAP hostname, port 993, SSL selection, email address, and password. Confirm that the source server permits remote IMAP access.
- **Certificate error:** Use the correct hostname and repair the server's certificate chain. Disabling TLS verification should only be considered for temporary diagnosis.
- **I want to run installation again:** Do not re-run `setup.sh` on a working system, and do not remove files before backing up `.env`, `data/secret.key`, and the MySQL database.

### Runtime behavior

- Passwords are Fernet-encrypted in MySQL and passed to imapsync through temporary passfiles with `0600` permissions.
- Encrypted passwords for finished or stopped jobs are deleted after 24 hours by default. Configure `CREDENTIAL_RETENTION_HOURS` to change this period; after deletion, add the account again instead of retrying it.
- The same source/target mailbox pair cannot run concurrently twice.
- Each transfer has separate PID and log files; the default concurrency is three accounts.
- A job completes only after a successful imapsync exit and integrity summary.
- Jobs left in progress after a service restart become `interrupted` and can be retried.
- New migrations are rejected when imapsync is unavailable.
- `migration_db.sql` is the only schema file required for a clean installation.
- Queue pause state survives service restarts. A password-free CSV report is available from the sidebar. The dashboard shows the latest 500 jobs while the report contains every job.

Run exactly one Uvicorn worker because the queue manager lives inside the application process. Do not re-run `setup.sh` or import `migration_db.sql` into a live installation during updates; follow the release-specific upgrade notes.

### Developer tests

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q
```

GitHub Actions validates the Python tests, JavaScript syntax, and Ubuntu installation scripts on every push and pull request.

## License

Released under the [MIT License](LICENSE).
