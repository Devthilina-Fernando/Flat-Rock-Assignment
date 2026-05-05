"""
Gmail poller — daemon thread that lives inside the FastAPI process.

Polls the configured Gmail inbox, processes attachments directly through
run_pipeline() (no HTTP round-trip), and publishes SSE events via event_bus.
"""
import base64
import os
import re
import threading

from app.config import get_settings
from app.db.session import SessionLocal
from app.services.orchestrator import run_pipeline
from app.utils.logging_config import get_logger
import app.services.event_bus as event_bus

logger = get_logger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
PROCESSED_LABEL = "VendorOnboardingProcessed"
SUPPORTED_MIME_TYPES = {
    "application/pdf",
    "image/png", "image/jpeg", "image/tiff", "image/bmp",
    "text/plain", "text/csv",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/octet-stream",
}


class GmailPoller(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="gmail-poller")
        self._stop_event = threading.Event()
        self._settings = get_settings()

    def stop(self) -> None:
        self._stop_event.set()

    # ── Main thread loop ───────────────────────────────────────────────────

    def run(self) -> None:
        settings = self._settings
        logger.info("Gmail poller starting",
                    credentials=settings.gmail_credentials_file,
                    interval=settings.gmail_poll_interval)
        try:
            creds = self._authenticate()
        except Exception as e:
            logger.error("Gmail authentication failed — poller exiting", error=str(e))
            return

        from googleapiclient.discovery import build
        service = build("gmail", "v1", credentials=creds)

        try:
            profile = service.users().getProfile(userId="me").execute()
            logger.info("Gmail authenticated", email=profile["emailAddress"])
        except Exception as e:
            logger.warning("Could not fetch Gmail profile", error=str(e))

        processed_label_id = self._get_or_create_label(service)

        while not self._stop_event.is_set():
            try:
                self._poll_once(service, processed_label_id)
            except Exception as e:
                logger.error("Gmail poll error", error=str(e),
                             error_type=type(e).__name__)
            self._stop_event.wait(timeout=settings.gmail_poll_interval)

        logger.info("Gmail poller stopped")

    # ── Auth ───────────────────────────────────────────────────────────────

    def _authenticate(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        settings = self._settings
        creds = None
        if os.path.exists(settings.gmail_token_file):
            creds = Credentials.from_authorized_user_file(
                settings.gmail_token_file, SCOPES
            )
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                # Interactive flow — only works in dev (requires a browser).
                # In Docker: pre-provision token.json via the standalone script.
                flow = InstalledAppFlow.from_client_secrets_file(
                    settings.gmail_credentials_file, SCOPES
                )
                creds = flow.run_local_server(port=0)
            with open(settings.gmail_token_file, "w") as f:
                f.write(creds.to_json())
        return creds

    # ── Gmail helpers ──────────────────────────────────────────────────────

    def _get_or_create_label(self, service) -> str:
        labels = (
            service.users().labels().list(userId="me").execute().get("labels", [])
        )
        for label in labels:
            if label["name"] == PROCESSED_LABEL:
                return label["id"]
        created = service.users().labels().create(
            userId="me",
            body={
                "name": PROCESSED_LABEL,
                "labelListVisibility": "labelHide",
                "messageListVisibility": "hide",
            },
        ).execute()
        return created["id"]

    @staticmethod
    def _get_sender(headers: list) -> str:
        for h in headers:
            if h["name"].lower() == "from":
                raw = h["value"]
                match = re.search(r"<([^>]+)>", raw)
                return match.group(1).strip() if match else raw.strip()
        return "unknown@gmail.com"

    @staticmethod
    def _get_subject(headers: list) -> str:
        for h in headers:
            if h["name"].lower() == "subject":
                return h["value"]
        return "(no subject)"

    @staticmethod
    def _decode_attachment(data: str) -> bytes:
        return base64.urlsafe_b64decode(data + "==")

    def _find_attachments(self, service, message_id: str, payload: dict) -> list[dict]:
        attachments: list[dict] = []

        def walk(part):
            mime = part.get("mimeType", "")
            filename = part.get("filename", "")
            body = part.get("body", {})
            if filename and mime in SUPPORTED_MIME_TYPES:
                if "data" in body:
                    file_bytes = self._decode_attachment(body["data"])
                elif "attachmentId" in body:
                    att = service.users().messages().attachments().get(
                        userId="me", messageId=message_id, id=body["attachmentId"]
                    ).execute()
                    file_bytes = self._decode_attachment(att["data"])
                else:
                    return
                attachments.append({"filename": filename, "mime": mime, "bytes": file_bytes})
            for sub in part.get("parts", []):
                walk(sub)

        walk(payload)
        return attachments

    # ── Poll cycle ─────────────────────────────────────────────────────────

    def _poll_once(self, service, processed_label_id: str) -> None:
        query = f"is:unread has:attachment -label:{PROCESSED_LABEL}"
        result = service.users().messages().list(
            userId="me", q=query, maxResults=10
        ).execute()
        messages = result.get("messages", [])
        if not messages:
            return

        logger.info("Gmail: new emails found", count=len(messages))

        for msg_stub in messages:
            msg_id = msg_stub["id"]
            msg = service.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()
            headers = msg["payload"].get("headers", [])
            sender = self._get_sender(headers)
            subject = self._get_subject(headers)
            attachments = self._find_attachments(service, msg_id, msg["payload"])

            if not attachments:
                service.users().messages().modify(
                    userId="me", id=msg_id,
                    body={"removeLabelIds": ["UNREAD"],
                          "addLabelIds": [processed_label_id]},
                ).execute()
                continue

            logger.info("Gmail: processing email",
                        sender=sender, attachments=len(attachments))

            # Notify the frontend that an email has arrived and is being processed
            event_bus.publish({
                "type": "email_received",
                "sender": sender,
                "subject": subject,
                "attachments": len(attachments),
            })

            for att in attachments:
                self._process_attachment(att, sender)

            service.users().messages().modify(
                userId="me", id=msg_id,
                body={"removeLabelIds": ["UNREAD"],
                      "addLabelIds": [processed_label_id]},
            ).execute()

    def _process_attachment(self, att: dict, sender: str) -> None:
        db = SessionLocal()
        try:
            result = run_pipeline(
                file_bytes=att["bytes"],
                filename=att["filename"],
                content_type=att["mime"],
                sender_email=sender,
                db=db,
            )
            company = (result.get("company") or {}).get("company_name", "Unknown")
            decision = result.get("routing_decision", "UNKNOWN")
            logger.info("Gmail: pipeline complete",
                        company=company, decision=decision, sender=sender)

            # pipeline_complete is already published by run_pipeline() itself

        except Exception as e:
            logger.error("Gmail: pipeline failed",
                         filename=att["filename"], error=str(e))
            event_bus.publish({
                "type": "pipeline_error",
                "filename": att["filename"],
                "sender": sender,
                "error": str(e),
            })
        finally:
            db.close()
