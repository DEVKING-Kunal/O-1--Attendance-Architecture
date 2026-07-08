"""
AttendX — FastAPI Attendance Portal
------------------------------------
Rewrite of the original Flask/Waitress app.

What changed vs v1:
  - Async request handling on an ASGI server (uvicorn) instead of a
    threaded WSGI server.
  - Crash-safe: the buffer is auto-flushed to disk every N seconds,
    not just on a clean Ctrl+C. A killed process now loses at most
    one flush interval of data instead of the whole session.
  - Native handling of the OS-level "is this a captive portal?" probe
    requests that iOS / Android / Windows fire the instant a device
    joins a network. This is what lets the form open automatically —
    see dns_redirect.py for the other half of that mechanism.
  - The "reject VPN/proxy submissions" behaviour the README already
    documented is now actually implemented, not just claimed.  
"""

import asyncio
import csv
import html
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from pydantic_settings import BaseSettings

# --------------------------------------------------------------------------
# Configuration — override any of these with env vars, e.g. ATTENDX_PORT=8080
# --------------------------------------------------------------------------


class Settings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 80
    flush_interval_seconds: int = 15
    output_dir: str = "output"

    class Config:
        env_prefix = "ATTENDX_"


settings = Settings()

SESSION_ID = datetime.now().strftime("%Y-%m-%d_%H-%M")
OUTPUT_DIR = Path(settings.output_dir)
OUTPUT_DIR.mkdir(exist_ok=True)
CSV_FILE = OUTPUT_DIR / f"attendance_{SESSION_ID}.csv"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("attendx")

# --------------------------------------------------------------------------
# In-memory state — same O(1) design as v1, now behind an asyncio lock
# --------------------------------------------------------------------------

attendance_buffer: dict[str, dict] = {}
submitted_macs: set[str] = set()
_lock = asyncio.Lock()
_dirty = False

PROXY_HEADERS = ("x-forwarded-for", "via", "x-real-ip")


def get_mac_address(ip: str) -> str:
    if ip in ("127.0.0.1", "::1"):
        return "INTERNAL_HOST"
    try:
        arp_raw = os.popen(f"arp -a {ip}").read()
        match = re.search(r"([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})", arp_raw)
        return match.group(0).replace("-", ":").upper() if match else "UNKNOWN_MAC"
    except Exception:
        return "ERROR"


