"""Main workflow orchestrator for outreach automation."""

import argparse
import re
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
    METHOD_MISSING,
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
from template_store import TemplateRecord


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

    def research_pending(self, auto_approve: bool = False, limit: Optional[int] = None):
        """Research all companies with 'new' status.

        Args:
            auto_approve: If True, mark emails as ready_to_send without review
                         (not recommended for production)
            limit: Maximum number of companies to process. If None, process all.
        """
        pending = self.sheet.get_pending_research()

        if not pending:
            print("No companies pending research.")
            return

        total_pending = len(pending)
        if limit is not None:
            pending = pending[:limit]

        print(f"Found {total_pending} companies to research")
        if limit is not None:
            print(f"Processing {len(pending)} compan{'ies' if len(pending) != 1 else 'y'}\n")
        else:
            print()

        for row_idx, row in pending:
            company = row.get(COLUMN_COMPANY, "")
            website = row.get(COLUMN_WEBSITE, "")

            if not website:
                print(f"[{company}] No website provided, skipping")
                self.sheet.update_row(row_idx, "no_website", METHOD_MANUAL, STATUS_SKIPPED)
                continue

            if not auto_approve:
                print(f"\n{'=' * 60}")
                print(f"Researching: {company}")
                print(f"Website: {website}")
                print(f"{'=' * 60}")

            # Research the company
            result = self.researcher.research_company(company, website)
            if not auto_approve:
                print(format_research_result(result))

            # Determine next action
            if result["best_email"]:
                if not auto_approve:
                    print(f"\n>>> Found email: {result['best_email']}")

                if auto_approve:
                    self._update_for_email(row_idx, result["best_email"], auto_send=False)
                else:
                    self._interactive_email_decision(row_idx, company, result)

            elif result["best_form"]:
                if not auto_approve:
                    print(f"\n>>> No email found, but contact form available: {result['best_form']}")
                self._interactive_form_decision(row_idx, company, result)

            else:
                if not auto_approve:
                    print(f"\n>>> No contact method found")
                self.sheet.update_row(
                    row_idx,
                    "None Found",
                    METHOD_MISSING,
                    STATUS_FAILED
                )
                if not auto_approve:
                    print(f"Marked as failed - no contact found")

    def _interactive_email_decision(self, row_idx: int, company: str, result: dict):
        """Interactive prompt for email outreach decision."""
        email = result["best_email"]

        # Use a deterministic preview template in this menu.
        template_id = self.preview.templates[0].id if self.preview.templates else None
        preview = self.preview.generate_preview(
            company,
            email,
            template_number=template_id,
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
            self._send_email_interactive(row_idx=row_idx, company=company, email=email)
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
        if auto_send:
            row = self.sheet.worksheet.row_values(row_idx)
            company = row[1] if len(row) > 1 else ""
            self._send_email_interactive(row_idx=row_idx, company=company, email=email)
        else:
            # Mark for later review
            self.sheet.update_row(row_idx, email, METHOD_EMAIL, STATUS_READY_TO_SEND)
            print(f"{self.sheet.worksheet.row_values(row_idx)[1]} - Marked as ready to send to: {email}")

    def _build_template_vars(self, company: str) -> dict:
        """Build template vars using configured defaults and company context."""
        return {
            "company_name": company,
            "sender_name": SENDER_NAME or "",
            "sender_title": SENDER_TITLE or "",
            "sender_company": SENDER_COMPANY or "",
            "sender_phone": SENDER_PHONE or "",
        }

    def _extract_placeholders(self, template: TemplateRecord) -> set[str]:
        """Extract placeholder names from subject/text/html template content."""
        pattern = r"\{\{([a-zA-Z0-9_]+)\}\}"
        content = f"{template.subject}\n{template.text_body}\n{template.html_body}"
        return set(re.findall(pattern, content))

    def _choose_template_interactive(self) -> Optional[TemplateRecord]:
        """Prompt user to select a template from available templates."""
        templates = self.preview.templates
        if not templates:
            print("No templates available.")
            return None

        while True:
            print("\nChoose template to send:")
            for index, template in enumerate(templates, start=1):
                print(f"  [{index}] {template.name}")
            print("  [x] Cancel send")

            choice = input("\nTemplate [1]: ").strip().lower() or "1"
            if choice == "x":
                return None
            if choice.isdigit():
                selected_index = int(choice)
                if 1 <= selected_index <= len(templates):
                    return templates[selected_index - 1]
            print("Invalid selection. Please choose a valid template number.")

    def _collect_required_template_vars(self, template: TemplateRecord, company: str) -> dict:
        """Prompt until all placeholders required by the selected template are set."""
        template_vars = self._build_template_vars(company)
        required_placeholders = self._extract_placeholders(template)

        # company_name is always set from sheet context.
        required_placeholders.discard("company_name")

        while True:
            missing = [
                name for name in sorted(required_placeholders)
                if not str(template_vars.get(name, "")).strip()
            ]
            if not missing:
                return template_vars

            print("\nMissing template parameters:")
            for name in missing:
                value = input(f"  Enter value for {name}: ").strip()
                if value:
                    template_vars[name] = value

            remaining = [
                name for name in sorted(required_placeholders)
                if not str(template_vars.get(name, "")).strip()
            ]
            if remaining:
                print("Some required parameters are still missing. Please provide them before sending.")

    def _prompt_template_for_send(self, company: str, email: str) -> tuple[Optional[TemplateRecord], Optional[dict]]:
        """Select a template and gather required variables with confirmation."""
        while True:
            selected_template = self._choose_template_interactive()
            if selected_template is None:
                return None, None

            template_vars = self._collect_required_template_vars(selected_template, company)
            print("\n\ntemplate_vars:", template_vars, "\n\n")
            template_vars.pop("company_name", None)
            template_vars.pop("to_email", None)
            preview = self.preview.generate_preview(
                company,
                email,
                template_number=selected_template.id,
                **template_vars,
            )

            print("\n" + preview["preview"])
            confirm = input("Send with this template? [y/n]: ").strip().lower() or "y"
            if confirm == "y":
                return selected_template, template_vars

            print("Let's choose again.")

    def _send_email_interactive(self, row_idx: int, company: str, email: str):
        """Send one email after explicit template selection and var validation."""
        if not self.email_client or self.dry_run:
            self.sheet.update_row(row_idx, email, METHOD_EMAIL, STATUS_READY_TO_SEND)
            print("Email sending is disabled. Marked as ready to send.")
            return

        selected_template, template_vars = self._prompt_template_for_send(company, email)
        if selected_template is None:
            self.sheet.update_row(row_idx, email, METHOD_EMAIL, STATUS_READY_TO_SEND)
            print("Send cancelled. Marked as ready to send.")
            return

        result = self.email_client.send_email(
            email,
            company,
            template=selected_template,
            **template_vars,
        )

        if result["success"]:
            self.sheet.mark_sent(row_idx, email)
            print("Email sent successfully!")
        else:
            self.sheet.update_row(row_idx, email, METHOD_EMAIL, STATUS_FAILED)
            print(f"Failed to send: {result['error']}")

    def _save_draft_local(self, row_idx: int, company: str, email: str):
        """Save email draft locally for review."""
        preview = self.preview.generate_preview(company, email)
        draft_file = f"draft_{company.replace(' ', '_').lower()}.txt"

        with open(draft_file, "w") as f:
            f.write(preview["preview"])

        self.sheet.update_row(row_idx, email, METHOD_EMAIL, STATUS_READY_TO_SEND)
        print(f"Draft saved to: {draft_file}")
        print("Review the file, then run 'python workflow.py --send' to send")

    def display_ready_to_send(self, limit: int = DAILY_EMAIL_LIMIT):
        """Display all emails ready to send for confirmation."""
        ready = self.sheet.get_ready_to_send()

        if not ready:
            print("No emails ready to send.")
            return False

        ready_to_display = ready[:limit]
        print(f"\n{'=' * 80}")
        print(f"READY TO SEND ({len(ready_to_display)} email{'s' if len(ready_to_display) != 1 else ''})")
        print(f"{'=' * 80}\n")

        print(f"{'Company':<40} | {'Email Address':<35}")
        print(f"{'-' * 40}-+-{'-' * 35}")

        for row_idx, row in ready_to_display:
            company = row.get(COLUMN_COMPANY, "")[:40]
            email = row.get(COLUMN_CONTACT, "")[:35]
            print(f"{company:<40} | {email:<35}")

        print(f"\n{'=' * 80}")
        return True

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

        selected_template: Optional[TemplateRecord] = None
        template_vars: dict = {}
        if not self.dry_run:
            first_company = ready[0][1].get(COLUMN_COMPANY, "")
            first_email = ready[0][1].get(COLUMN_CONTACT, "")
            selected_template, template_vars = self._prompt_template_for_send(
                first_company,
                first_email,
            )
            if selected_template is None:
                print("Cancelled batch send.")
                return

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
                template=selected_template,
                **template_vars,
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
        }

        unrecognized = {}
        for record in records:
            status = record.get(COLUMN_STATUS, "").strip()
            if status in counts:
                counts[status] += 1
            elif status:
                unrecognized[status] = unrecognized.get(status, 0) + 1

        print(f"\n{'=' * 50}")
        print("OUTREACH STATUS SUMMARY")
        print(f"{'=' * 50}")
        print(f"New (pending research):          {counts[STATUS_NEW]:>4}")
        print(f"Researched:                      {counts[STATUS_RESEARCHED]:>4}")
        print(f"Ready to send:                   {counts[STATUS_READY_TO_SEND]:>4}")
        print(f"Sent:                            {counts[STATUS_SENT]:>4}")
        print(f"Needs manual form submission:    {counts[STATUS_FORM_NEEDED]:>4}")
        print(f"Manual submitted:                {counts[STATUS_MANUAL_SUBMITTED]:>4}")
        print(f"Skipped:                         {counts[STATUS_SKIPPED]:>4}")
        print(f"Failed:                          {counts[STATUS_FAILED]:>4}")
        print(f"{'=' * 50}")
        print(f"Total:                           {len(records):>4}")
        
        if unrecognized:
            print(f"\nUnrecognized statuses:")
            for status, count in sorted(unrecognized.items()):
                print(f"  {status}: {count}")


