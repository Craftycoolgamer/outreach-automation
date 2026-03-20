# Outreach Automation - Human-in-the-Loop

A free, Python-based outreach automation system that researches companies, finds contact information, and manages outreach workflows with human approval at every critical step.

## Features

- **Google Sheets integration** - Your 5-column log stays in sync automatically
- **Email discovery** - Scrapes company websites to find contact emails
- **Contact form detection** - Identifies contact forms when emails aren't available
- **Email integration** - Sends emails via SMTP (works with any email provider)
- **Human checkpoints** - You approve every email before sending
- **CAPTCHA-safe** - Never attempts to bypass security measures
- **100% free** - Uses only free Google APIs and open-source libraries

## Sheet Format

Your Google Sheet must have exactly these 6 columns:

| date | company | website | contact | method | status |
|------|---------|---------|---------|--------|--------|

**Column Details:**
- **date** - Date added or last updated
- **company** - Company name
- **website** - Company website URL (used for research)
- **contact** - Email address or contact form URL (filled after research)
- **method** - How to contact (`email`, `contact_form`, or `manual`)
- **status** - Current workflow status

### Status Values
- `New` - Company added, pending research
- `Ready` - Email found, awaiting approval
- `Sent` - Email successfully sent
- `Forum` - Contact form found, needs manual submission
- `Manual` - You submitted the contact form
- `Skipped` - Intentionally skipped
- `Failed` - No contact method found or error occurred

### Method Values
- `Email` - Contacted via email
- `Forum` - Contacted via website form
- `Manual` - Manual process required

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your settings:
```
GOOGLE_SHEET_ID=your_sheet_id_here
EMAIL_USER=your_work_email@company.com
EMAIL_PASSWORD=your_email_password_or_app_key
SMTP_SERVER=smtp.your-email-provider.com
SMTP_PORT=587
DAILY_EMAIL_LIMIT=50
```

### 3. Set Up Google Sheets API

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project
3. Enable the **Google Sheets API**
4. Go to **IAM & Admin > Service Accounts**
5. Create a service account
6. Go to **Keys** tab > **Add Key** > **Create new key** > **JSON**
7. Download the JSON file as `credentials.json` in this project folder

### 4. Set Up Email (SMTP Configuration)

The system uses SMTP to send emails, which works with any email provider.

**Finding your SMTP settings:**

| Provider | SMTP Server | Port |
|----------|-------------|------|
| Microsoft 365 | `smtp.office365.com` | 587 |
| Google Workspace | `smtp.gmail.com` | 587 |
| Yahoo Business | `smtp.bizmail.yahoo.com` | 587 |
| Zoho | `smtp.zoho.com` | 587 |
| Generic | `smtp.your-domain.com` | 587 |

**Setup steps:**

