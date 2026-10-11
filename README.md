# Yeshiva Dining Feedback

Flask application for anonymous dining feedback with Neon PostgreSQL and a Hebrew RTL admin dashboard. Students do not need Google accounts, student registration, or individual access codes.

## Features
- Students scan a shared QR code and open the English, mobile-friendly feedback form.
- No student name, email, or student ID is requested or stored in feedback.
- An anonymous random browser token is stored in a secure, HTTP-only cookie; only its SHA-256 digest is stored in the database.
- A database unique constraint limits each browser token to one submission per meal type and meal date, including simultaneous duplicate requests.
- Hebrew RTL admin dashboard with averages, latest 100 submissions, and a downloadable QR image.
- Password-protected admin sign-in, CSRF protection, rate limits, request size limit, and security headers.

## Required Render environment variables
- SECRET_KEY: long random secret.
- DATABASE_URL: Neon PostgreSQL connection string with TLS enabled.
- ADMIN_USERNAME: manager username (default is admin).
- ADMIN_PASSWORD: strong, unique admin password.
- APP_BASE_URL: exact public HTTPS URL for this Render service; used to generate the QR destination.

Never commit real credentials or share the Neon connection string.

## Setup and operation
1. Set the environment variables above in Render.
2. Neon schema bootstrap runs additively on startup when DATABASE_URL is configured. It creates missing tables without deleting existing tables or rows.
3. Verify /ready returns HTTP 200.
4. Sign in at /admin/login.
5. Print or display the QR shown in the admin dashboard. Students scan it and submit feedback without signing in.
6. The same browser is blocked from submitting a second response for the same meal date and meal type.

## Privacy and abuse limits
- The feedback record is not linked to a student identity or a respondent token. A separate table stores only a one-way hash of the anonymous browser token, meal date, and meal type to enforce duplicate limits.
- This is a practical anonymous deterrent, not proof of one submission per human: students can bypass it by clearing browser data, using private browsing, or switching devices/browsers. A shared QR cannot reliably enforce one submission per person without an identity check or individually issued one-use credentials.
- Rate limiting currently uses per-process memory storage, so it is a basic safeguard rather than a guarantee against coordinated abuse.
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
