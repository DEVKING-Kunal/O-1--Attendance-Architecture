import gspread
from oauth2client.service_account import ServiceAccountCredentials
import csv
import os
import time
import sys

# Configuration
# Since we updated app.py to use session-based names, we find the latest one
def get_latest_attendance_file():
    files = [f for f in os.listdir('.') if f.startswith('attendance_') and f.endswith('.csv')]
    return max(files, key=os.path.getctime) if files else None

def sync_to_cloud():
    csv_file = get_latest_attendance_file()
    
    if not csv_file:
        print("No local attendance files found.")
        return

    print(f"Starting sync for: {csv_file}")
    
    try:
        #Authentication
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        client = gspread.authorize(creds)
        sheet = client.open("Attendance_Sheet").sheet1 

        # \Readigng
        rows_to_upload = []
        with open(csv_file, mode='r', encoding='utf-8') as file:
            reader = csv.reader(file)
            next(reader)  # Skip header
            rows_to_upload = list(reader)

        if not rows_to_upload:
            print("File is empty. Skipping.")
            return

        # Atomicity in Transaction
        print(f"Uploading {len(rows_to_upload)} records...")
        
        # This is the "Commit" point
        sheet.append_rows(rows_to_upload)
        
        # SUCCESS: ARCHIVE DATA 
        backup_name = f"synced_backup_{int(time.time())}.csv"
        os.rename(csv_file, backup_name)
        print(f"✅ Sync Complete. Local file archived as: {backup_name}")

    except Exception as e:
        # --- ROLLBACK LOGIC ---
        print(f"❌ TRANSACTION FAILED: {e}")
        print("⚠️ Rollback initiated: Local CSV has been preserved for retry.")
        # We do NOT rename or delete the file here. 
        # It stays in the folder to be picked up by the next sync attempt.

if __name__ == "__main__":
    sync_to_cloud()