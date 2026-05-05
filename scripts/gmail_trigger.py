"""
Gmail Trigger — polls your Gmail inbox for emails with attachments
and submits each attachment to the Vendor Onboarding API.

Setup:
  1. Enable Gmail API in Google Cloud Console
  2. Download OAuth credentials as credentials.json into this directory
  3. pip install google-auth-oauthlib google-api-python-client httpx
  4. python scripts/gmail_trigger.py

On first run it opens a browser for Gmail auth and saves token.json.
Subsequent runs use the cached token automatically.
"""

import base64
import os
import time
import sys

import httpx
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Load .env from the project root (one level above this script)
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

# ── Config ───────────────────────────────────────────────────────────────────
_missing = [k for k in ("API_BASE_URL",) if not os.environ.get(k)]
if _missing:
    print(f"[ERROR] Missing required environment variables: {', '.join(_missing)}")
    print("  Set them in your .env file.")
    sys.exit(1)

API_BASE_URL  = os.environ["API_BASE_URL"]
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL_SECONDS", "30"))
SCOPES        = ["https://www.googleapis.com/auth/gmail.modify"]

_SCRIPTS_DIR     = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE = os.path.join(_SCRIPTS_DIR, "credentials.json")
TOKEN_FILE       = os.path.join(_SCRIPTS_DIR, "token.json")

# Label applied to processed emails so we don't re-process them
PROCESSED_LABEL = "VendorOnboardingProcessed"

SUPPORTED_MIME_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/tiff",
    "image/bmp",
    "text/plain",
    "text/csv",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/octet-stream",
}
# ─────────────────────────────────────────────────────────────────────────────


def authenticate() -> Credentials:
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                print(
                    f"\n[ERROR] credentials.json not found at {CREDENTIALS_FILE}\n"
                    "  1. Go to https://console.cloud.google.com/\n"
                    "  2. APIs & Services → Credentials → Create OAuth 2.0 Client ID\n"
                    "  3. Application type: Desktop app\n"
                    "  4. Download JSON and save as scripts/credentials.json\n"
                )
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return creds


def get_or_create_label(service, name: str) -> str:
    """Return label ID, creating it if it doesn't exist."""
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    for label in labels:
        if label["name"] == name:
            return label["id"]
    created = service.users().labels().create(
        userId="me",
        body={"name": name, "labelListVisibility": "labelHide", "messageListVisibility": "hide"},
    ).execute()
    return created["id"]


def get_sender(headers: list) -> str:
    for h in headers:
        if h["name"].lower() == "from":
            raw = h["value"]
            import re
            match = re.search(r"<([^>]+)>", raw)
            return match.group(1).strip() if match else raw.strip()
    return "unknown@gmail.com"


def decode_attachment(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "==")


def find_attachments(service, message_id: str, payload: dict) -> list[dict]:
    """Recursively walk MIME parts and collect file attachments."""
    attachments = []

    def walk(part):
        mime = part.get("mimeType", "")
        filename = part.get("filename", "")
        body = part.get("body", {})

        if filename and mime in SUPPORTED_MIME_TYPES:
            if "data" in body:
                file_bytes = decode_attachment(body["data"])
            elif "attachmentId" in body:
                att = service.users().messages().attachments().get(
                    userId="me", messageId=message_id, id=body["attachmentId"]
                ).execute()
                file_bytes = decode_attachment(att["data"])
            else:
                return
            attachments.append({"filename": filename, "mime": mime, "bytes": file_bytes})

        for sub in part.get("parts", []):
            walk(sub)

    walk(payload)
    return attachments


def submit_to_api(filename: str, mime: str, file_bytes: bytes, sender: str) -> dict:
    """POST the attachment to /process/manual and return the JSON result."""
    files = {"file": (filename, file_bytes, mime)}
    data = {"sender_email": sender}
    resp = httpx.post(f"{API_BASE_URL}/process/manual", files=files, data=data, timeout=180)
    resp.raise_for_status()
    return resp.json()


def summarise(result: dict) -> str:
    company    = (result.get("company") or {}).get("company_name", "Unknown")
    decision   = result.get("routing_decision", "N/A")
    confidence = result.get("overall_confidence_score", 0)
    tier       = result.get("category_tier", "N/A")
    flags      = result.get("routing_flags", [])
    return (
        f"Company={company} | Decision={decision} | "
        f"Confidence={confidence:.2f} | Tier={tier} | Flags={flags}"
    )


def poll_once(service, processed_label_id: str):
    """Fetch unread emails without our processed label that have attachments."""
    query = f"is:unread has:attachment -label:{PROCESSED_LABEL}"
    result = service.users().messages().list(userId="me", q=query, maxResults=10).execute()
    messages = result.get("messages", [])

    if not messages:
        return

    print(f"\n[{time.strftime('%H:%M:%S')}] Found {len(messages)} new email(s) with attachments")

    for msg_stub in messages:
        msg_id = msg_stub["id"]
        msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        headers = msg["payload"].get("headers", [])
        sender = get_sender(headers)

        attachments = find_attachments(service, msg_id, msg["payload"])
        if not attachments:
            # Mark read anyway so we don't keep seeing it
            service.users().messages().modify(
                userId="me", id=msg_id,
                body={"removeLabelIds": ["UNREAD"], "addLabelIds": [processed_label_id]},
            ).execute()
            continue

        print(f"  From: {sender} | {len(attachments)} attachment(s)")

        for att in attachments:
            print(f"    Processing: {att['filename']} ({att['mime']})")
            try:
                result = submit_to_api(att["filename"], att["mime"], att["bytes"], sender)
                print(f"    Result: {summarise(result)}")
            except httpx.HTTPStatusError as e:
                print(f"    API error {e.response.status_code}: {e.response.text[:200]}")
            except Exception as e:
                print(f"    Error: {e}")

        # Mark as read and label as processed
        service.users().messages().modify(
            userId="me", id=msg_id,
            body={"removeLabelIds": ["UNREAD"], "addLabelIds": [processed_label_id]},
        ).execute()


def main():
    print("Vendor Onboarding — Gmail Trigger")
    print(f"  API:           {API_BASE_URL}")
    print(f"  Poll interval: {POLL_INTERVAL}s")
    print(f"  Label:         {PROCESSED_LABEL}")
    print()

    creds = authenticate()
    service = build("gmail", "v1", credentials=creds)

    profile = service.users().getProfile(userId="me").execute()
    print(f"  Authenticated as: {profile['emailAddress']}")
    print(f"  Watching for emails with attachments...\n")

    processed_label_id = get_or_create_label(service, PROCESSED_LABEL)

    # Check API health before looping
    try:
        health = httpx.get(f"{API_BASE_URL}/health", timeout=5).json()
        print(f"  API health: {health.get('status')} — components: {health.get('components')}")
    except Exception as e:
        print(f"  [WARNING] API not reachable at {API_BASE_URL}: {e}")
        print("  Start the server before sending test emails.\n")

    while True:
        try:
            poll_once(service, processed_label_id)
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] Poll error: {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
