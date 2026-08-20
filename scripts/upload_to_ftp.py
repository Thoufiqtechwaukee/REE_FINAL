import ftplib
import os
from pathlib import Path
import sys

# FTP Details
FTP_HOST = "68.178.174.167"
# Note: Update FTP_USER if your host requires a specific domain format (e.g. DOMAIN\apptwo)
FTP_USER = "apptwo"
FTP_PASS = "M30u~r7y7"

# Local frontend directory
LOCAL_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def upload_directory(ftp, local_dir, remote_dir=""):
    for item in os.listdir(local_dir):
        local_path = os.path.join(local_dir, item)
        remote_path = f"{remote_dir}/{item}" if remote_dir else item

        if os.path.isdir(local_path):
            try:
                ftp.mkd(remote_path)
                print(f"Created remote directory: {remote_path}")
            except Exception:
                pass  # Directory might already exist
            upload_directory(ftp, local_path, remote_path)
        else:
            with open(local_path, "rb") as f:
                ftp.storbinary(f"STOR {remote_path}", f)
                print(f"Uploaded: {remote_path}")


def main():
    print(f"Connecting to FTP server {FTP_HOST}...")
    try:
        ftp = ftplib.FTP(FTP_HOST, timeout=10)
        ftp.login(FTP_USER, FTP_PASS)
        print("Logged in successfully!")
        print("Uploading frontend files...")
        upload_directory(ftp, LOCAL_FRONTEND_DIR)
        ftp.quit()
        print("All frontend files uploaded successfully!")
    except Exception as e:
        print(f"FTP Error: {e}")
        print("\nPlease verify:")
        print("1. Is the username formatted with a domain name (e.g., SERVERNAME\\apptwo)?")
        print("2. Is FTP enabled for user 'apptwo' in your web hosting control panel?")


if __name__ == "__main__":
    main()
