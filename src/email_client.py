"""SMTP email client for sending outreach emails."""

import random
import smtplib
import ssl
from dataclasses import dataclass
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from html import escape

from config import (
    EMAIL_USER,
    EMAIL_PASSWORD,
    SMTP_SERVER,
    SMTP_PORT,
)
from template_store import TemplateRecord, TemplateStore


@dataclass(frozen=True)
class RenderedTemplate:
    """Rendered template bodies ready for transport or preview."""

    template: TemplateRecord
    subject: str
    text_body: str
    html_body: str


class SmtpOutreach:
    """Sends outreach emails via SMTP with random template selection."""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize SMTP client.

        Args:
            db_path: Optional path to the SQLite application database.
        """
        self.template_store = TemplateStore(db_path)
        self.templates = self._load_templates()
        self._validate_config()

    def _validate_config(self):
        """Validate that required SMTP settings are present."""
        missing = []
        if not EMAIL_USER:
            missing.append("EMAIL_USER")
        if not EMAIL_PASSWORD:
            missing.append("EMAIL_PASSWORD")
        if not SMTP_SERVER:
            missing.append("SMTP_SERVER")

        if missing:
            raise ValueError(
                f"Missing required email configuration: {', '.join(missing)}. "
                "Please check your .env file."
            )

    def _load_templates(self) -> list[TemplateRecord]:
        """Load all email templates from the SQLite application store."""
        return self.template_store.load_templates()

    def _get_random_template(self) -> TemplateRecord:
        """Randomly select a template from available templates."""
        return random.choice(self.templates)

    def _render_template(
        self,
        template: TemplateRecord,
        company_name: str,
        **template_vars,
    ) -> RenderedTemplate:
        """Render the selected template with placeholder substitution."""
        defaults = {
            "company_name": company_name,
            "sender_name": template_vars.get("sender_name", "Your Name"),
            "sender_title": template_vars.get("sender_title", "Your Title"),
            "sender_company": template_vars.get("sender_company", "Your Company"),
            "sender_phone": template_vars.get("sender_phone", ""),
            "industry": template_vars.get("industry", "your industry"),
        }
        defaults.update(template_vars)

        subject = template.subject
        text_body = template.text_body
        html_body = template.html_body

        for key, value in defaults.items():
            placeholder = f"{{{{{key}}}}}"
            replacement = str(value)
            subject = subject.replace(placeholder, replacement)
            text_body = text_body.replace(placeholder, replacement)
            html_body = html_body.replace(placeholder, replacement)

        return RenderedTemplate(
            template=template,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
        )

    def _plain_to_html(self, body: str) -> str:
        """Create a basic HTML fallback from plain text."""
        escaped_body = escape(body).replace("\n", "<br>\n")
        return f"<html><body><p>{escaped_body}</p></body></html>"

    def _prepare_message(
        self,
        to_email: str,
        company_name: str,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        html_body: Optional[str] = None,
        template: Optional[TemplateRecord] = None,
        **template_vars,
    ) -> MIMEMultipart:
        """Prepare email message with template substitution."""
        rendered_template = None
        if subject is None or body is None or html_body is None:
            selected_template = template or self._get_random_template()
            rendered_template = self._render_template(
                selected_template,
                company_name,
                **template_vars,
            )
            subject = subject or rendered_template.subject
            body = body or rendered_template.text_body
            html_body = html_body or rendered_template.html_body

        if html_body is None:
            html_body = self._plain_to_html(body)

        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = EMAIL_USER
        message["To"] = to_email

        message.attach(MIMEText(body, "plain"))
        message.attach(MIMEText(html_body, "html"))

        return message

    def send_email(
        self,
        to_email: str,
        company_name: str,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        html_body: Optional[str] = None,
        template: Optional[TemplateRecord] = None,
        **template_vars,
    ) -> dict:
        """Send an outreach email via SMTP.

        Args:
            to_email: Recipient email address
            company_name: Name of the company (for logging)
            subject: Email subject (uses template if not provided)
            body: Email body (uses template if not provided)
            template: Specific template to use (randomly selects if not provided)
            **template_vars: Variables to substitute in template

        Returns:
            Dict with success status and template used
        """
        # Select template if not provided
        selected_template = template or self._get_random_template()
        
        message = self._prepare_message(
            to_email,
            company_name,
            subject,
            body,
            html_body,
            selected_template,
            **template_vars,
        )

        try:
            context = ssl.create_default_context()

            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls(context=context)
                server.login(EMAIL_USER, EMAIL_PASSWORD)
                server.sendmail(EMAIL_USER, to_email, message.as_string())

            return {
                "success": True,
                "to": to_email,
                "company": company_name,
                "from": EMAIL_USER,
                "template_used": selected_template.id,
            }

        except smtplib.SMTPAuthenticationError as e:
            return {
                "success": False,
                "error": f"Authentication failed: {str(e)}. "
                         "Check your EMAIL_USER and EMAIL_PASSWORD in .env",
                "to": to_email,
                "company": company_name,
            }
        except smtplib.SMTPConnectError as e:
            return {
                "success": False,
                "error": f"Could not connect to SMTP server: {str(e)}. "
                         "Check your SMTP_SERVER and SMTP_PORT in .env",
                "to": to_email,
                "company": company_name,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "to": to_email,
                "company": company_name,
            }

    def send_emails_batch(
        self,
        recipients: list[dict],
        limit: int = 50,
    ) -> list[dict]:
        """Send multiple emails in a single SMTP connection.

        Args:
            recipients: List of dicts with 'email', 'company_name', and optional template vars
            limit: Maximum number of emails to send

        Returns:
            List of result dicts for each email
        """
        results = []
        context = ssl.create_default_context()

        try:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls(context=context)
                server.login(EMAIL_USER, EMAIL_PASSWORD)

                for i, recipient in enumerate(recipients):
                    if i >= limit:
                        break

                    to_email = recipient["email"]
                    company_name = recipient["company_name"]
                    # Randomly select template for each email
                    selected_template = self._get_random_template()

                    message = self._prepare_message(
                        to_email,
                        company_name,
                        recipient.get("subject"),
                        recipient.get("body"),
                        recipient.get("html_body"),
                        selected_template,
                        **recipient.get("template_vars", {}),
                    )

                    try:
                        server.sendmail(EMAIL_USER, to_email, message.as_string())
                        results.append({
                            "success": True,
                            "to": to_email,
                            "company": company_name,
                            "template_used": selected_template.id,
                        })
                    except Exception as e:
                        results.append({
                            "success": False,
                            "error": str(e),
                            "to": to_email,
                            "company": company_name,
                        })

        except Exception as e:
            return [{
                "success": False,
                "error": f"Failed to establish SMTP connection: {str(e)}",
            }]

        return results

    def preview_random_template(
        self,
        company_name: str,
        to_email: str,
        **template_vars,
    ) -> dict:
        """Generate a preview using a randomly selected template.
        
        Returns:
            Dict with subject, body, preview text, and template number used
        """
        selected_template = self._get_random_template()
        rendered_template = self._render_template(
            selected_template,
            company_name,
            **template_vars,
        )

        preview = f"""
{'=' * 60}
TEMPLATE #{selected_template.id}: {selected_template.name}
FROM: {EMAIL_USER}
TO: {to_email}
SUBJECT: {rendered_template.subject}
{'=' * 60}