def main():
    parser = argparse.ArgumentParser(
        description="Human-in-the-loop outreach automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python workflow.py --research              # Research all pending companies
  python workflow.py --research-one          # Research only one pending company
  python workflow.py --research --auto       # Auto-approve findings + batch confirm before sending
  python workflow.py --send                  # Send approved emails
  python workflow.py --status                # Show status summary
  python workflow.py --manual-forms          # Show forms needing submission
  python workflow.py --add "Acme Inc" "https://acme.com"
  python workflow.py --mark-submitted 5      # Mark row 5 as submitted
        """
    )

    parser.add_argument("--research", action="store_true",
                        help="Research all companies with 'new' status")
    parser.add_argument("--research-one", action="store_true",
                        help="Research only the next company with 'new' status")
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

    if args.research and args.research_one:
        print("Use either --research or --research-one, not both.")
        return

    if args.research and args.auto:
        workflow.research_pending(auto_approve=True)
        if workflow.display_ready_to_send(limit=args.limit):
            confirm = input("\nConfirm sending these emails? (y/n): ").strip().lower()
            if confirm == "y":
                workflow.send_approved_emails(limit=args.limit)
            else:
                print("Cancelled. Emails marked as ready but not sent.")
    elif args.research_one and args.auto:
        workflow.research_pending(auto_approve=True, limit=1)
        if workflow.display_ready_to_send(limit=args.limit):
            confirm = input("\nConfirm sending these emails? (y/n): ").strip().lower()
            if confirm == "y":
                workflow.send_approved_emails(limit=args.limit)
            else:
                print("Cancelled. Emails marked as ready but not sent.")
    elif args.research:
        workflow.research_pending(auto_approve=False)
    elif args.research_one:
        workflow.research_pending(auto_approve=False, limit=1)

    if args.send and not (args.research and args.auto):
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
