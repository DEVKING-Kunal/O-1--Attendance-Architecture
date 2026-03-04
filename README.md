<div align="center">

# ⚡ AttendX — High-Density Attendance Architecture

**A distributed, O(1) local-network attendance system built for real-world classroom scale.**

[![Python](https://img.shields.io/badge/Python-3.8+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-2.x-000000?style=for-the-badge&logo=flask&logoColor=white)](https://flask.palletsprojects.com)
[![Waitress](https://img.shields.io/badge/Waitress-WSGI_Server-4B8BBE?style=for-the-badge)](https://docs.pylonsproject.org/projects/waitress)
[![Google Sheets](https://img.shields.io/badge/Google_Sheets-API-34A853?style=for-the-badge&logo=googlesheets&logoColor=white)](https://developers.google.com/sheets)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

---

*Takes 100+ students from scan to confirmation in under a second — no internet, no rate limits, no dropped records.*

</div>

---

## Contents

- [The Problem This Solves](#-the-problem-this-solves)
- [Architecture Overview](#️-architecture-overview)
- [Key Features](#-key-features)
- [Project Structure](#️-project-structure)
- [How It Works](#️-how-it-works)
- [Setup & Deployment](#-setup--deployment)
- [Security & Threat Model](#️-security--threat-model)
- [Known Limitations](#️-known-limitations)
- [Complexity Summary](#-complexity-summary)
- [Roadmap](#️-roadmap)

---

## 📌 The Problem This Solves

### The Real-World Trigger

At **NIT Jalandhar**, a standard lecture slot is 50 minutes. Passing a physical register down every row of a 60–80 student classroom routinely burns **5 to 10 minutes** of that — just waiting for a sheet of paper to travel and come back. That's up to **20% of the lecture gone** before a single concept is taught, every single class, every single day.

The register is, algorithmically, an **O(N) sequential operation** — each student signs one after another. Digitizing it naively (having a server scan a list of enrolled users for each incoming check-in) doesn't fix the complexity, it just moves the same O(N) bottleneck online.

### The Algorithmic Problem

Most attendance tools hit a wall the moment an entire class tries to check in at once. Traditional systems scan a central database for every incoming request — that's **O(N) complexity** — which means the 100th student's request is 100× slower to validate than the first. Add a cloud API with a 60-writes-per-minute limit on top of that, and you get a guaranteed failure during peak load.

The root cause isn't the medium (paper vs. app) — it's the **data structure underneath**. Iterating an array or querying a table row-by-row to find a match is a linear search. No amount of better UI fixes that.

### The Fix

**AttendX flips the model.** Students push their own data to a lightweight local edge server. Validation runs against in-memory hash sets — **O(1) lookups, always**, regardless of whether there are 10 students or 200. Cloud sync happens *after* the session ends, in a single batched call. The result is constant-time processing, zero dependency on live internet during the session, and no lost records.

The 5–10 minute tax on every lecture drops to under 60 seconds.

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                     HOST MACHINE                        │
│                                                         │
│   ┌─────────────┐     ┌──────────────────────────────┐  │
│   │  QR Code    │     │   Waitress WSGI Edge Server  │  │
│   │  Generator  │────▶│   Flask App  +  Hash-Set RAM │  │
│   └─────────────┘     └──────────────┬───────────────┘  │
│                                      │                  │
│                              SIGINT / Ctrl+C            │
│                                      │                  │
│                         ┌────────────▼─────────────┐    │
│                         │  Local CSV Buffer (sorted)│    │
│                         └────────────┬─────────────┘    │
│                                      │                  │
│                              sync.py (post-session)     │
│                                      │                  │
│                         ┌────────────▼─────────────┐    │
│                         │     Google Sheets API     │    │
│                         └──────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
         ▲  ▲  ▲  ▲  ▲  (100+ simultaneous HTTP POSTs)
         │  │  │  │  │
    [Student Devices — scan QR, push payload]
```

---

## ✨ Key Features

- **O(1) duplicate validation** — MAC address and Roll Number checks run against Python dicts loaded in RAM, not a database query
- **Thundering herd resistant** — Waitress handles concurrent connections; no dropped requests under burst load
- **API rate-limit bypass** — Records buffer locally first; one atomic bulk-upload to Google Sheets per session
- **Graceful shutdown** — SIGINT triggers a sorted CSV write before the process exits, guaranteeing zero data loss
- **Buddy-punch prevention** — Strict 1:1 binding between Roll Number ↔ MAC address enforced at the server level
- **Proxy/VPN rejection** — Middleware inspects `X-Forwarded-For` and `Via` headers; off-site spoofing returns `403 Forbidden`
- **Offline first** — Entire session runs on a local hotspot; no internet dependency until the optional sync step

---

## 🗂️ Project Structure

```
attendx/
├── server.py            # Flask app + Waitress launcher + SIGINT handler
├── sync.py              # Bulk Google Sheets upload script
├── qr_gen.py            # Dynamic IP detection + QR code generator
├── credentials.json     # GCP service account key (git-ignored)
├── attendance_qr.png    # Generated QR code (git-ignored)
├── output/
│   └── session_*.csv    # Timestamped local buffer files
├── requirements.txt
└── README.md
```

---

## ⚙️ How It Works

### 1. Distributed Push Model

Instead of the server polling for devices, each student's browser sends a `POST` request with their Roll Number and the device's MAC address. The server is a passive receiver — it never iterates the student list to "find" someone.

### 2. O(1) Validation via Hash Sets

```python
# On startup — O(N) one-time load into RAM
enrolled_students = {roll: mac for roll, mac in load_roster()}
submitted_macs    = {}   # tracks MAC → Roll submitted this session
submitted_rolls   = {}   # tracks Roll → MAC submitted this session

# On each incoming request — O(1)
if mac_address in submitted_macs:
    return "Already submitted from this device", 409
if roll_number in submitted_rolls:
    return "Roll already marked", 409
```

Because dictionary lookups hash directly to a memory address, the 100th request validates in the same time as the 1st.

### 3. Write-Ahead Buffering

Accepted records land in an in-memory list instantly. The student sees a success confirmation in milliseconds. The CSV write and Google Sheets sync happen *outside* the request lifecycle, so they never block a student's response.

### 4. Atomic Shutdown & Sync

```
Ctrl+C  →  SIGINT handler  →  sort buffer (O(N log N))
        →  write session_<timestamp>.csv
        →  process exits cleanly

(later, on internet connection)
python sync.py  →  single batch_update call to Sheets API
```

---

## 🚀 Setup & Deployment

### Prerequisites

- Python 3.8+
- A Google Cloud project with **Google Sheets API** and **Google Drive API** enabled
- A service account with a downloaded JSON key

### Installation

```bash
git clone https://github.com/your-username/attendx.git
cd attendx
pip install -r requirements.txt
```

### Cloud Authentication

1. Download your service account key from Google Cloud Console
2. Rename it `credentials.json` and place it in the project root
3. Open your target Google Sheet and share it with the `client_email` from the JSON file
4. Rename the sheet tab to exactly `Attendance_Sheet`

> ⚠️ `credentials.json` is in `.gitignore`. Never commit this file.

### Running a Session

**Step 1 — Start your hotspot, generate the QR code**
```bash
python qr_gen.py
```
This auto-detects your active hotspot IP and writes `attendance_qr.png` to the project root. Display or print it for students to scan.

**Step 2 — Launch the edge server**
```bash
python server.py
```
Students connect to the hotspot, scan the QR, and submit. Watch confirmations log to the terminal in real time.

When everyone has checked in, press `Ctrl+C`. The session CSV writes automatically.

**Step 3 — Sync to Google Sheets**
```bash
python sync.py
```
Run this once you're back on a normal internet connection. It uploads the entire session in a single API call.

---

## 🛡️ Security & Threat Model

| Threat | Mitigation |
|---|---|
| **Buddy punching** (submitting for an absent friend) | 1:1 Roll Number ↔ MAC binding; dual hash-set check rejects any second submission from either side |
| **Remote access via VPN/proxy** | Middleware rejects requests containing `X-Forwarded-For` or `Via` headers with `403 Forbidden` |
| **Replay attacks** | In-session submitted sets make any repeated MAC or Roll Number a no-op after first acceptance |
| **Data loss on crash** | In-memory buffer + SIGINT handler ensures CSV is always written before the process exits |

---

## ⚠️ Known Limitations

**MAC Address Randomization (iOS 14+ / Android 10+)**

Modern phones randomize their MAC per SSID. This works fine within a single session but means the system can't recognize a returning device across days without the user disabling *Private Wi-Fi Address* for the classroom network.

*Planned fix:* Replace MAC-based identification with a cryptographic browser token established during a one-time onboarding handshake and stored in `localStorage`.

**Hotspot Association Limits**

Standard NIC drivers cap Wi-Fi hotspot clients at 8–15 simultaneous associations. The current workaround is instructing students to disconnect immediately after submitting, freeing up DHCP leases for the next wave.

*Recommended for scale:* Deploy behind a dedicated **MU-MIMO Wireless Access Point** that supports 50–200+ concurrent associations.

---

## 📊 Complexity Summary

| Operation | Complexity | Notes |
|---|---|---|
| Student validation | O(1) | Hash-set lookup in RAM |
| Duplicate check | O(1) | Dual hash-set, same lookup |
| Session buffer write | O(1) amortized | In-memory append |
| Shutdown sort | O(N log N) | One-time, post-session |
| Cloud sync | O(1) API calls | Single batch upload |
| Memory footprint | O(N) space | Full roster lives in RAM |

---

## 🗺️ Roadmap

- [ ] Browser-token based identification (replace MAC dependency)
- [ ] Web dashboard for live session monitoring
- [ ] Multi-session CSV merge utility
- [ ] Support for multiple concurrent class sections

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

<div align="center">
  Built to solve a real problem. Open to contributions.
</div>
