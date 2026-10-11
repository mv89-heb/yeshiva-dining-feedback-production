import hmac
import os
import secrets
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import urlparse

from authlib.integrations.flask_client import OAuth
from flask import (
    Flask, abort, flash, redirect, render_template, request,
    session, url_for
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint, func, select
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.middleware.proxy_fix import ProxyFix


def required_env(name):
    value = os.environ.get(name, "").strip()
    return value or None


app = Flask(__name__)
secret_key = required_env("SECRET_KEY")
if not secret_key:
    raise RuntimeError("SECRET_KEY is required. Set it in your environment.")

app.config.update(
    SECRET_KEY=secret_key,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "true").lower() == "true",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 8,
    MAX_CONTENT_LENGTH=16 * 1024,
)

# Render terminates HTTPS at its proxy. Trust one proxy hop so url_for(..., _external=True)
# and secure-cookie behavior use the public HTTPS URL.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

database_url = required_env("DATABASE_URL")
if database_url:
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
else:
    # Local development only. Production deployment should set DATABASE_URL to
    # a persistent managed PostgreSQL database (for example, Neon).
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///feedback-local.db"

app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
db = SQLAlchemy(app)

oauth = OAuth(app)
google_client_id = required_env("GOOGLE_CLIENT_ID")
google_client_secret = required_env("GOOGLE_CLIENT_SECRET")
if google_client_id and google_client_secret:
    oauth.register(
        name="google",
        client_id=google_client_id,
        client_secret=google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

MEALS = ("Breakfast", "Lunch", "Supper")
RATINGS = {
    1: {"label": "Poor", "emoji": "😞"},
    2: {"label": "Fair", "emoji": "😕"},
    3: {"label": "Good", "emoji": "😐"},
    4: {"label": "Very Good", "emoji": "🙂"},
    5: {"label": "Amazing", "emoji": "🤩"},
}


class Feedback(db.Model):
    __tablename__ = "feedback"

    id = db.Column(db.Integer, primary_key=True)
    meal = db.Column(db.String(20), nullable=False, index=True)
    rating = db.Column(db.Integer, nullable=False, index=True)
    comment = db.Column(db.String(1000), nullable=True)
    timestamp = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "meal IN ('Breakfast', 'Lunch', 'Supper')",
            name="ck_feedback_meal",
        ),
        CheckConstraint(
            "rating >= 1 AND rating <= 5",
            name="ck_feedback_rating",
        ),
    )


def csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


@app.context_processor
def template_globals():
    return {
        "csrf_token": csrf_token,
        "current_year": datetime.now(timezone.utc).year,
    }


@app.before_request
def enforce_csrf():
    if request.method == "POST":
        submitted = request.form.get("csrf_token", "")
        expected = session.get("_csrf_token", "")
        if not expected or not hmac.compare_digest(submitted, expected):
            abort(400, description="Your form session expired. Please reload and try again.")


def allowed_admin_emails():
    return {
        email.strip().lower()
        for email in os.environ.get("ADMIN_EMAILS", "").split(",")
        if email.strip()
    }


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_email"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.get("/")
def index():
    return render_template("index.html", meals=MEALS, ratings=RATINGS)


@app.post("/submit")
def submit_feedback():
    meal = request.form.get("meal", "").strip()
    raw_rating = request.form.get("rating", "").strip()
    comment = request.form.get("comment", "").strip()

    if meal not in MEALS:
        flash("Please select a valid meal.", "error")
        return redirect(url_for("index"))

    try:
        rating = int(raw_rating)
    except (TypeError, ValueError):
        rating = 0

    if rating not in RATINGS:
        flash("Please choose a rating from 1 to 5.", "error")
        return redirect(url_for("index"))

    if len(comment) > 1000:
        flash("Your comment must be 1,000 characters or fewer.", "error")
        return redirect(url_for("index"))

    try:
        db.session.add(Feedback(meal=meal, rating=rating, comment=comment or None))
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Could not save feedback")
        flash("We couldn't save your feedback. Please try again in a moment.", "error")
        return redirect(url_for("index"))

    session["_csrf_token"] = secrets.token_urlsafe(32)
    return render_template("index.html", meals=MEALS, ratings=RATINGS, submitted=True)


