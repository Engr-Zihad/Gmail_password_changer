"""
ui.py  (v3 — hardened)
-----------------------
CustomTkinter GUI for the Gmail Bulk Password Changer.

New in v3:
  • Rock-solid _on_sheet_error: guards against None / non-str errors so the
    "Sheet load error: None" bug can never surface again.
  • Skip-already-successful checkbox: reads password_update_results.csv and
    filters out emails whose last status == "Success" before the batch starts.
  • _set_buttons_running also toggles the new skip checkbox.
  • All other UI sections unchanged.
"""

import csv
import sys
import shutil
import threading
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import List, Dict, Optional, Set

import customtkinter as ctk

import sheet_loader
from automation import PasswordChangerWorker, RESULTS_FILE


# ── App-wide theme ─────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

FONT_TITLE  = ("Segoe UI", 20, "bold")
FONT_LABEL  = ("Segoe UI", 13)
FONT_SMALL  = ("Segoe UI", 11)
FONT_MONO   = ("Consolas", 11)
FONT_BUTTON = ("Segoe UI", 13, "bold")

COLOR_SUCCESS = "#2ECC71"
COLOR_FAIL    = "#E74C3C"
COLOR_WARN    = "#F39C12"
COLOR_INFO    = "#5DADE2"
COLOR_MUTED   = "#7F8C8D"


# ── Helper: load already-succeeded emails from results CSV ─────────────────────

def _load_already_succeeded() -> Set[str]:
    """
    Read password_update_results.csv and return the set of email addresses
    whose LAST recorded Status starts with 'Success'.
    (An email that failed once then succeeded on a re-run is treated as done.)
    """
    succeeded: Dict[str, str] = {}  # email -> latest status
    if not RESULTS_FILE.exists():
        return set()
    try:
        with open(RESULTS_FILE, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                email  = (row.get("Email") or "").strip().lower()
                status = (row.get("Status") or "").strip()
                if email:
                    succeeded[email] = status   # last row wins
    except Exception:
        return set()
    return {e for e, s in succeeded.items() if s.startswith("Success")}


# ── Security Lock Screen ───────────────────────────────────────────────────────

class LockScreen(ctk.CTkToplevel):
    """
    Modal security gate dialog shown before main window reveals.
    Only allows access if correct password is provided.
    """
    def __init__(self, master):
        super().__init__(master)
        self.master = master
        self.title("🔐 ZIHAD Gmail pw changer — Security Lock")
        self.geometry("400x260")
        self.resizable(False, False)

        # Center on screen
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - 400) // 2
        y = (sh - 260) // 2
        self.geometry(f"400x260+{x}+{y}")

        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self.after(150, lambda: self.pw_entry.focus_set())

    def _build_ui(self):
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=24, pady=20)

        # Title label
        title_lbl = ctk.CTkLabel(
            container,
            text="Enter Security Password to Unlock",
            font=("Segoe UI", 15, "bold"),
            text_color="#5DADE2",
        )
        title_lbl.pack(pady=(4, 14))

        # Password input row
        pw_row = ctk.CTkFrame(container, fg_color="transparent")
        pw_row.pack(fill="x", pady=(0, 4))

        self.pw_var = ctk.StringVar()
        self.pw_entry = ctk.CTkEntry(
            pw_row,
            textvariable=self.pw_var,
            placeholder_text="Enter password…",
            font=FONT_LABEL,
            height=38,
            show="•",
        )
        self.pw_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.pw_entry.bind("<Return>", lambda event: self._verify())

        self.toggle_btn = ctk.CTkButton(
            pw_row,
            text="Show",
            font=FONT_SMALL,
            width=65,
            height=38,
            fg_color="#2C3E50",
            hover_color="#34495E",
            command=self._toggle_show,
        )
        self.toggle_btn.pack(side="right")

        # Status label
        self.status_lbl = ctk.CTkLabel(
            container,
            text="",
            font=FONT_SMALL,
            text_color=COLOR_FAIL,
        )
        self.status_lbl.pack(pady=(0, 10))

        # Unlock button
        self.unlock_btn = ctk.CTkButton(
            container,
            text="Unlock App",
            font=FONT_BUTTON,
            height=40,
            fg_color="#1ABC9C",
            hover_color="#16A085",
            command=self._verify,
        )
        self.unlock_btn.pack(fill="x")

    def _toggle_show(self):
        if self.pw_entry.cget("show") == "•":
            self.pw_entry.configure(show="")
            self.toggle_btn.configure(text="Hide")
        else:
            self.pw_entry.configure(show="•")
            self.toggle_btn.configure(text="Show")

    def _verify(self):
        val = self.pw_var.get().strip()
        if val in ("2580Zihad!", "2580Zihad!."):
            self.destroy()
            self.master.deiconify()
            self.master.lift()
            self.master.focus_force()
        else:
            self.status_lbl.configure(text="❌ Incorrect password! Access denied.", text_color=COLOR_FAIL)
            self.pw_entry.delete(0, "end")
            self.pw_entry.focus_set()

    def _on_close(self):
        self.master.destroy()
        sys.exit(0)


