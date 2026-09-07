import json
from pathlib import Path
import unittest

from demo.make_fixture import build_fixture


ROOT = Path(__file__).resolve().parent


class DemoTests(unittest.TestCase):
    def test_fixture_uses_real_queue_rules_and_exact_public_states(self):
        fixture = build_fixture()
        self.assertTrue(fixture["synthetic"])
        self.assertEqual(fixture["duration_ms"], 24_000)
        self.assertEqual(fixture["fps"], 30)
        self.assertEqual(
            fixture["queued"]["preview"],
            "Tasks · Next: Run pre-release regression · 1 next · 0 waiting",
        )
        self.assertEqual(
            fixture["doing"]["preview"],
            "Tasks · Now: Run pre-release regression · 0 next · 0 waiting",
        )
        self.assertEqual(fixture["claim"]["command"], "herdr-tasks next")
        self.assertEqual(fixture["claim"]["task"]["owner_name"], "QA")

        serialized = json.dumps(fixture, sort_keys=True)
        for forbidden in ("/Users/", "agentakt", "FindProjectsApp", "token", "members"):
            self.assertNotIn(forbidden, serialized)

    def test_capture_is_deterministic_local_and_explicitly_synthetic(self):
        capture = (ROOT / "demo" / "capture.html").read_text(encoding="utf-8")
        runner = (ROOT / "demo" / "capture_demo.mjs").read_text(encoding="utf-8")
        self.assertIn("window.__setDemoTime", capture)
        self.assertIn("window.__DEMO_READY__", capture)
        self.assertIn("data.synthetic", capture)
        self.assertIn("FRAME_COUNT = 720", runner)
        self.assertIn('server.listen(0, "127.0.0.1"', runner)
        self.assertNotIn("FindProjectsApp", capture)
        self.assertNotIn("/Users/", capture + runner)
        self.assertNotIn("https://", capture)


if __name__ == "__main__":
    unittest.main()
