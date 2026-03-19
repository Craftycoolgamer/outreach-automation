"""Google Sheets integration for outreach automation."""

import json
from datetime import datetime
from typing import Optional
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials
from google.auth.transport.requests import Request

from config import (
    GOOGLE_SHEET_ID,
    COLUMN_DATE,
    COLUMN_COMPANY,
    COLUMN_WEBSITE,
    COLUMN_CONTACT,
    COLUMN_METHOD,
    COLUMN_STATUS,
    STATUS_NEW,
    STATUS_READY_TO_SEND,
    STATUS_SENT,
    STATUS_FORM_NEEDED,
    STATUS_MANUAL_SUBMITTED,
    METHOD_EMAIL,
    METHOD_CONTACT_FORM,
    VALID_STATUSES,
    VALID_METHODS,
    BASE_DIR,
)


def _row_has_company_and_website(record: dict) -> bool:
    company = (record.get(COLUMN_COMPANY) or "").strip()
    website = (record.get(COLUMN_WEBSITE) or "").strip()
    return bool(company and website)


class OutreachSheet:
    """Manages the outreach Google Sheet with 5-column format."""

    def __init__(self, credentials_path: Optional[str] = None):
        """Initialize Google Sheets connection.

        Args:
            credentials_path: Path to service account JSON file.
                              If None, looks for 'credentials.json' in project root.
        """
        self.credentials_path = credentials_path or str(BASE_DIR / "credentials.json")
        self.client = self._authenticate()
        self.sheet = self._get_sheet()
        self.worksheet = self.sheet.sheet1
        self._ensure_headers()

    def _authenticate(self) -> gspread.Client:
        """Authenticate with Google Sheets API."""
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]

        if not Path(self.credentials_path).exists():
            raise FileNotFoundError(
                f"Credentials file not found: {self.credentials_path}\n"
                "Please download from Google Cloud Console > IAM & Admin > Service Accounts > Keys"
            )

        credentials = Credentials.from_service_account_file(
            self.credentials_path, scopes=scopes
        )
        return gspread.authorize(credentials)

    def _get_sheet(self) -> gspread.Spreadsheet:
        """Get the spreadsheet by ID."""
        if not GOOGLE_SHEET_ID:
            raise ValueError("GOOGLE_SHEET_ID not set in .env file")
        return self.client.open_by_key(GOOGLE_SHEET_ID)

    def _ensure_headers(self):
        """Ensure the first row has the correct headers."""
        headers = [COLUMN_DATE, COLUMN_COMPANY, COLUMN_WEBSITE, COLUMN_CONTACT, COLUMN_METHOD, COLUMN_STATUS]
        current = self.worksheet.row_values(1)

        if not current or current != headers:
            # Clear first row and set headers
            self.worksheet.update("A1:F1", [headers])
            self.worksheet.format("A1:F1", {
                "textFormat": {"bold": True},
                "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9},
            })

    def get_all_records(self) -> list[dict]:
        """Get all records from the sheet as list of dicts.
        
        Only returns the first 6 columns (A-F) to avoid issues with
        extra columns that may exist in the sheet.
        """
        # Get all values from the sheet
        all_values = self.worksheet.get_all_values()
        
        if not all_values or len(all_values) < 1:
            return []
        
        # Headers are in the first row
        headers = all_values[0][:6]  # Only take first 6 columns
        
        # Convert rows to dicts, only using first 6 columns
        records = []
        for row in all_values[1:]:  # Skip header row
            # Pad row with empty strings if it's shorter than 6 columns
            row_values = (row + [""] * 6)[:6]
            record = {headers[i]: row_values[i] for i in range(len(headers))}
            records.append(record)
        
        return records

    def get_rows_by_status(self, status: str) -> list[dict]:
        """Get all rows with a specific status."""
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}. Valid: {VALID_STATUSES}")

        records = self.get_all_records()
        return [r for r in records if r.get(COLUMN_STATUS, "").lower() == status.lower()]

    def add_company(self, company: str, website: Optional[str] = None) -> int:
        """Add a new company to research.

        Args:
            company: Company name
            website: Company website URL

        Returns:
            Row number of the newly added company
        """
        today = datetime.now().strftime("%Y-%m-%d")
        row_data = [today, company, website or "", "", "", STATUS_NEW]

        next_row = len(self.worksheet.get_all_records()) + 2  # +2 for header and 0-index
        range_name = f"A{next_row}:F{next_row}"
        self.worksheet.update(range_name, [row_data])

        return next_row

    def update_row(self, row_index: int, contact: str, method: str, status: str):
        """Update a row with research results.

        Args:
            row_index: 1-based row index (header is row 1)
            contact: Email address or contact form URL
            method: 'email', 'contact_form', or 'manual'
            status: Current status of the outreach
        """
        if method not in VALID_METHODS:
            raise ValueError(f"Invalid method: {method}. Valid: {VALID_METHODS}")
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}. Valid: {VALID_STATUSES}")

        # Update contact (column D), method (column E), status (column F)
        self.worksheet.update(f"D{row_index}:F{row_index}", [[contact, method, status]])

    def update_status(self, row_index: int, status: str):
        """Update just the status column."""
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}. Valid: {VALID_STATUSES}")
        self.worksheet.update_cell(row_index, 6, status)  # Column F = 6

    def update_contact(self, row_index: int, contact: str):
        """Update just the contact column."""
        self.worksheet.update_cell(row_index, 4, contact)  # Column D = 4

    def mark_sent(self, row_index: int, email_address: str):
        """Mark a row as email sent."""
        today = datetime.now().strftime("%Y-%m-%d")
        # Only update the columns we actually intend to change.
        # Updating the full A:F range would overwrite company/website with None.
        self.worksheet.update_cell(row_index, 1, today)  # Column A (date)
        self.worksheet.update(
            f"D{row_index}:F{row_index}",
            [[email_address, METHOD_EMAIL, STATUS_SENT]],  # Columns D-F (contact/method/status)
        )

    def mark_manual_submitted(self, row_index: int, form_url: str):
        """Mark a row as manually submitted via contact form."""
        today = datetime.now().strftime("%Y-%m-%d")
        # Only update the columns we actually intend to change.
        # Updating the full A:F range would overwrite company/website with None.
        self.worksheet.update_cell(row_index, 1, today)  # Column A (date)
        self.worksheet.update(
            f"D{row_index}:F{row_index}",
            [[form_url, METHOD_CONTACT_FORM, STATUS_MANUAL_SUBMITTED]],  # Columns D-F (contact/method/status)
        )

    def get_pending_research(self) -> list[tuple[int, dict]]:
        """Get all rows needing research with their row indices.

        Returns:
            List of tuples (row_index, row_data)
        """
        records = self.get_all_records()
        pending = []

        for idx, record in enumerate(records, start=2):  # start=2 because row 1 is header
            status = record.get(COLUMN_STATUS, "")
            if status in [STATUS_NEW, ""] and _row_has_company_and_website(record):
                pending.append((idx, record))

        return pending

    def get_ready_to_send(self) -> list[tuple[int, dict]]:
        """Get all rows ready to send with their row indices."""
        records = self.get_all_records()
        ready = []

        for idx, record in enumerate(records, start=2):
            status = record.get(COLUMN_STATUS, "")
            method = record.get(COLUMN_METHOD, "")
            if status == STATUS_READY_TO_SEND and method == METHOD_EMAIL:
                ready.append((idx, record))

        return ready

    def get_needs_manual_submission(self) -> list[tuple[int, dict]]:
        """Get all rows needing manual contact form submission."""
        records = self.get_all_records()
        needs_manual = []

        for idx, record in enumerate(records, start=2):
            status = record.get(COLUMN_STATUS, "")
            method = record.get(COLUMN_METHOD, "")
            if status == STATUS_FORM_NEEDED and method == METHOD_CONTACT_FORM:
                needs_manual.append((idx, record))

        return needs_manual
