"""
automation.py  (v3 — bulk-hardened)
-------------------------------------
Playwright-based automation for changing Google account passwords.

New in v3:
  • Browser recycled every BROWSER_RECYCLE_EVERY accounts (default 30) so
    Chrome RAM never snowballs during 500-account runs.
  • Richer Step 7 success detection: handles redirect to myaccount home,
    "Password changed" banner/heading, "Continue to your Google Account" /
    "Get started" security-checkup screen (all common post-change states).
  • Strict try…finally around every context open/close (no context leaks).
  • Detailed per-step error messages unchanged from v2.
"""

import csv
import sys
import os
import time
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Callable, Optional

from playwright.sync_api import (
    sync_playwright,
    sync_playwright as _sync_playwright,
    Page,
    Browser,
    BrowserContext,
    TimeoutError as PlaywrightTimeout,
)


# ── Constants ──────────────────────────────────────────────────────────────────

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).parent
else:
    APP_DIR = Path(__file__).parent.resolve()

RESULTS_FILE = APP_DIR / "password_update_results.csv"
CSV_HEADERS  = ["Email", "Old Password", "New Password", "Status", "Timestamp", "Notes"]

# Navigate directly to PW-change page; ?hl=en locks English UI text
URL_PW_CHANGE = "https://myaccount.google.com/signinoptions/password?hl=en"

# Recycle the Chrome browser process every N accounts to keep RAM low
BROWSER_RECYCLE_EVERY = 30

# Timeouts (ms)
T_ELEMENT = 15_000   # wait for a specific DOM element
T_NAV     = 30_000   # page navigation
T_MANUAL  = 90_000   # wait for user to handle 2FA / CAPTCHA


# ── CSV helpers ────────────────────────────────────────────────────────────────

def _ensure_csv():
    if not RESULTS_FILE.exists():
        with open(RESULTS_FILE, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=CSV_HEADERS).writeheader()


def _append_result(email: str, old_pw: str, new_pw: str,
                   status: str, notes: str = ""):
    _ensure_csv()
    with open(RESULTS_FILE, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=CSV_HEADERS).writerow({
            "Email":        email,
            "Old Password": old_pw,
            "New Password": new_pw,
            "Status":       status,
            "Timestamp":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Notes":        notes,
        })


# ── Page-state helpers ─────────────────────────────────────────────────────────

def _url_has(page: Page, *fragments: str) -> bool:
    url = page.url.lower()
    return any(f.lower() in url for f in fragments)


def _body_has(page: Page, *phrases: str) -> bool:
    try:
        body = page.inner_text("body", timeout=4000).lower()
        return any(p.lower() in body for p in phrases)
    except Exception:
        return False


def _click_if_visible(page: Page, selector: str, timeout: int = 3000) -> bool:
    try:
        loc = page.locator(selector).first
        if loc.is_visible(timeout=timeout):
            loc.click()
            return True
    except Exception:
        pass
    return False


# ── Browser factory ────────────────────────────────────────────────────────────

_BROWSER_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--start-maximized",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-extensions",
]

def _launch_browser(pw) -> Browser:
    return pw.chromium.launch(
        channel="chrome",
        headless=False,     # will be overridden per-call if needed
        args=_BROWSER_ARGS,
        slow_mo=150,
    )


def _new_context(browser: Browser) -> BrowserContext:
    ctx = browser.new_context(
        viewport={"width": 1280, "height": 800},
        locale="en-US",
        timezone_id="America/New_York",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
    )
    ctx.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return ctx


# ── Single-account routine ─────────────────────────────────────────────────────

