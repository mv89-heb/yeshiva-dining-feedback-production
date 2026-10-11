import hashlib
import hmac
import io
import os
import secrets
from datetime import datetime, timezone
from functools import wraps

import qrcode
from flask import Flask, abort, flash, make_response, redirect, render_template, request, send_file, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import UniqueConstraint, func, text
from sqlalchemy.exc import IntegrityError
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
database_url = os.environ.get("DATABASE_URL", "").strip()
if database_url.startswith("postgres://"):
    database_url = "postgresql+psycopg://" + database_url[len("postgres://"):]
elif database_url.startswith("postgresql://") and "+psycopg" not in database_url:
    database_url = "postgresql+psycopg://" + database_url[len("postgresql://"):]
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or ("dev-only-change-this-secret" if os.environ.get("FLASK_ENV") != "production" and not os.environ.get("RENDER") else secrets.token_hex(32)),
    SQLALCHEMY_DATABASE_URI=database_url or "sqlite:///local-dev.db",
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True, "pool_recycle": 300} if database_url else {},
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")) or os.environ.get("FLASK_ENV") == "production",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 8,
    MAX_CONTENT_LENGTH=32 * 1024,
)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
db = SQLAlchemy(app)
csrf = CSRFProtect(app)
limiter = Limiter(get_remote_address, app=app, default_limits=[], storage_uri="memory://")

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin").strip()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "").rstrip("/")
RESPONDENT_COOKIE = "dining_respondent"
RESPONDENT_COOKIE_MAX_AGE = 60 * 60 * 24 * 365


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


class AnonymousSubmission(db.Model):
    __tablename__ = "anonymous_submissions"
    id = db.Column(db.Integer, primary_key=True)
    respondent_hash = db.Column(db.String(64), nullable=False)
    meal_date = db.Column(db.Date, nullable=False)
    meal_type = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        UniqueConstraint("respondent_hash", "meal_date", "meal_type", name="uq_anonymous_respondent_meal"),
    )


class AdminAudit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admin_email = db.Column(db.String(320), nullable=False, index=True)
    action = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("admin_authenticated"):
            flash("יש להתחבר כדי להיכנס ללוח הניהול.", "error")
            return redirect(url_for("admin_login"))
        return fn(*args, **kwargs)
    return wrapped


def respondent_digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def admin_audit(action):
    if os.environ.get("DATABASE_URL"):
        db.session.add(AdminAudit(admin_email=ADMIN_USERNAME or "admin", action=action))


def attach_respondent_cookie(response, token):
    response.set_cookie(
        RESPONDENT_COOKIE,
        token,
        max_age=RESPONDENT_COOKIE_MAX_AGE,
        httponly=True,
        secure=bool(os.environ.get("RENDER")) or os.environ.get("FLASK_ENV") == "production",
        samesite="Lax",
        path="/",
    )
    return response


