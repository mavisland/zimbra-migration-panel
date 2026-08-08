from __future__ import annotations

import asyncio
import csv
import hashlib
import hmac
import io
import json
import os
import re
import shutil
import secrets
import subprocess
import tempfile
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from typing_extensions import Annotated

import uvicorn
import pymysql
from pymysql.cursors import DictCursor
from dotenv import load_dotenv
from cryptography.fernet import Fernet
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
DATA = ROOT / "data"
LOGS = ROOT / "logs"
PIDS = DATA / "pids"
KEY_PATH = DATA / "secret.key"
MAX_PARALLEL = max(1, int(os.getenv("MAX_PARALLEL", "3")))
CSV_MAX_BYTES = max(1024, int(os.getenv("CSV_MAX_BYTES", str(5 * 1024 * 1024))))
CSV_MAX_ROWS = max(1, int(os.getenv("CSV_MAX_ROWS", "5000")))
CREDENTIAL_RETENTION_HOURS = max(0, int(os.getenv("CREDENTIAL_RETENTION_HOURS", "24")))
IMAPSYNC_PATH = os.getenv("IMAPSYNC_PATH", "imapsync")
IMAPSYNC_SSL_VERIFY = os.getenv("IMAPSYNC_SSL_VERIFY", "true").lower() in {"1", "true", "yes"}
APP_USERNAME = os.getenv("APP_USERNAME", "admin")
APP_PASSWORD_HASH = os.getenv("APP_PASSWORD_HASH", "")
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
SESSION_HTTPS_ONLY = os.getenv("SESSION_HTTPS_ONLY", "false").lower() in {"1", "true", "yes"}
ALLOWED_HOSTS = [host.strip() for host in os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if host.strip()]
TLS_CERTFILE = os.getenv("TLS_CERTFILE", "").strip() or None
TLS_KEYFILE = os.getenv("TLS_KEYFILE", "").strip() or None
CSV_REQUIRED_FIELDS = {"source_host", "source_port", "source_security", "source_email",
                       "source_password", "target_host", "target_port", "target_security",
                       "target_email", "target_password", "start_date", "end_date"}
IMAPSYNC_STATUS_CACHE: dict = {"checked_at": 0.0, "value": None}

DATA.mkdir(exist_ok=True)
LOGS.mkdir(exist_ok=True)
PIDS.mkdir(exist_ok=True)


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Database:
    """Small compatibility wrapper keeping transaction handling explicit."""

    def __init__(self):
        self.connection = pymysql.connect(
            host=os.getenv("MYSQL_HOST", "127.0.0.1"),
            port=int(os.getenv("MYSQL_PORT", "3306")),
            user=os.getenv("MYSQL_USER", "zimbra_migrator"),
            password=os.getenv("MYSQL_PASSWORD", ""),
            database=os.getenv("MYSQL_DATABASE", "zimbra_migration"),
            charset="utf8mb4", cursorclass=DictCursor, autocommit=False,
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, _tb):
        self.connection.rollback() if exc_type else self.connection.commit()
        self.connection.close()

    def execute(self, sql: str, params=None):
        sql = sql.replace("?", "%s")
        if isinstance(params, dict):
            sql = re.sub(r":([a-zA-Z_]\w*)", r"%(\1)s", sql)
        cursor = self.connection.cursor()
        cursor.execute(sql, params)
        return cursor


def db() -> Database:
    return Database()


def init_db() -> None:
    for pattern in (".pass-*", "pids/job-*.pid"):
        for stale_file in DATA.glob(pattern):
            stale_file.unlink(missing_ok=True)
    with db() as conn:
        conn.execute("INSERT IGNORE INTO app_state (state_key,state_value) VALUES ('paused','0')")
        conn.execute("""UPDATE jobs SET status='interrupted', pid=NULL, active_lock=NULL, finished_at=?,
            error='Uygulama yeniden başlatıldığı için aktarım kesildi'
            WHERE status IN ('starting','running','stopping')""", (now(),))


