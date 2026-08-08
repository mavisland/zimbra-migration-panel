#!/usr/bin/env python3
import getpass
import hashlib
import locale
import os
import secrets

language = os.getenv("INSTALL_LANGUAGE") or (locale.getlocale()[0] or "en")
turkish = language.lower().startswith("tr")
messages = {
    "password": "Panel parolası: " if turkish else "Panel password: ",
    "confirmation": "Panel parolası (tekrar): " if turkish else "Confirm panel password: ",
    "mismatch": "Parolalar eşleşmiyor" if turkish else "Passwords do not match",
    "length": "Parola en az 12 karakter olmalıdır" if turkish else "The password must be at least 12 characters long",
}

password = getpass.getpass(messages["password"])
confirmation = getpass.getpass(messages["confirmation"])
if password != confirmation:
    raise SystemExit(messages["mismatch"])
if len(password) < 12:
    raise SystemExit(messages["length"])

n, r, p = 16384, 8, 1
salt = secrets.token_bytes(16)
digest = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
print(f"$scrypt${n}${r}${p}${salt.hex()}${digest.hex()}")
