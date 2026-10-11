# Yeshiva Dining Feedback

Flask application for anonymous dining feedback with Neon PostgreSQL and a Hebrew RTL admin dashboard. No Google account or student registration is required.

## Features
- English, mobile-friendly student feedback form.
- No student name, email, student ID, or IP address is stored in the feedback record.
- One-time access codes: managers create codes and distribute one to each intended respondent. Each code can submit one feedback record only.
- Only a SHA-256 digest of each access code is stored; the raw code is displayed to the manager only immediately after generation.
- Hebrew RTL admin dashboard with averages, latest 100 submissions, and one-time code creation.
- Password-protected admin sign-in, CSRF protection, rate limits, request size limit, and security headers.
- Liveness endpoint at /health and database readiness endpoint at /ready.

## Required Render environment variables
- SECRET_KEY: long random secret.
- DATABASE_URL: Neon PostgreSQL connection string with TLS enabled.
- ADMIN_USERNAME: manager username (default is admin).
- ADMIN_PASSWORD: strong, unique admin password.
- APP_BASE_URL: exact public HTTPS URL for this Render service.

Never commit real credentials or share the Neon connection string.

## Setup and operation
1. Set the environment variables above in Render.
2. Neon schema bootstrap runs additively on startup when DATABASE_URL is configured. It creates missing tables without deleting existing tables or rows.
3. Verify /ready returns HTTP 200.
4. Sign in at /admin/login.
5. In the Hebrew dashboard, generate a batch of one-time codes and copy or print them. Raw codes are displayed once only. Give one code to each intended student.
6. Each code can be used for one feedback submission. Distribute codes privately; do not post the full batch publicly.

## Privacy and abuse limits
- The feedback record is not linked to an access-code ID; only the code's used status is recorded separately.
- Codes prevent repeat submissions using the same issued code, not multiple submissions by a person who obtains multiple codes. Distributing one code per student in person is the practical anonymous approach.
- Rate limiting currently uses per-process memory storage, so it is a basic safeguard rather than a guarantee against a coordinated attack.
- Render request logs may include network metadata independent of what this application stores in the feedback database.

## Local development
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# Set DATABASE_URL, SECRET_KEY, ADMIN_USERNAME, and ADMIN_PASSWORD
flask --app app init-db
flask --app app run --debug
```

Production uses Gunicorn via render.yaml. Free Render services may sleep while idle.
