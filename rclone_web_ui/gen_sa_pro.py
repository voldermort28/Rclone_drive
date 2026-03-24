import os
import json
import time
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

KEY_FILE = 'sa_key.json'
TARGET_DIR = 'accounts'
PROJECT_ID = 'quick-processor-491216-u1'
COUNT = 100

def create_sa_with_retry(iam, project_id, sa_id, display_name):
    for attempt in range(10):
        try:
            iam.projects().serviceAccounts().create(
                name=f"projects/{project_id}",
                body={
                    'accountId': sa_id,
                    'serviceAccount': {'displayName': display_name}
                }
            ).execute()
            return True
        except HttpError as e:
            if e.resp.status == 409:
                return True # Already exists
            elif e.resp.status == 429:
                print("Quota hit. Waiting 60s...", end=" ", flush=True)
                time.sleep(60)
            else:
                raise e
    return False

def create_key_with_retry(iam, project_id, email, key_path):
    import base64
    for attempt in range(15):
        try:
            key = iam.projects().serviceAccounts().keys().create(
                name=f"projects/{project_id}/serviceAccounts/{email}",
                body={}
            ).execute()
            key_content = base64.b64decode(key['privateKeyData']).decode('utf-8')
            with open(key_path, 'w') as f:
                f.write(key_content)
            return True
        except HttpError as e:
            if e.resp.status == 404:
                # Eventual consistency delay
                time.sleep(5)
            elif e.resp.status == 429:
                print("Quota hit. Waiting 60s...", end=" ", flush=True)
                time.sleep(60)
            else:
                raise e
    return False

def main():
    if not os.path.exists(TARGET_DIR):
        os.makedirs(TARGET_DIR)

    creds = service_account.Credentials.from_service_account_file(
        KEY_FILE, scopes=['https://www.googleapis.com/auth/cloud-platform']
    )
    iam = build('iam', 'v1', credentials=creds)
    print(f"Starting to create {COUNT} Service Accounts in project {PROJECT_ID}...")

    success_count = 0
    for i in range(1, COUNT + 1):
        sa_id = f"sa-{i:03d}"
        display_name = f"Auto Generated SA {i:03d}"
        email = f"{sa_id}@{PROJECT_ID}.iam.gserviceaccount.com"
        key_path = os.path.join(TARGET_DIR, f"{sa_id}.json")

        if os.path.exists(key_path):
            success_count += 1
            print(f"[{i}/{COUNT}] {sa_id} already has key. Skipping.")
            continue

        print(f"[{i}/{COUNT}] Processing {sa_id}...", end=" ", flush=True)
        try:
            if create_sa_with_retry(iam, PROJECT_ID, sa_id, display_name):
                print("SA Ok.", end=" ", flush=True)
                if create_key_with_retry(iam, PROJECT_ID, email, key_path):
                    print("Key Downloaded.")
                    success_count += 1
                else:
                    print("Failed to generate key (404/429 loops exhausted).")
            else:
                print("Failed to create SA (429 loop exhausted).")
            time.sleep(1)
        except Exception as e:
            print(f"\nError: {e}")
            if "PERMISSION_DENIED" in str(e):
                print("CRITICAL: Permission denied. Main SA needs roles.")
                return

    print(f"\\nSuccessfully secured {success_count}/{COUNT} SA Keys in {TARGET_DIR}/")

if __name__ == '__main__':
    main()
