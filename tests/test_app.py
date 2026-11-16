"""Regression tests for anonymous, per-browser/per-meal submission limits.

Run with: python -m unittest discover -s tests -v
"""
import os
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from app import app, db, Feedback, AnonymousSubmission, AdminUser, DishRating, PortionRating, WeeklyMenuDish, DailyMenuOverride, DailyMenuDish, limiter
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
        limiter.reset()
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
            "portion_rating": "4",
            "dish_name": "שניצלים",
            "dish_rating": "4",
            "comments": "",
        }, follow_redirects=False)

    def test_liveness_and_readiness_endpoints(self):
        live = self.client.get("/live")
        self.assertEqual(live.status_code, 200)
        self.assertEqual(live.get_json(), {"status": "alive"})
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.get_json()["status"], "ok")
        self.assertIn("commit", health.get_json())
        self.assertIn("branch", health.get_json())

        ready = self.client.get("/ready")
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.get_json(), {"status": "ready", "database": "ok"})

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


    def test_portion_and_dish_ratings_are_persisted_without_javascript(self):
        response = self.client.post("/feedback", data={
            "meal_date": self.today,
            "meal_type": "lunch",
            "food_rating": "4",
            "taste_rating": "5",
            "variety_rating": "3",
            "cleanliness_rating": "5",
            "portion_rating": "2",
            "dish_name": "שניצלים",
            "dish_rating": "5",
            "comments": "Very tasty",
        })
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            saved = Feedback.query.one()
            self.assertIn("Very tasty", saved.comments)
            self.assertIn("Portion size: 2/5", saved.comments)
            self.assertIn("Dish feedback: שניצלים — 5/5", saved.comments)

    def test_missing_menu_dish_is_rejected_without_saving(self):
        response = self.client.post("/feedback", data={
            "meal_date": self.today,
            "meal_type": "lunch",
            "food_rating": "4",
            "taste_rating": "4",
            "variety_rating": "3",
            "cleanliness_rating": "5",
            "portion_rating": "4",
            "dish_rating": "4",
            "comments": "",
        })
        self.assertEqual(response.status_code, 400)
        with app.app_context():
            self.assertEqual(Feedback.query.count(), 0)
            self.assertEqual(AnonymousSubmission.query.count(), 0)

    def test_unknown_menu_dish_is_rejected_without_saving(self):
        response = self.client.post("/feedback", data={
            "meal_date": self.today,
            "meal_type": "lunch",
            "food_rating": "4",
            "taste_rating": "4",
            "variety_rating": "3",
            "cleanliness_rating": "5",
            "portion_rating": "4",
            "dish_name": "מנה שלא קיימת בתפריט",
            "dish_rating": "4",
            "comments": "",
        })
        self.assertEqual(response.status_code, 400)
        with app.app_context():
            self.assertEqual(Feedback.query.count(), 0)
            self.assertEqual(AnonymousSubmission.query.count(), 0)

    def test_incomplete_dish_feedback_is_rejected_without_saving(self):
        response = self.client.post("/feedback", data={
            "meal_date": self.today,
            "meal_type": "lunch",
            "food_rating": "4",
            "taste_rating": "4",
            "variety_rating": "3",
            "cleanliness_rating": "5",
            "portion_rating": "4",
            "dish_name": "Schnitzel",
            "comments": "",
        })
        self.assertEqual(response.status_code, 400)
        with app.app_context():
            self.assertEqual(Feedback.query.count(), 0)
            self.assertEqual(AnonymousSubmission.query.count(), 0)

    def test_invalid_portion_rating_is_rejected_without_saving(self):
        response = self.client.post("/feedback", data={
            "meal_date": self.today,
            "meal_type": "lunch",
            "food_rating": "4",
            "taste_rating": "4",
            "variety_rating": "3",
            "cleanliness_rating": "5",
            "portion_rating": "9",
            "dish_name": "שניצלים",
            "dish_rating": "4",
            "comments": "",
        })
        self.assertEqual(response.status_code, 400)
        with app.app_context():
            self.assertEqual(Feedback.query.count(), 0)
            self.assertEqual(AnonymousSubmission.query.count(), 0)


    def test_multiple_selected_dishes_are_saved_as_independent_ratings(self):
        from app import MENU_DISHES
        response = self.client.post("/feedback", data={
            "meal_date": self.today,
            "meal_type": "lunch",
            "food_rating": "4", "taste_rating": "5", "variety_rating": "3",
            "cleanliness_rating": "5", "portion_rating": "4",
            "dish_slug": [MENU_DISHES[0][0], MENU_DISHES[1][0]],
            "dish_rating_" + MENU_DISHES[0][0]: "5",
            "dish_rating_" + MENU_DISHES[1][0]: "2",
            "comments": "Both tasted different.",
        })
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            self.assertEqual(DishRating.query.count(), 2)
            self.assertEqual(sorted(r.rating for r in DishRating.query.all()), [2, 5])
            self.assertEqual(PortionRating.query.one().rating, 4)
            self.assertEqual(Feedback.query.one().comments, "Both tasted different.")

    def test_weekly_menu_and_daily_override_are_resolved_separately(self):
        from app import MENU_DISHES, menu_items_for
        target = datetime.now(ZoneInfo("Asia/Jerusalem")).date()
        with app.app_context():
            weekly = WeeklyMenuDish(weekday=target.weekday(), meal_type="lunch",
                                    dish_slug=MENU_DISHES[0][0], category="main")
            db.session.add(weekly)
            db.session.commit()
            self.assertEqual([x["slug"] for x in menu_items_for(target, "lunch")], [MENU_DISHES[0][0]])
            override = DailyMenuOverride(meal_date=target, meal_type="lunch")
            db.session.add(override)
            db.session.flush()
            db.session.add(DailyMenuDish(menu_id=override.id, dish_slug=MENU_DISHES[1][0], category="side"))
            db.session.commit()
            result = menu_items_for(target, "lunch")
            self.assertEqual([x["slug"] for x in result], [MENU_DISHES[1][0]])
            self.assertEqual(result[0]["category"], "side")

    def test_student_menu_api_returns_only_configured_meal_items(self):
        from app import MENU_DISHES
        today = datetime.now(ZoneInfo("Asia/Jerusalem")).date()
        with app.app_context():
            db.session.add(WeeklyMenuDish(weekday=today.weekday(), meal_type="lunch",
                                          dish_slug=MENU_DISHES[0][0], category="main"))
            db.session.commit()
        response = self.client.get("/api/menu?date=" + self.today + "&meal_type=lunch")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["configured"])
        self.assertEqual(len(payload["dishes"]), 1)
        self.assertEqual(payload["dishes"][0]["slug"], MENU_DISHES[0][0])

    def test_selected_dish_not_in_configured_menu_is_rejected(self):
        from app import MENU_DISHES
        today = datetime.now(ZoneInfo("Asia/Jerusalem")).date()
        with app.app_context():
            db.session.add(WeeklyMenuDish(weekday=today.weekday(), meal_type="lunch",
                                          dish_slug=MENU_DISHES[0][0], category="main"))
            db.session.commit()
        response = self.client.post("/feedback", data={
            "meal_date": self.today, "meal_type": "lunch",
            "food_rating": "4", "taste_rating": "4", "variety_rating": "4",
            "cleanliness_rating": "4", "portion_rating": "4",
            "dish_slug": MENU_DISHES[1][0], "dish_rating_" + MENU_DISHES[1][0]: "4",
        })
        self.assertEqual(response.status_code, 400)
        with app.app_context():
            self.assertEqual(Feedback.query.count(), 0)
            self.assertEqual(AnonymousSubmission.query.count(), 0)


    def test_explicit_empty_daily_override_does_not_fall_back_to_weekly(self):
        from app import MENU_DISHES
        today = datetime.now(ZoneInfo("Asia/Jerusalem")).date()
        with app.app_context():
            db.session.add(WeeklyMenuDish(weekday=today.weekday(), meal_type="lunch",
                                          dish_slug=MENU_DISHES[0][0], category="main"))
            db.session.add(DailyMenuOverride(meal_date=today, meal_type="lunch"))
            db.session.commit()
        response = self.client.get("/api/menu?date=" + self.today + "&meal_type=lunch")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["configured"])
        self.assertEqual(payload["dishes"], [])

    def test_portion_rating_is_required_by_server(self):
        from app import MENU_DISHES
        response = self.client.post("/feedback", data={
            "meal_date": self.today, "meal_type": "lunch",
            "food_rating": "4", "taste_rating": "4", "variety_rating": "4",
            "cleanliness_rating": "4",
            "dish_slug": MENU_DISHES[0][0],
            "dish_rating_" + MENU_DISHES[0][0]: "4",
        })
        self.assertEqual(response.status_code, 400)
        with app.app_context():
            self.assertEqual(Feedback.query.count(), 0)
            self.assertEqual(AnonymousSubmission.query.count(), 0)

    def test_admin_menu_data_requires_manager_permission(self):
        response = self.client.get("/api/admin/menu?scope=weekly&weekday=0&meal_type=lunch")
        self.assertEqual(response.status_code, 302)

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
        for path in ("/", "/feedback", "/feedback/thanks", "/admin/login"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b"<!doctype html>", response.data.lower())
                if path == "/feedback":
                    self.assertIn(b"student-feedback-form", response.data)
                    self.assertIn(b"emoji-rating", response.data)
                    self.assertIn(b'id="main-dishes"', response.data)
                    self.assertIn(b'id="side-dishes"', response.data)
                    self.assertIn(b"meal_type", response.data)
                if path == "/feedback/thanks":
                    self.assertIn(b"FEEDBACK RECEIVED", response.data)

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