@app.after_request
def secure_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.context_processor
def common_template_values():
    return {"admin_logged_in": bool(session.get("admin_authenticated")), "current_year": datetime.now().year}


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
        response = make_response(render_template("feedback.html"))
        token = request.cookies.get(RESPONDENT_COOKIE, "")
        if len(token) < 32 or len(token) > 128:
            token = secrets.token_urlsafe(32)
        return attach_respondent_cookie(response, token)

    if not os.environ.get("DATABASE_URL"):
        flash("The feedback service is not configured yet. Please try again later.", "error")
        return render_template("feedback.html"), 503
    if request.form.get("website", "").strip():
        return redirect(url_for("feedback_thanks"))

    respondent_token = request.cookies.get(RESPONDENT_COOKIE, "")
    if len(respondent_token) < 32 or len(respondent_token) > 128:
        flash("Please scan the dining hall QR code again before submitting.", "error")
        return redirect(url_for("feedback"))

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

        respondent_hash = respondent_digest(respondent_token)
        duplicate = AnonymousSubmission.query.filter_by(
            respondent_hash=respondent_hash,
            meal_date=meal_date,
            meal_type=meal_type,
        ).first()
        if duplicate is not None:
            flash("A feedback response from this browser has already been recorded for this meal.", "error")
            return render_template("feedback.html"), 409

        db.session.add(AnonymousSubmission(
            respondent_hash=respondent_hash,
            meal_date=meal_date,
            meal_type=meal_type,
        ))
        db.session.add(Feedback(
            meal_date=meal_date,
            meal_type=meal_type,
            food_rating=rating("food_rating"),
            taste_rating=rating("taste_rating"),
            variety_rating=rating("variety_rating"),
            cleanliness_rating=rating("cleanliness_rating"),
            comments=comments,
        ))
        db.session.commit()
        return redirect(url_for("feedback_thanks"))
    except (ValueError, TypeError):
        db.session.rollback()
        flash("Please complete all ratings and choose a valid meal date.", "error")
        return render_template("feedback.html"), 400
    except IntegrityError:
        db.session.rollback()
        flash("A feedback response from this browser has already been recorded for this meal.", "error")
        return render_template("feedback.html"), 409
    except Exception:
        db.session.rollback()
        app.logger.exception("Could not save feedback")
        flash("We could not save your feedback. Please try again later.", "error")
        return render_template("feedback.html"), 503


@app.get("/feedback/thanks")
def feedback_thanks():
    return render_template("thanks.html")


@app.route("/admin/login", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def admin_login():
    if not ADMIN_PASSWORD:
        return render_template("setup_required.html", missing="ADMIN_PASSWORD in Render environment variables"), 503
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if hmac.compare_digest(username, ADMIN_USERNAME) and hmac.compare_digest(password, ADMIN_PASSWORD):
            session.clear()
            session.permanent = True
            session["admin_authenticated"] = True
            if os.environ.get("DATABASE_URL"):
                admin_audit("login")
                db.session.commit()
            return redirect(url_for("admin_dashboard"))
        flash("שם המשתמש או הסיסמה אינם נכונים.", "error")
        return render_template("admin_login.html"), 401
    return render_template("admin_login.html")


@app.post("/admin/logout")
@admin_required
def admin_logout():
    admin_audit("logout")
    if os.environ.get("DATABASE_URL"):
        db.session.commit()
    session.clear()
    return redirect(url_for("index"))


def dashboard_response():
    if not os.environ.get("DATABASE_URL"):
        abort(503, description="DATABASE_URL is not configured.")
    total = db.session.query(func.count(Feedback.id)).scalar() or 0
    averages = {
        "איכות האוכל": db.session.query(func.avg(Feedback.food_rating)).scalar(),
        "טעם": db.session.query(func.avg(Feedback.taste_rating)).scalar(),
        "מגוון": db.session.query(func.avg(Feedback.variety_rating)).scalar(),
        "ניקיון": db.session.query(func.avg(Feedback.cleanliness_rating)).scalar(),
    }
    recent = Feedback.query.order_by(Feedback.created_at.desc()).limit(100).all()
    return render_template("admin.html", total=total, averages=averages, recent=recent)


@app.get("/admin")
@admin_required
def admin_dashboard():
    return dashboard_response()


@app.get("/admin/qr.png")
@admin_required
def admin_qr_code():
    public_url = (APP_BASE_URL or request.url_root.rstrip("/")) + url_for("feedback")
    qr_image = qrcode.make(public_url)
    image_buffer = io.BytesIO()
    qr_image.save(image_buffer, format="PNG")
    image_buffer.seek(0)
    return send_file(image_buffer, mimetype="image/png", download_name="yeshiva-dining-feedback-qr.png", max_age=0)


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


# create_all adds missing tables and does not delete existing rows.
if os.environ.get("DATABASE_URL"):
    with app.app_context():
        try:
            db.create_all()
            app.logger.info("Database schema is available.")
        except Exception:
            db.session.rollback()
            app.logger.exception("Database schema bootstrap failed; readiness will report the issue.")