def cipher() -> Fernet:
    if not KEY_PATH.exists():
        KEY_PATH.write_bytes(Fernet.generate_key())
        try:
            os.chmod(KEY_PATH, 0o600)
        except OSError:
            pass
    return Fernet(KEY_PATH.read_bytes())


CRYPT = cipher()


def imapsync_status(force: bool = False) -> dict:
    if not force and IMAPSYNC_STATUS_CACHE["value"] and time.monotonic() - IMAPSYNC_STATUS_CACHE["checked_at"] < 30:
        return IMAPSYNC_STATUS_CACHE["value"]
    executable = shutil.which(IMAPSYNC_PATH) if not Path(IMAPSYNC_PATH).is_file() else str(Path(IMAPSYNC_PATH).resolve())
    if not executable:
        status = {"available": False, "path": IMAPSYNC_PATH, "version": None,
                  "error": "imapsync bulunamadı. Ubuntu kurulum adımlarını tamamlayın."}
        IMAPSYNC_STATUS_CACHE.update(checked_at=time.monotonic(), value=status)
        return status
    try:
        result = subprocess.run([executable, "--version"], capture_output=True, text=True,
                                timeout=10, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        output = (result.stdout or result.stderr).strip().splitlines()
        if result.returncode != 0:
            status = {"available": False, "path": executable, "version": None,
                      "error": output[-1] if output else f"imapsync çıkış kodu: {result.returncode}"}
        else:
            status = {"available": True, "path": executable,
                      "version": output[-1] if output else "Sürüm bilgisi alınamadı", "error": None}
    except (OSError, subprocess.SubprocessError) as exc:
        status = {"available": False, "path": executable, "version": None, "error": str(exc)}
    IMAPSYNC_STATUS_CACHE.update(checked_at=time.monotonic(), value=status)
    return status


def imapsync_exists() -> bool:
    return Path(IMAPSYNC_PATH).is_file() or shutil.which(IMAPSYNC_PATH) is not None


def require_imapsync() -> None:
    status = imapsync_status(force=True)
    if not status["available"]:
        raise HTTPException(503, status["error"])


def clean_security(value: str) -> str:
    value = value.strip().lower()
    if value not in {"ssl", "tls", "none"}:
        raise ValueError("Güvenlik ssl, tls veya none olmalıdır")
    return value


def verify_password(password: str, encoded: str) -> bool:
    try:
        marker, algorithm, n, r, p, salt_hex, digest_hex = encoded.split("$")
        if marker or algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex),
                                n=int(n), r=int(r), p=int(p), dklen=32).hex()
        return hmac.compare_digest(actual, digest_hex)
    except (ValueError, TypeError):
        return False


def append_security_args(cmd: list[str], normalized: dict) -> None:
    for side, prefix in ((1, "source"), (2, "target")):
        security = normalized[f"{prefix}_security"]
        if security == "ssl":
            cmd.append(f"--ssl{side}")
        elif security == "tls":
            cmd.append(f"--tls{side}")
        else:
            cmd += [f"--nossl{side}", f"--notls{side}"]
        if security != "none" and IMAPSYNC_SSL_VERIFY:
            cmd += [f"--sslargs{side}", "SSL_verify_mode=1",
                    f"--sslargs{side}", f"SSL_verifycn_name={normalized[f'{prefix}_host']}"]


