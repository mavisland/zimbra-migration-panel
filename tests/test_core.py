from __future__ import annotations

import hashlib
import importlib.util
import time
from datetime import date
from pathlib import Path

import pytest

import app

HASH_PASSWORD_PATH = Path(__file__).resolve().parents[1] / "scripts" / "hash-password.py"
HASH_PASSWORD_SPEC = importlib.util.spec_from_file_location("hash_password", HASH_PASSWORD_PATH)
assert HASH_PASSWORD_SPEC and HASH_PASSWORD_SPEC.loader
hash_password = importlib.util.module_from_spec(HASH_PASSWORD_SPEC)
HASH_PASSWORD_SPEC.loader.exec_module(hash_password)


def payload(**overrides):
    values = {
        "source_host": "imap.old.example",
        "source_port": "993",
        "source_security": "ssl",
        "source_email": "old@example.com",
        "source_password": "old-secret",
        "target_host": "mail.new.example",
        "target_port": "993",
        "target_security": "ssl",
        "target_email": "new@example.com",
        "target_password": "new-secret",
        "start_date": "",
        "end_date": "",
    }
    values.update(overrides)
    return values


def test_password_verification_accepts_only_matching_scrypt_hash():
    salt = bytes.fromhex("00112233445566778899aabbccddeeff")
    digest = hashlib.scrypt(b"correct horse", salt=salt, n=16384, r=8, p=1, dklen=32).hex()
    encoded = f"$scrypt$16384$8$1${salt.hex()}${digest}"

    assert app.verify_password("correct horse", encoded)
    assert not app.verify_password("wrong", encoded)
    assert not app.verify_password("correct horse", "invalid")


def test_payload_validation_normalizes_fields_and_rejects_bad_dates():
    normalized = app.validate_payload(payload(source_host=" imap.old.example ", source_port="143", source_security="tls"))
    assert normalized["source_host"] == "imap.old.example"
    assert normalized["source_port"] == 143
    assert normalized["source_security"] == "tls"

    with pytest.raises(ValueError, match="Bitiş tarihi"):
        app.validate_payload(payload(start_date="2026-08-10", end_date="2026-08-09"))


def test_imapsync_command_uses_passfiles_pid_lock_tls_and_date_filter(tmp_path):
    row = app.validate_payload(payload(start_date="2026-01-01", end_date="2026-02-01"))
    row["start_date"] = date(2026, 1, 1)
    row["end_date"] = date(2026, 2, 1)
    command = app.MigrationManager().command(row, "/tmp/source.pass", "/tmp/target.pass", tmp_path / "job.pid")

    assert "--passfile1" in command and "old-secret" not in command
    assert "--passfile2" in command and "new-secret" not in command
    assert "--pidfilelocking" in command
    assert "--ssl1" in command and "--ssl2" in command
    assert command[command.index("--search1") + 1] == "SENTSINCE 01-Jan-2026 SENTBEFORE 01-Feb-2026"


def test_progress_parser_counts_a_copied_message_without_database_flush():
    state = {"transferred": 0, "skipped": 0, "bytes_transferred": 0, "discovered": 10,
             "last_flush": time.monotonic(), "sync_good": False, "unidentified_ok": False,
             "detected_errors": None, "exited_ok": False}
    app.MigrationManager().parse_progress(42, "msg Inbox/1 {2048} copied to Inbox/1 0.12 msgs/s\n", state)

    assert state["transferred"] == 1
    assert state["bytes_transferred"] == 2048


def test_public_job_never_exposes_encrypted_passwords():
    result = app.public_job({"id": 1, "source_password": b"encrypted", "target_password": b"encrypted"})
    assert result["credentials_available"] is True
    assert "source_password" not in result
    assert "target_password" not in result


def test_password_prompt_retries_after_blank_input(monkeypatch, capsys):
    answers = iter(["", "valid-password-123", "valid-password-123"])
    monkeypatch.setattr(hash_password.getpass, "getpass", lambda _prompt: next(answers))

    encoded = hash_password.generate_password_hash("en")

    assert encoded.startswith("$scrypt$")
    assert "cannot be empty" in capsys.readouterr().err
