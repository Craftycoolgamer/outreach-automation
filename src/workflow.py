"""Main workflow orchestrator for outreach automation."""

import argparse
import sys
from datetime import datetime
from typing import Optional

from config import (
    STATUS_NEW,
    STATUS_RESEARCHED,
    STATUS_READY_TO_SEND,
    STATUS_SENT,
    STATUS_FORM_NEEDED,
    STATUS_MANUAL_SUBMITTED,
    STATUS_SKIPPED,
    STATUS_FAILED,
    METHOD_EMAIL,
    METHOD_CONTACT_FORM,
    METHOD_MANUAL,
    DAILY_EMAIL_LIMIT,
    COLUMN_COMPANY,
    COLUMN_WEBSITE,
    COLUMN_CONTACT,
    COLUMN_STATUS,
    SENDER_NAME,
    SENDER_TITLE,
    SENDER_COMPANY,
    SENDER_PHONE,
)
from sheets import OutreachSheet
from scraper import CompanyResearcher, format_research_result
from email_client import SmtpOutreach, EmailPreview


class OutreachWorkflow:
    """Human-in-the-loop outreach workflow."""

    def __init__(self, dry_run: bool = False):
        """Initialize workflow components.

        Args:
            dry_run: If True, don't actually send emails or update sheets
        """
        self.dry_run = dry_run
        self.sheet = OutreachSheet()
        self.researcher = CompanyResearcher()
        self.preview = EmailPreview()
        self.email_client: Optional[SmtpOutreach] = None

        if not dry_run:
            try:
                self.email_client = SmtpOutreach()
            except ValueError as e:
                print(f"Warning: Email not configured. {e}")
                print("To enable: Add EMAIL_USER, EMAIL_PASSWORD, and SMTP_SERVER to .env")

    def research_pending(self, auto_approve: bool = False):
        """Research all companies with 'new' status.

        Args:
            auto_approve: If True, mark emails as ready_to_send without review
                         (not recommended for production)
        """
        pending = self.sheet.get_pending_research()

        if not pending:
            print("No companies pending research.")
            return

        print(f"Found {len(pending)} companies to research\n")

        for row_idx, row in pending:
            company = row.get(COLUMN_COMPANY, "")
            website = row.get(COLUMN_WEBSITE, "")

            if not website:
                print(f"[{company}] No website provided, skipping")
                self.sheet.update_row(row_idx, "no_website", METHOD_MANUAL, STATUS_SKIPPED)
                continue

            print(f"\n{'=' * 60}")
            print(f"Researching: {company}")
            print(f"Website: {website}")
            print(f"{'=' * 60}")

            # Research the company
            result = self.researcher.research_company(company, website)
            print(format_research_result(result))

            # Determine next action
            if result["best_email"]:
                print(f"\n>>> Found email: {result['best_email']}")

                if auto_approve:
                    self._update_for_email(row_idx, result["best_email"], auto_send=False)
                else:
                    self._interactive_email_decision(row_idx, company, result)

            elif result["best_form"]:
                print(f"\n>>> No email found, but contact form available: {result['best_form']}")
                self._interactive_form_decision(row_idx, company, result)

            else:
                print(f"\n>>> No contact method found")
                self.sheet.update_row(
                    row_idx,
                    "none_found",
                    METHOD_MANUAL,
                    STATUS_FAILED
                )
                print(f"Marked as failed - no contact found")

    def _interactive_email_decision(self, row_idx: int, company: str, result: dict):
        """Interactive prompt for email outreach decision."""
        email = result["best_email"]

        # Generate preview with sender information
        preview = self.preview.generate_preview(
            company,
            email,
            sender_name=SENDER_NAME,
            sender_title=SENDER_TITLE,
            sender_company=SENDER_COMPANY,
            sender_phone=SENDER_PHONE,
        )
        print("\n" + preview["preview"])

        print("\nOptions:")
        print("  [s] Send now (requires SMTP config)")
        print("  [r] Mark as ready to send (review later) ← Recommended")
        print("  [f] Use contact form instead")
        print("  [x] Skip this company")

        choice = input("\nChoice [r]: ").strip().lower() or "r"

        if choice == "s":
            self._update_for_email(row_idx, email, auto_send=True)
        elif choice == "r":
            self._update_for_email(row_idx, email, auto_send=False)
        elif choice == "f":
            if result["best_form"]:
                self.sheet.update_row(row_idx, result["best_form"], METHOD_CONTACT_FORM, STATUS_FORM_NEEDED)
                print(f"Saved contact form for manual submission: {result['best_form']}")
            else:
                print("No contact form available, marking as failed")
                self.sheet.update_row(row_idx, "no_form", METHOD_MANUAL, STATUS_FAILED)
        else:
            self.sheet.update_row(row_idx, email, METHOD_EMAIL, STATUS_SKIPPED)
            print("Skipped")

    def _interactive_form_decision(self, row_idx: int, company: str, result: dict):
        """Interactive prompt for contact form decision."""
        form_url = result["best_form"]

        print(f"\nContact form URL: {form_url}")
        print("\nOptions:")
        print("  [y] Mark for manual submission (you'll do this later)")
        print("  [x] Skip this company")

        choice = input("\nChoice [y]: ").strip().lower() or "y"

        if choice == "y":
            self.sheet.update_row(row_idx, form_url, METHOD_CONTACT_FORM, STATUS_FORM_NEEDED)
            print(f"Saved for manual submission")
        else:
            self.sheet.update_row(row_idx, form_url, METHOD_CONTACT_FORM, STATUS_SKIPPED)
            print("Skipped")

    def _update_for_email(self, row_idx: int, email: str, auto_send: bool = False):
        """Update sheet for email outreach."""
        if auto_send and self.email_client and not self.dry_run:
            # Send immediately
            row = self.sheet.worksheet.row_values(row_idx)
            company = row[1]  # Column B

            result = self.email_client.send_email(
                email,
                company,
                sender_name=SENDER_NAME,
                sender_title=SENDER_TITLE,
                sender_company=SENDER_COMPANY,
                sender_phone=SENDER_PHONE,
            )

            if result["success"]:
                self.sheet.mark_sent(row_idx, email)
                print(f"Email sent successfully!")
            else:
                self.sheet.update_row(row_idx, email, METHOD_EMAIL, STATUS_FAILED)
                print(f"Failed to send: {result['error']}")
        else:
            # Mark for later review
            self.sheet.update_row(row_idx, email, METHOD_EMAIL, STATUS_READY_TO_SEND)
            print(f"Marked as ready to send to: {email}")

    def _save_draft_local(self, row_idx: int, company: str, email: str):
        """Save email draft locally for review."""
        preview = self.preview.generate_preview(company, email)
        draft_file = f"draft_{company.replace(' ', '_').lower()}.txt"

        with open(draft_file, "w") as f:
            f.write(preview["preview"])

        self.sheet.update_row(row_idx, email, METHOD_EMAIL, STATUS_READY_TO_SEND)
        print(f"Draft saved to: {draft_file}")
        print("Review the file, then run 'python workflow.py --send' to send")

    def send_approved_emails(self, limit: int = DAILY_EMAIL_LIMIT):
        """Send all emails marked as 'ready_to_send'."""
        ready = self.sheet.get_ready_to_send()

        if not ready:
            print("No emails ready to send.")
            return

        if not self.email_client and not self.dry_run:
            print("Email not configured. Cannot send emails.")
            print("Check your EMAIL_USER, EMAIL_PASSWORD, and SMTP_SERVER in .env")
            return

        print(f"Found {len(ready)} email(s) ready to send (limit: {limit})\n")

        sent_count = 0
        for row_idx, row in ready[:limit]:
            if sent_count >= limit:
                print(f"\nReached daily limit ({limit}). Stopping.")
                break

            company = row.get(COLUMN_COMPANY, "")
            email = row.get(COLUMN_CONTACT, "")

            print(f"Sending to {company} at {email}...")

            if self.dry_run:
                print("  [DRY RUN] Would send email")
                sent_count += 1
                continue

            result = self.email_client.send_email(
                email,
                company,
                sender_name=SENDER_NAME,
                sender_title=SENDER_TITLE,
                sender_company=SENDER_COMPANY,
                sender_phone=SENDER_PHONE,
            )

            if result["success"]:
                self.sheet.mark_sent(row_idx, email)
                print(f"  Sent!")
                sent_count += 1
            else:
                print(f"  Failed: {result['error']}")
                self.sheet.update_status(row_idx, STATUS_FAILED)

        print(f"\nSent {sent_count} emails")

    def show_manual_submissions(self):
        """Show all companies needing manual contact form submission."""
        needs_manual = self.sheet.get_needs_manual_submission()

        if not needs_manual:
            print("No companies need manual submission.")
            return

        print(f"\n{'=' * 70}")
        print(f"COMPANIES NEEDING MANUAL CONTACT FORM SUBMISSION ({len(needs_manual)})")
        print(f"{'=' * 70}\n")

        for row_idx, row in needs_manual:
            company = row.get(COLUMN_COMPANY, "")
            form_url = row.get(COLUMN_CONTACT, "")

            print(f"Row {row_idx}: {company}")
            print(f"  Form URL: {form_url}")
            print()

        print("After submitting forms, update sheet status to 'manual_submitted'")
        print("Or run: python workflow.py --mark-submitted <row_number>")

    def mark_submitted(self, row_number: int):
        """Mark a row as manually submitted via contact form."""
        if self.dry_run:
            print(f"[DRY RUN] Would mark row {row_number} as submitted")
            return

        row = self.sheet.worksheet.row_values(row_number)
        if len(row) < 3:
            print(f"Row {row_number} not found or invalid")
            return

        company = row[1]
        form_url = row[2]

        self.sheet.mark_manual_submitted(row_number, form_url)
        print(f"Marked row {row_number} ({company}) as manually submitted")

    def add_company(self, company: str, website: str):
        """Add a new company to the research queue."""
        row = self.sheet.add_company(company, website)
        print(f"Added '{company}' to row {row}")
        print(f"Run 'python workflow.py --research' to process")

    def show_status(self):
        """Show current status summary."""
        records = self.sheet.get_all_records()

        counts = {
            STATUS_NEW: 0,
            STATUS_RESEARCHED: 0,
            STATUS_READY_TO_SEND: 0,
            STATUS_SENT: 0,
            STATUS_FORM_NEEDED: 0,
            STATUS_MANUAL_SUBMITTED: 0,
            STATUS_SKIPPED: 0,
            STATUS_FAILED: 0,
            "other": 0,
        }

        for record in records:
            status = record.get(COLUMN_STATUS, "")
            if status in counts:
                counts[status] += 1
            else:
                counts["other"] += 1

        print(f"\n{'=' * 50}")
        print("OUTREACH STATUS SUMMARY")
        print(f"{'=' * 50}")
        print(f"New (pending research):        {counts[STATUS_NEW]:>4}")
        print(f"Researched:                      {counts[STATUS_RESEARCHED]:>4}")
        print(f"Ready to send:                   {counts[STATUS_READY_TO_SEND]:>4}")
        print(f"Sent:                            {counts[STATUS_SENT]:>4}")
        print(f"Needs manual form submission:    {counts[STATUS_FORM_NEEDED]:>4}")
        print(f"Manual submitted:                {counts[STATUS_MANUAL_SUBMITTED]:>4}")
        print(f"Skipped:                         {counts[STATUS_SKIPPED]:>4}")
        print(f"Failed:                          {counts[STATUS_FAILED]:>4}")
        print(f"{'=' * 50}")
        print(f"Total:                           {len(records):>4}")


