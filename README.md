<div align="center">

# AttendX — O(1) Classroom Attendance System

**A local-network attendance tool that reduces a 5–10 minute classroom ritual to under 60 seconds.**

[![Python](https://img.shields.io/badge/Python-3.8+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Uvicorn](https://img.shields.io/badge/Uvicorn-ASGI_Server-4B8BBE?style=for-the-badge)](https://www.uvicorn.org)
[![Google Sheets](https://img.shields.io/badge/Google_Sheets-API-34A853?style=for-the-badge&logo=googlesheets&logoColor=white)](https://developers.google.com/sheets)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

</div>

---

## Contents

- [The Problem](#the-problem)
- [Why Not Just Use a Google Form?](#why-not-just-use-a-google-form)
- [How It Works](#how-it-works)
- [The Captive Portal Layer](#the-captive-portal-layer)
- [Project Structure](#project-structure)
- [Setup & Deployment](#setup--deployment)
- [Security](#security)
- [Known Limitations](#known-limitations)
- [Complexity Summary](#complexity-summary)
- [Roadmap](#roadmap)

---

## The Problem

At **NIT Jalandhar**, a standard lecture is 50 minutes. Passing a physical attendance register across 60–80 students burns **5 to 10 minutes** of that — every class, every day — before a single concept is taught. That's up to 20% of teaching time, gone.

The register is an **O(N) sequential operation**. Each student signs one after the other; the sheet can only be in one place at a time. Simply moving to a digital form doesn't fix this — if the server validates each submission by scanning a list of enrolled students, you've just moved the same O(N) problem online.

The real fix is changing the data structure. This project validates every submission with a single Python dictionary lookup — **O(1), constant time** — so the 80th student's request processes just as fast as the 1st.

---

## Why Not Just Use a Google Form?

| Scenario | Google Form | AttendX |
|---|---|---|
| Classroom internet goes down | Form won't load, session is lost | Runs entirely on a local hotspot; no internet needed during class |
| 70 students submit simultaneously | Sheets API rate limit is ~60 writes/min — some submissions fail silently with HTTP 429 | All records land in local memory first; cloud sync is one batched call after the session |
| Student submits from outside the classroom | No way to enforce physical presence | Requests carrying proxy/VPN headers are rejected at the server with HTTP 403 |
| One student submits for a friend | A form has no way to detect this | Each device MAC address is bound to exactly one roll number |
| Internet is available but unstable | Partial submissions with no way to know what was lost | Local CSV is always written first; sync runs separately when connection is stable |

The core issue with a Google Form for burst attendance is that it writes to the cloud **synchronously, one record at a time**. Under real classroom load — 70 students in a 2-minute window — you will hit the API rate limit. Most failures are silent: the student sees no error, and the record never appears in the sheet.

AttendX decouples the submission experience from the cloud write entirely.

---

## How It Works

### 1. Students push, the server doesn't poll

The professor's laptop runs a FastAPI server on port 80. Students connect to the laptop's mobile hotspot and scan a QR code that opens the attendance form directly. The server receives submissions — it never needs to go looking for anyone.

### 2. O(1) validation via Python dictionaries

```python
# Two data structures track what's been submitted this session
attendance_buffer: dict[str, dict] = {}   # roll_number → record
submitted_macs:    set[str]        = set() # MAC addresses seen

# Every incoming request is validated like this — O(1), no scanning
if roll in attendance_buffer:
    return error("Roll number already recorded.")

if mac != "UNKNOWN_MAC" and mac in submitted_macs:
    return error("Device already used for submission.")
```

A Python dict lookup computes a hash of the key and goes directly to that memory slot. It does not iterate. This is why validation stays constant-time regardless of class size.

### 3. Records buffer locally; sync happens later

Validated submissions are stored in-memory and the student immediately gets a confirmation. Nothing waits for a network call. Two persistence mechanisms protect the data:

- **Autosave loop** — an async background task wakes every 15 seconds. If any new submissions have arrived since the last flush, it writes the full sorted buffer to disk using an atomic rename (`attendance_<SESSION_ID>.tmp` → `attendance_<SESSION_ID>.csv`). A mid-write crash can never produce a corrupt file.
- **Final write on shutdown** — when the server exits cleanly, the same write_csv routine runs one last time to capture any submissions since the last autosave.

### 4. Shutdown and sync flow

```
Session ends → server shuts down
  → final atomic CSV write to output/attendance_<SESSION_ID>.csv

(after the lecture, once internet is available)
python sync.py
  → exports output/xlsx/<SESSION_ID>.xlsx  ← formatted, freeze-paned, ready to share
  → creates a new tab named <SESSION_ID> in the master Google Sheet
  → uploads all records in a single append_rows() call
  → archives the local CSV as synced_backup_<timestamp>.csv
```

Each session gets its own worksheet tab. The professor can open any past session independently without scrolling through one ever-growing sheet. The local `.xlsx` is written **before** the cloud call, so a slow or failed internet connection never blocks the professor from having the file.

---

## The Captive Portal Layer

Most operating systems probe for internet connectivity the instant a device joins a Wi-Fi network. iOS pings `captive.apple.com`, Android pings `connectivitycheck.gstatic.com`, and Windows pings `msftconnecttest.com`. If the response doesn't match what the OS expects for "real internet", it pops a **captive portal** — the same browser mini-window you see at airports asking you to log in.

`app.py` registers the exact routes these probes expect:

```
GET /generate_204                 → Android (Connectivity Check)
GET /hotspot-detect.html          → iOS / macOS (CaptiveNetworkSupport)
GET /connecttest.txt, /ncsi.txt   → Windows (NCSI)
GET /{any other path}             → catch-all redirect to /
```

All of these return a `302 → /`, which is enough to trigger the portal on most OS versions.

**Current state:** these routes are live and working in `app.py`, but they only trigger if the OS's probe request actually reaches this server. For that to happen, the device's DNS must resolve those probe domains to the hotspot IP — which requires a DNS redirect layer not yet included in this repository. Without it, the QR code (`attendance_qr.png`, generated by `make_qr.py`) is the delivery mechanism: students scan it and the form opens directly. The probe routes are the next step on the roadmap and the groundwork is already in place.

---

## Project Structure

```
attendx/
├── app.py               # FastAPI server + async autosave + captive portal probe routes
├── sync.py              # Post-session: exports .xlsx locally, pushes new tab to Google Sheets
├── make_qr.py           # Detects hotspot IP via psutil, generates attendance_qr.png
├── credentials.json     # GCP service account key  ← git-ignored
├── attendance_qr.png    # Generated QR code        ← git-ignored
├── output/
│   ├── attendance_<SESSION_ID>.csv    # Active session data (autosaved every 15s)
│   ├── synced_backup_<timestamp>.csv  # Archived after successful cloud sync
│   └── xlsx/
│       └── <SESSION_ID>.xlsx          # Formatted Excel export (offline-ready)
├── requirements.txt
└── README.md
```

---

## Setup & Deployment

### Prerequisites

- Python 3.8+
- Administrator / root privileges (port 80 is a privileged port)
- A Google Cloud project with **Google Sheets API** and **Google Drive API** enabled
- A service account key (JSON) downloaded from Google Cloud Console

### Installation

```bash
git clone https://github.com/DEVKING-Kunal/O-1--Attendance-Architecture.git
cd attendx
pip install -r requirements.txt
```

### Cloud Authentication

1. Download your service account JSON key from Google Cloud Console
2. Rename it `credentials.json` and place it in the project root
3. Share your Google Sheet with the `client_email` value from inside that JSON file
4. The master spreadsheet must exist and be named exactly `Attendance_Sheet`

> `credentials.json` is in `.gitignore`. Do not commit it.

### Running a Session

**Step 1 — Enable your laptop's mobile hotspot, then generate the QR code:**
```bash
python make_qr.py
```
Detects the active hotspot IP via `psutil`, generates `attendance_qr.png`, and prints the detected URL. Display this QR code to students — it opens the form directly in their browser.

**Step 2 — Start the server (requires Administrator / sudo):**
```bash
# Windows (run terminal as Administrator)
python app.py

# Linux / macOS
sudo python app.py
```
The server starts on port 80 and begins autosaving to `output/` every 15 seconds. The terminal will log each autosave and every submission. The server can be stopped with `Ctrl+C` or any clean shutdown — the final write runs automatically on exit.

**Step 3 — Sync after the lecture (once internet is available):**
```bash
python sync.py
```
Writes a formatted `.xlsx` to `output/xlsx/`, then uploads the session to a new tab in Google Sheets. If the cloud push fails, the local `.xlsx` already exists and the original CSV is preserved for a retry.

---

## Security

| Concern | How it's handled |
|---|---|
| One student marking for a friend | Each MAC address is bound to one roll number and vice versa. A second submission from either side is rejected with an error. |
| Submitting from outside the classroom via VPN or proxy | `app.py` checks for `X-Forwarded-For`, `Via`, and `X-Real-IP` headers on every submission. Any request carrying these headers returns HTTP 403. |
| Same student submitting twice | Both the roll number dict and the MAC set are checked; a duplicate on either side is rejected. |
| Data loss on crash | The autosave loop flushes to disk every 15 seconds using an atomic rename. An abrupt crash loses at most 15 seconds of submissions, not the whole session. |
| Corrupt CSV from mid-write crash | All writes go to a `.tmp` file first; the final rename is atomic. A crash mid-write leaves the previous clean CSV intact. |

---

## Known Limitations

**MAC address randomization (iOS 14+ / Android 10+)**

Modern phones assign a different random MAC to each Wi-Fi network. This means the MAC seen today may differ from the one seen tomorrow, and in some cases two different real devices may present the same randomized MAC. The current workaround is asking students to disable "Private Wi-Fi Address" for the classroom hotspot — this can't be enforced. The right fix (a browser fingerprint token set during one-time enrolment) is on the roadmap.

**Hotspot concurrent device limits**

A laptop's Wi-Fi card can only associate with roughly 8–15 devices simultaneously when acting as a hotspot. The workaround is the disconnect prompt shown after a successful submission, which frees the slot for the next student. A dedicated wireless access point removes this constraint entirely.

**Captive portal requires a DNS redirect layer**

The probe intercept routes in `app.py` are live, but they only trigger if the OS's connectivity-check DNS queries resolve to this machine. That requires either a local DNS server answering every query with the hotspot IP, or a hotspot configuration that advertises this machine as the DNS server. That component is not yet in the repository. See the roadmap.

---

## Complexity Summary

| Operation | Complexity | Notes |
|---|---|---|
| Duplicate roll check | O(1) | Dict key lookup |
| Duplicate MAC check | O(1) | Set membership test |
| Recording a submission | O(1) amortized | Dict insertion |
| Autosave sort | O(N log N) | Runs at most once every 15 seconds |
| Final write on shutdown | O(N log N) | Runs once |
| Cloud sync | 1 API call | Entire session as a single `append_rows()` |
| Memory usage | O(N) | N = submissions this session |

---

## Roadmap

- [ ] DNS redirect layer — serve every domain from the hotspot IP so OS captive-portal probes auto-trigger (groundwork already in `app.py`)
- [ ] Browser token-based identity — replaces MAC binding, removes MAC randomization dependency
- [ ] Live session dashboard — real-time submission count via the `/status` JSON endpoint
- [ ] Periodic autosave interval configurable via env var (currently hardcoded to 15 seconds in `Settings`)
- [ ] Multi-section support — run parallel sessions for different course sections

---

## License

MIT — see [LICENSE](LICENSE) for details.

---

<div align="center">
Built to recover 5 minutes of every lecture. Open to contributions.
</div>