def _change_password_for_account(
    page: Page,
    email: str,
    old_password: str,
    new_password: str,
    log: Callable[[str], None],
    is_paused: Callable[[], bool],
    is_stopped: Callable[[], bool],
) -> str:
    """
    Returns one of:
        "Success"
        "Stopped"
        "Skipped (<reason>)"
        "Failed (<step>: <detail>)"
        "Uncertain (verify manually — <url>)"
    """

    def _gate(_label: str = "") -> Optional[str]:
        while is_paused():
            if is_stopped():
                return "Stopped"
            time.sleep(0.3)
        if is_stopped():
            return "Stopped"
        return None

    # ── STEP 1: Navigate to password-change page ────────────────────────────
    log("  → [Step 1] Navigating to Google password-change page…")
    try:
        page.goto(URL_PW_CHANGE, wait_until="domcontentloaded", timeout=T_NAV)
        time.sleep(1.5)
        log(f"  →           Landed on: {page.url}")
    except PlaywrightTimeout as exc:
        return f"Failed (Step 1 navigation timeout: {exc})"
    except Exception as exc:
        return f"Failed (Step 1 navigation: {exc})"

    if (s := _gate()): return s

    # ── STEP 2: Enter email ─────────────────────────────────────────────────
    if _url_has(page, "accounts.google.com", "signin", "servicerouter"):
        log("  → [Step 2] Google sign-in detected — entering email…")
        try:
            email_loc = page.locator(
                'input#identifierId, input[type="email"]:visible'
            ).first
            email_loc.wait_for(state="visible", timeout=T_ELEMENT)
            email_loc.click()
            email_loc.fill(email)
            page.wait_for_timeout(400)
            email_loc.press("Enter")
            log(f"  →           Email submitted: {email}")
        except PlaywrightTimeout as exc:
            return (
                f"Failed (Step 2: email field not visible after {T_ELEMENT}ms. "
                f"URL: {page.url}. Exception: {exc})"
            )
        except Exception as exc:
            return f"Failed (Step 2 email entry: {exc})"
    else:
        log(f"  → [Step 2] Not on sign-in page — skipping email step. URL: {page.url}")

    if (s := _gate()): return s

    # ── STEP 3: Enter current password ─────────────────────────────────────
    log("  → [Step 3] Waiting for current-password field…")
    try:
        pwd_loc = page.locator(
            'input[name="Passwd"]:visible, '
            '#password input[type="password"]:visible, '
            'input[type="password"]:visible'
        ).first

        try:
            pwd_loc.wait_for(state="visible", timeout=T_ELEMENT)
        except PlaywrightTimeout:
            if _body_has(page, "couldn't find", "find your google account", "no account"):
                return "Failed (Step 3: account not found on Google)"
            log(f"  ⚠️  [Step 3] Password field not visible — unusual page. URL: {page.url}")
            log("  ⚠️  Waiting up to 90s for manual action…")
            pwd_loc.wait_for(state="visible", timeout=T_MANUAL)

        pwd_loc.click()
        pwd_loc.fill(old_password)
        page.wait_for_timeout(400)
        pwd_loc.press("Enter")
        log("  →           Current password submitted.")
        time.sleep(3)
        log(f"  →           Post-login URL: {page.url}")

    except PlaywrightTimeout as exc:
        return (
            f"Failed (Step 3: password field not visible. "
            f"URL: {page.url}. Exception: {exc})"
        )
    except Exception as exc:
        return f"Failed (Step 3 password entry: {exc})"

    if (s := _gate()): return s

    # ── STEP 3b: Wrong-password check ───────────────────────────────────────
    if _body_has(page, "wrong password", "incorrect password", "password is incorrect"):
        return "Failed (Step 3b: wrong current password — check Column B)"

    # ── STEP 3c: Auto-handle Workspace consent prompt ───────────────────────
    for sel in [
        '#confirm',
        'input[name="confirm"]',
        'button:has-text("I understand")',
        'button:has-text("Continue")',
        '[data-action-button]:has-text("Continue")',
    ]:
        if _click_if_visible(page, sel, timeout=2500):
            log(f"  →  [Step 3c] Auto-clicked Workspace prompt: '{sel}'")
            time.sleep(2)
            break

    if (s := _gate()): return s

    # ── STEP 3d: Handle re-auth prompt ─────────────────────────────────────
    try:
        re_auth = page.locator(
            'input[name="Passwd"]:visible, '
            '#password input[type="password"]:visible'
        ).first
        if re_auth.is_visible(timeout=3000):
            log("  →  [Step 3d] Re-auth prompt — re-entering current password…")
            re_auth.click()
            re_auth.fill(old_password)
            page.wait_for_timeout(300)
            re_auth.press("Enter")
            time.sleep(3)
            log(f"  →            Post re-auth URL: {page.url}")
    except Exception:
        pass

    if (s := _gate()): return s

    # ── STEP 4: Arrive on password-change screen ────────────────────────────
    log("  → [Step 4] Navigating to password-change screen…")
    try:
        if not _url_has(page, "signinoptions/password"):
            page.goto(URL_PW_CHANGE, wait_until="domcontentloaded", timeout=T_NAV)
            time.sleep(2)
            log(f"  →           URL after goto: {page.url}")

        if _url_has(page, "challenge", "2sv", "totp", "phone"):
            log("  ⚠️  [Step 4] 2FA / security challenge — complete in browser. Waiting 90s…")
            try:
                page.wait_for_url("**/signinoptions/password**", timeout=T_MANUAL)
                log(f"  →           Challenge cleared. URL: {page.url}")
            except PlaywrightTimeout:
                return f"Skipped (Step 4: 2FA not completed within 90s. URL: {page.url})"

        if _url_has(page, "accounts.google.com") and not _url_has(page, "signinoptions"):
            log(f"  ⚠️  [Step 4] Session not established. URL: {page.url}")
            log("  ⚠️  Waiting up to 90s for manual completion…")
            try:
                page.wait_for_url("**/signinoptions/password**", timeout=T_MANUAL)
            except PlaywrightTimeout:
                return f"Skipped (Step 4: session not established. URL: {page.url})"

    except PlaywrightTimeout as exc:
        return f"Failed (Step 4 navigation timeout: {exc})"
    except Exception as exc:
        return f"Failed (Step 4: {exc})"

    if (s := _gate()): return s

    # ── STEP 5: Fill new + confirm password ────────────────────────────────
    log("  → [Step 5] Filling new-password fields…")
    try:
        new_pw_loc = page.locator('input[type="password"]:visible')
        deadline   = time.time() + 15

        while time.time() < deadline:
            count = new_pw_loc.count()
            if count >= 2:
                break
            log(f"  →           Waiting for 2 PW inputs (found {count})…")
            time.sleep(1)
        else:
            count = new_pw_loc.count()
            if count == 0:
                return (
                    f"Failed (Step 5: no visible password inputs after 15s. "
                    f"URL: {page.url})"
                )
            log("  ⚠️  [Step 5] Only 1 password field found — trying anyway.")

        new_pw_loc.nth(0).click()
        new_pw_loc.nth(0).fill(new_password)
        page.wait_for_timeout(300)
        log("  →           New-password field filled.")

        if new_pw_loc.count() >= 2:
            new_pw_loc.nth(1).click()
            new_pw_loc.nth(1).fill(new_password)
            page.wait_for_timeout(300)
            log("  →           Confirm-password field filled.")

    except PlaywrightTimeout as exc:
        return f"Failed (Step 5 timeout: {exc})"
    except Exception as exc:
        return f"Failed (Step 5 filling: {exc})"

    if (s := _gate()): return s

    # ── STEP 6: Submit ──────────────────────────────────────────────────────
    log("  → [Step 6] Submitting 'Change password'…")
    try:
        submitted = False
        for sel in [
            'button:has-text("Change password"):visible',
            'button:has-text("Save"):visible',
            'button[type="submit"]:visible',
            'div[role="button"]:has-text("Change password"):visible',
            'button[jsname="LgbsSe"]:visible',
            '#save-password-button',
        ]:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=2500):
                    btn.click()
                    submitted = True
                    log(f"  →           Clicked: '{sel}'")
                    break
            except Exception:
                continue

        if not submitted:
            log("  ⚠️  [Step 6] No button found — pressing Enter on last PW field…")
            try:
                pw_inputs = page.locator('input[type="password"]:visible')
                last      = pw_inputs.count() - 1
                if last >= 0:
                    pw_inputs.nth(last).press("Enter")
                    submitted = True
                    log("  →           Pressed Enter on confirm field.")
            except Exception as exc:
                log(f"  →           Enter fallback failed: {exc}")

        if not submitted:
            return (
                f"Failed (Step 6: no submit button found and Enter fallback failed. "
                f"URL: {page.url})"
            )

        # ── Step 6b: Handle "Stay signed in on devices" confirmation dialog ──
        # Some accounts with active phone sessions show a modal dialog after
        # the first "Change password" click.  The original button becomes
        # disabled and a SECOND "Change password" button appears inside the
        # modal.  If no devices → no dialog → we just continue.
        time.sleep(2)

        modal_clicked = False
        try:
            # Strategy A: button inside a modal/alertdialog container
            modal_btn = page.locator(
                '[role="dialog"] button:has-text("Change password"), '
                '[aria-modal="true"] button:has-text("Change password"), '
                '[role="alertdialog"] button:has-text("Change password")'
            ).first
            if modal_btn.is_visible(timeout=3000):
                log("  →  [Step 6b] Device confirmation pop-up detected! "
                    "Clicking modal 'Change password'…")
                modal_btn.click()
                modal_clicked = True
        except Exception:
            pass  # no modal appeared — that's fine

        # Strategy B: "stay signed in" text visible → click last enabled button
        if not modal_clicked:
            try:
                if _body_has(page, "stay signed in on these devices",
                             "stay signed in on your devices"):
                    fallback_btn = page.locator(
                        'button:has-text("Change password"):not([disabled]):visible'
                    ).last
                    if fallback_btn.is_visible(timeout=2000):
                        log("  →  [Step 6b] 'Stay signed in' text detected — "
                            "clicking last active 'Change password' button…")
                        fallback_btn.click()
                        modal_clicked = True
            except Exception:
                pass

        # Wait for Google to finish processing (toast / redirect)
        if modal_clicked:
            time.sleep(4)
            log(f"  →           Post-modal URL: {page.url}")
        else:
            time.sleep(2)  # no modal — shorter wait, password likely already changed

        log(f"  →           Post-submit URL: {page.url}")

    except Exception as exc:
        return f"Failed (Step 6 submit: {exc})"

    if (s := _gate()): return s

    # ── STEP 7: Verify success ──────────────────────────────────────────────
    log("  → [Step 7] Verifying result…")
    try:
        final_url  = page.url
        body_after = ""
        try:
            body_after = page.inner_text("body", timeout=5000).lower()
        except Exception:
            pass

        # ── Signal A: success phrases in body text ──────────────────────
        success_phrases = [
            "password changed",
            "your password was changed",
            "password has been changed",
            "you changed your password",
            "password was updated",
        ]
        success_in_body = any(p in body_after for p in success_phrases)

        # ── Signal B: post-change redirect to myaccount home ───────────
        success_in_url = (
            "myaccount.google.com" in final_url
            and "signinoptions" not in final_url
            and "accounts.google.com" not in final_url
        )

        # ── Signal C: "Continue to your Google Account" / "Get started"
        #    security-checkup landing screen (common after PW change) ──
        success_post_change_screen = any(p in body_after for p in [
            "continue to your google account",
            "get started",
            "review your account",
            "your account is protected",
            "security checkup",
        ])

        # ── Signal D: visible toast / heading banner ────────────────────
        success_toast = False
        try:
            success_toast = page.locator(
                ':text("Password changed"), :text("password changed")'
            ).first.is_visible(timeout=4000)
        except Exception:
            pass

        if success_in_body or success_in_url or success_post_change_screen or success_toast:
            log("  ✅ Password changed successfully!")
            return "Success"

        # ── Still on PW-change page → validation error ─────────────────
        if _url_has(page, "signinoptions/password"):
            err_detail = ""
            try:
                err_loc = page.locator(
                    '[aria-live="assertive"], .error-msg, [role="alert"]'
                ).first
                if err_loc.is_visible(timeout=2000):
                    err_detail = err_loc.inner_text(timeout=2000).strip()
            except Exception:
                pass
            msg = "password-change form still visible"
            if err_detail:
                msg += f" — Google says: '{err_detail}'"
            return f"Failed (Step 7: {msg}. URL: {final_url})"

        # ── Ambiguous ───────────────────────────────────────────────────
        log("  ⚠️  [Step 7] Outcome ambiguous — please verify manually.")
        log(f"  →           Final URL: {final_url}")
        return f"Uncertain (verify manually — URL: {final_url})"

    except Exception as exc:
        return f"Uncertain (Step 7 exception: {exc})"


