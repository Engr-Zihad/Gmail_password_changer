# 🔐 Gmail Bulk Password Changer — Setup Guide

## Project Structure

```
Gmail pw/
├── main.py               ← Entry point — run this
├── ui.py                 ← CustomTkinter GUI
├── automation.py         ← Playwright automation engine
├── sheet_loader.py       ← Google Sheet URL → CSV parser
├── requirements.txt      ← Python dependencies
├── SETUP.md              ← This file
└── password_update_results.csv   ← Auto-created after first run
```

---

## ⚙️ One-Time Setup (run these once)

Open **Command Prompt** or **PowerShell** in the project folder:

```bash
# 1. (Optional but recommended) Create a virtual environment
python -m venv venv
venv\Scripts\activate

# 2. Install Python packages
pip install -r requirements.txt

# 3. Install Playwright's Chrome browser driver
playwright install chrome

# 4. Launch the app
python main.py
```

> **Requires:** Python 3.9+ and Google Chrome already installed on your PC.

---

## 🚀 How to Use

### Step 1 — Prepare your Google Sheet
- **Column A:** Email address (e.g. `user@gmail.com`)
- **Column B:** Current password
- Share the sheet: **Share → Anyone with the link → Viewer**
- Copy the share URL

### Step 2 — Load the sheet
1. Paste the Google Sheet URL into the first field.
2. Click **"Load & Verify"** — it will tell you how many accounts were found.

### Step 3 — Set the new password
- Type the new password (minimum 8 characters).
- Use the **Show/Hide** toggle to confirm it.

### Step 4 — Adjust settings
| Setting | Recommended |
|---------|-------------|
| Show browser window | **ON** (lets you solve CAPTCHAs manually) |
| Delay between accounts | **8–15 seconds** (reduces rate-limiting risk) |

### Step 5 — Start
- Click **▶ Start** and confirm the prompt.
- Watch the live log for per-account status.
- If a CAPTCHA or 2FA prompt appears, solve it manually — the app waits 90 seconds.
- Results are saved to `password_update_results.csv` **immediately** after each account.

### Step 6 — Export results
- Click **📄 Export Results CSV** to save a copy anywhere you like.

---

## ⚠️ Important Notes

1. **Google may block automated logins.** Using headed mode (browser visible) and a reasonable delay greatly reduces this risk. If an account is blocked, the log will tell you.

2. **2FA accounts:** If an account has two-factor authentication enabled, the app will pause and wait up to 90 seconds for you to complete it manually in the browser window.

3. **Wrong password:** If the current password in Column B is wrong, the account is logged as `Failed` and the batch continues.

4. **Results file** (`password_update_results.csv`) is appended after every account — even if the app crashes mid-batch, all previously processed accounts are already saved.

5. **Never share** `password_update_results.csv` — it contains plaintext passwords.

---

## 📋 Results CSV Columns

| Column | Description |
|--------|-------------|
| Email | The Gmail account |
| Old Password | The password from the sheet |
| New Password | The new password applied |
| Status | `Success`, `Failed (reason)`, `Skipped`, `Uncertain` |
| Timestamp | Date and time of processing |
| Notes | Extra context about failures |
