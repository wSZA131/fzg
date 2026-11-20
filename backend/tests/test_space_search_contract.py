import copy
import unittest
from unittest.mock import patch

try:
    from app import server as backend_app

    _APP_IMPORT_ERROR = ""
except Exception as exc:
    backend_app = None
    _APP_IMPORT_ERROR = str(exc)


SPACE_PAYLOAD = {
    "activeEntrySpaceId": "sp1",
    "spaces": [
        {
            "id": "sp1",
            "name": "纺织材料",
            "items": [
                {
                    "id": "it1",
                    "name": "涤纶纤维性能总结",
                    "kind": "note",
                    "summary": "涤纶强度高、吸湿性差",
                    "content": "涤纶属于合成纤维，强度高但吸湿性差，常用于运动面料。",
                    "tags": ["涤纶", "合成纤维"],
                    "updatedAt": "2026-11-18T10:00:00",
                    "fileDataUrl": "data:text/plain;base64,QUJDREVGRw==",
                },
                {
                    "id": "it2",
                    "name": "棉织物整理工艺",
                    "kind": "document",
                    "summary": "棉织物后整理流程",
                    "content": "退浆、煮练、漂白、丝光属于棉织物前处理工序。",
                    "tags": ["棉"],
                    "updatedAt": "2026-11-17T09:00:00",
                },
            ],
        },
        {
            "id": "sp2",
            "name": "复习计划",
            "items": [
                {
                    "id": "it3",
                    "name": "涤纶错题整理",
                    "kind": "note",
                    "summary": "涤纶相关的易错点",
                    "content": "",
                    "tags": [],
                    "updatedAt": "2026-11-18T12:00:00",
                }
            ],
        },
    ],
}


@unittest.skipIf(backend_app is None, f"backend app unavailable: {_APP_IMPORT_ERROR}")
class TestSpaceSearchContract(unittest.TestCase):
    def setUp(self):
        backend_app.app.testing = True
        self.client = backend_app.app.test_client()

    def _patch_space(self):
        def get_user_space_payload(user_id):
            return copy.deepcopy(SPACE_PAYLOAD)

        def resolve_current_request_user_id_from_args():
            from flask import request

            return str(request.args.get("user_id") or "u_test"), None

        return patch.multiple(
            backend_app,
            get_user_space_payload=get_user_space_payload,
            resolve_current_request_user_id_from_args=resolve_current_request_user_id_from_args,
        )

    def _search(self, query, **params):
        from urllib.parse import urlencode

        payload = {"user_id": "u_test", "q": query}
        payload.update(params)
        return self.client.get(f"/api/spaces/search?{urlencode(payload)}")

    def test_search_matches_title_and_content(self):
        with self._patch_space():
            resp = self._search("涤纶")

        self.assertEqual(200, resp.status_code)
        data = resp.get_json() or {}
        self.assertTrue(data.get("success"))
        results = data.get("results") or []
        ids = [row.get("item_id") for row in results]
        self.assertIn("it1", ids)
        self.assertIn("it3", ids)
        self.assertNotIn("it2", ids)

    def test_search_returns_space_context(self):
        with self._patch_space():
            data = self._search("涤纶").get_json() or {}

        first = (data.get("results") or [])[0]
        self.assertIn(first.get("space_id"), {"sp1", "sp2"})
        self.assertTrue(first.get("space_name"))
        self.assertTrue(first.get("snippet"))

    def test_search_does_not_leak_data_url(self):
        with self._patch_space():
            data = self._search("涤纶").get_json() or {}

        serialized = str(data)
        self.assertNotIn("base64", serialized)

    def test_search_requires_keyword(self):
        with self._patch_space():
            resp = self.client.get("/api/spaces/search?user_id=u_test")

        self.assertEqual(400, resp.status_code)
        self.assertEqual("INVALID_INPUT", (resp.get_json() or {}).get("error_code"))

    def test_search_returns_empty_when_no_match(self):
        with self._patch_space():
            data = self._search("不存在的关键词").get_json() or {}

        self.assertEqual(0, data.get("count"))
        self.assertEqual([], data.get("results"))

    def test_search_respects_limit(self):
        with self._patch_space():
            data = self._search("涤纶", limit="1").get_json() or {}

        self.assertEqual(1, len(data.get("results") or []))


if __name__ == "__main__":
    unittest.main()