def validate_payload(payload: dict) -> dict:
    required = ["source_host", "source_email", "source_password", "target_host", "target_email", "target_password"]
    if any(not str(payload.get(key, "")).strip() for key in required):
        raise ValueError("Zorunlu alanlar eksik")
    for key in ("source_host", "target_host", "source_email", "target_email"):
        value = str(payload[key]).strip()
        if any(ord(char) < 32 for char in value):
            raise ValueError(f"{key} kontrol karakteri içeremez")
    for key in ("source_email", "target_email"):
        email = str(payload[key]).strip()
        if email.count("@") != 1 or not all(email.split("@")):
            raise ValueError(f"Geçersiz e-posta adresi: {email}")
    source_port = int(payload.get("source_port") or 993)
    target_port = int(payload.get("target_port") or 993)
    if not 1 <= source_port <= 65535 or not 1 <= target_port <= 65535:
        raise ValueError("Port 1 ile 65535 arasında olmalıdır")
    start_date = str(payload.get("start_date") or "").strip()
    end_date = str(payload.get("end_date") or "").strip()
    start = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
    end = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None
    if start and end and end < start:
        raise ValueError("Bitiş tarihi başlangıç tarihinden önce olamaz")
    return {
        "source_host": str(payload["source_host"]).strip(), "source_port": source_port,
        "source_security": clean_security(str(payload.get("source_security") or "ssl")),
        "source_email": str(payload["source_email"]).strip(), "source_password": str(payload["source_password"]),
        "target_host": str(payload["target_host"]).strip(), "target_port": target_port,
        "target_security": clean_security(str(payload.get("target_security") or "ssl")),
        "target_email": str(payload["target_email"]).strip(), "target_password": str(payload["target_password"]),
        "start_date": start_date or None, "end_date": end_date or None,
    }


def add_job(payload: dict) -> int:
    normalized = validate_payload(payload)
    lock_material = "\0".join(str(normalized[key]).strip().lower() for key in
                              ("source_host", "source_email", "target_host", "target_email"))
    lock_key = hashlib.sha256(lock_material.encode()).hexdigest()
    values = {
        **normalized,
        "source_password": CRYPT.encrypt(normalized["source_password"].encode()),
        "target_password": CRYPT.encrypt(normalized["target_password"].encode()),
        "lock_key": lock_key,
        "active_lock": lock_key,
    }
    with db() as conn:
        cursor = conn.execute(
            """INSERT INTO jobs
            (source_host,source_port,source_security,source_email,source_password,
             target_host,target_port,target_security,target_email,target_password,
             start_date,end_date,lock_key,active_lock,created_at)
            VALUES (:source_host,:source_port,:source_security,:source_email,:source_password,
                    :target_host,:target_port,:target_security,:target_email,:target_password,
                    :start_date,:end_date,:lock_key,:active_lock,:created_at)""",
            dict(values, created_at=now()),
        )
        return int(cursor.lastrowid)


def public_job(row: dict) -> dict:
    item = dict(row)
    item["credentials_available"] = bool(item.get("source_password") and item.get("target_password"))
    item.pop("source_password", None)
    item.pop("target_password", None)
    return item


def summarize_imapsync_failure(stdout: str, stderr: str, returncode: int, secret_paths=None) -> str:
    text = "\n".join(part for part in (stdout, stderr) if part)
    for secret_path in secret_paths or []:
        text = text.replace(str(secret_path), "[PASSFILE]")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    non_stack = [line for line in lines if not re.search(r"\bcalled at .+ line \d+\.?$", line, re.I)]
    markers = re.compile(r"error|failure|failed|invalid|denied|certificate|authentication|can't|cannot|unable", re.I)
    important = [line for line in non_stack if markers.search(line)]
    selected = (important[-6:] if important else non_stack[-8:])
    version = imapsync_status().get("version") or "unknown"
    details = "\n".join(selected) if selected else "No diagnostic output was produced."
    return f"imapsync exit code: {returncode} · version: {version}\n{details}"


def test_connections(payload: dict) -> dict:
    normalized = validate_payload(payload)
    passfiles = []
    try:
        for password in (normalized["source_password"], normalized["target_password"]):
            handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=DATA, prefix=".pass-")
            handle.write(password)
            handle.close()
            os.chmod(handle.name, 0o600)
            passfiles.append(handle.name)
        cmd = [IMAPSYNC_PATH, "--host1", normalized["source_host"], "--port1", str(normalized["source_port"]),
               "--user1", normalized["source_email"], "--passfile1", passfiles[0],
               "--host2", normalized["target_host"], "--port2", str(normalized["target_port"]),
               "--user2", normalized["target_email"], "--passfile2", passfiles[1],
               "--justlogin", "--nolog", "--noreleasecheck"]
        append_security_args(cmd, normalized)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=90,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if result.returncode:
            raise ValueError(summarize_imapsync_failure(
                result.stdout, result.stderr, result.returncode, passfiles))
        return {"ok": True, "message": "Kaynak ve hedef IMAP oturumları doğrulandı"}
    except subprocess.TimeoutExpired as exc:
        raise ValueError("IMAP bağlantı testi 90 saniyede tamamlanamadı") from exc
    finally:
        for filename in passfiles:
            Path(filename).unlink(missing_ok=True)


