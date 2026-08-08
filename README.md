# Zimbra IMAP Migration Panel

[Türkçe](#türkçe) · [English](#english)

Browser-based, MySQL-backed queue and monitoring panel for parallel `imapsync` migrations. It supports single-account and CSV imports, three concurrent transfers by default, live progress, status/domain grouping, encrypted credentials, retries, and transfer logs.

> This is an independent community project. It is not affiliated with or endorsed by Zimbra or the imapsync project.

> ### Zimbra için profesyonel desteğe mi ihtiyacınız var?
>
> Zimbra kurulumu, sürüm yükseltme, posta taşıma, bakım, yedekleme, performans iyileştirme ve arıza giderme konularında planlama ve uygulama desteği sunabilirim.
>
> **[Destek talebi oluşturun →](https://github.com/mavisland/zimbra-migration-panel/issues/new?template=professional-support.yml)**
>
> Talebinizde parola, özel anahtar veya sunucu erişim bilgisi paylaşmayın. İlk görüşmeden sonra hassas bilgiler için güvenli bir iletişim yöntemi belirlenir.

> ### Need professional Zimbra support?
>
> I can help plan and deliver Zimbra installation, upgrades, mail migration, maintenance, backup, performance tuning, and incident troubleshooting.
>
> **[Request support →](https://github.com/mavisland/zimbra-migration-panel/issues/new?template=professional-support.yml)**
>
> Do not include passwords, private keys, or server credentials in a public request. A secure communication method can be agreed upon after initial contact.

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

`sudo` sizden Ubuntu kullanıcı parolanızı isteyebilir. Kurulum daha sonra panel için bir kullanıcı adı ve parola sorar. Kullanıcı adını boş bırakırsanız `admin` kullanılır; kullanıcı adı yalnızca ASCII harf ve rakam içerebilir, özel karakter kullanılamaz. Panel parolası Ubuntu parolasından farklıdır, en az 12 karakter olmalıdır ve tarayıcıda oturum açmak için kullanılır. Parola yazılırken ekranda karakter görünmemesi normaldir. Boş, kısa veya eşleşmeyen değer girilirse kurulum kapanmadan yeniden sorar.

`setup.sh` ilk kurulumun tamamını yürütür:

- Kurulum boyunca sistem dili Türkçeyse Türkçe, diğer dillerde İngilizce mesajlar gösterir.
- Ubuntu 20.04'ün varsayılan Python 3.8 sürümü dahil Python 3.8+ ile `venv`/`pip` bileşenlerini denetler. Python eksik veya eskiyse otomatik kurulum yapmadan örnek Ubuntu komutunu gösterip durur.
- imapsync ve bağımsız MySQL/MariaDB bileşenlerini denetler; eksikleri kurar.
- `/opt/zimbra-migration` dizini ile kısıtlı `zimbra-migrator` servis kullanıcısını oluşturur.
- `zimbra_migration` veritabanını ve yalnızca bu veritabanında CRUD yetkili kullanıcıyı oluşturur.
- Tek şema dosyası olan `migration_db.sql` dosyasını içe aktarır.
- Panel kullanıcı adı/parolasını alır; uygulama sırlarını ve `.env` dosyasını üretir.
- systemd servisini etkinleştirip başlatır.

`setup.sh` güvenle tekrar çalıştırılabilir. Mevcut kurulum algılandığında `.env`, şifreleme anahtarı, veritabanı, hesap parolaları ve iş kayıtları korunur; uygulama dosyaları, Python bağımlılıkları ve systemd servisi güncellenir. Yarım kalan ilk kurulumda mevcut veritabanı ve kullanıcı yeniden kullanılarak eksik adımlar tamamlanır.

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
- **Kurulumu tekrar çalıştırmak istiyorum:** Çalışan sistemde `setup.sh` dosyasını yeniden çalıştırabilirsiniz. Betik mevcut yapılandırmayı ve verileri korur; önemli bir güncelleme öncesinde `.env`, `data/secret.key` ve MySQL veritabanını yedeklemeniz yine önerilir.

### Çalışma biçimi

- Parolalar MySQL'de Fernet ile şifreli tutulur ve imapsync'e `0600` izinli geçici passfile üzerinden verilir.
- Tamamlanan veya duran işlerin şifreli parolaları varsayılan olarak 24 saat sonra silinir. Süre `CREDENTIAL_RETENTION_HOURS` ile değiştirilebilir; sonrasında yeniden denemek için hesap tekrar eklenmelidir.
- Aynı kaynak/hedef posta kutusu çifti eş zamanlı olarak ikinci kez başlatılamaz.
- Her aktarım ayrı PID ve log dosyası kullanır; varsayılan paralellik üç hesaptır.
- İş, imapsync başarılı çıkış ve bütünlük özeti verdiğinde tamamlanmış sayılır.
- Servis yeniden başlarsa yarım kalan işler `interrupted` olur ve yeniden denenebilir.
- imapsync bulunamazsa yeni aktarım kabul edilmez.
- Bağlantı testi başarısız olduğunda panel, Perl çağrı zinciri yerine imapsync çıkış kodunu, sürümünü ve anlamlı hata satırlarını gösterir; geçici parola dosyası yolları maskelenir.
- `migration_db.sql` temiz kurulum için gereken bütün tabloları içeren tek şema dosyasıdır.
- Kuyruğu duraklatma seçimi servis yeniden başlatıldığında korunur; parola içermeyen CSV raporu sol menüden indirilebilir. Dashboard son 500 işi gösterir, rapor bütün işleri içerir.
- Arayüz tarayıcı dili `tr` ile başlıyorsa Türkçe, diğer bütün dillerde İngilizce gösterilir. Tahmini süre, çalışan işlerin geçen süre/aktarılan mesaj hızından hesaplanır; henüz mesaj sayısı keşfedilmemiş işler varken hesaplanıyor durumu gösterilir.

Kuyruk yöneticisi uygulama içinde çalıştığından yalnızca tek Uvicorn worker kullanın. Güncelleme için yeni kodu aldıktan sonra `setup.sh` yeniden çalıştırılabilir; `migration_db.sql` dosyasını ise canlı veritabanına elle içe aktarmayın.

### Güncelleme

Git deposundaki `git pull` yalnızca klonlanan kaynak dizini günceller; çalışan `/opt/zimbra-migration` kopyasını tek başına değiştirmez. Güncellemeyi devreye almak için depo dizininde iki komutu birlikte çalıştırın:

```bash
git pull --ff-only
sudo bash setup.sh
```

`setup.sh` mevcut `.env`, şifreleme anahtarı ve verileri korur; güncel dosyaları `/opt/zimbra-migration` altına kopyalar, Python bağımlılıklarını eşitler ve `zimbra-migration` servisini yeniden başlatır. Servis durumunda `active (running)` gördüğünüzde yeni sürüm devrededir.

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

`sudo` may ask for your Ubuntu account password. The installer then asks for a panel username and password. Leaving the username empty selects `admin`; usernames may contain only ASCII letters and numbers, with no special characters. The panel password is separate from the Ubuntu password, must be at least 12 characters long, and is used to sign in through the browser. It is normal for no characters to appear while typing a password. Empty, short, or mismatched values are requested again without terminating setup.

`setup.sh` performs the complete first-time installation:

- Displays Turkish messages throughout installation when the system locale is Turkish, and English messages for every other locale.
- Supports Ubuntu 20.04's default Python 3.8 and checks for Python 3.8+ with the `venv`/`pip` components. If Python is missing or outdated, it does not install Python automatically; it stops and prints an example Ubuntu command.
- Checks imapsync and the independent MySQL/MariaDB service, installing missing components.
- Creates `/opt/zimbra-migration` and the restricted `zimbra-migrator` service account.
- Creates the `zimbra_migration` database and a user limited to CRUD access on that database.
- Imports the single schema file, `migration_db.sql`.
- Prompts for the panel username/password and generates application secrets and `.env`.
- Enables and starts the systemd service.

`setup.sh` is safe to run again. When it detects an existing installation, it preserves `.env`, the encryption key, database, account credentials, and job records while refreshing application files, Python dependencies, and the systemd service. After a partial first installation, it reuses the existing database and user and completes the remaining steps.

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
- **I want to run installation again:** You may run `setup.sh` again on a working system. It preserves existing configuration and data; backing up `.env`, `data/secret.key`, and the MySQL database before an important update is still recommended.

### Runtime behavior

- Passwords are Fernet-encrypted in MySQL and passed to imapsync through temporary passfiles with `0600` permissions.
- Encrypted passwords for finished or stopped jobs are deleted after 24 hours by default. Configure `CREDENTIAL_RETENTION_HOURS` to change this period; after deletion, add the account again instead of retrying it.
- The same source/target mailbox pair cannot run concurrently twice.
- Each transfer has separate PID and log files; the default concurrency is three accounts.
- A job completes only after a successful imapsync exit and integrity summary.
- Jobs left in progress after a service restart become `interrupted` and can be retried.
- New migrations are rejected when imapsync is unavailable.
- When a connection test fails, the panel shows the imapsync exit code, version, and meaningful diagnostic lines instead of the Perl call stack; temporary password-file paths are masked.
- `migration_db.sql` is the only schema file required for a clean installation.
- Queue pause state survives service restarts. A password-free CSV report is available from the sidebar. The dashboard shows the latest 500 jobs while the report contains every job.
- The interface uses Turkish when the browser language starts with `tr`, and English for every other language. ETA is calculated from elapsed time per transferred message for running jobs; it remains in the calculating state while queued jobs have not discovered their message counts.

Run exactly one Uvicorn worker because the queue manager lives inside the application process. After pulling updated code, `setup.sh` may be run again; do not manually import `migration_db.sql` into a live database.

### Updating

Running `git pull` updates only the cloned source directory; it does not update the active copy under `/opt/zimbra-migration` by itself. Run both commands from the repository directory:

```bash
git pull --ff-only
sudo bash setup.sh
```

`setup.sh` preserves the existing `.env`, encryption key, and data; copies current files into `/opt/zimbra-migration`, synchronizes Python dependencies, and restarts the `zimbra-migration` service. The new version is active when the service reports `active (running)`.

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

Developed by **Tanju Yıldız**, 2026.