# ── Batch orchestrator ─────────────────────────────────────────────────────────

class PasswordChangerWorker:
    """
    Runs the full batch in a background daemon thread.
    Recycles the Chrome process every BROWSER_RECYCLE_EVERY accounts.
    """

    def __init__(
        self,
        accounts:        List[Dict[str, str]],
        new_password:    str,
        headed:          bool,
        delay_seconds:   int,
        on_log:          Callable[[str], None],
        on_progress:     Callable[[int, int, int, int], None],
        on_account_done: Callable[[str, str], None],
        on_all_done:     Callable[[], None],
    ):
        self.accounts        = accounts
        self.new_password    = new_password
        self.headed          = headed
        self.delay_seconds   = delay_seconds
        self.on_log          = on_log
        self.on_progress     = on_progress
        self.on_account_done = on_account_done
        self.on_all_done     = on_all_done

        self._paused  = False
        self._stopped = False
        self._thread: Optional[threading.Thread] = None

    # ── Public control API ─────────────────────────────────────────────────

    def start(self):
        _ensure_csv()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def pause(self):
        self._paused = True
        self.on_log("⏸  Paused — will finish current account first.")

    def resume(self):
        self._paused = False
        self.on_log("▶️  Resumed.")

    def stop(self):
        self._stopped = True
        self._paused  = False
        self.on_log("🛑 Stop requested — finishing current account…")

    def is_paused(self)  -> bool: return self._paused
    def is_stopped(self) -> bool: return self._stopped

    # ── Worker thread ──────────────────────────────────────────────────────

    def _run(self):
        total         = len(self.accounts)
        success_count = 0
        failed_count  = 0

        self.on_log(
            f"🚀 Starting batch: {total} accounts  |  "
            f"headed={self.headed}  |  delay={self.delay_seconds}s  |  "
            f"browser recycled every {BROWSER_RECYCLE_EVERY} accounts"
        )
        self.on_progress(0, total, 0, 0)

        with _sync_playwright() as pw:

            browser: Optional[Browser] = None
            accounts_since_recycle     = 0

            def _get_browser() -> Browser:
                nonlocal browser, accounts_since_recycle
                if browser is None:
                    browser = pw.chromium.launch(
                        channel="chrome",
                        headless=not self.headed,
                        args=_BROWSER_ARGS,
                        slow_mo=150,
                    )
                    self.on_log("  🌐 Chrome launched.")
                return browser

            def _recycle_browser():
                nonlocal browser, accounts_since_recycle
                if browser is not None:
                    try:
                        browser.close()
                    except Exception:
                        pass
                    browser = None
                accounts_since_recycle = 0
                self.on_log("  ♻️  Browser recycled (memory cleanup).")

            try:
                for idx, account in enumerate(self.accounts, start=1):
                    if self.is_stopped():
                        break

                    email  = account["email"]
                    old_pw = account["password"]

                    self.on_log(f"\n{'─' * 58}")
                    self.on_log(f"[{idx}/{total}] 🔑 Processing: {email}")

                    # Recycle browser every N accounts
                    if accounts_since_recycle > 0 and accounts_since_recycle % BROWSER_RECYCLE_EVERY == 0:
                        _recycle_browser()

                    b   = _get_browser()
                    ctx = None

                    try:
                        ctx = _new_context(b)
                        page = ctx.new_page()

                        status = _change_password_for_account(
                            page=page,
                            email=email,
                            old_password=old_pw,
                            new_password=self.new_password,
                            log=self.on_log,
                            is_paused=self.is_paused,
                            is_stopped=self.is_stopped,
                        )
                    except Exception:
                        tb = traceback.format_exc()
                        self.on_log(f"  ❌ Unhandled exception:\n{tb}")
                        status = "Failed (unhandled exception — see log)"
                    finally:
                        # Always close the context — never leak it
                        if ctx is not None:
                            try:
                                ctx.close()
                            except Exception:
                                pass

                    accounts_since_recycle += 1

                    # Tally
                    if status.startswith("Success"):
                        success_count += 1
                    else:
                        failed_count += 1

                    self.on_log(f"  → Final status: {status}")
                    self.on_account_done(email, status)

                    _append_result(
                        email=email,
                        old_pw=old_pw,
                        new_pw=self.new_password,
                        status=status,
                    )

                    self.on_progress(idx, total, success_count, failed_count)

                    # Inter-account delay (interruptible)
                    if idx < total and not self.is_stopped():
                        self.on_log(f"  ⏳ Waiting {self.delay_seconds}s before next account…")
                        for _ in range(self.delay_seconds * 2):
                            if self.is_stopped():
                                break
                            time.sleep(0.5)

            finally:
                # Guaranteed browser cleanup even if the loop crashes
                _recycle_browser()

        self.on_log(f"\n{'═' * 58}")
        self.on_log(
            f"✅ Batch complete!  "
            f"Success: {success_count}  |  Failed/Skipped: {failed_count}"
        )
        self.on_log(f"📄 Results saved to: {RESULTS_FILE.resolve()}")
        self.on_all_done()
