import re
import unittest
from unittest.mock import patch

try:
    from app import server as backend_app
    from app.api import agent_routes
    from app.services import rate_limit

    _APP_IMPORT_ERROR = ""
except Exception as exc:
    backend_app = None
    _APP_IMPORT_ERROR = str(exc)


FAST_POLICIES = (
    (re.compile(r"^/api/agent/ocr-tutor$"), "agent_tutor", 2),
    (re.compile(r"^/api/"), "api", 1000),
)


@unittest.skipIf(backend_app is None, f"backend app unavailable: {_APP_IMPORT_ERROR}")
class TestRateLimitContract(unittest.TestCase):
    def setUp(self):
        rate_limit.reset_all()
        backend_app.app.testing = True
        self.client = backend_app.app.test_client()

    def tearDown(self):
        rate_limit.reset_all()

    def _post_tutor(self, client, ip="203.0.113.20"):
        return client.post(
            "/api/agent/ocr-tutor",
            json={},
            environ_base={"REMOTE_ADDR": ip},
        )

    def test_disabled_by_default_passes_through(self):
        with patch.object(rate_limit, "RATE_LIMIT_ENABLED", False):
            codes = [self._post_tutor(self.client).status_code for _ in range(6)]
        self.assertNotIn(429, codes)

    def test_enabled_blocks_after_threshold(self):
        with patch.object(rate_limit, "RATE_LIMIT_ENABLED", True), patch.object(
            rate_limit, "POLICIES", FAST_POLICIES
        ):
            codes = [self._post_tutor(self.client).status_code for _ in range(4)]

        self.assertNotEqual(429, codes[0])
        self.assertNotEqual(429, codes[1])
        self.assertEqual(429, codes[2])
        self.assertEqual(429, codes[3])

    def test_rejected_response_contract(self):
        with patch.object(rate_limit, "RATE_LIMIT_ENABLED", True), patch.object(
            rate_limit, "POLICIES", FAST_POLICIES
        ):
            for _ in range(2):
                self._post_tutor(self.client)
            resp = self._post_tutor(self.client)

        self.assertEqual(429, resp.status_code)
        self.assertTrue(resp.headers.get("Retry-After", "").isdigit())
        data = resp.get_json() or {}
        self.assertFalse(data.get("success"))
        self.assertEqual("RATE_LIMITED", data.get("error_code"))

    def test_health_is_exempt(self):
        with patch.object(rate_limit, "RATE_LIMIT_ENABLED", True), patch.object(
            rate_limit, "POLICIES", FAST_POLICIES
        ):
            codes = [self.client.get("/health").status_code for _ in range(4)]

        self.assertEqual([200, 200, 200, 200], codes)

    def test_clients_are_isolated(self):
        with patch.object(rate_limit, "RATE_LIMIT_ENABLED", True), patch.object(
            rate_limit, "POLICIES", FAST_POLICIES
        ):
            for _ in range(3):
                self._post_tutor(self.client, ip="203.0.113.30")
            other = self._post_tutor(self.client, ip="203.0.113.31")

        self.assertNotEqual(429, other.status_code)

    def test_prometheus_metrics_format(self):
        resp = self.client.get("/metrics")
        self.assertEqual(200, resp.status_code)
        self.assertIn("text/plain", resp.content_type or "")

        body = resp.get_data(as_text=True)
        required = (
            "fzg_agent_requests_total",
            "fzg_agent_success_rate",
            "fzg_agent_latency_avg_ms",
            "fzg_rate_limit_enabled",
        )
        for metric in required:
            self.assertIn(metric, body)

        declared = [
            line.split()[2] for line in body.splitlines() if line.startswith("# HELP ")
        ]
        self.assertEqual(len(declared), len(set(declared)), "HELP 不应重复声明")

    def test_eval_meta_reports_environment(self):
        meta = agent_routes._eval_environment_snapshot()

        for key in (
            "ai_enabled",
            "ai_key_configured",
            "provider",
            "model",
            "agent_mode",
            "kb_mode",
            "kb_ready",
            "notes",
        ):
            self.assertIn(key, meta)

        self.assertIn(meta["agent_mode"], {"llm", "local_rule_fallback"})
        self.assertIsInstance(meta["notes"], list)
        if meta["agent_mode"] != "llm":
            self.assertTrue(meta["notes"], "非 LLM 模式必须给出说明")


if __name__ == "__main__":
    unittest.main()