class MigrationManager:
    def __init__(self) -> None:
        self.stop_event = asyncio.Event()
        self.wakeup = asyncio.Event()
        self.running: dict[int, asyncio.subprocess.Process] = {}
        self.tasks: set[asyncio.Task] = set()
        self.loop_task: Optional[asyncio.Task] = None
        self.paused = False
        self.last_housekeeping = 0.0

    async def start(self) -> None:
        with db() as conn:
            state = conn.execute("SELECT state_value FROM app_state WHERE state_key='paused'").fetchone()
        self.paused = bool(state and state["state_value"] == "1")
        self.purge_expired_credentials()
        self.loop_task = asyncio.create_task(self.scheduler())

    async def shutdown(self) -> None:
        self.stop_event.set()
        self.wakeup.set()
        if self.loop_task:
            await self.loop_task
        running_ids = list(self.running)
        if running_ids:
            placeholders = ",".join("?" for _ in running_ids)
            with db() as conn:
                conn.execute(f"""UPDATE jobs SET status='interrupted', pid=NULL, active_lock=NULL, finished_at=?,
                    error='Uygulama kapatıldığı için aktarım kesildi' WHERE id IN ({placeholders})""",
                    (now(), *running_ids))
        for process in list(self.running.values()):
            process.terminate()
        if self.tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*self.tasks, return_exceptions=True), timeout=15)
            except asyncio.TimeoutError:
                for process in list(self.running.values()):
                    process.kill()

    async def scheduler(self) -> None:
        while not self.stop_event.is_set():
            if time.monotonic() - self.last_housekeeping >= 60:
                self.purge_expired_credentials()
            capacity = MAX_PARALLEL - len(self.running)
            if capacity > 0 and not self.paused and imapsync_exists():
                with db() as conn:
                    rows = conn.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY id LIMIT ?", (capacity,)).fetchall()
                    for row in rows:
                        updated = conn.execute("UPDATE jobs SET status='starting', started_at=? WHERE id=? AND status='queued'", (now(), row["id"]))
                        if updated.rowcount:
                            task = asyncio.create_task(self.run_job(row["id"]))
                            self.tasks.add(task)
                            task.add_done_callback(self.tasks.discard)
            self.wakeup.clear()
            try:
                await asyncio.wait_for(self.wakeup.wait(), timeout=1)
            except asyncio.TimeoutError:
                pass

    def purge_expired_credentials(self) -> None:
        cutoff = now() - timedelta(hours=CREDENTIAL_RETENTION_HOURS)
        with db() as conn:
            conn.execute("""UPDATE jobs SET source_password=NULL,target_password=NULL,credentials_purged_at=?
                WHERE credentials_purged_at IS NULL AND finished_at IS NOT NULL AND finished_at <= ?
                AND status IN ('completed','failed','stopped','interrupted')""", (now(), cutoff))
        self.last_housekeeping = time.monotonic()

    def command(self, row: dict, pass1: str, pass2: str, pid_path: Path) -> list[str]:
        cmd = [IMAPSYNC_PATH,
               "--host1", row["source_host"], "--port1", str(row["source_port"]),
               "--user1", row["source_email"], "--passfile1", pass1,
               "--host2", row["target_host"], "--port2", str(row["target_port"]),
               "--user2", row["target_email"], "--passfile2", pass2,
               "--automap", "--addheader", "--pidfile", str(pid_path),
               "--pidfilelocking", "--nolog"]
        append_security_args(cmd, row)
        search_terms = []
        if row["start_date"]:
            search_terms.append(f"SENTSINCE {row['start_date'].strftime('%d-%b-%Y')}")
        if row["end_date"]:
            search_terms.append(f"SENTBEFORE {row['end_date'].strftime('%d-%b-%Y')}")
        if search_terms:
            cmd += ["--search1", " ".join(search_terms)]
        return cmd

    async def run_job(self, job_id: int) -> None:
        with db() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return
        log_path = LOGS / f"job-{job_id}.log"
        pid_path = PIDS / f"job-{job_id}.pid"
        passfiles: list[str] = []
        try:
            if not row["source_password"] or not row["target_password"]:
                raise ValueError("Aktarım parolaları güvenli saklama süresi sonunda silinmiş")
            for encrypted in (row["source_password"], row["target_password"]):
                handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=DATA, prefix=".pass-")
                handle.write(CRYPT.decrypt(encrypted).decode())
                handle.close()
                try:
                    os.chmod(handle.name, 0o600)
                except OSError:
                    pass
                passfiles.append(handle.name)
            pid_path.unlink(missing_ok=True)
            cmd = self.command(row, passfiles[0], passfiles[1], pid_path)
            with db() as conn:
                conn.execute("UPDATE jobs SET status='running', log_path=? WHERE id=?", (str(log_path), job_id))
            with log_path.open("w", encoding="utf-8", errors="replace") as logfile:
                progress_state = {"transferred": 0, "skipped": 0, "bytes_transferred": 0,
                                  "discovered": 0, "last_flush": 0.0, "sync_good": False,
                                  "unidentified_ok": False, "detected_errors": None,
                                  "exited_ok": False}
                process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                self.running[job_id] = process
                with db() as conn:
                    conn.execute("UPDATE jobs SET pid=? WHERE id=?", (process.pid, job_id))
                assert process.stdout
                async for raw in process.stdout:
                    line = raw.decode(errors="replace")
                    logfile.write(line)
                    logfile.flush()
                    self.parse_progress(job_id, line, progress_state)
                code = await process.wait()
                self.flush_progress(job_id, progress_state, force=True)
            with db() as conn:
                current = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()["status"]
                if current == "stopping":
                    conn.execute("UPDATE jobs SET status='stopped', active_lock=NULL, finished_at=?, pid=NULL WHERE id=?", (now(), job_id))
                elif current == "interrupted":
                    conn.execute("UPDATE jobs SET active_lock=NULL, finished_at=?, pid=NULL WHERE id=?", (now(), job_id))
                elif code == 0 and self.sync_verified(progress_state):
                    conn.execute("""UPDATE jobs SET status='completed', active_lock=NULL, verified=1,
                        detected_errors=0, progress=100, finished_at=?, pid=NULL WHERE id=?""", (now(), job_id))
                else:
                    detected = progress_state.get("detected_errors")
                    reason = f"imapsync çıkış kodu: {code}" if code else "imapsync tamamlandı ancak bütünlük doğrulaması başarısız"
                    conn.execute("""UPDATE jobs SET status='failed', active_lock=NULL, verified=0,
                        detected_errors=?, error=?, finished_at=?, pid=NULL WHERE id=?""",
                        (detected, reason, now(), job_id))
        except Exception as exc:
            with db() as conn:
                conn.execute("UPDATE jobs SET status='failed', active_lock=NULL, error=?, finished_at=?, pid=NULL WHERE id=?", (str(exc), now(), job_id))
        finally:
            self.running.pop(job_id, None)
            for filename in passfiles:
                Path(filename).unlink(missing_ok=True)
            pid_path.unlink(missing_ok=True)
            self.wakeup.set()

    @staticmethod
    def sync_verified(state: dict) -> bool:
        content_ok = state["sync_good"] or state["discovered"] == 0
        return bool(state["exited_ok"] and content_ok and state["unidentified_ok"]
                    and state["detected_errors"] == 0)

    def parse_progress(self, job_id: int, line: str, state: dict) -> None:
        copied = re.search(r"^msg .*\{(\d+)\}\s+copied to ", line, re.I)
        if copied:
            state["transferred"] += 1
            state["bytes_transferred"] += int(copied.group(1))
        patterns = {
            "discovered": r"^Host1 Nb messages:\s*(\d+) messages",
            "transferred": r"^Messages transferred\s*:\s*(\d+)",
            "skipped": r"^Messages skipped\s*:\s*(\d+)",
            "bytes_transferred": r"^Total bytes transferred\s*:\s*(\d+)",
        }
        for field, pattern in patterns.items():
            match = re.search(pattern, line, re.I)
            if match:
                state[field] = int(match.group(1))
        if re.search(r"^The sync looks good, all \d+ identified messages in host1 are on host2", line):
            state["sync_good"] = True
        if line.startswith("There is no unidentified message on host1."):
            state["unidentified_ok"] = True
        detected = re.search(r"^Detected (\d+) errors", line)
        if detected:
            state["detected_errors"] = int(detected.group(1))
        if re.search(r"^Exiting with return value 0 .*EX_OK", line):
            state["exited_ok"] = True
        self.flush_progress(job_id, state)

    def flush_progress(self, job_id: int, state: dict, force: bool = False) -> None:
        current_time = time.monotonic()
        if not force and current_time - state["last_flush"] < 1:
            return
        state["last_flush"] = current_time
        discovered = state["discovered"]
        progress = min(99, round(state["transferred"] * 100 / discovered)) if discovered else 0
        with db() as conn:
            conn.execute("""UPDATE jobs SET discovered=?,transferred=?,skipped=?,
                bytes_transferred=?,progress=?,detected_errors=? WHERE id=?""",
                (discovered, state["transferred"], state["skipped"],
                 state["bytes_transferred"], progress, state["detected_errors"], job_id))

    async def stop(self, job_id: int) -> None:
        process = self.running.get(job_id)
        with db() as conn:
            row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Aktarım bulunamadı")
            if row["status"] in {"queued", "starting"}:
                conn.execute("UPDATE jobs SET status='stopped', active_lock=NULL, finished_at=? WHERE id=?", (now(), job_id))
                return
            if row["status"] != "running" or not process:
                raise HTTPException(409, "Aktarım durdurulabilir durumda değil")
            conn.execute("UPDATE jobs SET status='stopping' WHERE id=?", (job_id,))
        process.terminate()


