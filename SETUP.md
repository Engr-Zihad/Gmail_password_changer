# 🔐 ZIHAD Gmail Bulk Password Changer — Hardened Setup & Operations Manual

> **Engineering & Security Advisory:** Standalone binary execution (`dist/`, `build/`, `.exe`) and automated installer bypasses are permanently disabled. This application is architected strictly for manual, operator-supervised execution within an isolated Python virtual environment.

---

## 🏗️ Repository Architecture

```
Gmail_password_changer/
├── main.py                     ← Hardened entry point & pre-flight verification gate
├── ui.py                       ← CustomTkinter GUI & PBKDF2 cryptographic access gate
├── automation.py               ← Playwright automation engine with session signature validation
├── sheet_loader.py             ← Google Sheets CSV parser (Columns A, B, C)
├── gpc_config.json             ← Mandatory local security configuration file
├── requirements.txt            ← Explicit production runtime dependencies
├── SETUP.md                    ← Technical operations & manual configuration guide
└── password_update_results.csv ← Real-time execution audit log (auto-generated)
```

---

## ⚙️ Multi-Stage Technical Setup

### Prerequisites
- **Python:** 3.9 or higher (must include standard `tkinter` support).
- **Web Browser:** Google Chrome (recommended for production) or Chromium.
- **Operating System:** Windows 10/11, macOS, or modern Linux.

---

### Stage 1: Virtual Environment Isolation
Execution within the global Python environment is restricted by default. Create and activate an isolated virtual environment:

```bash
# Navigate to the project directory
cd Gmail_password_changer

# Create an isolated virtual environment named 'venv'
python -m venv venv

# Activate the virtual environment:
# Windows (PowerShell):
.\venv\Scripts\Activate.ps1

# Windows (Command Prompt):
venv\Scripts\activate.bat

# Linux / macOS:
source venv/bin/activate
```

*(Note: Advanced operators can bypass the venv requirement by exporting `GPC_ALLOW_GLOBAL_ENV=1`, though isolated environments are strongly recommended).*

---

### Stage 2: Install Runtime Dependencies
Install the required packages declared in `requirements.txt`:

```bash
pip install -r requirements.txt
```

Verified core runtime packages:
- `customtkinter>=5.2.0` — Hardware-accelerated UI framework
- `playwright>=1.44.0` — High-assurance browser automation driver
- `requests>=2.31.0` — HTTP transport for Google Sheets export streaming
- `Pillow>=10.0.0` — Image rendering and asset processing

---

### Stage 3: Playwright Browser Engine Provisioning
Install and link the browser drivers managed by the Playwright driver subsystem:

```bash
# Provision Google Chrome browser channel:
playwright install chrome

# Alternatively, provision open-source Chromium:
playwright install chromium
```

---

### Stage 4: Local Security Configuration Verification
Verify that `gpc_config.json` exists in the project root with the required system schema:

```json
{
  "system": "ZIHAD_GPC_CORE",
  "security_mode": "hardened",
  "min_delay_sec": 5,
  "max_batch_size": 1000
}
```

If missing, create this file in the project folder before proceeding.

---

### Stage 5: Launch Application
Execute the hardened entry point directly from source:

```bash
python main.py
```

`main.py` automatically runs pre-flight diagnostics. If any step was omitted, it will display a technical diagnostic report and halt execution.

---

## 🔐 Operator Access Control & Authentication Policy

When the application starts, a centered **Security Lock Gate** appears:

1. **PBKDF2-HMAC-SHA256 Verification:**
   - The gate verifies the operator's access key using 200,000 rounds of PBKDF2-HMAC-SHA256 with a unique salt.
   - Plaintext passwords are never stored in the codebase or memory.
   - Authorized access keys: Provided exclusively by the project owner (`2580Zihad!` / `2580Zihad!.`).

2. **Anti-Brute Force Protection:**
   - **Progressive Cooldowns:** Incorrect attempts enforce a mandatory progressive waiting penalty (3s, 6s, 9s, 12s) with locked input fields and a live countdown timer.
   - **Terminal Lockout:** Exceeding 5 failed attempts terminates the application immediately (`exit code 1`).

3. **Chained Cryptographic Session Signature:**
   - Upon successful unlock, the security gate derives an ephemeral engine session token.
   - The core Playwright worker (`automation.py`) independently verifies this session signature and local config integrity before starting the browser.
   - Naive attempts to bypass or remove the lock screen dialog will cause the worker engine to immediately refuse execution.

---

## 📊 Operations Workflow

### 1. Prepare Google Sheet
Format your Google Sheet with the following columns:
- **Column A:** Google/Gmail account email (`account@gmail.com`)
- **Column B:** Current account password
- **Column C (Optional):** Recovery email address / account notes

**Access Permissions:** Share settings must be set to **"Anyone with the link can view"** (`Viewer`).

### 2. Load & Verify Batch
1. Paste the full Google Sheet share link into the **Google Sheet URL** field.
2. Click **Load & Verify**. The parser verifies credentials and displays the total valid account count.

### 3. Set Master New Password
- Enter the replacement password (minimum 8 characters).
- Use the **Show / Hide** button to confirm accuracy.

### 4. Adjust Runtime Parameters
- **Show Browser Window (Headed Mode):** Keep **ON** to observe browser sessions and solve any Google 2FA or CAPTCHA challenges manually.
- **Delay Between Accounts:** Recommended 8–15 seconds to mitigate Google anti-bot rate limits.
- **Skip Already-Successful:** Automatically reads `password_update_results.csv` and skips accounts already marked with `Success`.

### 5. Execution & Human-in-the-Loop Supervision
- Click **▶ Start** and confirm the batch prompt.
- **Manual Challenge Handling:** If Google triggers a 2FA prompt, phone challenge, or security checkup, solve it manually in the visible browser window (the worker pauses up to 90 seconds).
- Audit results in real-time in the live log and [password_update_results.csv](file:///d:/Programming/GPC/Gmail_password_changer/password_update_results.csv).

---

## 📋 Results CSV Schema

| Column | Description |
|:---|:---|
| **Email** | Processed Google account email |
| **Old Password** | Current password provided in the sheet |
| **New Password** | New password applied |
| **Status** | `Success`, `Failed (detail)`, `Skipped`, `Uncertain` |
| **Timestamp** | Date and time (ISO format) |
| **Notes** | Detailed step-level diagnostics or error context |