{rendered_template.text_body}

{'=' * 60}
"""

        return {
            "subject": rendered_template.subject,
            "body": rendered_template.text_body,
            "html_body": rendered_template.html_body,
            "preview": preview,
            "company": company_name,
            "to": to_email,
            "template_number": selected_template.id,
            "template_name": selected_template.name,
        }


class EmailPreview:
    """Preview emails without sending (for human review)."""

    def __init__(self, db_path: Optional[str] = None):
        self.template_store = TemplateStore(db_path)
        self.templates = self._load_templates()

    def _load_templates(self) -> list[TemplateRecord]:
        """Load all email templates from the SQLite application store."""
        return self.template_store.load_templates()

    def _get_random_template(self) -> TemplateRecord:
        """Randomly select a template from available templates."""
        return random.choice(self.templates)

    def _render_template(
        self,
        template: TemplateRecord,
        company_name: str,
        **template_vars,
    ) -> RenderedTemplate:
        """Render the selected template with placeholder substitution."""
        defaults = {
            "company_name": company_name,
            "sender_name": template_vars.get("sender_name", "Your Name"),
            "sender_title": template_vars.get("sender_title", "Your Title"),
            "sender_company": template_vars.get("sender_company", "Your Company"),
            "sender_phone": template_vars.get("sender_phone", ""),
            "industry": template_vars.get("industry", "your industry"),
        }
        defaults.update(template_vars)

        subject = template.subject
        text_body = template.text_body
        html_body = template.html_body

        for key, value in defaults.items():
            placeholder = f"{{{{{key}}}}}"
            replacement = str(value)
            subject = subject.replace(placeholder, replacement)
            text_body = text_body.replace(placeholder, replacement)
            html_body = html_body.replace(placeholder, replacement)

        return RenderedTemplate(
            template=template,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
        )

    def generate_preview(
        self,
        company_name: str,
        to_email: str,
        template_number: Optional[int] = None,
        **template_vars,
    ) -> dict:
        """Generate email preview for review.

        Args:
            company_name: Name of the company
            to_email: Recipient email address
            template_number: Specific template ID to use.
                           If None, randomly selects a template.
            **template_vars: Variables for template substitution

        Returns:
            Dict with subject, body, preview text, and template number used
        """
        # Select specific template or random one
        if template_number is not None:
            selected_template = next(
                (template for template in self.templates if template.id == template_number),
                None,
            )
            if selected_template is None:
                raise ValueError(f"Template {template_number} does not exist")
        else:
            selected_template = self._get_random_template()

        rendered_template = self._render_template(
            selected_template,
            company_name,
            **template_vars,
        )

        preview = f"""
{'=' * 60}
TEMPLATE #{selected_template.id}: {selected_template.name}
FROM: {EMAIL_USER if 'EMAIL_USER' in globals() else 'your@email.com'}
TO: {to_email}
SUBJECT: {rendered_template.subject}
{'=' * 60}

{rendered_template.text_body}

{'=' * 60}
"""

        return {
            "subject": rendered_template.subject,
            "body": rendered_template.text_body,
            "html_body": rendered_template.html_body,
            "preview": preview,
            "company": company_name,
            "to": to_email,
            "template_number": selected_template.id,
            "template_name": selected_template.name,
        }

    def preview_all_templates(
        self,
        company_name: str,
        to_email: str,
        **template_vars,
    ) -> list[dict]:
        """Generate previews for all available templates.

        Returns:
            List of preview dicts, one for each template
        """
        previews = []
        for i in range(len(self.templates)):
            preview = self.generate_preview(
                company_name, to_email, template_number=i + 1, **template_vars
            )
            previews.append(preview)
        return previews
