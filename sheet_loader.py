"""
sheet_loader.py  (v3 — hardened)
---------------------------------
Converts any Google Sheets share URL into a cache-busted direct CSV export
URL and parses the sheet into a list of {'email', 'password'} dicts.

Fixes over v2:
  • Cache-busted export URL  (&t=<unix_timestamp>)
  • UTF-8 BOM handling       (utf-8-sig decode)
  • Private-sheet detection  (HTML response guard)
  • Smart header detection   (skip row 1 ONLY if no '@' in col-A)
  • Never returns ([], None) — always raises ValueError with a clear message
  • Tab gid preserved from both ?gid= and #gid= URL variants

No Google API key or service account is required.
"""

import csv
import io
import re
import time
from typing import List, Dict, Tuple

import requests


# ── URL parsing ────────────────────────────────────────────────────────────────

def _extract_sheet_id(url: str) -> str:
    """Pull the spreadsheet ID out of any Google Sheets URL variant."""
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
    if m:
        return m.group(1)
    raise ValueError(
        "Could not find a Google Sheets ID in the URL.\n\n"
        "Expected format:\n"
        "  https://docs.google.com/spreadsheets/d/SHEET_ID/edit?usp=sharing\n\n"
        "Make sure you copied the full URL from the browser address bar."
    )


def _extract_gid(url: str) -> str:
    """Extract the tab gid from ?gid= or #gid= in the URL. Defaults to '0'."""
    m = re.search(r"[#&?]gid=(\d+)", url)
    return m.group(1) if m else "0"


def _build_csv_url(sheet_id: str, gid: str) -> str:
    """Build a cache-busted CSV export URL."""
    ts = int(time.time())
    return (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}"
        f"/export?format=csv&gid={gid}&t={ts}"
    )


# ── Main loader ────────────────────────────────────────────────────────────────

def load_accounts(sheet_url: str) -> Tuple[List[Dict[str, str]], str]:
    """
    Fetch a public Google Sheet and return:
        accounts  – list of {'email': str, 'password': str}
        csv_url   – the resolved export URL (displayed in the UI)

    Raises ValueError with a user-friendly message on any failure.
    Never returns an empty accounts list — always raises if zero rows found.
    """
    sheet_url = sheet_url.strip()
    sheet_id  = _extract_sheet_id(sheet_url)
    gid       = _extract_gid(sheet_url)
    csv_url   = _build_csv_url(sheet_id, gid)

    # ── Fetch ──────────────────────────────────────────────────────────────
    try:
        resp = requests.get(
            csv_url,
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0"},
            allow_redirects=True,
        )
    except requests.exceptions.ConnectionError:
        raise ValueError(
            "Could not connect to Google Sheets.\n"
            "Check your internet connection and try again."
        )
    except requests.exceptions.Timeout:
        raise ValueError("Request timed out after 30 seconds. Try again.")
    except Exception as exc:
        raise ValueError(f"Network error: {exc}")

    # ── Private / restricted sheet guard ──────────────────────────────────
    # When a sheet is private, Google returns an HTML login/error page instead of CSV.
    content_type = resp.headers.get("Content-Type", "")
    raw_text_peek = resp.content[:200].decode("utf-8-sig", errors="replace").lstrip()

    if (
        "text/html" in content_type
        or raw_text_peek.startswith("<!DOCTYPE")
        or raw_text_peek.lower().startswith("<html")
    ):
        raise ValueError(
            "⚠️  Sheet is private or access is restricted!\n\n"
            "Fix: Open the sheet in Google Sheets → Share → "
            "Change to 'Anyone with the link' → Viewer → Done.\n\n"
            "Then paste the link again and click Load & Verify."
        )

    # ── HTTP errors ────────────────────────────────────────────────────────
    if resp.status_code == 403:
        raise ValueError(
            "Access denied (HTTP 403).\n"
            "Make sure the Google Sheet is shared as "
            "'Anyone with the link can VIEW'."
        )
    if resp.status_code != 200:
        raise ValueError(
            f"Google returned HTTP {resp.status_code}.\n"
            "Check the URL and your internet connection."
        )

    # ── Decode — handle UTF-8 BOM that Google sometimes adds ──────────────
    text = resp.content.decode("utf-8-sig").strip()
    if not text:
        raise ValueError(
            f"The sheet (gid={gid}) returned empty content.\n"
            "Make sure the tab has data in it."
        )

    # ── Parse CSV ──────────────────────────────────────────────────────────
    reader   = csv.reader(io.StringIO(text))
    accounts: List[Dict[str, str]] = []
    skipped_blank  = 0
    skipped_short  = 0
    total_rows     = 0

    for row_num, row in enumerate(reader, start=1):
        total_rows += 1

        # Skip completely blank rows
        if not any(cell.strip() for cell in row):
            skipped_blank += 1
            continue

        # Skip the first row ONLY if Column A does NOT contain '@'
        # (meaning it's a header like "Email", "Account", etc.)
        # If row 1 contains a real email, treat it as data — never discard it.
        if row_num == 1:
            col_a = row[0].strip() if row else ""
            if "@" not in col_a:
                # It's a header row — skip it
                continue
            # else: row 1 has a real email, fall through to parse it

        # Need at least 2 columns (email, password)
        if len(row) < 2:
            skipped_short += 1
            continue

        email    = row[0].strip()
        password = row[1].strip()
        recovery = row[2].strip() if len(row) > 2 else ""

        # Must have both values and email must look valid (contains '@')
        if not email or not password or "@" not in email:
            skipped_short += 1
            continue

        accounts.append({
            "email": email,
            "password": password,
            "recovery": recovery,
        })

    # ── Never return an empty list silently ───────────────────────────────
    if not accounts:
        detail_parts = []
        if skipped_blank:
            detail_parts.append(f"{skipped_blank} blank rows")
        if skipped_short:
            detail_parts.append(
                f"{skipped_short} rows skipped (missing email/password or no '@')"
            )
        detail = (", ".join(detail_parts) + ".") if detail_parts else ""

        raise ValueError(
            f"No valid Email + Password rows found in Columns A & B "
            f"of this sheet tab (gid={gid}).\n\n"
            f"Scanned {total_rows} total row(s). {detail}\n\n"
            "Expected layout:\n"
            "  Column A = Email address (must contain '@')\n"
            "  Column B = Current password\n"
            "  Column C = Recovery email (optional)\n\n"
            "If you edited the sheet recently, wait 10 seconds and try again "
            "(Google caches exports briefly)."
        )

    return accounts, csv_url
