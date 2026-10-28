"""Regression tests for anonymous, per-browser/per-meal submission limits.

Run with: python -m unittest discover -s tests -v
"""
import os
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from app import app, db, Feedback, AnonymousSubmission, AdminUser
from werkzeug.security import generate_password_hash


class AnonymousSubmissionLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_database_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = "sqlite-test-configured"
        app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False,
            SQLALCHEMY_DATABASE_URI="sqlite://",
            SQLALCHEMY_ENGINE_OPTIONS={},
            RATELIMIT_ENABLED=False,
        )
        with app.app_context():
            db.create_all()

    @classmethod
    def tearDownClass(cls):
        with app.app_context():
            db.session.remove()
            db.drop_all()
        if cls.original_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = cls.original_database_url

    def setUp(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()
            db.create_all()
        self.client = app.test_client()
        self.today = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
        self.client.get("/feedback")  # issues the anonymous browser token

    def submit(self, client, meal_type="lunch"):
        return client.post("/feedback", data={
            "meal_date": self.today,
            "meal_type": meal_type,
            "food_rating": "4",
            "taste_rating": "4",
            "variety_rating": "3",
            "cleanliness_rating": "5",
            "comments": "",
        }, follow_redirects=False)

    def test_same_browser_cannot_submit_same_meal_twice(self):
        first = self.submit(self.client, "lunch")
        second = self.submit(self.client, "lunch")
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 409)
        with app.app_context():
            self.assertEqual(Feedback.query.count(), 1)
            self.assertEqual(AnonymousSubmission.query.count(), 1)

    def test_same_browser_can_submit_different_meals(self):
        self.assertEqual(self.submit(self.client, "breakfast").status_code, 302)
        self.assertEqual(self.submit(self.client, "lunch").status_code, 302)
        with app.app_context():
            self.assertEqual(Feedback.query.count(), 2)
            self.assertEqual(AnonymousSubmission.query.count(), 2)

    def test_another_browser_has_an_independent_anonymous_limit(self):
        self.assertEqual(self.submit(self.client, "dinner").status_code, 302)
        other_client = app.test_client()
        other_client.get("/feedback")  # receives a different token
        self.assertEqual(self.submit(other_client, "dinner").status_code, 302)
        with app.app_context():
            self.assertEqual(Feedback.query.count(), 2)

    def test_post_without_browser_token_is_rejected(self):
        client_without_token = app.test_client()
        response = self.submit(client_without_token, "lunch")
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            self.assertEqual(Feedback.query.count(), 0)

    def test_non_today_meal_is_rejected(self):
        from datetime import timedelta
        yesterday = (datetime.now(ZoneInfo("Asia/Jerusalem")).date() - timedelta(days=1)).isoformat()
        response = self.client.post("/feedback", data={
            "meal_date": yesterday,
            "meal_type": "lunch",
            "food_rating": "4",
            "taste_rating": "4",
            "variety_rating": "3",
            "cleanliness_rating": "5",
            "comments": "",
        })
        self.assertEqual(response.status_code, 400)
        with app.app_context():
            self.assertEqual(Feedback.query.count(), 0)

    def test_invalid_rating_rolls_back_and_does_not_block_valid_retry(self):
        invalid = self.client.post("/feedback", data={
            "meal_date": self.today,
            "meal_type": "lunch",
            "food_rating": "6",
            "taste_rating": "4",
            "variety_rating": "3",
            "cleanliness_rating": "5",
            "comments": "",
        })
        self.assertEqual(invalid.status_code, 400)
        with app.app_context():
            self.assertEqual(Feedback.query.count(), 0)
            self.assertEqual(AnonymousSubmission.query.count(), 0)

        valid = self.submit(self.client, "lunch")
        self.assertEqual(valid.status_code, 302)
        with app.app_context():
            self.assertEqual(Feedback.query.count(), 1)
            self.assertEqual(AnonymousSubmission.query.count(), 1)


    def test_language_switch_rejects_backslash_redirect(self):
        response = self.client.post("/language", data={
            "language": "he",
            "next": "/\\\\evil.example",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/")

    def test_language_switch_allows_safe_local_redirect(self):
        response = self.client.post("/language", data={
            "language": "he",
            "next": "/feedback",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/feedback")

    def test_public_templates_render(self):
        for path in ("/", "/feedback/thanks", "/admin/login"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b"<!doctype html>", response.data.lower())

    def test_admin_dashboard_template_renders_after_login(self):
        with app.app_context():
            db.session.add(AdminUser(
                username="design-admin",
                password_hash=generate_password_hash("LongSecurePassword123!"),
                role="superadmin",
                is_active=True,
                can_view_feedback=True,
                can_manage_users=True,
            ))
            db.session.commit()

        with self.client.session_transaction() as session:
            session["admin_user_id"] = 1
            session["admin_username"] = "design-admin"
        dashboard = self.client.get("/admin")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b"User and permission management", dashboard.data)

if __name__ == "__main__":
    unittest.main()
