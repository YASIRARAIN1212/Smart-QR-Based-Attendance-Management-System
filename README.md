# Smart QR-Based Attendance Management System

# CampusAttend 🎓
### QR-Based Student Attendance Management System

**University project:** EF101-P10 · Fall 2026  
**Project contributor:** Muhammad Yasir 233, Muhammad Hassan 220, Muhammad Hamza 240  
**Stack:** Python · Flask · Jinja2 · JavaScript · Tailwind CSS · SQLAlchemy · SQLite  
**Status:** Educational demonstration / pre-production prototype

## Contents
1. [Overview](#overview)
2. [Features](#features)
3. [Technology stack](#technology-stack)
4. [Project structure](#project-structure)
5. [Installation and local setup](#installation-and-local-setup)
6. [Demo accounts](#demo-accounts)
7. [How to use CampusAttend](#how-to-use-campusattend)
8. [How QR and GPS attendance works](#how-qr-and-gps-attendance-works)
9. [Database explained](#database-explained)
10. [Customization](#customization)
11. [Environment configuration](#environment-configuration)
12. [Phone testing over HTTPS](#phone-testing-over-https)
13. [Testing and troubleshooting](#testing-and-troubleshooting)
14. [Deployment checklist](#deployment-checklist)

## Overview
CampusAttend is a browser-based university attendance application. A professor creates a class session and displays a QR code. A logged-in student scans it with a phone. The Flask backend validates the QR token, session rules, student eligibility, and GPS distance, then saves an attendance record. Professors, students, and administrators view records through role-specific dashboards.

**Architecture:** Phone/Browser → HTML + JavaScript → Flask routes → SQLAlchemy → Database → Dashboards and reports.

## Features

### Student
- Login with student account (undergraduate or postgraduate).
- Scan class QR codes using the device camera.
- Share GPS location when prompted for location verification.
- View attendance dashboard and daily/weekly attendance summaries.
- View recorded attendance; dashboard metrics depend on session and reporting rules.

### Professor / Faculty (`employee` role)
- Create and manage teaching sessions associated with subjects.
- Generate and refresh session QR codes.
- View student check-ins and verification status.
- Export attendance to CSV and Excel.
- Manual attendance CSV import is present in the inspected update; manually imported rows are marked `MANUAL_PRESENT`, QR/GPS `VERIFIED`.

### Administrator
- Manage users and subjects.
- Review sessions, attendance and subject enrollments.
- Inspect attendance and audit logs.
- Export attendance reports and use administrative email/job features where configured.

### Verification and platform features
- Signed QR tokens and expiry validation.
- Time-limited class sessions.
- GPS radius verification (default code limit: 100 m; check current configuration).
- Duplicate check-in prevention for the same student/session.
- Role-based route access, password hashing, CAPTCHA-related code, rate limiting and CSRF protection.
- Optional SMTP notifications and scheduled weekly report job.
- Responsive browser UI, Flask templates and Tailwind styling.

**Important:** The availability and accuracy of individual reports, email sending, and dashboard statistics should be confirmed by testing the deployed version.

## Technology stack

| Technology | Purpose |
|---|---|
| Python | Backend language |
| Flask | HTTP routes and application server |
| Flask Blueprints | Organize student, teacher and admin routes |
| Jinja2 / HTML | Render dashboards and forms |
| JavaScript | QR camera, GPS and browser interactions |
| Tailwind CSS | User-interface styling |
| SQLAlchemy / Flask-SQLAlchemy | Database models and queries |
| SQLite | Local development/demo database |
| Flask-Migrate / Alembic | Database schema migrations |
| PostgreSQL + psycopg2 | Option for a persistent hosted database |
| APScheduler | Background scheduled jobs |
| Flask-Mail / SMTP | Optional email reporting |
| pytest | Automated tests |
| Cloudflare Tunnel | Temporary HTTPS access during local phone testing |

## Project structure

```text
Smart-QR-Based-Attendance-Management-System/
│
├── __pycache__/
├── .venv/
├── .env
├── .gitattributes
├── .gitignore
│
├── instance/
│   └── attendance.db
│
├── LAB/
│   ├── LAB
│   ├── migrations/
│   │   ├── alembic.ini
│   │   ├── env.py
│   │   ├── README
│   │   └── script.py.mako
│   │
│   ├── static/
│   │   ├── css/
│   │   ├── images/
│   │   └── qr_codes/
│   │
│   └── templates/
│       └── admin/
│           ├── audit_logs.html
│           ├── create_session.html
│           ├── create_subject.html
│           ├── create_user.html
│           ├── dashboard.html
│           ├── edit_user.html
│           ├── email_settings.html
│           ├── enrollments.html
│           ├── list_users.html
│           ├── qr_attendance.html
│           ├── scheduled_jobs.html
│           ├── session_attendance.html
│           ├── student_records.html
│           └── view_user.html
│
├
│   │
│   ├── auth/
│   │   ├── admin_login.html
│   │   ├── change_password_required.html
│   │   ├── forgot_password.html
│   │   ├── login_form.html
│   │   ├── login.html
│   │   └── reset_password.html
│   │
│   ├── email/
│   │   ├── password_reset.html
│   │   ├── weekly_report.html
│   │   └── weekly_report.txt
│   │
│   ├── student/
│   │   ├── daily_attendance.html
│   │   ├── dashboard.html
│   │   ├── scan_qr.html
│   │   └── weekly_attendance.html
│   │
│   ├── teacher/
│   │   ├── create_session.html
│   │   ├── dashboard.html
│   │   ├── session_attendance.html
│   │   ├── upload_attendance.html
│   │   └── view_session.html
│   │
│   ├── base.html
│   └── error.html
│
├── tests/
│   └── test_core.py
│
├── views/
│
├── app.py
├── auth.py
├── captcha.py
├── CONTRIBUTIONS_TEMPLATE.md
├── demo_database_backup.db
├── extensions.py
├── init_db.py
├── LICENSE
├── mailer.py
├── migrate_database.py
├── migrate_to_neon.py
├── models.py
├── package-lock.json
├── package.json
├── README.md
├── requirements.txt
├── restore_demo_database.py
├── seed_data.py
├── tailwind.config.js
└── utils.py
```
> The ZIP you received may contain one extra enclosing folder. In VS Code, open the **inner folder containing `app.py` and `requirements.txt`**. Some distributed ZIPs omit the active `instance/attendance.db`; do not assume the runtime database is included.

## Installation and local setup

### Requirements
- Windows 10/11 (instructions below), Python 3.10+ recommended, VS Code and an internet connection for installation.
- A modern browser (Chrome or Edge).
- A free [Neon](https://neon.tech/) account for a hosted PostgreSQL database (recommended for a shared/deployed database).
- For QR testing on a phone: camera, location services and an HTTPS URL.

### Step 1 — Extract and open
1. Extract the project ZIP.
2. Open VS Code → **File → Open Folder**.
3. Select the folder containing `app.py`.
4. Open **Terminal → New Terminal** (PowerShell).

### Step 2 — Create a Python virtual environment

```powershell
py -m venv .venv
```

### Step 3 — Install dependencies

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

This method does not require activating the virtual environment, so it avoids PowerShell execution-policy errors. The project dependencies must include a PostgreSQL driver such as `psycopg2-binary` when using Neon. If it is not already listed in `requirements.txt`, install it with:

```powershell
.\.venv\Scripts\python.exe -m pip install psycopg2-binary
```

### Step 4 — Create your Neon PostgreSQL database

1. Open [https://neon.tech/](https://neon.tech/) and sign in.
2. Create a new project.
3. Choose the project name and region, then create the project.
4. Open the project's **Connect** dialog.
5. Select the database, branch, and role you want the application to use.
6. Copy the PostgreSQL connection string. Use the connection string supplied by Neon; do not type or guess the host, username, password, or database name.

Neon connection strings normally use PostgreSQL format and require SSL. Keep the full connection string private.

### Step 5 — Set the Neon database connection

In the **same PowerShell terminal** that you will use to start Flask, set `DATABASE_URL` to the connection string copied from Neon:

```powershell
$env:DATABASE_URL = "postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require"
```

Replace the example value with your actual Neon connection string. Do not commit this value to GitHub or share it publicly.

This project reads the database connection from `DATABASE_URL`. Setting it in the current PowerShell terminal makes it available to the Flask process started from that terminal. If you open a new terminal, set it again. For deployment, add `DATABASE_URL` in your hosting provider's environment-variable settings instead.

### Step 6 — Initialize the database

Start the application after setting `DATABASE_URL`. The application uses SQLAlchemy and calls `db.create_all()` to create missing tables.

```powershell
.\.venv\Scripts\python.exe app.py
```

Keep the terminal open and check that the application starts without a database connection error. `db.create_all()` creates missing tables; it does **not** migrate existing table structures or load the large demonstration dataset. If your repository includes migration files, apply the project's documented migrations before using an existing database. Do not run a destructive demo restore against your Neon database.

### Step 7 — Open the application

Open **http://127.0.0.1:5000** on the laptop. Keep the terminal running. If a different port is shown in the terminal, use that port.

### Step 8 — Choose your demo data carefully
- If you intend to use the local SQLite database instead of Neon and your folder already has a working `instance/attendance.db`, **back it up and keep it**.
- If the ZIP includes `demo_database_backup.db`, it contains the documented large synthetic demo dataset. The included `restore_demo_database.py` is a **destructive restore**: it can replace your active data. Run it only in a disposable demo environment after inspecting its code and making a backup. Do not run it against Neon or any database containing records you want to keep.
- `seed_data.py` is a **different small sample-data script**. It uses different login credentials (see below). Do not run it against your active attendance database unless you intend to populate that database.
- `app.py` calls `db.create_all()` to create missing tables, but this **does not migrate existing table structures** or automatically load the large demonstration dataset.

### Step 9 — Run tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Passing unit tests does not replace a real phone QR/GPS test.

## Demo accounts

### A. Large packaged synthetic demo database
These are the credentials documented for the **250-student / 15-faculty demo database**, *provided that this dataset has actually been restored or is already the active database*.


### B. Small sample dataset created by `seed_data.py`
These credentials apply **only if you ran that script against the current database**:

| Role | Email | Demo password |
|---|---|---|
| Admin | `admin@campus.test` | `CampusDemo2026!` |
| Faculty | `faculty01@campus.test` | `CampusDemo2026!` |
| Faculty 2 | `faculty02@campus.test` | `CampusDemo2026!` |
| Students | `student001@campus.test` ` | `CampusDemo2026!` |

**Never publish a live instance with these known demo credentials, actual student data, or a bundled demo database.** Change all accounts/passwords and use a fresh production database before accepting real users.

## How to use CampusAttend

### Professor workflow
1. Sign in as a faculty member.
2. Open the professor dashboard and choose a subject.
3. Create a new class session with correct start/end times and location.
4. Display the generated QR code to the class.
5. Ask an enrolled student to scan it from their phone.
6. Check the session attendance page for a VERIFIED record.
7. Export a CSV/Excel report if needed.

### Student workflow
1. Open the website on a phone over HTTPS.
2. Sign in using the student's own account.
3. Allow camera and location permissions.
4. Open **Scan QR Code**, scan the professor's **fresh** QR code.
5. Read the result message, then refresh the student dashboard.
6. Confirm the record appears in recent attendance or the appropriate session summary.

### Admin workflow
1. Sign in with an admin account.
2. Review users, subjects, enrollments and sessions.
3. Inspect QR attendance and export reports.
4. Configure email settings if report emails are required.
5. Review audit activity and scheduled-job behavior.

## How QR and GPS attendance works

```text
Professor creates session
        ↓
Flask stores session and signs QR token
        ↓
Student browser scans QR and obtains GPS coordinates
        ↓
POST request reaches student attendance route
        ↓
Server validates token, expiry, session, enrollment,
GPS radius and duplicate-check rules
        ↓
SQLAlchemy inserts attendance row and commits transaction
        ↓
Professor and student dashboards query attendance records
```

The QR code is **not** the database record. It contains information used to validate the request. The backend creates the attendance row only after the checks succeed.


## Database explained

### Development database
By default, `app.py` uses `sqlite:///attendance.db`, which Flask-SQLAlchemy normally resolves to the Flask instance directory: `instance/attendance.db`. A configured `DATABASE_URL` overrides this path. Back up the **active** database, not just a similarly named file.

### Main models
- `User`: students, professors and administrators; roles, profile data and password hashes.
- `FamilyEmail`: guardian/family contact addresses.
- `Subject`: course information and faculty association.
- `Enrollment`: student-to-subject enrollment relationships.
- `Session`: a specific class meeting, times, GPS coordinates and QR token.
- `Attendance`: one student's recorded attendance for a session, with verification information.
- `AuditLog`: system activity history.

### How to inspect the database without programming
1. Download **DB Browser for SQLite** from https://sqlitebrowser.org/.
2. Stop Flask before making a standalone copy of the database, or use a proper SQLite backup method.
3. Open the **copy** in DB Browser for SQLite.
4. Click **Browse Data** and select `users`, `subjects`, `sessions`, `attendance` or `enrollments`.
5. Do not edit real records in the database viewer.

### How an update is saved

```python
# Simplified example; not a replacement for project routes.
db.session.add(attendance)
db.session.commit()
```

`add()` stages a new record; `commit()` persists the database transaction. Dashboards then run separate queries to read the saved rows.

### Database backup
Make regular, access-controlled backups of the active database and test restoring them. Do not commit `.db`, `.sqlite`, `.env` or password files to GitHub.

## Customization

| Want to change | Where to look | Notes |
|---|---|---|
| Website title / headings | `templates/base.html` and other `templates/` | Search for displayed text |
| Logo / favicon | `static/` and `templates/base.html` | Update asset paths and browser cache |
| Theme colors / layout | `templates/`, `static/`, `tailwind.config.js` | Rebuild CSS if using compiled Tailwind assets |
| Student dashboard | `views/student.py`, `templates/student/` | Keep queries consistent with attendance status rules |
| Professor dashboard | `views/teacher.py`, `templates/teacher/` | Check route/template variable names |
| Admin features | `views/admin.py`, `templates/admin/` | Restrict to admin role |
| QR token rules | `utils.py` and QR attendance routes | Changing expiry/signatures can invalidate old tokens |
| GPS allowed distance | `utils.py` / relevant route | Retest with real devices; do not silently weaken checks |
| Session time rules | `models.py`, `views/teacher.py`, `views/student.py` | Be consistent about time zones |
| Attendance calculations | `utils.py`, `views/student.py`, reporting code | Decide treatment of ongoing sessions and manual attendance |
| Email reports | `mailer.py`, `app.py` | SMTP credentials belong in environment variables |
| Scheduled jobs | `app.py`, admin job routes | Avoid duplicate schedulers on multi-worker hosts |
| Database schema | `models.py`, `migrations/` | Use a reviewed migration; back up before changing |
| Demo users | `seed_data.py` or demo backup | Never reset a live database casually |

**Recommended customization process:** make a backup → edit one file → run tests → restart Flask → verify with student/professor accounts → commit the change to version control.

## Environment configuration

`app.py` reads these settings from environment variables:

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Flask session/signing secret; required when `FLASK_ENV=production` |
| `DATABASE_URL` | Database connection string; required when `FLASK_ENV=production` |
| `FLASK_ENV` | Used by this project for production configuration checks |
| `SMTP_HOST` | SMTP mail server |
| `SMTP_PORT` | SMTP port (typically 587 for TLS or 465 for SSL) |
| `SMTP_USER` | SMTP login |
| `SMTP_PASSWORD` | SMTP password/app password |
| `MAIL_DEFAULT_SENDER` | Sender address |
| `RECAPTCHA_SITE_KEY` | Public reCAPTCHA site key |
| `RECAPTCHA_SECRET_KEY` | Private reCAPTCHA secret |

Example **names only** (replace values; never commit real secrets):

```dotenv
FLASK_ENV=production
SECRET_KEY=REPLACE_WITH_LONG_RANDOM_SECRET
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DBNAME
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=REPLACE_ME
SMTP_PASSWORD=REPLACE_ME
MAIL_DEFAULT_SENDER=noreply@example.com
RECAPTCHA_SITE_KEY=REPLACE_ME
RECAPTCHA_SECRET_KEY=REPLACE_ME
```

The presence of a `.env` file does not guarantee every launch method loads it. Confirm the actual environment seen by the process. Avoid printing secrets in logs.

## Phone testing over HTTPS

Camera and GPS access normally require a secure context. Opening `http://192.168.x.x:5000` on a phone may block these browser APIs.

1. Run Flask on the laptop.
2. Open a **second** PowerShell terminal.
3. Start a temporary tunnel:

```powershell
cloudflared tunnel --url http://localhost:5000
```

4. Copy the actual `https://...trycloudflare.com` URL displayed by the terminal.
5. Open it in Chrome on the phone and grant camera/location permissions.
6. Use a newly generated class QR code.

**Do not use a temporary Cloudflare Tunnel or Flask's debug server as your permanent production deployment.** Anyone with the tunnel URL may reach the exposed app; use demo data only.

## Testing and troubleshooting

| Symptom | Possible cause / first check |
|---|---|
| `ModuleNotFoundError` | Install `requirements.txt` using the same `.venv` Python |
| Website not loading | Is Flask running? Is the URL/port correct? |
| Phone camera blocked | Use HTTPS and Chrome; grant camera permission |
| GPS not available | Grant location permission; enable phone location services |
| QR says `Token Expired` | Create/refresh a new QR; check session time, token TTL and server clock |
| QR rejected due to distance | Confirm session coordinates, GPS accuracy and permitted radius |
| Professor shows VERIFIED, student shows zero | Inspect `attendance` record, student/session IDs and dashboard query/statistics |
| Attendance only appears after session ends | Review active-session filtering in student calculations |
| Duplicate attendance | A check-in for that student/session may already exist |
| Demo login fails | Check which database/dataset is actually active |
| Email does not send | Check SMTP credentials, network access and scheduler logs |
| Database seems empty | Check `DATABASE_URL`, active instance folder and whether demo data was restored |
| Excel/CSV differs | Check selected session, statuses, import rules and export route |

### Minimum live acceptance test
- [ ] Admin, faculty and student can sign in using **test-only** accounts.
- [ ] Faculty can create a session with a valid time and location.
- [ ] Fresh QR scans work on Android Chrome over HTTPS.
- [ ] Valid enrolled student is marked VERIFIED in the database.
- [ ] Duplicate scan does not create duplicate attendance.
- [ ] Expired token and out-of-radius scans are rejected appropriately.
- [ ] Professor and student see consistent attendance records.
- [ ] Daily/weekly attendance calculations are verified before and after session end.
- [ ] CSV and Excel exports contain the expected records.
- [ ] Backups and restore procedures work.
- [ ] SMTP notifications work, if enabled.
- [ ] No demo credentials or private database files are publicly accessible.

## Deployment checklist

**Do not assume the existing local prototype is production-ready.** Before deployment:

1. Use a managed host for the Flask application with HTTPS and a supported production WSGI server (e.g., Gunicorn on Linux).
2. Provision persistent PostgreSQL storage; set `DATABASE_URL` and `SECRET_KEY` as host-managed secrets.
3. Review migration compatibility before changing databases. `db.create_all()` does not upgrade existing schemas.
4. Use a new database and private, unique credentials; remove all demo accounts.
5. Confirm CSRF, login protection, session cookies, rate limits, permissions and password reset behavior.
6. Review QR replay/expiry, GPS spoofing, session authorization and duplicate check-in handling.
7. Ensure only one intended scheduler instance runs; a scheduler started inside each web worker can send duplicate jobs.
8. Confirm timezone handling and date calculations in production.
9. Set up access-controlled backups, retention rules, monitoring and error logs.
10. Run full browser, mobile and database integration tests before admitting real users.

### Production readiness warning
The application uses in-memory rate-limit storage in the inspected `app.py` and starts APScheduler during app initialization. These require review for multi-process production hosting. Also, GPS proximity alone does not prevent spoofing or proxy attendance. Obtain appropriate consent for location processing and follow your institution's privacy and retention requirements.


This project was adapted from an existing codebase and further customized with AI assistance. Preserve applicable original copyright and license notices. See `LICENSE` and `ATTRIBUTION_AND_AI_DISCLOSURE.md` in the repository for exact terms. Do not represent third-party code or generated demo data as independently authored or collected real-world records.

---

**CampusAttend — Scan. Verify. Record. Review.**
