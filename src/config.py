"""Configuration management for outreach automation."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.parent

# Google Sheets
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")

# Email Configuration (SMTP)
EMAIL_USER = os.getenv("EMAIL_USER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
SMTP_SERVER = os.getenv("SMTP_SERVER", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

# Sender Information (for email templates)
SENDER_NAME = os.getenv("SENDER_NAME")
SENDER_TITLE = os.getenv("SENDER_TITLE")
SENDER_COMPANY = os.getenv("SENDER_COMPANY")
SENDER_PHONE = os.getenv("SENDER_PHONE")

# Template directory
TEMPLATE_DIR = BASE_DIR / "templates"

# Outreach limits
DAILY_EMAIL_LIMIT = int(os.getenv("DAILY_EMAIL_LIMIT", "50"))

# Email templates (randomly selected when sending)
EMAIL_TEMPLATES = sorted(
    str(p) for p in TEMPLATE_DIR.glob("*template*.txt")
)

# Scraping
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "10"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Sheet column names (6-column format)
COLUMN_DATE = "date"
COLUMN_COMPANY = "company"
COLUMN_WEBSITE = "website"
COLUMN_CONTACT = "contact"
COLUMN_METHOD = "method"
COLUMN_STATUS = "status"

# Status values
STATUS_NEW = "New"
STATUS_RESEARCHED = "Researched"
STATUS_READY_TO_SEND = "Ready"
STATUS_SENT = "Email Sent"
STATUS_FORM_NEEDED = "Forum"
STATUS_MANUAL_SUBMITTED = "Manual"
STATUS_SKIPPED = "Skipped"
STATUS_FAILED = "Failed"

# Method values
METHOD_EMAIL = "Email"
METHOD_CONTACT_FORM = "Forum"
METHOD_MANUAL = "Manual"

# Valid status transitions
VALID_STATUSES = [
    STATUS_NEW,
    STATUS_RESEARCHED,
    STATUS_READY_TO_SEND,
    STATUS_SENT,
    STATUS_FORM_NEEDED,
    STATUS_MANUAL_SUBMITTED,
    STATUS_SKIPPED,
    STATUS_FAILED,
]

VALID_METHODS = [
    METHOD_EMAIL,
    METHOD_CONTACT_FORM,
    METHOD_MANUAL,
]