manager = MigrationManager()


class AuthCSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/login" or request.url.path.startswith("/static/"):
            return await call_next(request)
        if not request.session.get("authenticated"):
            if request.url.path.startswith("/api/"):
                return JSONResponse({"detail": "Oturum açmanız gerekiyor"}, status_code=401)
            return RedirectResponse("/login", status_code=303)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            supplied = request.headers.get("x-csrf-token", "")
            expected = request.session.get("csrf_token", "")
            if not expected or not hmac.compare_digest(supplied, expected):
                return JSONResponse({"detail": "Geçersiz CSRF belirteci"}, status_code=403)
        return await call_next(request)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if len(SESSION_SECRET) < 32:
        raise RuntimeError("SESSION_SECRET en az 32 karakter olmalıdır")
    if not APP_PASSWORD_HASH:
        raise RuntimeError("APP_PASSWORD_HASH yapılandırılmalıdır")
    if bool(TLS_CERTFILE) != bool(TLS_KEYFILE):
        raise RuntimeError("TLS_CERTFILE ve TLS_KEYFILE birlikte yapılandırılmalıdır")
    init_db()
    await manager.start()
    yield
    await manager.shutdown()


app = FastAPI(title="Zimbra IMAP Aktarım Paneli", lifespan=lifespan)
app.add_middleware(AuthCSRFMiddleware)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET,
                   session_cookie="zimbra_migration_session", same_site="strict",
                   https_only=SESSION_HTTPS_ONLY, max_age=8 * 60 * 60)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS or ["localhost"])
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/login")
def login_page():
    return FileResponse(ROOT / "static" / "login.html")


