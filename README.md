# Zimbra IMAP Aktarım Paneli

imapsync işlemlerini web arayüzünden yöneten, MySQL tabanlı aktarım kuyruğudur. Tekli veya CSV hesap ekleme, en fazla üç paralel aktarım, canlı ilerleme, domain/durum gruplama, şifreli parola saklama ve CSV raporlama sağlar.

## İlk kurulum

Ubuntu sunucuda depoyu klonlayıp kurulum betiğini çalıştırın:

```bash
git clone https://github.com/mavisland/zimbra-migration-panel.git
cd zimbra-migration-panel
sudo bash setup.sh
```

Betik yalnızca ilk kurulum içindir ve sırasıyla şunları yapar:

- Python 3.10+ ve imapsync sürümlerini denetler; yalnızca eksik bileşenleri kurar.
- `/opt/zimbra-migration` dizini ile `zimbra-migrator` servis kullanıcısını hazırlar.
- `zimbra_migration` veritabanını ve yalnızca bu veritabanında CRUD yetkili kullanıcıyı oluşturur.
- Tek şema dosyası olan `migration_db.sql` dosyasını içe aktarır.
- Panel kullanıcı adı/parolasını sorup `.env` ve şifreleme ayarlarını üretir.
- systemd servisini kurup başlatır.

Zimbra’nın `/opt/zimbra` altındaki gömülü MariaDB/MySQL veritabanı, Zimbra’ya ait şema ve yükseltme yaşam döngüsünün parçasıdır. Panel tablolarını buraya eklemek yerine `setup.sh`, işletim sisteminde bağımsız bir MySQL/MariaDB hizmeti varsa onu kullanır; yoksa `default-mysql-server` kurar. Böylece Zimbra veritabanına ve kimlik bilgilerine dokunulmaz.

`setup.sh` tüm ilk kurulum işlemlerini yürütür; kullanıcıdan yalnızca panel kullanıcı adı ve parolası istenir. Mevcut `/opt/zimbra-migration/.env` dosyası varsa veri kaybını önlemek için durur.

Kurulum sonunda gösterilen adresi tarayıcıda açın:

```text
http://SUNUCU_IP:8787
```

Portu genel internete açmayın. Yalnızca yönetici bilgisayarına izin verme örneği:

```bash
sudo ufw allow from YONETICI_IP to any port 8787 proto tcp
```

Servis kontrolü:

```bash
sudo systemctl status zimbra-migration
sudo journalctl -u zimbra-migration -f
```

## Kurulumun doğrulanması

```bash
command -v imapsync
imapsync --version
mysql -h 127.0.0.1 -u zimbra_migrator -p \
  -e "SELECT COUNT(*) FROM zimbra_migration.jobs;"
curl -I http://127.0.0.1:8787/login
```

MySQL parolası `/opt/zimbra-migration/.env` içinde otomatik üretilir. Uygulamanın Fernet anahtarı ilk başlangıçta `/opt/zimbra-migration/data/secret.key` olarak oluşur; bu dosyayı güvenli biçimde yedekleyin.

## Güvenli erişim

Panelde scrypt parola özeti kullanan oturum açma, imzalı oturum çerezi, CSRF koruması ve güvenilir Host kontrolü bulunur. HTTP erişimini yalnızca güvenilir LAN/VPN üzerinde kullanın.

SSH tüneliyle erişmek için uygulamayı `.env` içinde `APP_HOST=127.0.0.1` yapıp:

```bash
ssh -L 8787:127.0.0.1:8787 kullanici@zimbra-sunucusu
```

ardından yerel tarayıcıda `http://127.0.0.1:8787` adresini açabilirsiniz.

Doğrudan Uvicorn TLS kullanmak için:

```dotenv
SESSION_HTTPS_ONLY=true
TLS_CERTFILE=/opt/zimbra-migration/certs/fullchain.pem
TLS_KEYFILE=/opt/zimbra-migration/certs/privkey.pem
```

Sertifika dosyalarının `zimbra-migrator` tarafından okunabildiğinden emin olun. Nginx kullanılmaz.

## CSV biçimi

```csv
source_host,source_port,source_security,source_email,source_password,target_host,target_port,target_security,target_email,target_password,start_date,end_date
imap.example.com,993,ssl,old@example.com,old-secret,mail.example.com,993,ssl,new@example.com,new-secret,,
```

CSV UTF-8 olmalı; varsayılan sınırlar 5 MiB ve 5.000 hesaptır. Tarihler isteğe bağlı ve `YYYY-MM-DD` biçimindedir. Tekli formdaki **Bağlantıyı Test Et** işlemi imapsync `--justlogin` çalıştırır ve posta taşımaz.

## Aktarım güvenliği ve davranışı

- Parolalar MySQL’de Fernet ile şifreli tutulur ve imapsync’e izinleri `0600` olan geçici passfile üzerinden verilir.
- Her iş ayrı PID dosyası kullanır; aynı kaynak/hedef mailbox çifti aynı anda ikinci kez başlatılamaz.
- Başarılı `msg ... copied to ...` satırları canlı sayaçları günceller.
- İş yalnızca imapsync sıfır koduyla çıktığında ve bütünlük özeti `Detected 0 errors` verdiğinde tamamlanır.
- Servis yeniden başlarsa yarım kalan işler `interrupted` durumuna alınır ve yeniden denenebilir.
- imapsync yoksa panel yeni aktarım kabul etmez.
- `migration_db.sql` tüm güncel tablo, indeks ve kısıtları içeren tek kurulum dosyasıdır.

## systemd

Servis tanımı: [`deploy/zimbra-migration.service`](deploy/zimbra-migration.service)

Kuyruk yöneticisi uygulama içinde çalıştığı için yalnızca tek Uvicorn worker kullanılmalıdır. Uygulama verileri:

```text
/opt/zimbra-migration/data
/opt/zimbra-migration/logs
```

## Güncelleme

İlk kurulum betiğini güncelleme için tekrar çalıştırmayın. Güncelleme süreci ayrıca hazırlanacaktır. Canlı veritabanında `migration_db.sql` dosyasını yeniden içe aktarmayın.