1. **Find your SMTP settings** from your email provider's documentation
2. **Get your email password/app key:**
   - Some providers require an "App Password" instead of your regular password
   - Microsoft 365: [Create app password](https://support.microsoft.com/en-us/account-billing/manage-app-passwords-for-two-step-verification-d8dc47c6-13bc-4e63-9609-ce3aa9652989)
   - Google: [Create app password](https://support.google.com/accounts/answer/185833)
3. **Add to your `.env` file:**
   ```
   EMAIL_USER=your_email@company.com
   EMAIL_PASSWORD=your_app_password_here
   SMTP_SERVER=smtp.office365.com
   SMTP_PORT=587
   ```

### 5. Share Your Google Sheet

1. Open your Google Sheet
2. Click **Share** button
3. Add the service account email (ends with `@...gserviceaccount.com`) as **Editor**
4. Copy the Sheet ID from the URL (the long string between `/d/` and `/edit`)
5. Add it to your `.env` file

### 6. Template Database

Email templates are now stored in the SQLite application database at `outreach.db`.

The `templates` table stores:
- `name`
- `subject`
- `text_body_path` - path to a `.txt` file in `templates/`
- `html_body_path` - path to a `.html` file in `templates/`

Both linked files must exist inside `templates/` or the email client will raise an error during startup.

## Usage

### Add Companies to Research

```bash
python src/workflow.py --add "Acme Inc" "https://acme.com"
```

Or add manually in Google Sheets with status `New`.

### Research Pending Companies

```bash
python3 src/workflow.py --research
```

This will:
1. Scrape each company website
2. Find emails or contact forms
3. Show you a preview
4. Ask for your decision

Options during research:
- `[s]` Send now (requires SMTP config)
- `[r]` Mark as ready to send (review later) ← **Recommended**
- `[f]` Use contact form instead
- `[x]` Skip this company

### Send Approved Emails

```bash
python3 src/workflow.py --send
```

Sends all emails marked `Ready`.

### Check Manual Submissions Needed

```bash
python3 src/workflow.py --manual-forms
```

Shows all companies with contact forms waiting for your manual submission.

### Mark a Form as Submitted

```bash
python3 src/workflow.py --mark-submitted 5
```

(Where 5 is the row number in your sheet)

### Check Status Summary

```bash
python3 src/workflow.py --status
```

## Typical Daily Workflow

```bash
# 1. Add new companies (or add directly in sheet)
python3 src/workflow.py --add "Company Name" "https://company.com"

# 2. Research all pending companies
python3 src/workflow.py --research

# 3. Review and mark forms as submitted (if any)
python3 src/workflow.py --manual-forms
python3 src/workflow.py --mark-submitted 8

# 4. Send approved emails
python3 src/workflow.py --send

# 5. Check overall status
python3 src/workflow.py --status
```

## Customizing Email Templates

Update the linked body files in `templates/` and the matching row in `db.db`.

Example schema:

```sql
CREATE TABLE templates (
   id INTEGER PRIMARY KEY AUTOINCREMENT,
   name TEXT NOT NULL UNIQUE,
   subject TEXT NOT NULL,
   text_body_path TEXT NOT NULL,
   html_body_path TEXT NOT NULL
);
```

Example text body file:

```
Hi {{company_name}} Team,

Your custom message here...

Best regards,
{{sender_name}}
```

Available variables:
- `{{company_name}}` - Company name from sheet
- `{{sender_name}}` - Your name
- `{{sender_title}}` - Your job title
- `{{sender_company}}` - Your company
- `{{sender_phone}}` - Your phone number
- `{{industry}}` - Industry placeholder

## File Structure

```
outreach-automation/
├── src/
│   ├── config.py          # Configuration and constants
│   ├── sheets.py          # Google Sheets integration
│   ├── scraper.py         # Website research/scraping
│   ├── email_client.py    # SMTP email client
│   └── workflow.py        # Main workflow orchestrator
├── templates/
│   ├── outreach_template_nickd.txt
│   └── outreach_template_nickd.html
├── outreach.db            # SQLite application database
├── .env                   # Your environment variables (not in git)
├── .env.example           # Example environment file
├── credentials.json       # Google Sheets service account key
├── requirements.txt
└── README.md
```

## Safety & Compliance

### What This Tool Does NOT Do

- ❌ Bypass CAPTCHAs
- ❌ Auto-submit contact forms
- ❌ Send mass emails without approval
- ❌ Scrape data at high speeds
- ❌ Store data outside your Google Sheet

### What This Tool DOES Do

- ✅ Respects website terms of service
- ✅ Adds delays between requests
- ✅ Shows you every email before sending
- ✅ Logs everything in your sheet
- ✅ Uses proper email authentication

### Email Sending Limits

SMTP sending limits vary by provider:
- Microsoft 365: 10,000 emails/day (depends on plan)
- Google Workspace: 2,000 emails/day
- Most hosting providers: 250-500 emails/hour

The script respects the `DAILY_EMAIL_LIMIT` in your `.env` file.

## Troubleshooting

### "Credentials file not found"

Download your service account JSON from Google Cloud Console and save as `credentials.json` in the project folder.

### "Sheet not found"

- Verify `GOOGLE_SHEET_ID` is correct in `.env`
- Make sure the service account has Editor access to the sheet

### "Email not configured"

- Check that `.env` file contains all required SMTP settings:
  - `EMAIL_USER` - your email address
  - `EMAIL_PASSWORD` - your password or app key
  - `SMTP_SERVER` - your email provider's SMTP server
  - `SMTP_PORT` - usually 587 for TLS
- Verify your email provider allows SMTP access
- If using Microsoft 365 or Gmail, you may need an app-specific password

### Permission Denied Errors

- Go to Google Cloud Console > APIs & Services > Credentials
- Check that Google Sheets API is enabled
- Verify the service account has Editor access to your sheet

### Rate Limiting

If websites block your requests:
- Increase delays in `config.py` (add time.sleep calls)
- Use a different IP (VPN)
- Reduce daily volume

## Development

### Running in Dry-Run Mode

Test without making changes:

```bash
python3 src/workflow.py --research --dry-run
python3 src/workflow.py --send --dry-run
```

### Testing Individual Modules

```python
# Test sheet connection
from src.sheets import OutreachSheet
sheet = OutreachSheet()
print(sheet.get_all_records())

# Test scraper
from src.scraper import CompanyResearcher
researcher = CompanyResearcher()
result = researcher.research_company("Test Co", "https://example.com")
print(result)

# Test email sending
from src.email_client import SmtpOutreach
email = SmtpOutreach()
result = email.send_email("test@example.com", "Test Company")
print(result)
```

## License

This project is provided as-is for educational and legitimate business outreach purposes. Always comply with:
- CAN-SPAM Act (US)
- GDPR (EU)
- Website Terms of Service
- Your employer's policies
