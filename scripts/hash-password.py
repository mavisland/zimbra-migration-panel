#!/usr/bin/env python3
import getpass
import hashlib
import secrets

password = getpass.getpass("Panel parolası: ")
confirmation = getpass.getpass("Panel parolası (tekrar): ")
if password != confirmation:
    raise SystemExit("Parolalar eşleşmiyor")
if len(password) < 12:
    raise SystemExit("Parola en az 12 karakter olmalıdır")

n, r, p = 16384, 8, 1
salt = secrets.token_bytes(16)
digest = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
print(f"$scrypt${n}${r}${p}${salt.hex()}${digest.hex()}")
