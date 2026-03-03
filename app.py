import os
import re
import csv
import signal
import sys
from datetime import datetime
from flask import Flask, request, render_template_string
from waitress import serve

app = Flask(__name__)

# CONFIGURATION
SESSION_ID = datetime.now().strftime("%Y-%m-%d_%H-%M")
CSV_FILE = f"attendance_{SESSION_ID}.csv"

# In-memory buffer for O(1) ingestion
# Using a dict to prevent duplicate Roll Numbers instantly
attendance_buffer = {}
submitted_macs = set()

def get_mac_address(ip):
    if ip in ("127.0.0.1", "::1"): return "INTERNAL_HOST"
    try:
        arp_raw = os.popen(f"arp -a {ip}").read()
        match = re.search(r"([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})", arp_raw)
        return match.group(0).replace('-', ':').upper() if match else "UNKNOWN_MAC"
    except:
        return "ERROR"

def finalize_and_exit(sig, frame):
    """
    Triggered by KeyboardInterrupt (Ctrl+C). 
    Performs the final sort and atomic write to disk.
    """
    print(f"\n[!] Shutdown signal received. Finalizing {len(attendance_buffer)} records...")
    
    if attendance_buffer:
        # Sort by Roll Number before writing - O(N log N)
        sorted_entries = sorted(attendance_buffer.values(), key=lambda x: x['roll'])
        
        try:
            with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                writer.writerow(["Timestamp", "Roll_Number", "MAC_Address", "IPv4_Address"])
                for entry in sorted_entries:
                    writer.writerow([entry['time'], entry['roll'], entry['mac'], entry['ip']])
            print(f"✅ Data successfully sorted and saved to: {CSV_FILE}")
        except Exception as e:
            print(f"❌ Critical Error saving data: {e}")
    else:
        print("⚠️ No records were captured this session.")
    
    print("[*] Server offline.")
    sys.exit(0)

# Register the signal handler for a clean Ctrl+C exit
signal.signal(signal.SIGINT, finalize_and_exit)

#  UI 
HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Portal</title>
    <style>
        :root { --blue: #1a73e8; --red: #d93025; --green: #188038; }
        body { font-family: -apple-system, sans-serif; background: #f1f3f4; display: flex; justify-content: center; padding: 40px 20px; }
        .container { background: #fff; padding: 32px; border-radius: 8px; box-shadow: 0 1px 2px rgba(0,0,0,0.1); width: 100%; max-width: 400px; }
        .session { font-size: 12px; color: #5f6368; margin-bottom: 20px; text-transform: uppercase; letter-spacing: 1px; }
        input { width: 100%; padding: 12px; border: 1px solid #dadce0; border-radius: 4px; font-size: 16px; margin-bottom: 16px; box-sizing: border-box; }
        button { width: 100%; padding: 12px; background: var(--blue); color: #fff; border: none; border-radius: 4px; font-weight: 500; cursor: pointer; }
        .status { padding: 16px; border-radius: 4px; margin-bottom: 20px; font-size: 14px; }
        .success { background: #e6f4ea; color: var(--green); border: 1px solid #ceead6; }
        .error { background: #fce8e6; color: var(--red); border: 1px solid #fad2cf; }
        .urgent { margin-top: 24px; padding: 16px; border: 2px solid var(--red); color: var(--red); font-weight: bold; text-align: center; animation: pulse 2s infinite; }
        @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.6; } 100% { opacity: 1; } }
    </style>
</head>
<body>
    <div class="container">
        <div class="session">Session ID: {{ session }}</div>
        {% if status == 'success' %}
            <div class="status success">Attendance recorded for <strong>{{ roll }}</strong>.</div>
            <div class="urgent">⚠️ DISCONNECT FROM WI-FI NOW ⚠️</div>
        {% elif status == 'error' %}
            <div class="status error">{{ message }}</div>
            <button onclick="window.location.href='/'">Try Again</button>
        {% else %}
            <form method="POST" action="/submit">
                <input type="text" name="roll_number" placeholder="Enter Roll Number" required autocomplete="off">
                <button type="submit">Submit</button>
            </form>
        {% endif %}
    </div>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_PAGE, status="none", session=SESSION_ID)

@app.route("/submit", methods=["POST"])
def submit():
    roll = request.form.get("roll_number", "").strip().upper()
    ip = request.remote_addr
    mac = get_mac_address(ip)

    if roll in attendance_buffer:
        return render_template_string(HTML_PAGE, status="error", message="Roll number already recorded.", session=SESSION_ID)

    if mac != "UNKNOWN_MAC" and mac in submitted_macs:
        return render_template_string(HTML_PAGE, status="error", message="Device already used for submission.", session=SESSION_ID)

    # O(1) In-Memory storage
    attendance_buffer[roll] = {
        'time': datetime.now().strftime("%H:%M:%S"),
        'roll': roll,
        'mac': mac,
        'ip': ip
    }
    submitted_macs.add(mac)
    
    return render_template_string(HTML_PAGE, status="success", roll=roll, session=SESSION_ID)

if __name__ == "__main__":
    print(f"[*] Attendance Portal Live. Session: {SESSION_ID}")
    print("[*] NOTE: Press Ctrl+C to stop the server and save sorted data.")
    serve(app, host="0.0.0.0", port=80, threads=50)