def main():
    parser = argparse.ArgumentParser(
        description="Human-in-the-loop outreach automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python workflow.py --research              # Research all pending companies
  python workflow.py --research --auto       # Auto-approve findings
  python workflow.py --send                  # Send approved emails
  python workflow.py --status                # Show status summary
  python workflow.py --manual-forms          # Show forms needing submission
  python workflow.py --add "Acme Inc" "https://acme.com"
  python workflow.py --mark-submitted 5      # Mark row 5 as submitted
        """
    )

    parser.add_argument("--research", action="store_true",
                        help="Research all companies with 'new' status")
    parser.add_argument("--auto", action="store_true",
                        help="Auto-approve research findings (use with --research)")
    parser.add_argument("--send", action="store_true",
                        help="Send all emails marked 'ready_to_send'")
    parser.add_argument("--status", action="store_true",
                        help="Show status summary")
    parser.add_argument("--manual-forms", action="store_true",
                        help="Show companies needing manual form submission")
    parser.add_argument("--add", nargs=2, metavar=("COMPANY", "WEBSITE"),
                        help="Add a new company to research")
    parser.add_argument("--mark-submitted", type=int, metavar="ROW",
                        help="Mark a row as manually submitted")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't actually send emails or update sheets")
    parser.add_argument("--limit", type=int, default=DAILY_EMAIL_LIMIT,
                        help=f"Email send limit (default: {DAILY_EMAIL_LIMIT})")

    args = parser.parse_args()

    if len(sys.argv) == 1:
        parser.print_help()
        return

    workflow = OutreachWorkflow(dry_run=args.dry_run)

    if args.research:
        workflow.research_pending(auto_approve=args.auto)

    if args.send:
        workflow.send_approved_emails(limit=args.limit)

    if args.status:
        workflow.show_status()

    if args.manual_forms:
        workflow.show_manual_submissions()

    if args.add:
        workflow.add_company(args.add[0], args.add[1])

    if args.mark_submitted:
        workflow.mark_submitted(args.mark_submitted)


if __name__ == "__main__":
    main()
