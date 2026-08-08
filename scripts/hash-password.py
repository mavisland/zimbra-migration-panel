#!/usr/bin/env python3
import getpass
import hashlib
import locale
import os
import secrets
import sys

def password_messages(language=None):
    language = language or os.getenv("INSTALL_LANGUAGE") or (locale.getlocale()[0] or "en")
    turkish = language.lower().startswith("tr")
    return {
        "password": "Panel parolası: " if turkish else "Panel password: ",
        "confirmation": "Panel parolası (tekrar): " if turkish else "Confirm panel password: ",
        "mismatch": "Parolalar eşleşmiyor" if turkish else "Passwords do not match",
        "length": "Parola en az 12 karakter olmalıdır" if turkish else "The password must be at least 12 characters long",
        "required": "Parola boş bırakılamaz" if turkish else "The password cannot be empty",
    }


def generate_password_hash(language=None):
    messages = password_messages(language)
    while True:
        password = getpass.getpass(messages["password"])
        if not password:
            print(messages["required"], file=sys.stderr)
            continue
        if len(password) < 12:
            print(messages["length"], file=sys.stderr)
            continue
        confirmation = getpass.getpass(messages["confirmation"])
        if password != confirmation:
            print(messages["mismatch"], file=sys.stderr)
            continue
        n, r, p = 16384, 8, 1
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
        return f"$scrypt${n}${r}${p}${salt.hex()}${digest.hex()}"


if __name__ == "__main__":
    print(generate_password_hash())
