"""Real Chromium viewport regression tests for the Hebrew/English mobile layouts."""
import os
import unittest

from playwright.sync_api import sync_playwright
from werkzeug.security import generate_password_hash

from app import AdminUser, app, db


class MobileViewportTests(unittest.TestCase):
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
        db.engine.dispose()

    @classmethod
    def tearDownClass(cls):
        with app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()
        if cls.original_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = cls.original_database_url

    def setUp(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()
            db.create_all()
            db.session.add(AdminUser(
                username="mobile-admin",
                password_hash=generate_password_hash("MobileTestPassword1!"),
                role="superadmin",
                is_active=True,
                can_view_feedback=True,
                can_manage_users=True,
                created_by="mobile viewport test",
            ))
            db.session.commit()
        self.client = app.test_client()
        self.client.post("/admin/login", data={
            "username": "mobile-admin",
            "password": "MobileTestPassword1!",
        })

    def test_admin_and_student_pages_fit_phone_viewports_in_both_directions(self):
        pages = []
        for language in ("he", "en"):
            self.client.post("/language", data={"language": language, "next": "/admin"})
            pages.append((f"admin-{language}", self.client.get("/admin").get_data(as_text=True)))
            pages.append((f"feedback-{language}", self.client.get("/feedback").get_data(as_text=True)))

        widths = (320, 360, 375, 390, 430)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            for page_name, html in pages:
                for width in widths:
                    page.set_viewport_size({"width": width, "height": 844})
                    page.set_content(html, wait_until="domcontentloaded")
                    metrics = page.evaluate("""() => {
                      const main = document.querySelector('main');
                      const rect = main.getBoundingClientRect();
                      return {
                        viewport: window.innerWidth,
                        rootWidth: document.documentElement.scrollWidth,
                        bodyWidth: document.body.scrollWidth,
                        mainLeft: rect.left,
                        mainRight: rect.right
                      };
                    }""")
                    self.assertLessEqual(
                        metrics["rootWidth"], width + 1,
                        f"{page_name} at {width}px has document horizontal overflow: {metrics}",
                    )
                    self.assertLessEqual(
                        metrics["bodyWidth"], width + 1,
                        f"{page_name} at {width}px has body horizontal overflow: {metrics}",
                    )
                    self.assertGreaterEqual(
                        metrics["mainLeft"], -1,
                        f"{page_name} at {width}px starts outside the left edge: {metrics}",
                    )
                    self.assertLessEqual(
                        metrics["mainRight"], width + 1,
                        f"{page_name} at {width}px ends outside the right edge: {metrics}",
                    )
            browser.close()


if __name__ == "__main__":
    unittest.main()
