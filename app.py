from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import uvicorn
import pymysql
from pymysql.cursors import DictCursor
from dotenv import load_dotenv
from cryptography.fernet import Fernet
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
DATA = ROOT / "data"
LOGS = ROOT / "logs"
PIDS = DATA / "pids"
KEY_PATH = DATA / "secret.key"
MAX_PARALLEL = max(1, int(os.getenv("MAX_PARALLEL", "3")))
IMAPSYNC_PATH = os.getenv("IMAPSYNC_PATH", "imapsync")

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


def imapsync_status() -> dict:
    executable = shutil.which(IMAPSYNC_PATH) if not Path(IMAPSYNC_PATH).is_file() else str(Path(IMAPSYNC_PATH).resolve())
    if not executable:
        return {"available": False, "path": IMAPSYNC_PATH, "version": None,
                "error": "imapsync bulunamadı. Ubuntu kurulum adımlarını tamamlayın."}
    try:
        result = subprocess.run([executable, "--version"], capture_output=True, text=True,
                                timeout=10, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        output = (result.stdout or result.stderr).strip().splitlines()
        if result.returncode != 0:
            return {"available": False, "path": executable, "version": None,
                    "error": output[-1] if output else f"imapsync çıkış kodu: {result.returncode}"}
        return {"available": True, "path": executable,
                "version": output[-1] if output else "Sürüm bilgisi alınamadı", "error": None}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "path": executable, "version": None, "error": str(exc)}


def imapsync_exists() -> bool:
    return Path(IMAPSYNC_PATH).is_file() or shutil.which(IMAPSYNC_PATH) is not None


def require_imapsync() -> None:
    status = imapsync_status()
    if not status["available"]:
        raise HTTPException(503, status["error"])


def clean_security(value: str) -> str:
    value = value.strip().lower()
    if value not in {"ssl", "tls", "none"}:
        raise ValueError("Güvenlik ssl, tls veya none olmalıdır")
    return value


def add_job(payload: dict) -> int:
    required = ["source_host", "source_email", "source_password", "target_host", "target_email", "target_password"]
    if any(not str(payload.get(key, "")).strip() for key in required):
        raise ValueError("Zorunlu alanlar eksik")
    lock_material = "\0".join(str(payload[key]).strip().lower() for key in
                              ("source_host", "source_email", "target_host", "target_email"))
    lock_key = hashlib.sha256(lock_material.encode()).hexdigest()
    values = {
        "source_host": str(payload["source_host"]).strip(),
        "source_port": int(payload.get("source_port", 993)),
        "source_security": clean_security(str(payload.get("source_security", "ssl"))),
        "source_email": str(payload["source_email"]).strip(),
        "source_password": CRYPT.encrypt(str(payload["source_password"]).encode()),
        "target_host": str(payload["target_host"]).strip(),
        "target_port": int(payload.get("target_port", 993)),
        "target_security": clean_security(str(payload.get("target_security", "ssl"))),
        "target_email": str(payload["target_email"]).strip(),
        "target_password": CRYPT.encrypt(str(payload["target_password"]).encode()),
        "start_date": str(payload.get("start_date") or "").strip() or None,
        "end_date": str(payload.get("end_date") or "").strip() or None,
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
            values | {"created_at": now()},
        )
        return int(cursor.lastrowid)


def public_job(row: dict) -> dict:
    item = dict(row)
    item.pop("source_password", None)
    item.pop("target_password", None)
    return item


class MigrationManager:
    def __init__(self) -> None:
        self.stop_event = asyncio.Event()
        self.wakeup = asyncio.Event()
        self.running: dict[int, asyncio.subprocess.Process] = {}
        self.tasks: set[asyncio.Task] = set()
        self.loop_task: asyncio.Task | None = None
        self.paused = False

    async def start(self) -> None:
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

    def command(self, row: dict, pass1: str, pass2: str, pid_path: Path) -> list[str]:
        cmd = [IMAPSYNC_PATH,
               "--host1", row["source_host"], "--port1", str(row["source_port"]),
               "--user1", row["source_email"], "--passfile1", pass1,
               "--host2", row["target_host"], "--port2", str(row["target_port"]),
               "--user2", row["target_email"], "--passfile2", pass2,
               "--automap", "--addheader", "--pidfile", str(pid_path),
               "--pidfilelocking", "--nolog"]
        for side in (1, 2):
            security = row[f"{'source' if side == 1 else 'target'}_security"]
            if security == "ssl": cmd.append(f"--ssl{side}")
            elif security == "tls": cmd.append(f"--tls{side}")
        if row["start_date"]:
            cmd += ["--search1", f"SENTSINCE {row['start_date'].strftime('%d-%b-%Y')}"]
        if row["end_date"]:
            cmd += ["--search1", f"SENTBEFORE {row['end_date'].strftime('%d-%b-%Y')}"]
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


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    await manager.start()
    yield
    await manager.shutdown()


app = FastAPI(title="Zimbra IMAP Aktarım Paneli", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/jobs")
def jobs():
    with db() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY id DESC").fetchall()
    return [public_job(row) for row in rows]


@app.get("/api/summary")
def summary():
    with db() as conn:
        row = conn.execute("""SELECT COALESCE(SUM(discovered),0) discovered,
            COALESCE(SUM(transferred),0) transferred, COALESCE(SUM(skipped),0) skipped,
            COUNT(*) total,
            SUM(CASE WHEN status='running' THEN 1 ELSE 0 END) running,
            SUM(CASE WHEN status='queued' THEN 1 ELSE 0 END) queued,
            SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) completed,
            SUM(CASE WHEN status IN ('failed','interrupted') THEN 1 ELSE 0 END) failed
            FROM jobs""").fetchone()
    return dict(row) | {"max_parallel": MAX_PARALLEL, "paused": manager.paused}


@app.post("/api/control/pause")
def toggle_pause():
    manager.paused = not manager.paused
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
        job_id = add_job(locals())
    except pymysql.err.IntegrityError as exc:
        raise HTTPException(409, "Bu kaynak ve hedef hesap için zaten aktif bir aktarım var") from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    manager.wakeup.set()
    return {"id": job_id}


@app.post("/api/jobs/import")
async def import_jobs(file: Annotated[UploadFile, File()]):
    require_imapsync()
    content = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    ids, errors = [], []
    for line, row in enumerate(reader, 2):
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
        row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Aktarım bulunamadı")
        if row["status"] in {"running", "starting", "stopping"}:
            raise HTTPException(409, "Çalışan aktarım yeniden başlatılamaz")
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
    uvicorn.run("app:app", host=os.getenv("APP_HOST", "127.0.0.1"), port=int(os.getenv("APP_PORT", "8787")), reload=False)