@app.post("/login")
async def login(request: Request, username: Annotated[str, Form()], password: Annotated[str, Form()]):
    if not hmac.compare_digest(username, APP_USERNAME) or not verify_password(password, APP_PASSWORD_HASH):
        return RedirectResponse("/login?error=1", status_code=303)
    request.session.clear()
    request.session.update(authenticated=True, username=username, csrf_token=secrets.token_urlsafe(32))
    return RedirectResponse("/", status_code=303)


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/session")
def session_info(request: Request):
    return {"username": request.session.get("username"), "csrf_token": request.session["csrf_token"]}


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/jobs")
def jobs(limit: int = Query(500, ge=1, le=1000), offset: int = Query(0, ge=0)):
    with db() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
    return [public_job(row) for row in rows]


@app.get("/api/reports/jobs.csv")
def jobs_report():
    columns = ["id", "source_host", "source_email", "target_host", "target_email", "status",
               "discovered", "transferred", "skipped", "bytes_transferred", "progress", "verified",
               "detected_errors", "error", "created_at", "started_at", "finished_at"]
    with db() as conn:
        rows = conn.execute(f"SELECT {','.join(columns)} FROM jobs ORDER BY id DESC").fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([row[column] if row[column] is not None else "" for column in columns])
    filename = f"zimbra-migration-report-{now().strftime('%Y%m%d-%H%M%S')}.csv"
    return Response("\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/summary")
