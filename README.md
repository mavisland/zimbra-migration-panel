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
