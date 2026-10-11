import os
import secrets
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import urljoin

from authlib.integrations.flask_client import OAuth
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import text
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
database_url = os.environ.get("DATABASE_URL", "").strip()
if database_url.startswith("postgres://"):
    database_url = "postgresql+psycopg://" + database_url[len("postgres://"):]
elif database_url.startswith("postgresql://") and "+psycopg" not in database_url:
    database_url = "postgresql+psycopg://" + database_url[len("postgresql://"):]
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or "dev-only-change-this-secret",
    SQLALCHEMY_DATABASE_URI=database_url or "sqlite:///local-dev.db",
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True, "pool_recycle": 300} if database_url else {},
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")) or os.environ.get("FLASK_ENV") == "production",
    MAX_CONTENT_LENGTH=32 * 1024,
)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
db = SQLAlchemy(app)
csrf = CSRFProtect(app)
limiter = Limiter(get_remote_address, app=app, default_limits=[], storage_uri="memory://")
oauth = OAuth(app)

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
ADMIN_EMAILS = {x.strip().lower() for x in os.environ.get("ADMIN_EMAILS", "").split(",") if x.strip()}
APP_BASE_URL = os.environ.get("APP_BASE_URL", "").rstrip("/")
if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    oauth.register(name="google", client_id=GOOGLE_CLIENT_ID, client_secret=GOOGLE_CLIENT_SECRET,
                   server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
                   client_kwargs={"scope": "openid email profile"})

class Feedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    meal_date = db.Column(db.Date, nullable=False, index=True)
    meal_type = db.Column(db.String(20), nullable=False, index=True)
    food_rating = db.Column(db.Integer, nullable=False)
    taste_rating = db.Column(db.Integer, nullable=False)
    variety_rating = db.Column(db.Integer, nullable=False)
    cleanliness_rating = db.Column(db.Integer, nullable=False)
    comments = db.Column(db.String(1200), nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

class AdminAudit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admin_email = db.Column(db.String(320), nullable=False, index=True)
    action = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        email = (session.get("admin_email") or "").lower()
        if not email or email not in ADMIN_EMAILS:
            flash("יש להתחבר באמצעות חשבון מנהל מורשה.", "error")
            return redirect(url_for("admin_login"))
        return fn(*args, **kwargs)
    return wrapped

@app.after_request
def secure_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'")
    return response

@app.context_processor
def common_template_values():
    return {"admin_logged_in": bool(session.get("admin_email") in ADMIN_EMAILS), "current_year": datetime.now().year}

@app.get("/health")
def health():
    return {"status": "ok", "database_configured": bool(os.environ.get("DATABASE_URL"))}, 200

@app.get("/ready")
def ready():
    if not os.environ.get("DATABASE_URL"):
        return {"status": "not_ready", "reason": "DATABASE_URL is not configured"}, 503
    try:
        db.session.execute(text("SELECT 1"))
        return {"status": "ready", "database": "connected"}, 200
    except Exception:
        db.session.rollback()
        app.logger.exception("Readiness database check failed")
        return {"status": "not_ready", "database": "unavailable"}, 503

@app.get("/")
def index():
    return render_template("index.html")

@app.route("/feedback", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def feedback():
    if request.method == "GET":
        return render_template("feedback.html")
    if not os.environ.get("DATABASE_URL"):
        flash("The feedback service is not configured yet. Please try again later.", "error")
        return render_template("feedback.html"), 503
    try:
        meal_type = request.form.get("meal_type", "").strip().lower()
        meal_date = datetime.strptime(request.form.get("meal_date", ""), "%Y-%m-%d").date()
        if meal_type not in {"breakfast", "lunch", "dinner"}:
            raise ValueError("Invalid meal type")
        def rating(name):
            value = int(request.form.get(name, ""))
            if not 1 <= value <= 5:
                raise ValueError("Ratings must be between 1 and 5")
            return value
        comments = request.form.get("comments", "").strip()
        if len(comments) > 1200:
            raise ValueError("Comments are too long")
        if request.form.get("website", "").strip():
            return redirect(url_for("feedback_thanks"))
        item = Feedback(meal_date=meal_date, meal_type=meal_type,
                        food_rating=rating("food_rating"), taste_rating=rating("taste_rating"),
                        variety_rating=rating("variety_rating"), cleanliness_rating=rating("cleanliness_rating"),
                        comments=comments)
        db.session.add(item)
        db.session.commit()
        return redirect(url_for("feedback_thanks"))
    except (ValueError, TypeError):
        db.session.rollback()
        flash("Please complete all ratings and choose a valid meal date.", "error")
        return render_template("feedback.html"), 400
    except Exception:
        db.session.rollback()
        app.logger.exception("Could not save feedback")
        flash("We could not save your feedback. Please try again later.", "error")
        return render_template("feedback.html"), 503

@app.get("/feedback/thanks")
def feedback_thanks():
    return render_template("thanks.html")

@app.get("/admin")
@admin_required
def admin_dashboard():
    if not app.config["SQLALCHEMY_DATABASE_URI"]:
        abort(503, description="DATABASE_URL is not configured.")
    from sqlalchemy import func
    total = db.session.query(func.count(Feedback.id)).scalar() or 0
    averages = {
        "איכות האוכל": db.session.query(func.avg(Feedback.food_rating)).scalar(),
        "טעם": db.session.query(func.avg(Feedback.taste_rating)).scalar(),
        "מגוון": db.session.query(func.avg(Feedback.variety_rating)).scalar(),
        "ניקיון": db.session.query(func.avg(Feedback.cleanliness_rating)).scalar(),
    }
    recent = Feedback.query.order_by(Feedback.created_at.desc()).limit(100).all()
    return render_template("admin.html", total=total, averages=averages, recent=recent)

@app.get("/admin/login")
def admin_login():
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return render_template("setup_required.html", missing="Google OAuth"), 503
    if not ADMIN_EMAILS:
        return render_template("setup_required.html", missing="ADMIN_EMAILS"), 503
    return render_template("admin_login.html")

@app.get("/admin/login/google")
@limiter.limit("10 per minute")
def google_login():
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        abort(503, description="Google OAuth is not configured.")
    session.pop("admin_email", None)
    redirect_uri = urljoin((APP_BASE_URL or request.url_root).rstrip("/") + "/", "admin/callback")
    return oauth.google.authorize_redirect(redirect_uri, prompt="select_account")

@app.get("/admin/callback")
def google_callback():
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        abort(503)
    try:
        token = oauth.google.authorize_access_token()
        userinfo = token.get("userinfo") or oauth.google.userinfo()
        email = str(userinfo.get("email", "")).strip().lower()
        verified = userinfo.get("email_verified") is True or userinfo.get("email_verified") == "true"
        if not verified or email not in ADMIN_EMAILS:
            session.clear()
            return render_template("access_denied.html"), 403
        session.clear()
        session["admin_email"] = email
        session["admin_logout_csrf"] = secrets.token_urlsafe(32)
        if os.environ.get("DATABASE_URL"):
            db.session.add(AdminAudit(admin_email=email, action="login"))
            db.session.commit()
        return redirect(url_for("admin_dashboard"))
    except Exception:
        db.session.rollback()
        app.logger.exception("Google OAuth callback failed")
        return render_template("setup_required.html", missing="Google OAuth callback configuration"), 503

@app.post("/admin/logout")
@admin_required
def admin_logout():
    if not secrets.compare_digest(request.form.get("csrf_token", ""), session.get("admin_logout_csrf", "")):
        abort(400)
    session.clear()
    return redirect(url_for("index"))

@app.errorhandler(413)
def too_large(_error):
    return "Request too large.", 413

@app.errorhandler(429)
def rate_limited(_error):
    return render_template("error.html", code=429, message="Too many requests. Please wait and try again."), 429

@app.cli.command("init-db")
def init_db():
    """Create tables without deleting existing data."""
    if not app.config["SQLALCHEMY_DATABASE_URI"]:
        raise RuntimeError("Set DATABASE_URL before initializing the database.")
    with app.app_context():
        db.create_all()
    print("Database tables are ready.")
