import hashlib
import hmac
import io
import os
import secrets
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
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
secret_key = os.environ.get("SECRET_KEY", "").strip()
if not secret_key and (os.environ.get("RENDER") or os.environ.get("FLASK_ENV") == "production"):
    raise RuntimeError("SECRET_KEY must be configured in production.")

app.config.update(
    SECRET_KEY=secret_key or "dev-only-change-this-secret",
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
            flash(translate("Please sign in to access the admin dashboard.", "יש להתחבר כדי להיכנס ללוח הניהול."), "error")
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


def translate(en, he):
    return he if session.get("language", "en") == "he" else en


@app.context_processor
def common_template_values():
    today = datetime.now(ZoneInfo("Asia/Jerusalem")).date()
    language = session.get("language", "en")
    translations = {
        "site_name": "Yeshiva Dining" if language == "en" else "חדר האוכל בישיבה",
        "admin_dashboard": "Admin dashboard" if language == "en" else "לוח ניהול",
        "home_tagline": "YOUR VOICE HELPS US IMPROVE" if language == "en" else "המשוב שלכם עוזר לנו להשתפר",
        "home_title": "How was your meal?" if language == "en" else "איך הייתה הארוחה?",
        "home_intro": "Share quick, honest feedback about the food, taste, variety, and dining hall cleanliness. Your feedback helps us make every meal better." if language == "en" else "שתפו משוב קצר וכנה על האוכל, הטעם, המגוון והניקיון בחדר האוכל. המשוב שלכם עוזר לנו לשפר כל ארוחה.",
        "give_feedback": "Give feedback" if language == "en" else "שליחת משוב",
        "quick_simple": "Quick and simple" if language == "en" else "מהיר ופשוט",
        "quick_simple_desc": "Rate a meal in about a minute, right from your phone." if language == "en" else "דרגו את הארוחה בתוך כדקה, ישירות מהטלפון.",
        "help_improve": "Help us improve" if language == "en" else "עוזרים לנו להשתפר",
        "help_improve_desc": "Your comments help the kitchen team understand what works and what needs attention." if language == "en" else "ההערות שלכם עוזרות לצוות המטבח להבין מה עובד ומה דורש שיפור.",
        "feedback_kicker": "DINING HALL · STUDENT FEEDBACK" if language == "en" else "חדר האוכל · משוב תלמידים",
        "feedback_title": "Tell us about your meal" if language == "en" else "ספרו לנו על הארוחה",
        "feedback_intro": "Rate each item from 1 (poor) to 5 (excellent). No name, email, or student ID is requested. This form uses an anonymous browser token to discourage duplicate submissions for the same meal." if language == "en" else "דרגו כל סעיף מ־1 (גרוע) עד 5 (מצוין). אין צורך בשם, בדוא״ל או במספר תלמיד. נעשה שימוש במזהה דפדפן אנונימי כדי לצמצם שליחת משובים כפולים לאותה ארוחה.",
        "meal_date": "Meal date" if language == "en" else "תאריך הארוחה",
        "which_meal": "Which meal?" if language == "en" else "איזו ארוחה?",
        "choose_meal": "Choose a meal" if language == "en" else "בחרו ארוחה",
        "breakfast": "Breakfast" if language == "en" else "ארוחת בוקר",
        "lunch": "Lunch" if language == "en" else "ארוחת צהריים",
        "dinner": "Dinner" if language == "en" else "ארוחת ערב",
        "food_quality": "Overall food quality" if language == "en" else "איכות האוכל הכללית",
        "taste": "Taste" if language == "en" else "טעם",
        "variety": "Variety of dishes" if language == "en" else "מגוון המנות",
        "cleanliness": "Dining hall cleanliness" if language == "en" else "ניקיון חדר האוכל",
        "poor_excellent": "1 = Poor · 5 = Excellent" if language == "en" else "1 = גרוע · 5 = מצוין",
        "comments_label": "Additional comments (optional)" if language == "en" else "הערות נוספות (לא חובה)",
        "comments_placeholder": "What did you like? What could be better?" if language == "en" else "מה אהבתם? מה אפשר לשפר?",
        "submit_feedback": "Submit feedback" if language == "en" else "שליחת המשוב",
        "thanks_title": "Thank you!" if language == "en" else "תודה רבה!",
        "thanks_message": "Your feedback has been received. Your voice helps improve our dining experience." if language == "en" else "המשוב שלכם התקבל. בזכותכם נוכל לשפר את חוויית הארוחות.",
        "rate_another": "Rate another meal" if language == "en" else "דירוג ארוחה נוספת",
        "admin_login": "Manager sign in" if language == "en" else "כניסת מנהלים",
        "admin_login_intro": "Only authorized managers can access the dashboard." if language == "en" else "הכניסה ללוח הניהול מוגבלת למנהלים בלבד.",
        "username": "Username" if language == "en" else "שם משתמש",
        "password": "Password" if language == "en" else "סיסמה",
        "sign_in": "Sign in" if language == "en" else "כניסה למערכת",
        "management": "Dining hall management" if language == "en" else "ניהול חדר האוכל",
        "connected_as": "Signed in as:" if language == "en" else "מחובר/ת:",
        "logout": "Sign out" if language == "en" else "התנתקות",
        "qr_title": "Student feedback QR code" if language == "en" else "QR למשוב התלמידים",
        "qr_desc": "Students can scan this code with their phone camera to open the form. No Google account or individual code is required." if language == "en" else "התלמידים סורקים את הקוד במצלמת הטלפון ונכנסים ישירות לטופס. אין צורך בחשבון Google או בקוד אישי.",
        "qr_alt": "QR code for anonymous dining feedback" if language == "en" else "קוד QR למשוב אנונימי על חדר האוכל",
        "download_qr": "Download QR for printing" if language == "en" else "הורדת QR להדפסה",
        "duplicate_limit": "The system blocks repeat submissions from the same browser for the same meal and date. This is anonymous, but cannot reliably identify someone who switches devices or browsers." if language == "en" else "המערכת מגבילה שליחה חוזרת מאותו דפדפן לאותה ארוחה ותאריך. ההגבלה אנונימית, אך אינה יכולה לזהות בוודאות אדם שעובר למכשיר או לדפדפן אחר.",
        "total_feedback": "Total feedback submissions" if language == "en" else "מספר משובים כולל",
        "latest_feedback": "Latest feedback" if language == "en" else "משובים אחרונים",
        "latest_desc": "Showing up to the latest 100 submissions. No student identity details are stored here." if language == "en" else "מוצגים עד 100 משובים אחרונים. אין כאן פרטי זהות של תלמידים.",
        "meal_date_col": "Meal date" if language == "en" else "תאריך הארוחה",
        "meal_col": "Meal" if language == "en" else "ארוחה",
        "quality_col": "Quality" if language == "en" else "איכות",
        "taste_col": "Taste" if language == "en" else "טעם",
        "variety_col": "Variety" if language == "en" else "מגוון",
        "cleanliness_col": "Cleanliness" if language == "en" else "ניקיון",
        "comments_col": "Comments" if language == "en" else "הערות",
        "submitted_col": "Submitted at" if language == "en" else "נשלח בתאריך",
        "no_feedback": "No feedback has been received yet." if language == "en" else "עדיין לא התקבלו משובים.",
        "something_wrong": "Something went wrong" if language == "en" else "משהו השתבש",
        "return_home": "Return home" if language == "en" else "חזרה לדף הראשי",
        "setup_title": "Setup required" if language == "en" else "נדרשת הגדרה",
        "setup_message": "The action cannot be completed. A required setting is missing:" if language == "en" else "לא ניתן להשלים את הפעולה. חסרה הגדרה נדרשת:",
        "setup_hint": "Please complete the environment variables in Render. Do not enter secrets in this form." if language == "en" else "יש להשלים את משתני הסביבה ב-Render. אין להזין סודות בטופס זה.",
        "language_label": "שפה" if language == "en" else "Language",
        "switch_language": "עברית" if language == "en" else "English",
    }
    return {
        "admin_logged_in": bool(session.get("admin_authenticated")),
        "current_year": today.year,
        "current_date": today,
        "language": language,
        "is_hebrew": language == "he",
        "t": translations,
    }


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


@app.post("/language")
def set_language():
    language = request.form.get("language", "en").strip().lower()
    if language in {"en", "he"}:
        session["language"] = language
    next_path = request.form.get("next", "/")
    if not next_path.startswith("/") or next_path.startswith("//"):
        next_path = "/"
    return redirect(next_path)


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
        flash(translate("The feedback service is not configured yet. Please try again later.", "שירות המשוב עדיין אינו מוגדר. נסו שוב מאוחר יותר."), "error")
        return render_template("feedback.html"), 503
    if request.form.get("website", "").strip():
        return redirect(url_for("feedback_thanks"))

    respondent_token = request.cookies.get(RESPONDENT_COOKIE, "")
    if len(respondent_token) < 32 or len(respondent_token) > 128:
        flash(translate("Please scan the dining hall QR code again before submitting.", "סרקו שוב את קוד ה־QR של חדר האוכל לפני שליחת המשוב."), "error")
        return redirect(url_for("feedback"))

    try:
        meal_type = request.form.get("meal_type", "").strip().lower()
        meal_date = datetime.strptime(request.form.get("meal_date", ""), "%Y-%m-%d").date()
        today = datetime.now(ZoneInfo("Asia/Jerusalem")).date()
        if meal_date != today:
            raise ValueError("Feedback is accepted only for today's meals.")
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
            flash(translate("A response from this browser has already been recorded for this meal.", "כבר התקבל משוב מדפדפן זה עבור ארוחה זו."), "error")
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
        flash(translate("Please complete all ratings and choose a valid meal date.", "יש למלא את כל הדירוגים ולבחור תאריך ארוחה תקין."), "error")
        return render_template("feedback.html"), 400
    except IntegrityError:
        db.session.rollback()
        flash("A feedback response from this browser has already been recorded for this meal.", "error")
        return render_template("feedback.html"), 409
    except Exception:
        db.session.rollback()
        app.logger.exception("Could not save feedback")
        flash(translate("We could not save your feedback. Please try again later.", "לא הצלחנו לשמור את המשוב. נסו שוב מאוחר יותר."), "error")
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
        if hmac.compare_digest(username.encode("utf-8"), ADMIN_USERNAME.encode("utf-8")) and hmac.compare_digest(password.encode("utf-8"), ADMIN_PASSWORD.encode("utf-8")):
            preferred_language = session.get("language", "en")
            session.clear()
            session["language"] = preferred_language
            session.permanent = True
            session["admin_authenticated"] = True
            if os.environ.get("DATABASE_URL"):
                admin_audit("login")
                db.session.commit()
            return redirect(url_for("admin_dashboard"))
        flash(translate("The username or password is incorrect.", "שם המשתמש או הסיסמה אינם נכונים."), "error")
        return render_template("admin_login.html"), 401
    return render_template("admin_login.html")


@app.post("/admin/logout")
@admin_required
def admin_logout():
    admin_audit("logout")
    if os.environ.get("DATABASE_URL"):
        db.session.commit()
    preferred_language = session.get("language", "en")
    session.clear()
    session["language"] = preferred_language
    return redirect(url_for("index"))


def dashboard_response():
    if not os.environ.get("DATABASE_URL"):
        abort(503, description="DATABASE_URL is not configured.")
    total = db.session.query(func.count(Feedback.id)).scalar() or 0
    averages = {
        translate("Food quality", "איכות האוכל"): db.session.query(func.avg(Feedback.food_rating)).scalar(),
        translate("Taste", "טעם"): db.session.query(func.avg(Feedback.taste_rating)).scalar(),
        translate("Variety", "מגוון"): db.session.query(func.avg(Feedback.variety_rating)).scalar(),
        translate("Cleanliness", "ניקיון"): db.session.query(func.avg(Feedback.cleanliness_rating)).scalar(),
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
    return render_template("error.html", code=429, message=translate("Too many requests. Please wait and try again.", "נשלחו יותר מדי בקשות. המתינו ונסו שוב.")), 429


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