@app.get("/admin/login")
def admin_login():
    if session.get("admin_email"):
        return redirect(url_for("admin_dashboard"))
    if not google_client_id or not google_client_secret:
        return render_template(
            "admin_login.html",
            configuration_error=True,
        ), 503
    return render_template("admin_login.html", configuration_error=False)


@app.get("/auth/google")
def google_login():
    if not google_client_id or not google_client_secret:
        abort(503, description="Google sign-in is not configured.")
    redirect_uri = required_env("GOOGLE_REDIRECT_URI") or url_for(
        "google_callback", _external=True
    )
    return oauth.google.authorize_redirect(redirect_uri, prompt="select_account")


@app.get("/auth/google/callback")
def google_callback():
    if not google_client_id or not google_client_secret:
        abort(503, description="Google sign-in is not configured.")
    try:
        token = oauth.google.authorize_access_token()
        user_info = token.get("userinfo")
        if not user_info:
            user_info = oauth.google.parse_id_token(token, nonce=None)
    except Exception:
        app.logger.exception("Google OAuth callback failed")
        flash("Google sign-in failed. Please try again.", "error")
        return redirect(url_for("admin_login"))

    email = str(user_info.get("email", "")).strip().lower()
    email_verified = user_info.get("email_verified") is True
    allowlist = allowed_admin_emails()

    if not email or not email_verified or email not in allowlist:
        app.logger.warning("Blocked admin sign-in for email=%s", email or "(missing)")
        session.clear()
        return render_template("access_denied.html"), 403

    session.clear()
    session["admin_email"] = email
    session["admin_name"] = user_info.get("name") or email
    session.permanent = True
    session["_csrf_token"] = secrets.token_urlsafe(32)
    return redirect(url_for("admin_dashboard"))


@app.get("/admin")
@admin_required
def admin_dashboard():
    total = db.session.scalar(select(func.count(Feedback.id))) or 0
    avg_value = db.session.scalar(select(func.avg(Feedback.rating)))
    average = round(float(avg_value), 2) if avg_value is not None else 0.0

    meal_stats = {}
    for meal in MEALS:
        count, avg = db.session.execute(
            select(func.count(Feedback.id), func.avg(Feedback.rating))
            .where(Feedback.meal == meal)
        ).one()
        meal_stats[meal] = {
            "count": int(count or 0),
            "average": round(float(avg), 2) if avg is not None else 0.0,
        }

    # Summary metrics are calculated over all records; table lists recent records.
    feedback = db.session.scalars(
        select(Feedback)
        .order_by(Feedback.timestamp.desc(), Feedback.id.desc())
        .limit(500)
    ).all()

    positive_count = db.session.scalar(
        select(func.count(Feedback.id)).where(Feedback.rating >= 4)
    ) or 0
    positive_percent = round(positive_count / total * 100) if total else 0

    return render_template(
        "admin.html",
        authenticated=True,
        admin_name=session.get("admin_name", session["admin_email"]),
        admin_email=session["admin_email"],
        total=total,
        average=average,
        meal_stats=meal_stats,
        feedback=feedback,
        ratings=RATINGS,
        positive_percent=positive_percent,
    )


@app.post("/admin/logout")
@admin_required
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


@app.get("/health")
def health():
    try:
        db.session.execute(select(1))
        return {"status": "ok"}, 200
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception("Database health check failed")
        return {"status": "unhealthy"}, 503


@app.errorhandler(400)
def bad_request(error):
    return render_template(
        "error.html",
        code=400,
        message=getattr(error, "description", "Bad request."),
    ), 400


@app.errorhandler(404)
def not_found(error):
    return render_template(
        "error.html",
        code=404,
        message="The page you're looking for doesn't exist.",
    ), 404


@app.errorhandler(503)
def service_unavailable(error):
    return render_template(
        "error.html",
        code=503,
        message=getattr(error, "description", "The service is temporarily unavailable."),
    ), 503


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