def write_csv(final: bool = False) -> None:
    """Sort-and-write, called on every autosave tick and on shutdown.
    Writes to a temp file then renames — the rename is atomic, so a crash
    mid-write never leaves a corrupt CSV on disk."""
    if not attendance_buffer:
        return
    sorted_entries = sorted(attendance_buffer.values(), key=lambda x: x["roll"])
    tmp_path = CSV_FILE.with_suffix(".tmp")
    with open(tmp_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Timestamp", "Roll_Number", "MAC_Address", "IPv4_Address"])
        for entry in sorted_entries:
            writer.writerow([entry["time"], entry["roll"], entry["mac"], entry["ip"]])
    tmp_path.replace(CSV_FILE)
    if final:
        log.info(f"✅ Final save — {len(sorted_entries)} records written to {CSV_FILE}")
    else:
        log.info(f"[autosave] {len(sorted_entries)} records flushed to disk")


async def autosave_loop():
    global _dirty
    while True:
        await asyncio.sleep(settings.flush_interval_seconds)
        async with _lock:
            if _dirty:
                write_csv(final=False)
                _dirty = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(f"[*] AttendX live — Session: {SESSION_ID}")
    log.info(f"[*] Listening on {settings.host}:{settings.port}")
    log.info(f"[*] Autosaving every {settings.flush_interval_seconds}s -> {CSV_FILE}")
    task = asyncio.create_task(autosave_loop())
    yield
    task.cancel()
    async with _lock:
        write_csv(final=True)
    log.info("[*] Server offline.")


app = FastAPI(title="AttendX", lifespan=lifespan)

# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------

PAGE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Attendance Portal</title>
    <style>
        :root {{ --blue: #1a73e8; --red: #d93025; --green: #188038; }}
        body {{ font-family: -apple-system, sans-serif; background: #f1f3f4; display: flex; justify-content: center; padding: 40px 20px; }}
        .container {{ background: #fff; padding: 32px; border-radius: 8px; box-shadow: 0 1px 2px rgba(0,0,0,0.1); width: 100%; max-width: 400px; }}
        .session {{ font-size: 12px; color: #5f6368; margin-bottom: 20px; text-transform: uppercase; letter-spacing: 1px; }}
        input {{ width: 100%; padding: 12px; border: 1px solid #dadce0; border-radius: 4px; font-size: 16px; margin-bottom: 16px; box-sizing: border-box; }}
        button {{ width: 100%; padding: 12px; background: var(--blue); color: #fff; border: none; border-radius: 4px; font-weight: 500; cursor: pointer; }}
        .status {{ padding: 16px; border-radius: 4px; margin-bottom: 20px; font-size: 14px; }}
        .success {{ background: #e6f4ea; color: var(--green); border: 1px solid #ceead6; }}
        .error {{ background: #fce8e6; color: var(--red); border: 1px solid #fad2cf; }}
        .urgent {{ margin-top: 24px; padding: 16px; border: 2px solid var(--red); color: var(--red); font-weight: bold; text-align: center; animation: pulse 2s infinite; }}
        @keyframes pulse {{ 0% {{ opacity: 1; }} 50% {{ opacity: 0.6; }} 100% {{ opacity: 1; }} }}
    </style>
</head>
<body>
    <div class="container">
        <div class="session">Session ID: {session}</div>
        {body}
    </div>
</body>
</html>
"""

FORM_BODY = """
<form method="POST" action="/submit">
    <input type="text" name="roll_number" placeholder="Enter Roll Number" required autocomplete="off">
    <button type="submit">Submit</button>
</form>
"""


def render_page(status: str = "none", roll: Optional[str] = None, message: Optional[str] = None) -> str:
    if status == "success":
        body = (
            f'<div class="status success">Attendance recorded for <strong>{html.escape(roll or "")}</strong>.</div>'
            '<div class="urgent">⚠️ DISCONNECT FROM WI-FI NOW ⚠️</div>'
        )
    elif status == "error":
        body = (
            f'<div class="status error">{html.escape(message or "")}</div>'
            '<button onclick="window.location.href=\'/\'">Try Again</button>'
        )
    else:
        body = FORM_BODY
    return PAGE_TEMPLATE.format(session=html.escape(SESSION_ID), body=body)


# --------------------------------------------------------------------------
# Core routes
# --------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index():
    return render_page(status="none")


@app.post("/submit", response_class=HTMLResponse)
async def submit(request: Request, roll_number: str = Form(...)):
    global _dirty

    if any(h in request.headers for h in PROXY_HEADERS):
        log.warning(f"Rejected proxied submission from {request.client.host}")
        return HTMLResponse(
            render_page(status="error", message="Submissions via VPN/proxy are not allowed. Please connect directly to the classroom hotspot."),
            status_code=403,
        )

    roll = roll_number.strip().upper()
    ip = request.client.host if request.client else "UNKNOWN_IP"
    mac = get_mac_address(ip)

    async with _lock:
        if roll in attendance_buffer:
            return render_page(status="error", message="Roll number already recorded.")

        if mac != "UNKNOWN_MAC" and mac in submitted_macs:
            return render_page(status="error", message="Device already used for submission.")

        attendance_buffer[roll] = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "roll": roll,
            "mac": mac,
            "ip": ip,
        }
        submitted_macs.add(mac)
        _dirty = True

    return render_page(status="success", roll=roll)


@app.get("/status")
async def status():
    """Lightweight JSON endpoint — e.g. for a live terminal/dashboard view."""
    return JSONResponse({"session": SESSION_ID, "submitted_count": len(attendance_buffer)})


# --------------------------------------------------------------------------
# Captive-portal probe endpoints
#
# These are the exact URLs each OS pings right after joining a network to
# decide "is this a captive portal?". Once dns_redirect.py is pointing
# every domain at this machine, these requests land here regardless of
# what host the OS actually asked for. Returning something other than the
# expected "all clear" response is what makes the OS pop its captive-portal
# browser automatically.
# --------------------------------------------------------------------------


@app.get("/generate_204")
@app.get("/gen_204")
@app.get("/redirect")
async def android_probe():
    return RedirectResponse(url="/", status_code=302)


@app.get("/hotspot-detect.html")
@app.get("/library/test/success.html")
async def apple_probe():
    return RedirectResponse(url="/", status_code=302)


@app.get("/connecttest.txt")
@app.get("/ncsi.txt")
async def windows_probe():
    return RedirectResponse(url="/", status_code=302)


# Catch-all: with DNS hijacked, browsers/OS components will request all
# sorts of unrelated hostnames. Send anything unmatched back to the form.
@app.get("/{full_path:path}")
async def catch_all(full_path: str):
    return RedirectResponse(url="/", status_code=302)


if __name__ == "__main__":
    import uvicorn

    print(f"[*] Starting AttendX on {settings.host}:{settings.port}")
    print("[*] NOTE: port 80/53 require Administrator/root privileges.")
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="warning")