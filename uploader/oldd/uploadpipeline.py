import os
import subprocess
import time
from pathlib import Path
import datetime

# --- CONFIGURATION ---
TARGET_FOLDER = r"C:\Users\Administrator\Pictures\YTchromeNEON\output\videos\toupload"
UPLOAD_SCRIPT = r"C:\Users\Administrator\Pictures\uploader\upload_video.py"
LOG_FILE = "upload_history.log"

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = '--profile-directory="Default"'
YT_STUDIO_URL = "https://studio.youtube.com/channel/UC4laQaWkDDNJt8x_2O935Ng/content?d=ud"
# ---------------------

def log(msg):
    """Prints to console with a timestamp."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}")

def get_processed_files():
    if not os.path.exists(LOG_FILE):
        return set()
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def mark_as_processed(filename):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{filename}\n")

def main():
    target_dir = Path(TARGET_FOLDER)
    if not target_dir.exists():
        log(f"ERROR: Directory does not exist -> {target_dir}")
        return

    processed = get_processed_files()
    videos = [p for p in target_dir.iterdir() if p.is_file() and p.suffix.lower() == ".mp4"]
    
    if not videos:
        log("No new .mp4 files found to upload.")
        return

    log(f"Found {len(videos)} video(s). Checking against upload history...")

    for video in videos:
        if video.name in processed:
            log(f"SKIP: '{video.name}' (Already uploaded)")
            continue

        log(f"\n--- STARTING UPLOAD: {video.name} ---")
        
        # 1. Open YouTube Studio in Chrome
        log("Opening YouTube Studio in Chrome...")
        chrome_cmd = f'"{CHROME_PATH}" {PROFILE} "{YT_STUDIO_URL}"'
        subprocess.Popen(chrome_cmd, shell=True)
        
        # 2. Wait 10 seconds for it to load
        log("Waiting 10 seconds for YouTube Studio to load...")
        time.sleep(10)
        
        # 3. Run your upload Python script
        log(f"Executing upload_video.py with '{video.name}'...")
        upload_cmd = f'python -u "{UPLOAD_SCRIPT}" "{video.resolve()}"'
        
        try:
            # We use check=True so it throws an error if the upload script crashes
            subprocess.run(upload_cmd, shell=True, check=True)
            
            # 4. Log it as successfully processed
            log(f"SUCCESS: '{video.name}' uploaded completely.")
            mark_as_processed(video.name)
            
        except subprocess.CalledProcessError as e:
            log(f"FAIL: Upload script failed for '{video.name}'. (Exit Code {e.returncode})")
            log("It has NOT been added to the history log, so it will retry next time.")
            
        except Exception as e:
            log(f"ERROR: Something went wrong executing the upload script: {e}")
            
    log("\nAll pending videos processed.")

if __name__ == "__main__":
    main()