def summary():
    with db() as conn:
        row = conn.execute("""SELECT COALESCE(SUM(discovered),0) discovered,
            COALESCE(SUM(transferred),0) transferred, COALESCE(SUM(skipped),0) skipped,
            COUNT(*) total,
            COALESCE(SUM(CASE WHEN status='running' THEN 1 ELSE 0 END),0) running,
            COALESCE(SUM(CASE WHEN status='queued' THEN 1 ELSE 0 END),0) queued,
            COALESCE(SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END),0) completed,
            COALESCE(SUM(CASE WHEN status IN ('failed','interrupted') THEN 1 ELSE 0 END),0) failed
            FROM jobs""").fetchone()
    result = dict(row)
    result.update(max_parallel=MAX_PARALLEL, paused=manager.paused)
    return result


@app.post("/api/control/pause")
def toggle_pause():
    manager.paused = not manager.paused
    with db() as conn:
        conn.execute("UPDATE app_state SET state_value=? WHERE state_key='paused'",
                     ("1" if manager.paused else "0",))
    manager.wakeup.set()
    return {"paused": manager.paused}


@app.delete("/api/jobs/queue")
def clear_queue():
    with db() as conn:
        cursor = conn.execute("DELETE FROM jobs WHERE status='queued'")
        deleted = cursor.rowcount
    return {"deleted": deleted}


@app.post("/api/jobs")
def create_job(
    source_host: Annotated[str, Form()], source_port: Annotated[int, Form()] = 993,
    source_security: Annotated[str, Form()] = "ssl", source_email: Annotated[str, Form()] = "",
    source_password: Annotated[str, Form()] = "", target_host: Annotated[str, Form()] = "",
    target_port: Annotated[int, Form()] = 993, target_security: Annotated[str, Form()] = "ssl",
    target_email: Annotated[str, Form()] = "", target_password: Annotated[str, Form()] = "",
    start_date: Annotated[str, Form()] = "", end_date: Annotated[str, Form()] = "",
):
    require_imapsync()
    try:
        test_connections(locals())
        job_id = add_job(locals())
    except pymysql.err.IntegrityError as exc:
        raise HTTPException(409, "Bu kaynak ve hedef hesap için zaten aktif bir aktarım var") from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    manager.wakeup.set()
    return {"id": job_id}


