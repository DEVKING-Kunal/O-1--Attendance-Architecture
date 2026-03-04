<div align="center">

# AttendX — O(1) Classroom Attendance System

**A local-network attendance tool that reduces a 5–10 minute classroom ritual to under 60 seconds.**

[![Python](https://img.shields.io/badge/Python-3.8+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-2.x-000000?style=for-the-badge&logo=flask&logoColor=white)](https://flask.palletsprojects.com)
[![Waitress](https://img.shields.io/badge/Waitress-WSGI_Server-4B8BBE?style=for-the-badge)](https://docs.pylonsproject.org/projects/waitress)
[![Google Sheets](https://img.shields.io/badge/Google_Sheets-API-34A853?style=for-the-badge&logo=googlesheets&logoColor=white)](https://developers.google.com/sheets)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

</div>

---

## Contents

- [The Problem](#the-problem)
- [Why Not Just Use a Google Form?](#why-not-just-use-a-google-form)
- [How It Works](#how-it-works)
- [The Captive Portal Trick](#the-captive-portal-trick)
- [Project Structure](#project-structure)
- [Setup & Deployment](#setup--deployment)
- [Security Considerations](#security-considerations)
- [Known Limitations](#known-limitations)
- [Complexity Summary](#complexity-summary)
- [Roadmap](#roadmap)

---

## The Problem

At **NIT Jalandhar**, a standard lecture is 50 minutes. Passing a physical attendance register across 60–80 students burns **5 to 10 minutes** of that — every class, every day — before the lecture even starts. That's up to 20% of teaching time gone before a single concept is taught.

The register is an **O(N) sequential operation**. Each student signs one after the other; the sheet can only be in one place at a time. Simply moving to a digital form doesn't fix this — if the server validates each incoming submission by scanning a list of enrolled students, you've just moved the same O(N) problem online.

The real fix is changing the data structure. This project loads the student roster into a Python dictionary (hash map) on startup. Every incoming submission is validated with a single key lookup — **O(1), constant time** — so the 80th student's request is processed just as fast as the 1st.

---

## Why Not Just Use a Google Form?

This question deserves a direct answer, because a Google Form is the obvious first instinct.

| Scenario | Google Form | AttendX |
|---|---|---|
| Classroom internet goes down | Form won't load, session is lost | Runs entirely on a local hotspot, no internet needed during class |
| 70 students submit simultaneously | Sheets API rate limit is ~60 writes/min — some submissions fail silently with HTTP 429 errors | All records land in local memory first; cloud sync is one batched call after the session |
| Student submits from outside classroom | No way to enforce physical presence | Requests not originating from the local network are rejected |
| One student submits for an absent friend | A form has no way to detect this | Each device MAC address is bound to exactly one roll number |
| Internet is available but unstable | Partial submissions with no way to know what was lost | Local CSV is always written first; sync happens separately when connection is stable |

The core issue with a Google Form for burst attendance is that it writes to the cloud **synchronously, one record at a time**. Under real classroom load — 70 students in a 2-minute window — you will hit the API rate limit. Most of those failures are silent: the student gets no error, the record just never appears in the sheet.

This project decouples the submission experience from the cloud write entirely.

---

## How It Works

### 1. Students push, the server doesn't poll

The professor's laptop runs a small Flask server. Students connect to a hotspot on that same machine and submit a form with their roll number. The server receives data — it never needs to go looking for anyone.

### 2. O(1) validation via Python dictionaries

```python
# Loaded once at startup from the roster CSV — O(N) one time
enrolled_students = {roll_number: name for ...}

# Two dictionaries track what's been submitted this session
submitted_macs  = {}   # MAC address  → roll number
submitted_rolls = {}   # roll number  → MAC address

# Every incoming request is validated like this — O(1)
if mac_address in submitted_macs:
    return "Already submitted from this device", 409

if roll_number in submitted_rolls:
    return "Roll number already marked", 409
```

A Python dictionary lookup computes a hash of the key and goes directly to that memory slot. It does not scan anything. This is why validation stays constant-time regardless of class size.

### 3. Records buffer locally, sync happens later

When a submission passes validation, it's appended to an in-memory list and the student immediately gets a confirmation. Nothing waits for a network call. When the professor presses `Ctrl+C`, the server writes a sorted, timestamped CSV to disk before exiting. After the lecture, `sync.py` uploads that CSV to Google Sheets in a single batch call — one API request for the entire class.

### 4. Shutdown & sync flow

```
Ctrl+C
  → SIGINT handler triggers
  → buffer sorted by roll number  (O(N log N), runs once)
  → written to  output/session_<timestamp>.csv
  → process exits

(later, once internet is available)
python sync.py
  → reads CSV
  → single batch_update() call to Sheets API
```

---

## The Captive Portal Trick

When a device connects to an unknown Wi-Fi network, most operating systems automatically probe for internet access. If that probe gets an unexpected response, the OS pops up a **captive portal** — the same browser window you see at airports or cafes asking you to sign in before you can use the internet.

This project deliberately exploits that behavior.

The Flask server intercepts the OS connectivity-check requests (iOS pings `captive.apple.com`, Android pings `connectivitycheck.gstatic.com`, Windows pings `msftconnecttest.com`) and returns a response that triggers the portal. The result: **as soon as a student connects to the hotspot, the attendance form opens automatically in their browser.** No QR scan, no URL to type, no instruction to follow.

This removes the most friction-heavy step for students and works across every major mobile OS without any app installation.

---

## Project Structure

```
attendx/
├── server.py            # Flask app + Waitress server + SIGINT handler
├── sync.py              # Post-session Google Sheets upload
├── qr_gen.py            # Hotspot IP detection + QR code generator (fallback)
├── credentials.json     # GCP service account key  ← git-ignored
├── attendance_qr.png    # Generated QR code        ← git-ignored
├── output/
│   └── session_*.csv    # Local session records
├── requirements.txt
└── README.md
```

---

## Setup & Deployment

### Prerequisites

- Python 3.8+
- A Google Cloud project with **Google Sheets API** and **Google Drive API** enabled
- A service account key (JSON) downloaded from Google Cloud Console

### Installation

```bash
git clone https://github.com/your-username/attendx.git
cd attendx
pip install -r requirements.txt
```

### Cloud Authentication

1. Download your service account JSON key from Google Cloud Console
2. Rename it `credentials.json` and place it in the project root
3. Share your Google Sheet with the `client_email` value from inside that JSON file
4. Make sure the sheet tab is named exactly `Attendance_Sheet`

> `credentials.json` is in `.gitignore`. Do not commit it.

### Running a Session

**Step 1 — Enable your laptop's mobile hotspot, then run:**
```bash
python qr_gen.py
```
Detects the active hotspot IP and generates `attendance_qr.png` as a fallback for devices that don't trigger the captive portal automatically.

**Step 2 — Start the server:**
```bash
python server.py
```
Students connect to the hotspot. The captive portal opens the form automatically on most devices. Submissions log to the terminal in real time. Press `Ctrl+C` when done — the CSV writes on exit.

**Step 3 — Sync once you have internet:**
```bash
python sync.py
```
Uploads the entire session to Google Sheets in a single API call.

---

## Security Considerations

| Concern | How it's handled |
|---|---|
| One student marking attendance for a friend | Each MAC address is bound to one roll number and vice versa. A second submission from either side returns 409. |
| Submitting from outside the classroom via VPN | Server checks for `X-Forwarded-For` and `Via` headers. Requests routed through a proxy return 403. |
| Same student submitting twice | Both MAC and roll number dictionaries are checked; a duplicate on either side is rejected. |
| Data loss if the laptop crashes mid-session | The SIGINT handler covers a clean `Ctrl+C` exit. An abrupt crash would lose the in-memory buffer. This is a known gap — see limitations. |

---

## Known Limitations

**MAC address randomization (iOS 14+ / Android 10+)**

Modern phones assign a different random MAC to each Wi-Fi network for privacy. This means the MAC seen today may differ tomorrow. The current workaround is asking students to disable "Private Wi-Fi Address" for the classroom hotspot — this is inconvenient and can't be enforced.

The right fix is replacing MAC-based identity with a browser token set during a one-time enrolment step. It's on the roadmap.

**Hotspot client limits**

A laptop's Wi-Fi card can only associate with roughly 8–15 devices simultaneously when acting as a hotspot. The workaround is having students disconnect immediately after submitting to free up the slot. This works in practice but is clunky. A proper wireless access point removes this problem entirely.

**No crash recovery**

If the process is killed abruptly (power loss, force quit) rather than via `Ctrl+C`, the in-memory buffer is lost. A periodic flush to disk on every N submissions would fix this but hasn't been built yet.

---

## Complexity Summary

| Operation | Complexity | Notes |
|---|---|---|
| Enrollment lookup | O(1) | Dictionary key check |
| Duplicate detection | O(1) | Two dictionary key checks |
| Recording a submission | O(1) amortized | List append in memory |
| Session sort on shutdown | O(N log N) | Runs once, post-session |
| Cloud sync | 1 API call | Entire session as a single batch |
| Memory usage | O(N) | Full roster held in RAM |

---

## Roadmap

- [ ] Browser token-based identity (removes MAC randomization dependency)
- [ ] Periodic disk flush every N submissions (crash recovery)
- [ ] Live session view in the terminal or a simple web dashboard
- [ ] Support for multiple sections running in parallel

---

## License

MIT — see [LICENSE](LICENSE) for details.

---

<div align="center">
Built to recover 5 minutes of every lecture. Open to contributions.
</div>
