"""Web scraper for finding emails and contact forms on company websites."""

import re
import subprocess
import time
from urllib.parse import urljoin, urlparse
from typing import Optional

import logging
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT, MAX_RETRIES, USER_AGENT

debug_log_path = Path(__file__).resolve().parent.parent / "scraper_debug.log"

logger = logging.getLogger("scraperDebug")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    file_handler = logging.FileHandler(debug_log_path, encoding="utf-8")
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.propagate = False


class CompanyResearcher:
    """Researches company websites to find contact information."""

    # Pages to check for contact info
    CONTACT_PATHS = [
        "/contact",
        "/contact-us",
        "/about",
        "/about-us",
        "/team",
        "/company",
        "/support",
        "/help",
        "/sales",
        "/get-in-touch",
        "/reach-out",
    ]

    # Email patterns (common business email patterns)
    EMAIL_PATTERNS = [
        r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',  # Standard email
        r'mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',  # mailto links
    ]

    # Excluded email patterns (no-reply, noreply, etc.)
    EXCLUDED_PATTERNS = [
        r'noreply',
        r'no[_\-]?reply',
        r'do[_\-]?not[_\-]?reply',
        r'unsubscribe',
        r'postmaster',
        r'webmaster',
        r'hostmaster',
        r'admin@',
        r'root@',
        r'hello@',  # Generic but often monitored
    ]

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
        })

    def _has_contact_signals(self, html: str, url: str) -> bool:
        """Return True when HTML appears to contain contact/email content."""
        html_lower = html.lower()
        domain = urlparse(url).netloc.replace("www.", "").lower()
        return (
            "mailto:" in html_lower
            or f"@{domain}" in html_lower
            or "contact" in html_lower
        )

    def _get_page_with_curl(self, url: str) -> Optional[str]:
        """Fallback fetch using curl for sites that block requests client."""
        try:
            cmd = [
                "curl",
                "-sL",
                "--max-time",
                str(REQUEST_TIMEOUT),
                url,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            html = result.stdout or ""
            if result.returncode == 0 and html.strip():
                logger.info("GET curl_success | url=%s | len=%s", url, len(html))
                return html

            logger.warning(
                "GET curl_failed | url=%s | returncode=%s | stderr=%s",
                url,
                result.returncode,
                (result.stderr or "")[:200],
            )
        except Exception as exc:
            logger.warning("GET curl_exception | url=%s | error=%r", url, exc)

        return None

    def _get_page(self, url: str) -> Optional[str]:
        """Fetch page content with retries.

        Notes:
        - Returns HTML for normal 2xx responses.
        - Soft-accepts 403/429 HTML responses so downstream parsing can still
        extract emails/contact info from WAF/challenge pages that contain content.
        """
        for attempt in range(MAX_RETRIES):
            try:
                logger.info("GET start | url=%s | attempt=%s/%s", url, attempt + 1, MAX_RETRIES)
                response = self.session.get(
                    url,
                    timeout=REQUEST_TIMEOUT,
                    allow_redirects=True,
                )

                content_type = (response.headers.get("Content-Type") or "").lower()
                body = response.text or ""
                status = response.status_code

                logger.info(
                    "GET response | url=%s | final_url=%s | status=%s | len=%s | content_type=%s",
                    url,
                    response.url,
                    status,
                    len(body),
                    content_type,
                )

                # Normal success path
                if 200 <= status < 300:
                    return body

                # Some anti-bot layers return a block page with 403/429.
                # Try curl fallback first, then decide whether to accept the
                # original body.
                if status in (403, 429) and "text/html" in content_type and body.strip():
                    fallback_body = self._get_page_with_curl(url)
                    if fallback_body:
                        fallback_signals = self._has_contact_signals(fallback_body, url)
                        logger.info(
                            "GET curl_fallback_signals | url=%s | contact_signals=%s",
                            url,
                            fallback_signals,
                        )
                        if fallback_signals:
                            logger.info("GET using_curl_fallback | url=%s", url)
                            return fallback_body

                    has_contact_signals = self._has_contact_signals(body, url)
                    logger.warning(
                        "GET blocked_html | url=%s | status=%s | contact_signals=%s",
                        url,
                        status,
                        has_contact_signals,
                    )
                    if has_contact_signals:
                        return body
                    if fallback_body:
                        logger.info("GET using_curl_fallback_no_signals | url=%s", url)
                        return fallback_body

                # Keep retrying for other status codes
                logger.warning(
                    "GET non-success status | url=%s | status=%s | attempt=%s/%s",
                    url,
                    status,
                    attempt + 1,
                    MAX_RETRIES,
                )

            except requests.exceptions.Timeout as exc:
                logger.warning(
                    "GET timeout | url=%s | attempt=%s/%s | error=%s",
                    url,
                    attempt + 1,
                    MAX_RETRIES,
                    repr(exc),
                )

            except requests.exceptions.RequestException as exc:
                logger.warning(
                    "GET request_exception | url=%s | attempt=%s/%s | error=%s",
                    url,
                    attempt + 1,
                    MAX_RETRIES,
                    repr(exc),
                )

            if attempt == MAX_RETRIES - 1:
                logger.error("GET failed after retries | url=%s", url)
                return None

            time.sleep(1 * (attempt + 1))

        return None

    def _normalize_url(self, url: str) -> str:
        """Ensure URL has proper scheme."""
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        return url

    def _extract_emails(self, html: str, base_url: str) -> list[str]:
        """Extract email addresses from HTML content."""
        emails = []
        seen = set()

        for pattern in self.EMAIL_PATTERNS:
            matches = re.findall(pattern, html)
            for match in matches:
                if isinstance(match, tuple):
                    match = match[0]
                email = match.lower().strip()

                # Skip excluded patterns
                should_skip = any(
                    re.search(excluded, email, re.IGNORECASE)
                    for excluded in self.EXCLUDED_PATTERNS
                )
                if should_skip:
                    continue

                # Basic validation
                if "@" in email and "." in email.split("@")[1]:
                    if email not in seen:
                        seen.add(email)
                        emails.append(email)

        return emails

    def _find_contact_forms(self, soup: BeautifulSoup, base_url: str) -> list[str]:
        """Find contact form URLs on the page."""
        forms = []

        # Look for forms that might be contact forms
        for form in soup.find_all("form"):
            # Check form attributes for contact indicators
            form_text = form.get_text().lower()
            form_action = form.get("action", "")
            form_id = form.get("id", "").lower()
            form_class = " ".join(form.get("class", [])).lower()

            contact_indicators = [
                "contact", "message", "inquiry", "quote", "demo",
                "reach", "get in touch", "talk", "sales"
            ]

            is_contact = any(ind in form_text for ind in contact_indicators)
            is_contact = is_contact or any(ind in form_id for ind in contact_indicators)
            is_contact = is_contact or any(ind in form_class for ind in contact_indicators)

            if is_contact:
                action_url = urljoin(base_url, form_action) if form_action else base_url
                forms.append(action_url)

        # Also look for links to contact pages
        for link in soup.find_all("a", href=True):
            href = link.get("href", "").lower()
            link_text = link.get_text().lower()

            if any(path in href for path in self.CONTACT_PATHS):
                full_url = urljoin(base_url, href)
                if full_url not in forms:
                    forms.append(full_url)

        return forms

    def research_company(self, company_name: str, website: str) -> dict:
        """Research a company website for contact information.

        Args:
            company_name: Name of the company
            website: Company website URL

        Returns:
            Dict with keys: emails (list), contact_forms (list), best_email, best_form
        """
        base_url = self._normalize_url(website)
        domain = urlparse(base_url).netloc.replace("www.", "")

        all_emails = []
        all_forms = []
        pages_checked = []

        # Check homepage first
        homepage_html = self._get_page(base_url)
        if homepage_html:
            pages_checked.append(base_url)
            homepage_emails = self._extract_emails(homepage_html, base_url)
            all_emails.extend(homepage_emails)

            soup = BeautifulSoup(homepage_html, "lxml")
            homepage_forms = self._find_contact_forms(soup, base_url)
            all_forms.extend(homepage_forms)

        # Check contact pages
        for path in self.CONTACT_PATHS:
            page_url = urljoin(base_url, path)
            if page_url in pages_checked:
                continue

            time.sleep(0.5)  # Be polite

            page_html = self._get_page(page_url)
            if not page_html:
                continue

            pages_checked.append(page_url)
            page_emails = self._extract_emails(page_html, page_url)
            all_emails.extend(page_emails)

            soup = BeautifulSoup(page_html, "lxml")
            page_forms = self._find_contact_forms(soup, page_url)
            all_forms.extend(page_forms)

        # Remove duplicates while preserving order
        seen_emails = set()
        unique_emails = []
        for email in all_emails:
            if email not in seen_emails:
                seen_emails.add(email)
                unique_emails.append(email)

        seen_forms = set()
        unique_forms = []
        for form in all_forms:
            if form not in seen_forms:
                seen_forms.add(form)
                unique_forms.append(form)

        # Determine best contact method
        best_email = self._select_best_email(unique_emails, domain)
        best_form = unique_forms[0] if unique_forms else None

        return {
            "company_name": company_name,
            "website": website,
            "domain": domain,
            "emails": unique_emails,
            "contact_forms": unique_forms,
            "best_email": best_email,
            "best_form": best_form,
            "pages_checked": pages_checked,
        }

    def _select_best_email(self, emails: list[str], domain: str) -> Optional[str]:
        """Select the best email from a list based on heuristics."""
        if not emails:
            return None

        if len(emails) == 1:
            return emails[0]

        # Prefer emails matching the company domain
        domain_emails = [e for e in emails if domain in e.split("@")[1]]
        if domain_emails:
            emails = domain_emails

        # Prefer common business emails over random ones
        priority_keywords = ["sales", "business", "partnerships", "partnership", "hello", "contact", "support", "service", "info"]
        for keyword in priority_keywords:
            for email in emails:
                if keyword in email:
                    return email

        # Return first email (they're already ordered by discovery priority)
        return emails[0]


def format_research_result(result: dict) -> str:
    """Format research result for display."""
    lines = [
        f"Company: {result['company_name']}",
        f"Website: {result['website']}",
        f"Domain: {result['domain']}",
        f"Pages checked: {len(result['pages_checked'])}",
        "",
        f"Emails found ({len(result['emails'])}):",
    ]

    if result['emails']:
        for email in result['emails']:
            marker = " <- BEST" if email == result['best_email'] else ""
            lines.append(f"  - {email}{marker}")
    else:
        lines.append("  None found")

    lines.extend(["", f"Contact forms found ({len(result['contact_forms'])}):"])

    if result['contact_forms']:
        for form in result['contact_forms'][:3]:  # Limit to first 3
            lines.append(f"  - {form}")
    else:
        lines.append("  None found")

    return "\n".join(lines)
