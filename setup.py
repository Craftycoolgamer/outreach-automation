#!/usr/bin/env python3
"""Setup helper for outreach automation."""

import os
import sys
from pathlib import Path


def check_files():
    """Check for required credential files."""
    base_dir = Path(__file__).parent

    required_files = {
        ".env": "Environment configuration (copy from .env.example)",
        "credentials.json": "Google Sheets service account key",
        "gmail_credentials.json": "Gmail OAuth credentials (optional, for sending)",
    }

    print("Checking for required files...\n")

    all_ok = True
    for filename, description in required_files.items():
        filepath = base_dir / filename
        exists = filepath.exists()
        status = "✓" if exists else "✗"
        print(f"{status} {filename:30} - {description}")
        if filename == ".env" and not exists:
            all_ok = False

    return all_ok


def check_env():
    """Check environment variables."""
    from dotenv import load_dotenv
    load_dotenv()

    print("\nChecking environment variables...\n")

    required_vars = ["GOOGLE_SHEET_ID"]
    optional_vars = ["GMAIL_USER", "DAILY_EMAIL_LIMIT"]

    all_ok = True
    for var in required_vars:
        value = os.getenv(var, "")
        status = "✓" if value else "✗"
        display = value[:20] + "..." if len(value) > 20 else value
        print(f"{status} {var:30} = {display}")
        if not value:
            all_ok = False

    for var in optional_vars:
        value = os.getenv(var, "")
        status = "✓" if value else "○"
        display = value[:20] + "..." if len(value) > 20 else value
        print(f"{status} {var:30} = {display or '(not set)'}")

    return all_ok


def test_sheets_connection():
    """Test Google Sheets connection."""
    print("\nTesting Google Sheets connection...")

    try:
        sys.path.insert(0, str(Path(__file__).parent / "src"))
        from sheets import OutreachSheet

        sheet = OutreachSheet()
        records = sheet.get_all_records()
        print(f"✓ Successfully connected to sheet")
        print(f"  Found {len(records)} existing records")
        return True
    except FileNotFoundError as e:
        print(f"✗ {e}")
        return False
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return False


def main():
    print("=" * 60)
    print("OUTREACH AUTOMATION SETUP CHECKER")
    print("=" * 60)

    files_ok = check_files()
    env_ok = check_env()

    if files_ok and env_ok:
        sheets_ok = test_sheets_connection()
    else:
        sheets_ok = False

    print("\n" + "=" * 60)
    if files_ok and env_ok and sheets_ok:
        print("✓ ALL CHECKS PASSED - Ready to use!")
        print("\nTry these commands:")
        print("  python src/workflow.py --status")
        print("  python src/workflow.py --add 'Test Co' 'https://example.com'")
        print("  python src/workflow.py --research")
    else:
        print("✗ SETUP INCOMPLETE")
        print("\nPlease:")
        if not files_ok:
            print("  1. Copy .env.example to .env and fill in your values")
            print("  2. Download credentials.json from Google Cloud Console")
        if not env_ok:
            print("  3. Edit .env and set GOOGLE_SHEET_ID")
        if not sheets_ok and files_ok and env_ok:
            print("  4. Verify sheet ID and sharing permissions")

        print("\nSee README.md for detailed setup instructions.")

    print("=" * 60)


if __name__ == "__main__":
    main()
