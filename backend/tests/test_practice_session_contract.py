import copy
import unittest
from unittest.mock import patch

try:
    from app import server as backend_app

    _APP_IMPORT_ERROR = ""
except Exception as exc:
    backend_app = None
    _APP_IMPORT_ERROR = str(exc)


@unittest.skipIf(backend_app is None, f"backend app unavailable: {_APP_IMPORT_ERROR}")
class TestPracticeSessionContract(unittest.TestCase):
    def setUp(self):
        backend_app.app.testing = True
        self.client = backend_app.app.test_client()
        self.events = {}

    def _storage(self):
        def append_user_event(user_id, suffix, item):
            self.events.setdefault((user_id, suffix), []).append(copy.deepcopy(item))

        def load_user_event_list(user_id, suffix):
            return copy.deepcopy(self.events.get((user_id, suffix), []))

        def resolve_request_user_id_from_json(data):
            return str((data or {}).get("user_id") or "u_test"), None

        def resolve_request_user_id_from_args():
            from flask import request

            return str(request.args.get("user_id") or "u_test"), None

        return patch.multiple(
            backend_app,
            append_user_event=append_user_event,
            load_user_event_list=load_user_event_list,
            resolve_request_user_id_from_json=resolve_request_user_id_from_json,
            resolve_request_user_id_from_args=resolve_request_user_id_from_args,
        )

    def _session(self, session_id="s1"):
        return {
            "id": session_id,
            "title": "导数专项练习",
            "concept": "导数",
            "scope": "concept",
            "difficulty": "medium",
            "items": [{"id": "q1"}, {"id": "q2"}, {"id": "q3"}],
            "answers": {
                "q1": {"correct": True, "score": 1},
                "q2": {"correct": False, "score": 0},
            },
            "elapsedSeconds": 320,
            "completedAt": 1763500000000,
        }

    def test_save_practice_session_computes_summary(self):
        with self._storage():
            resp = self.client.post(
                "/api/question_bank/practice-session",
                json={"user_id": "u_test", "session": self._session()},
            )

        self.assertEqual(200, resp.status_code)
        payload = (resp.get_json() or {}).get("session") or {}
        self.assertEqual(3, payload.get("total_count"))
        self.assertEqual(2, payload.get("answered_count"))
        self.assertEqual(1, payload.get("correct_count"))
        self.assertAlmostEqual(0.3333, payload.get("accuracy"), places=4)
        self.assertEqual(320, payload.get("elapsed_seconds"))
        self.assertEqual("导数", payload.get("concept"))

        stored = self.events.get(("u_test", "practice_session")) or []
        self.assertEqual(1, len(stored))

    def test_save_rejects_non_object_session(self):
        with self._storage():
            resp = self.client.post(
                "/api/question_bank/practice-session",
                json={"user_id": "u_test", "session": "not-an-object"},
            )

        self.assertEqual(400, resp.status_code)
        self.assertEqual("INVALID_INPUT", (resp.get_json() or {}).get("error_code"))

    def test_list_practice_sessions_sorted_desc(self):
        with self._storage():
            self.client.post(
                "/api/question_bank/practice-session",
                json={"user_id": "u_test", "session": self._session("s1")},
            )
            self.client.post(
                "/api/question_bank/practice-session",
                json={"user_id": "u_test", "session": self._session("s2")},
            )
            resp = self.client.get("/api/question_bank/practice-sessions?user_id=u_test")

        self.assertEqual(200, resp.status_code)
        data = resp.get_json() or {}
        self.assertEqual(2, data.get("count"))
        items = data.get("items") or []
        self.assertEqual(2, len(items))
        self.assertGreaterEqual(
            str(items[0].get("timestamp") or ""),
            str(items[1].get("timestamp") or ""),
        )

    def test_list_isolated_by_user(self):
        with self._storage():
            self.client.post(
                "/api/question_bank/practice-session",
                json={"user_id": "user_a", "session": self._session("s1")},
            )
            resp = self.client.get("/api/question_bank/practice-sessions?user_id=user_b")

        self.assertEqual(0, (resp.get_json() or {}).get("count"))


if __name__ == "__main__":
    unittest.main()
