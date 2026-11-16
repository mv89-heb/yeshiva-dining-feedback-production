"""Regression tests for persistent admin accounts and per-user permissions."""
import os
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app import app, db, AdminUser, Feedback, PortionRating, DishRating
from werkzeug.security import generate_password_hash


class AdminPermissionTests(unittest.TestCase):
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
            db.session.add_all([
                AdminUser(username="admin", password_hash=generate_password_hash("StrongTestPassword1!"),
                          role="superadmin", is_active=True, can_view_feedback=True,
                          can_manage_users=True, created_by="test"),
                AdminUser(username="viewer", password_hash=generate_password_hash("ViewerTestPassword1!"),
                          role="manager", is_active=True, can_view_feedback=True,
                          can_manage_users=False, created_by="test"),
                AdminUser(username="disabled", password_hash=generate_password_hash("DisabledTestPassword1!"),
                          role="manager", is_active=False, can_view_feedback=True,
                          can_manage_users=False, created_by="test"),
            ])
            db.session.commit()
        self.client = app.test_client()

    def login(self, username, password):
        return self.client.post("/admin/login", data={"username": username, "password": password},
                                follow_redirects=False)


    def test_admin_menu_editor_loads_external_script_after_document(self):
        self.login("admin", "StrongTestPassword1!")
        response = self.client.get("/admin/menu")
        self.assertEqual(response.status_code, 200)
        html = response.data.decode("utf-8")
        title = html.split("<title>", 1)[1].split("</title>", 1)[0]
        self.assertNotIn("<script", title)
        self.assertIn("/static/admin-menu.js", html)
        self.assertIn('id="weekly-menu-status"', html)
        self.assertIn('id="daily-menu-status"', html)

    def test_dashboard_filters_feedback_by_date_and_meal(self):
        today = datetime.now(ZoneInfo("Asia/Jerusalem")).date()
        yesterday = today - timedelta(days=1)
        with app.app_context():
            lunch = Feedback(
                meal_date=today, meal_type="lunch",
                food_rating=5, taste_rating=5, variety_rating=4,
                cleanliness_rating=5, comments="filter-lunch-only",
            )
            dinner = Feedback(
                meal_date=yesterday, meal_type="dinner",
                food_rating=1, taste_rating=2, variety_rating=1,
                cleanliness_rating=2, comments="filter-dinner-only",
            )
            db.session.add_all([lunch, dinner])
            db.session.flush()
            db.session.add(PortionRating(feedback_id=lunch.id, rating=5))
            db.session.add(DishRating(
                feedback_id=lunch.id, dish_slug="schnitzel",
                category="main", rating=5,
            ))
            db.session.commit()

        self.login("admin", "StrongTestPassword1!")
        response = self.client.get(
            f"/admin?date_from={today.isoformat()}&date_to={today.isoformat()}&meal_type=lunch"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"filter-lunch-only", response.data)
        self.assertNotIn(b"filter-dinner-only", response.data)
        self.assertIn(b"5.00", response.data)

    def test_dashboard_rejects_invalid_filter_ranges(self):
        self.login("admin", "StrongTestPassword1!")
        self.assertEqual(self.client.get("/admin?meal_type=brunch").status_code, 400)
        self.assertEqual(self.client.get("/admin?date_from=2026-11-17&date_to=2026-11-16").status_code, 400)

    def test_superadmin_can_open_user_management(self):
        self.login("admin", "StrongTestPassword1!")
        response = self.client.get("/admin")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"User and permission management", response.data)

    def test_viewer_can_see_feedback_but_cannot_manage_users(self):
        self.login("viewer", "ViewerTestPassword1!")
        self.assertEqual(self.client.get("/admin").status_code, 200)
        self.assertEqual(self.client.get("/admin/users").status_code, 403)
        self.assertEqual(self.client.get("/admin").status_code, 200)

    def test_disabled_user_cannot_log_in(self):
        response = self.login("disabled", "DisabledTestPassword1!")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.client.get("/admin").status_code, 302)

    def test_superadmin_is_not_editable_through_user_update(self):
        self.login("admin", "StrongTestPassword1!")
        with app.app_context():
            admin_id = AdminUser.query.filter_by(username="admin").one().id
        response = self.client.post(f"/admin/users/{admin_id}/update", data={
            "can_view_feedback": "on", "can_manage_users": "on", "is_active": "on"
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            admin = AdminUser.query.filter_by(username="admin").one()
            self.assertTrue(admin.is_active)
            self.assertEqual(admin.role, "superadmin")

    def test_viewer_cannot_change_another_users_permissions(self):
        self.login("viewer", "ViewerTestPassword1!")
        with app.app_context():
            disabled_id = AdminUser.query.filter_by(username="disabled").one().id

        response = self.client.post(f"/admin/users/{disabled_id}/update", data={
            "can_view_feedback": "on",
            "can_manage_users": "on",
            "is_active": "on",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 403)

        with app.app_context():
            disabled = AdminUser.query.filter_by(username="disabled").one()
            self.assertFalse(disabled.is_active)
            self.assertFalse(disabled.can_manage_users)


if __name__ == "__main__":
    unittest.main()