# ── Main window ────────────────────────────────────────────────────────────────

class App(ctk.CTk):

    def __init__(self):
        super().__init__()

        # Start hidden until security password unlocked
        self.withdraw()

        self.title("ZIHAD Gmail pw changer")
        self.geometry("880x820")
        self.minsize(760, 700)
        self.resizable(True, True)

        # Center main window
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = max(0, (sw - 880) // 2)
        y = max(0, (sh - 820) // 2)
        self.geometry(f"880x820+{x}+{y}")

        # State
        self._accounts: List[Dict[str, str]] = []
        self._worker:   Optional[PasswordChangerWorker] = None
        self._running   = False
        self._paused    = False
        self._total     = 0

        self._build_ui()

        # Display centered security lock screen
        self.lock_screen = LockScreen(self)

    # ══════════════════════════════════════════════════════════════════════
    # UI Construction
    # ══════════════════════════════════════════════════════════════════════

    def _build_ui(self):

        # ── Title ──────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=20, pady=(18, 0))
        ctk.CTkLabel(hdr, text="🔐  ZIHAD Gmail pw changer",
                     font=FONT_TITLE).pack(side="left")
        ctk.CTkLabel(hdr, text="powered by Playwright + CustomTkinter",
                     font=FONT_SMALL, text_color=COLOR_MUTED).pack(side="right", padx=4)
        ctk.CTkFrame(self, height=2, fg_color="#2C3E50").pack(fill="x", padx=20, pady=(10, 0))

        # ── Scrollable body ────────────────────────────────────────────────
        main = ctk.CTkScrollableFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=20, pady=10)

        # ── Section 1: Google Sheet URL ────────────────────────────────────
        self._section_header(main, "1  │  Google Sheet URL")

        row1 = ctk.CTkFrame(main, fg_color="transparent")
        row1.pack(fill="x", pady=(0, 4))

        self._sheet_url_var = ctk.StringVar()
        self._sheet_entry = ctk.CTkEntry(
            row1,
            textvariable=self._sheet_url_var,
            placeholder_text="Paste your Google Sheet share link here…",
            font=FONT_LABEL, height=40,
        )
        self._sheet_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self._load_btn = ctk.CTkButton(
            row1, text="Load & Verify", font=FONT_BUTTON,
            width=150, height=40, command=self._on_load_sheet,
        )
        self._load_btn.pack(side="right")

        self._sheet_status_label = ctk.CTkLabel(
            main, text="No sheet loaded yet.",
            font=FONT_SMALL, text_color=COLOR_MUTED, anchor="w",
        )
        self._sheet_status_label.pack(fill="x", pady=(0, 10))

        # ── Section 2: New Password ────────────────────────────────────────
        self._section_header(main, "2  │  New Password (applied to ALL accounts)")

        row2 = ctk.CTkFrame(main, fg_color="transparent")
        row2.pack(fill="x", pady=(0, 4))

        self._new_pw_var = ctk.StringVar()
        self._pw_entry = ctk.CTkEntry(
            row2, textvariable=self._new_pw_var,
            placeholder_text="Enter new password (min. 8 characters)…",
            font=FONT_LABEL, height=40, show="●",
        )
        self._pw_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self._pw_toggle_btn = ctk.CTkButton(
            row2, text="Show", font=FONT_SMALL, width=70, height=40,
            fg_color="#2C3E50", hover_color="#34495E",
            command=self._toggle_password_visibility,
        )
        self._pw_toggle_btn.pack(side="right")

        self._pw_strength_label = ctk.CTkLabel(
            main, text="", font=FONT_SMALL, text_color=COLOR_MUTED, anchor="w",
        )
        self._pw_strength_label.pack(fill="x", pady=(0, 2))
        self._new_pw_var.trace_add("write", self._on_password_typed)

        # ── Section 3: Settings ────────────────────────────────────────────
        self._section_header(main, "3  │  Settings")

        settings_frame = ctk.CTkFrame(main, corner_radius=10)
        settings_frame.pack(fill="x", pady=(0, 10))

        # Headed switch
        sw_row = ctk.CTkFrame(settings_frame, fg_color="transparent")
        sw_row.pack(fill="x", padx=16, pady=(12, 6))
        ctk.CTkLabel(sw_row, text="🖥️  Show browser window (headed mode)",
                     font=FONT_LABEL).pack(side="left")
        self._headed_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(sw_row, variable=self._headed_var, text="",
                      onvalue=True, offvalue=False, width=56).pack(side="right")

        # Delay slider
        delay_row = ctk.CTkFrame(settings_frame, fg_color="transparent")
        delay_row.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkLabel(delay_row, text="⏳  Delay between accounts:",
                     font=FONT_LABEL).pack(side="left")
        self._delay_label = ctk.CTkLabel(delay_row, text="8 s",
                                          font=FONT_LABEL, width=50)
        self._delay_label.pack(side="right")
        self._delay_var = ctk.IntVar(value=8)
        ctk.CTkSlider(
            delay_row, from_=5, to=30, number_of_steps=25,
            variable=self._delay_var, command=self._on_delay_change,
        ).pack(side="right", fill="x", expand=True, padx=(10, 8))

        # ── Skip-already-successful checkbox ──────────────────────────────
        skip_row = ctk.CTkFrame(settings_frame, fg_color="transparent")
        skip_row.pack(fill="x", padx=16, pady=(0, 12))

        self._skip_done_var = ctk.BooleanVar(value=True)
        self._skip_checkbox = ctk.CTkCheckBox(
            skip_row,
            text="  ⏭️  Skip already-successful emails (from password_update_results.csv)",
            variable=self._skip_done_var,
            font=FONT_LABEL,
            checkbox_width=22,
            checkbox_height=22,
        )
        self._skip_checkbox.pack(side="left", anchor="w")

        # ── Section 4: Progress ────────────────────────────────────────────
        self._section_header(main, "4  │  Progress")

        prog_frame = ctk.CTkFrame(main, corner_radius=10)
        prog_frame.pack(fill="x", pady=(0, 10))

        self._progress_bar = ctk.CTkProgressBar(prog_frame, height=18, corner_radius=8)
        self._progress_bar.pack(fill="x", padx=16, pady=(14, 6))
        self._progress_bar.set(0)

        counters_row = ctk.CTkFrame(prog_frame, fg_color="transparent")
        counters_row.pack(fill="x", padx=16, pady=(0, 12))

        self._progress_text = ctk.CTkLabel(
            counters_row, text="Processed: 0 / 0", font=FONT_LABEL)
        self._progress_text.pack(side="left")

        self._success_label = ctk.CTkLabel(
            counters_row, text="✅  Success: 0",
            font=FONT_LABEL, text_color=COLOR_SUCCESS)
        self._success_label.pack(side="left", padx=(24, 0))

        self._failed_label = ctk.CTkLabel(
            counters_row, text="❌  Failed: 0",
            font=FONT_LABEL, text_color=COLOR_FAIL)
        self._failed_label.pack(side="left", padx=(24, 0))

        self._skipped_label = ctk.CTkLabel(
            counters_row, text="⏭️  Skipped: 0",
            font=FONT_LABEL, text_color=COLOR_MUTED)
        self._skipped_label.pack(side="left", padx=(24, 0))

        # ── Section 5: Live Log ────────────────────────────────────────────
        self._section_header(main, "5  │  Live Log")

        log_frame = ctk.CTkFrame(main, corner_radius=10)
        log_frame.pack(fill="both", expand=True, pady=(0, 10))

        self._log_box = ctk.CTkTextbox(
            log_frame, font=FONT_MONO, height=220,
            wrap="word", state="disabled",
        )
        self._log_box.pack(fill="both", expand=True, padx=8, pady=8)

        tb = self._log_box._textbox
        tb.tag_config("success", foreground=COLOR_SUCCESS)
        tb.tag_config("fail",    foreground=COLOR_FAIL)
        tb.tag_config("warn",    foreground=COLOR_WARN)
        tb.tag_config("info",    foreground=COLOR_INFO)
        tb.tag_config("muted",   foreground=COLOR_MUTED)

        log_clear_row = ctk.CTkFrame(main, fg_color="transparent")
        log_clear_row.pack(fill="x", pady=(0, 2))
        ctk.CTkButton(
            log_clear_row, text="Clear Log", font=FONT_SMALL,
            width=90, height=28, fg_color="#2C3E50", hover_color="#34495E",
            command=self._clear_log,
        ).pack(side="right")

        # ── Section 6: Action Buttons ──────────────────────────────────────
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(4, 18))

        self._start_btn = ctk.CTkButton(
            btn_frame, text="▶  Start", font=FONT_BUTTON, height=46,
            fg_color="#1ABC9C", hover_color="#16A085", command=self._on_start,
        )
        self._start_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self._pause_btn = ctk.CTkButton(
            btn_frame, text="⏸  Pause", font=FONT_BUTTON, height=46,
            fg_color="#F39C12", hover_color="#D68910",
            command=self._on_pause_resume, state="disabled",
        )
        self._pause_btn.pack(side="left", fill="x", expand=True, padx=6)

        self._stop_btn = ctk.CTkButton(
            btn_frame, text="⏹  Stop", font=FONT_BUTTON, height=46,
            fg_color=COLOR_FAIL, hover_color="#C0392B",
            command=self._on_stop, state="disabled",
        )
        self._stop_btn.pack(side="left", fill="x", expand=True, padx=6)

        self._export_btn = ctk.CTkButton(
            btn_frame, text="📄  Export Results CSV", font=FONT_BUTTON, height=46,
            fg_color="#2980B9", hover_color="#2471A3", command=self._on_export_csv,
        )
        self._export_btn.pack(side="left", fill="x", expand=True, padx=(6, 0))

    # ══════════════════════════════════════════════════════════════════════
    # UI helpers
    # ══════════════════════════════════════════════════════════════════════

    def _section_header(self, parent, text: str):
        ctk.CTkLabel(parent, text=text, font=("Segoe UI", 13, "bold"),
                     anchor="w", text_color=COLOR_INFO).pack(fill="x", pady=(12, 4))

    def _log(self, message: str):
        """Thread-safe log append with colour tagging."""
        def _append():
            tb = self._log_box._textbox
            self._log_box.configure(state="normal")
            ts   = datetime.now().strftime("%H:%M:%S")
            line = f"[{ts}] {message}\n"
            msg_l = message.lower()
            if "✅" in message or "success" in msg_l:
                tag = "success"
            elif "❌" in message or "failed" in msg_l or "error" in msg_l:
                tag = "fail"
            elif "⚠️" in message or "warn" in msg_l or "challenge" in msg_l or "skipped" in msg_l:
                tag = "warn"
            elif "🚀" in message or "→" in message or "navigat" in msg_l:
                tag = "info"
            elif "─" in message or "═" in message:
                tag = "muted"
            else:
                tag = None
            if tag:
                tb.insert("end", line, tag)
            else:
                tb.insert("end", line)
            self._log_box.configure(state="disabled")
            self._log_box._textbox.see("end")
        self.after(0, _append)

    def _clear_log(self):
        self._log_box.configure(state="normal")
        self._log_box.delete("1.0", "end")
        self._log_box.configure(state="disabled")

    def _toggle_password_visibility(self):
        if self._pw_entry.cget("show") == "●":
            self._pw_entry.configure(show="")
            self._pw_toggle_btn.configure(text="Hide")
        else:
            self._pw_entry.configure(show="●")
            self._pw_toggle_btn.configure(text="Show")

    def _on_delay_change(self, value):
        self._delay_label.configure(text=f"{int(value)} s")

    def _on_password_typed(self, *_):
        pw = self._new_pw_var.get()
        n  = len(pw)
        if n == 0:
            self._pw_strength_label.configure(text="", text_color=COLOR_MUTED)
        elif n < 8:
            self._pw_strength_label.configure(
                text=f"⚠️  Too short ({n}/8 minimum)", text_color=COLOR_WARN)
        elif n < 12:
            self._pw_strength_label.configure(
                text="🟡  Acceptable length", text_color=COLOR_WARN)
        elif n < 16:
            self._pw_strength_label.configure(
                text="🟢  Good password length", text_color=COLOR_SUCCESS)
        else:
            self._pw_strength_label.configure(
                text="💪  Strong password length", text_color=COLOR_SUCCESS)

    def _set_buttons_running(self, running: bool):
        if running:
            self._start_btn.configure(state="disabled")
            self._pause_btn.configure(state="normal")
            self._stop_btn.configure(state="normal")
            self._load_btn.configure(state="disabled")
            self._sheet_entry.configure(state="disabled")
            self._pw_entry.configure(state="disabled")
            self._skip_checkbox.configure(state="disabled")
        else:
            self._start_btn.configure(state="normal")
            self._pause_btn.configure(state="disabled", text="⏸  Pause")
            self._stop_btn.configure(state="disabled")
            self._load_btn.configure(state="normal")
            self._sheet_entry.configure(state="normal")
            self._pw_entry.configure(state="normal")
            self._skip_checkbox.configure(state="normal")

    # ══════════════════════════════════════════════════════════════════════
    # Event handlers
    # ══════════════════════════════════════════════════════════════════════

    def _on_load_sheet(self):
        url = self._sheet_url_var.get().strip()
        if not url:
            messagebox.showwarning("Missing URL",
                                   "Please paste a Google Sheet URL first.")
            return

        self._load_btn.configure(text="Loading…", state="disabled")
        self._sheet_status_label.configure(text="⏳  Fetching sheet…",
                                            text_color=COLOR_INFO)
        self._log(f"Loading Google Sheet: {url[:80]}…")

        def _do_load():
            # Wrap the entire call; capture both value and exception cleanly
            accounts = []
            csv_url  = None
            error    = None
            try:
                accounts, csv_url = sheet_loader.load_accounts(url)
            except Exception as exc:
                error = exc   # keep the actual exception object

            if error is not None:
                # Convert to a clean string — guard against None str() edge-cases
                err_msg = str(error) if error is not None else "Unknown error (no details)"
                if not err_msg or err_msg.strip() == "None":
                    err_msg = (
                        "An unknown error occurred while loading the sheet.\n"
                        "Make sure the sheet is shared publicly and try again."
                    )
                self.after(0, lambda: self._on_sheet_error(err_msg))
            elif not accounts:
                # Shouldn't happen with the new sheet_loader, but guard anyway
                self.after(0, lambda: self._on_sheet_error(
                    "No valid accounts found in the sheet.\n"
                    "Make sure Column A = Email and Column B = Password."
                ))
            else:
                self._accounts = accounts
                self.after(0, lambda: self._on_sheet_loaded(accounts, csv_url))

        threading.Thread(target=_do_load, daemon=True).start()

    def _on_sheet_loaded(self, accounts: list, csv_url: str):
        n = len(accounts)
        csv_display = (csv_url or "")[:70]
        self._sheet_status_label.configure(
            text=f"✅  {n} account(s) loaded!   CSV: {csv_display}…",
            text_color=COLOR_SUCCESS,
        )
        self._load_btn.configure(text="Load & Verify", state="normal")
        self._log(f"✅ Sheet loaded: {n} accounts found.")
        for a in accounts[:3]:
            self._log(f"   Preview → {a['email']}")
        if n > 3:
            self._log(f"   … and {n - 3} more.")

    def _on_sheet_error(self, error: str):
        # Final safety net: error must always be a non-empty string
        if not error or not isinstance(error, str) or error.strip() in ("", "None"):
            error = (
                "An unknown error occurred while loading the sheet.\n"
                "Make sure the sheet is shared publicly and try again."
            )
        short = error[:120].replace("\n", " ")
        self._sheet_status_label.configure(
            text=f"❌  {short}", text_color=COLOR_FAIL)
        self._load_btn.configure(text="Load & Verify", state="normal")
        self._log(f"❌ Sheet load error: {error}")
        messagebox.showerror("Sheet Load Failed", error)

    def _on_start(self):
        if not self._accounts:
            messagebox.showwarning("No Accounts",
                                   "Please load a Google Sheet first.")
            return

        new_pw = self._new_pw_var.get().strip()
        if len(new_pw) < 8:
            messagebox.showwarning(
                "Weak Password",
                f"The new password must be at least 8 characters.\n"
                f"(Current length: {len(new_pw)})",
            )
            return

        # ── Apply skip-already-successful filter ───────────────────────────
        accounts_to_run = self._accounts
        skip_count      = 0

        if self._skip_done_var.get():
            already_done = _load_already_succeeded()
            if already_done:
                before = len(accounts_to_run)
                accounts_to_run = [
                    a for a in accounts_to_run
                    if a["email"].strip().lower() not in already_done
                ]
                skip_count = before - len(accounts_to_run)
                self._log(
                    f"⏭️  Skip filter: {skip_count} already-successful account(s) removed. "
                    f"{len(accounts_to_run)} remaining."
                )

        if not accounts_to_run:
            messagebox.showinfo(
                "All Done Already!",
                f"All {len(self._accounts)} account(s) in the sheet already have "
                f"'Success' in password_update_results.csv.\n\n"
                "Uncheck 'Skip already-successful emails' to re-run them.",
            )
            return

        confirm = messagebox.askyesno(
            "Confirm Batch Start",
            f"About to change passwords for {len(accounts_to_run)} account(s)."
            + (f"\n({skip_count} already-successful account(s) skipped)" if skip_count else "")
            + f"\n\nNew password: {'●' * len(new_pw)}"
            + "\n\nThis CANNOT be undone automatically.\n\nProceed?",
        )
        if not confirm:
            return

        self._running = True
        self._paused  = False
        self._total   = len(accounts_to_run)
        self._set_buttons_running(True)
        self._progress_bar.set(0)
        self._progress_text.configure(text=f"Processed: 0 / {self._total}")
        self._success_label.configure(text="✅  Success: 0")
        self._failed_label.configure(text="❌  Failed: 0")
        self._skipped_label.configure(text=f"⏭️  Skipped: {skip_count}")

        self._worker = PasswordChangerWorker(
            accounts=accounts_to_run,
            new_password=new_pw,
            headed=self._headed_var.get(),
            delay_seconds=int(self._delay_var.get()),
            on_log=self._log,
            on_progress=self._on_progress_update,
            on_account_done=self._on_account_done,
            on_all_done=self._on_all_done,
        )
        self._worker.start()

    def _on_pause_resume(self):
        if self._worker is None:
            return
        if not self._paused:
            self._worker.pause()
            self._paused = True
            self._pause_btn.configure(text="▶  Resume")
        else:
            self._worker.resume()
            self._paused = False
            self._pause_btn.configure(text="⏸  Pause")

    def _on_stop(self):
        if self._worker:
            self._worker.stop()

    def _on_export_csv(self):
        if not RESULTS_FILE.exists():
            messagebox.showinfo(
                "No Results Yet",
                "No results file found.\nRun the batch first to generate results.",
            )
            return
        dest = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile=f"password_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            title="Export Results CSV",
        )
        if dest:
            shutil.copy2(RESULTS_FILE, dest)
            self._log(f"📄 Results exported to: {dest}")
            messagebox.showinfo("Export Complete", f"Results saved to:\n{dest}")

    # ══════════════════════════════════════════════════════════════════════
    # Worker callbacks  (always via self.after → main thread)
    # ══════════════════════════════════════════════════════════════════════

    def _on_progress_update(self, current: int, total: int,
                             success: int, failed: int):
        def _upd():
            frac = current / total if total > 0 else 0
            self._progress_bar.set(frac)
            self._progress_text.configure(text=f"Processed: {current} / {total}")
            self._success_label.configure(text=f"✅  Success: {success}")
            self._failed_label.configure(text=f"❌  Failed: {failed}")
        self.after(0, _upd)

    def _on_account_done(self, email: str, status: str):
        pass  # live logging already handled inside the worker via on_log

    def _on_all_done(self):
        def _upd():
            self._running = False
            self._paused  = False
            self._set_buttons_running(False)
        self.after(0, _upd)
