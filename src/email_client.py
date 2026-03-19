"""SMTP email client for sending outreach emails."""

import os
import random
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import Optional

from config import (
    EMAIL_USER,
    EMAIL_PASSWORD,
    SMTP_SERVER,
    SMTP_PORT,
    EMAIL_TEMPLATES,
    BASE_DIR,
)


class SmtpOutreach:
    """Sends outreach emails via SMTP with random template selection."""

    def __init__(self, template_paths: Optional[list[str]] = None):
        """Initialize SMTP client.

        Args:
            template_paths: List of paths to email template files.
                          If None, uses EMAIL_TEMPLATES from config.
        """
        self.template_paths = template_paths or EMAIL_TEMPLATES
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

    def _load_templates(self) -> list[str]:
        """Load all email templates from files."""
        templates = []
        for template_path in self.template_paths:
            path = Path(template_path)
            if path.exists():
                templates.append(path.read_text())
        
        # If no templates loaded, use default
        if not templates:
            templates = [self._default_template()]
        
        return templates

    def _get_random_template(self) -> str:
        """Randomly select a template from available templates."""
        return random.choice(self.templates)

    def _default_template(self) -> str:
        """Default outreach email template."""
        return """Subject: Partnership Opportunity with {{company_name}}

Hi {{company_name}} Team,

I hope this message finds you well. I'm reaching out from {{sender_company}} to explore a potential partnership opportunity.

After reviewing {{company_name}}'s work in {{industry}}, I believe there could be valuable synergies between our organizations.

Would you be open to a brief conversation to explore how we might collaborate?

Looking forward to hearing from you.

Best regards,
{{sender_name}}
{{sender_title}}
{{sender_company}}
{{sender_phone}}
"""

    def _prepare_message(
        self,
        to_email: str,
        company_name: str,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        template: Optional[str] = None,
        **template_vars,
    ) -> MIMEMultipart:
        """Prepare email message with template substitution."""
        if subject is None or body is None:
            # Use provided template or pick a random one
            email_text = template or self._get_random_template()

            defaults = {
                "company_name": company_name,
                "sender_name": template_vars.get("sender_name", "Your Name"),
                "sender_title": template_vars.get("sender_title", "Your Title"),
                "sender_company": template_vars.get("sender_company", "Your Company"),
                "sender_phone": template_vars.get("sender_phone", ""),
                "industry": template_vars.get("industry", "your industry"),
            }
            defaults.update(template_vars)

            lines = email_text.strip().split("\n")
            template_subject = "Partnership Opportunity"

            if lines[0].startswith("Subject:"):
                template_subject = lines[0].replace("Subject:", "").strip()
                template_body = "\n".join(lines[1:]).strip()
            else:
                template_body = email_text

            for key, value in defaults.items():
                placeholder = f"{{{{{key}}}}}"
                template_subject = template_subject.replace(placeholder, str(value))
                template_body = template_body.replace(placeholder, str(value))

            subject = subject or template_subject
            body = body or template_body

        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = EMAIL_USER
        message["To"] = to_email

        message.attach(MIMEText(body, "plain"))

        return message

    def send_email(
        self,
        to_email: str,
        company_name: str,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        template: Optional[str] = None,
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
            to_email, company_name, subject, body, selected_template, **template_vars
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
                "template_used": self.templates.index(selected_template) + 1 if selected_template in self.templates else None,
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
                        selected_template,
                        **recipient.get("template_vars", {}),
                    )

                    try:
                        server.sendmail(EMAIL_USER, to_email, message.as_string())
                        results.append({
                            "success": True,
                            "to": to_email,
                            "company": company_name,
                            "template_used": self.templates.index(selected_template) + 1,
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
        template_num = self.templates.index(selected_template) + 1
        
        defaults = {
            "company_name": company_name,
            "sender_name": template_vars.get("sender_name", "Your Name"),
            "sender_title": template_vars.get("sender_title", "Your Title"),
            "sender_company": template_vars.get("sender_company", "Your Company"),
            "sender_phone": template_vars.get("sender_phone", ""),
            "industry": template_vars.get("industry", "your industry"),
        }
        defaults.update(template_vars)

        lines = selected_template.strip().split("\n")
        template_subject = "Partnership Opportunity"

        if lines[0].startswith("Subject:"):
            template_subject = lines[0].replace("Subject:", "").strip()
            template_body = "\n".join(lines[1:]).strip()
        else:
            template_body = selected_template

        for key, value in defaults.items():
            placeholder = f"{{{{{key}}}}}"
            template_subject = template_subject.replace(placeholder, str(value))
            template_body = template_body.replace(placeholder, str(value))

        preview = f"""
{'=' * 60}
TEMPLATE #{template_num}
FROM: {EMAIL_USER}
TO: {to_email}
SUBJECT: {template_subject}
{'=' * 60}

{template_body}

{'=' * 60}
"""

        return {
            "subject": template_subject,
            "body": template_body,
            "preview": preview,
            "company": company_name,
            "to": to_email,
            "template_number": template_num,
        }


class EmailPreview:
    """Preview emails without sending (for human review)."""

    def __init__(self, template_paths: Optional[list[str]] = None):
        self.template_paths = template_paths or EMAIL_TEMPLATES
        self.templates = self._load_templates()

    def _load_templates(self) -> list[str]:
        """Load all email templates from files."""
        templates = []
        for template_path in self.template_paths:
            path = Path(template_path)
            if path.exists():
                templates.append(path.read_text())
        
        if not templates:
            templates = [self._default_template()]
        
        return templates

    def _get_random_template(self) -> str:
        """Randomly select a template from available templates."""
        return random.choice(self.templates)

    def _default_template(self) -> str:
        """Default outreach email template."""
        return """Subject: Partnership Opportunity with {{company_name}}

Hi {{company_name}} Team,

I hope this message finds you well. I'm reaching out from {{sender_company}} to explore a potential partnership opportunity.

After reviewing {{company_name}}'s work in {{industry}}, I believe there could be valuable synergies between our organizations.

Would you be open to a brief conversation to explore how we might collaborate?

Looking forward to hearing from you.

Best regards,
{{sender_name}}
{{sender_title}}
{{sender_company}}
{{sender_phone}}
"""

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
            template_number: Specific template to use (1, 2, or 3). 
                           If None, randomly selects a template.
            **template_vars: Variables for template substitution

        Returns:
            Dict with subject, body, preview text, and template number used
        """
        # Select specific template or random one
        if template_number and 1 <= template_number <= len(self.templates):
            selected_template = self.templates[template_number - 1]
        else:
            selected_template = self._get_random_template()
            template_number = self.templates.index(selected_template) + 1

        defaults = {
            "company_name": company_name,
            "sender_name": template_vars.get("sender_name", "Your Name"),
            "sender_title": template_vars.get("sender_title", "Your Title"),
            "sender_company": template_vars.get("sender_company", "Your Company"),
            "sender_phone": template_vars.get("sender_phone", ""),
            "industry": template_vars.get("industry", "your industry"),
        }
        defaults.update(template_vars)

        lines = selected_template.strip().split("\n")
        template_subject = "Partnership Opportunity"

        if lines[0].startswith("Subject:"):
            template_subject = lines[0].replace("Subject:", "").strip()
            template_body = "\n".join(lines[1:]).strip()
        else:
            template_body = selected_template

        for key, value in defaults.items():
            placeholder = f"{{{{{key}}}}}"
            template_subject = template_subject.replace(placeholder, str(value))
            template_body = template_body.replace(placeholder, str(value))

        preview = f"""
{'=' * 60}
TEMPLATE #{template_number}
FROM: {EMAIL_USER if 'EMAIL_USER' in globals() else 'your@email.com'}
TO: {to_email}
SUBJECT: {template_subject}
{'=' * 60}

{template_body}

{'=' * 60}
"""

        return {
            "subject": template_subject,
            "body": template_body,
            "preview": preview,
            "company": company_name,
            "to": to_email,
            "template_number": template_number,
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
