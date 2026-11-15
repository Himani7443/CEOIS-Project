# CEOIS — Community Electricity Outage Information System

A Flask + SQLite college CSP prototype for manually maintained outage announcements and community power-supply reports. It is **not connected to live APCPDCL data** and does not send SMS notifications.

## Requirements
- Python 3.10 or newer
- Windows and VS Code (or another editor)

## Setup on Windows
1. Extract the ZIP into a normal project folder.
2. Open that folder in VS Code.
3. Open Terminal → New Terminal.
4. Create a virtual environment:
   ```powershell
   py -m venv .venv
   ```
5. Activate it in PowerShell:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```
   If PowerShell blocks activation, use Command Prompt and run `\.venv\Scripts\activate.bat`, or run `.venv\Scripts\python.exe -m pip ...` directly.
6. Install packages:
   ```powershell
   python -m pip install -r requirements.txt
   ```
7. Copy `.env.example` to a new file named `.env`. Set `SECRET_KEY` to a random value with at least 32 characters, and set your own `ADMIN_USERNAME` and `ADMIN_PASSWORD`. Do not share `.env`.
8. Run the website:
   ```powershell
   python app.py
   ```
9. Open `http://127.0.0.1:5000` in your browser.

## Admin features
- Open **Admin** from the navigation and use the credentials you set in `.env`.
- The dashboard supports report filters, report status updates, and report deletion with confirmation.
- **Manage Outages** lets the administrator add, edit, and delete manually maintained outage announcements.
- Admin sessions expire after 20 minutes of inactivity. Repeated failed logins are temporarily blocked within the running app process.

## Data and privacy
- SQLite data is stored in `ceois.db` beside `database.py`.
- Existing reports are preserved by database initialization.
- Back up `ceois.db` before making manual database changes.
- Do not share real names/problem descriptions in public screenshots or public repositories.
- The ZIP shared for review should not contain `.env`, `.venv`, or Python cache files.

## Prototype limitations
- No live electricity-provider integration.
- No real SMS or email notifications.
- Area status is an aggregate of CEOIS community reports, not confirmation that electricity is available.
- Login throttling is in-memory and intended for this local educational prototype. Before public production deployment, use a persistent rate limiter, HTTPS, managed secrets, and a production-grade deployment setup.
