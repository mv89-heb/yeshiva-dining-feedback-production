# Yeshiva Dining Feedback

Flask application for anonymous dining feedback with Neon PostgreSQL and a Hebrew RTL admin dashboard protected by Google OAuth.

## Features
- English, mobile-friendly student feedback form.
- Anonymous feedback: no student name or email field.
- Ratings for food quality, taste, variety and cleanliness, plus optional comments.
- Hebrew RTL admin dashboard with averages and the 100 most recent submissions.
- Google OAuth sign-in restricted to an explicit email allow-list.
- Liveness endpoint at /health and database readiness endpoint at /ready.
- Basic rate limits, request size limit, security headers and admin-login audit record.

## Required Render environment variables
- SECRET_KEY: long random secret (Render Blueprint can generate it).
- DATABASE_URL: Neon PostgreSQL connection string with TLS enabled.
- ADMIN_EMAILS: comma-separated Google email addresses authorized for admin.
- GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET: OAuth web application credentials.
- APP_BASE_URL: exact public HTTPS URL for this Render service.

Never commit real credentials.

## Neon setup
1. Select the Neon project and database.
2. Copy the PostgreSQL connection string and set it as DATABASE_URL in Render. Keep its password private and ensure TLS is enabled.
3. After the first deploy, run `flask --app app init-db` in a Render shell. This creates tables and does not delete data.
4. Verify /ready returns HTTP 200.

## Google OAuth setup
1. In Google Cloud Console, configure the OAuth consent screen.
2. Create an OAuth Client ID of type Web application.
3. Add this Authorized redirect URI exactly: `https://YOUR-RENDER-HOST/admin/callback`.
4. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, ADMIN_EMAILS and APP_BASE_URL in Render.
5. Test an authorized Google account and a non-authorized account.

## Local development
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# Set environment variables before starting the app
flask --app app init-db
flask --app app run --debug
```

Production uses Gunicorn via render.yaml.

## Notes
- Free Render services may sleep while idle.
- Rate limiting currently uses per-process memory storage; use shared Redis-compatible storage for robust multi-instance throttling.
- Before broad public use, add CSRF protection to the public feedback form (for example Flask-WTF); admin logout already validates a CSRF token.