@app.post("/api/preflight")
def preflight(
    source_host: Annotated[str, Form()], source_port: Annotated[int, Form()] = 993,
    source_security: Annotated[str, Form()] = "ssl", source_email: Annotated[str, Form()] = "",
    source_password: Annotated[str, Form()] = "", target_host: Annotated[str, Form()] = "",
    target_port: Annotated[int, Form()] = 993, target_security: Annotated[str, Form()] = "ssl",
    target_email: Annotated[str, Form()] = "", target_password: Annotated[str, Form()] = "",
    start_date: Annotated[str, Form()] = "", end_date: Annotated[str, Form()] = "",
):
    require_imapsync()
    try:
        return test_connections(locals())
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/jobs/import")
async def import_jobs(file: Annotated[UploadFile, File()]):
    require_imapsync()
    raw = await file.read(CSV_MAX_BYTES + 1)
    if len(raw) > CSV_MAX_BYTES:
        raise HTTPException(413, f"CSV en fazla {CSV_MAX_BYTES} byte olabilir")
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(422, "CSV UTF-8 kodlamasında olmalıdır") from exc
    reader = csv.DictReader(io.StringIO(content))
    headers = set(reader.fieldnames or [])
    missing = sorted(CSV_REQUIRED_FIELDS - headers)
    if missing:
        raise HTTPException(422, f"CSV başlıkları eksik: {', '.join(missing)}")
    ids, errors = [], []
    for line, row in enumerate(reader, 2):
        if line - 1 > CSV_MAX_ROWS:
            errors.append({"line": line, "error": f"En fazla {CSV_MAX_ROWS} hesap içe aktarılabilir"})
            break
        try:
            ids.append(add_job(row))
        except pymysql.err.IntegrityError:
            errors.append({"line": line, "error": "Bu hesap için zaten aktif bir aktarım var"})
        except Exception as exc:
            errors.append({"line": line, "error": str(exc)})
    manager.wakeup.set()
    return {"created": len(ids), "ids": ids, "errors": errors}


@app.post("/api/jobs/{job_id}/stop")
async def stop_job(job_id: int):
    await manager.stop(job_id)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: int):
    with db() as conn:
        row = conn.execute("SELECT status,source_password,target_password FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Aktarım bulunamadı")
        if row["status"] in {"running", "starting", "stopping"}:
            raise HTTPException(409, "Çalışan aktarım yeniden başlatılamaz")
        if not row["source_password"] or not row["target_password"]:
            raise HTTPException(409, "Parolalar saklama süresi sonunda silindi; hesabı yeniden ekleyin")
        try:
            conn.execute("""UPDATE jobs SET status='queued',active_lock=lock_key,error=NULL,
                progress=0,discovered=0,transferred=0,skipped=0,bytes_transferred=0,
                verified=0,detected_errors=NULL,started_at=NULL,finished_at=NULL WHERE id=?""", (job_id,))
        except pymysql.err.IntegrityError as exc:
            raise HTTPException(409, "Bu hesap için başka bir aktif aktarım var") from exc
    manager.wakeup.set()
    return {"ok": True}


@app.get("/api/jobs/{job_id}/log")
def job_log(job_id: int):
    with db() as conn:
        row = conn.execute("SELECT log_path FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row or not row["log_path"] or not Path(row["log_path"]).exists():
        raise HTTPException(404, "Log henüz oluşmadı")
    return FileResponse(row["log_path"], media_type="text/plain", filename=f"job-{job_id}.log")


@app.get("/api/events")
async def events():
    async def stream():
        while True:
            yield f"data: {json.dumps({'updated_at': now().isoformat()})}\n\n"
            await asyncio.sleep(2)
    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/system")
def system_status():
    return {"imapsync": imapsync_status(), "max_parallel": MAX_PARALLEL}


if __name__ == "__main__":
    uvicorn.run("app:app", host=os.getenv("APP_HOST", "127.0.0.1"),
                port=int(os.getenv("APP_PORT", "8787")), reload=False,
                ssl_certfile=TLS_CERTFILE, ssl_keyfile=TLS_KEYFILE)
