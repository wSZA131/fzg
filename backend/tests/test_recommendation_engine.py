import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.recommendation_engine import (
    build_recommendation_feed,
    collect_open_resource_queries,
)


class RecommendationEngineTests(unittest.TestCase):
    def _open_resource(self, resource_id, concept, kind="open_article", provider="Wikipedia"):
        return {
            "id": resource_id,
            "title": f"{concept} 开放资源",
            "concept": concept,
            "resource_kind": kind,
            "resource_type": "开放教材" if kind == "open_textbook" else "拓展阅读",
            "provider": provider,
            "difficulty": "medium",
            "duration_minutes": 6,
            "cover_url": "https://example.com/cover.jpg",
            "action": {
                "type": "external_course",
                "concept": concept,
                "url": f"https://example.com/{resource_id}",
            },
            "tags": [concept, "开放资源"],
            "learning_styles": ["visual"],
            "quality_score": 0.8,
        }

    def test_cold_start_does_not_invent_content(self):
        feed = build_recommendation_feed(
            user_id="guest_cold",
            profile={},
            knowledge={"concepts": [], "relations": [], "deleted_concepts": []},
            reminders={"due_items": []},
            limit=8,
        )

        self.assertEqual(feed["items"], [])
        self.assertEqual(feed["audit"]["candidate_count"], 0)

    def test_only_open_api_resources_are_returned(self):
        feed = build_recommendation_feed(
            user_id="guest_external",
            profile={
                "learning_style": "visual",
                "style_method": "rule",
                "style_scores": {"visual": 0.8},
                "interests": ["导数"],
            },
            knowledge={
                "concepts": [{"concept": "导数", "mastery": 0.25}],
                "relations": [],
                "deleted_concepts": [],
            },
            reminders={
                "due_items": [{
                    "concept": "极限",
                    "mastery": 0.45,
                    "overdue_days": 2,
                    "priority": 72,
                }],
            },
            open_resources=[
                self._open_resource("wiki-derivative", "导数"),
                self._open_resource("book-limit", "极限", "open_textbook", "Wikibooks"),
            ],
            limit=8,
        )

        items = feed["items"]
        self.assertGreaterEqual(len(items), 2)
        self.assertTrue(all(item["resource_kind"] in {"open_article", "open_textbook", "open_video"} for item in items))
        self.assertIn("weak_mastery", items[0]["reason_codes"])
        self.assertTrue(any("review_due" in item["reason_codes"] for item in items))
        self.assertIn("evidence_brief", items[0])
        self.assertIn("source_evidence", items[0])
        self.assertIn("strategy_tags", items[0])
        self.assertTrue(all((item.get("action") or {}).get("url") for item in items))

    def test_no_open_resources_means_empty_explore(self):
        feed = build_recommendation_feed(
            user_id="guest_no_open",
            profile={"interests": ["导数"]},
            knowledge={"concepts": [{"concept": "导数", "mastery": 0.2}], "relations": [], "deleted_concepts": []},
            reminders={"due_items": []},
            limit=8,
        )
        self.assertEqual(feed["items"], [])

    def test_excluded_and_dismissed_resources_are_not_returned(self):
        open_resources = [self._open_resource("wiki-feedback", "导数")]
        base = build_recommendation_feed(
            user_id="guest_feedback",
            profile={"interests": ["导数"]},
            knowledge={"concepts": [], "relations": [], "deleted_concepts": []},
            reminders={"due_items": []},
            open_resources=open_resources,
            limit=8,
        )
        first_ids = [item["id"] for item in base["items"]]
        self.assertTrue(first_ids)
        dismissed_id = first_ids[0]

        feed = build_recommendation_feed(
            user_id="guest_feedback",
            profile={"interests": ["导数"]},
            knowledge={"concepts": [], "relations": [], "deleted_concepts": []},
            reminders={"due_items": []},
            open_resources=open_resources,
            feedback_events=[{
                "resource_id": dismissed_id,
                "event_type": "dismiss",
                "timestamp": "2099-01-01T00:00:00",
            }],
            exclude_ids=first_ids,
            limit=8,
        )

        returned_ids = {item["id"] for item in feed["items"]}
        self.assertNotIn(dismissed_id, returned_ids)
        self.assertFalse(returned_ids & set(first_ids))

    def test_refresh_returns_eight_new_cards(self):
        kinds = ["open_article", "open_textbook", "open_lesson", "open_paper", "external_book", "open_video"]
        resources = []
        for index in range(24):
            kind = kinds[index % len(kinds)]
            provider = {
                "open_article": "Wikipedia",
                "open_textbook": "OpenStax",
                "open_lesson": "Oak National Academy",
                "open_paper": "Google Scholar",
                "external_book": "Google Play Books",
                "open_video": "YouTube",
            }[kind]
            resources.append(self._open_resource(f"external-{index}", "导数", kind, provider))

        profile = {"learning_style": "visual", "style_method": "rule", "interests": ["导数"]}
        knowledge = {"concepts": [{"concept": "导数", "mastery": 0.3}], "relations": [], "deleted_concepts": []}
        first = build_recommendation_feed(
            user_id="guest_batch",
            profile=profile,
            knowledge=knowledge,
            reminders={"due_items": []},
            open_resources=resources,
            limit=8,
        )
        first_ids = [item["id"] for item in first["items"]]
        self.assertEqual(len(first_ids), 8)

        second = build_recommendation_feed(
            user_id="guest_batch",
            profile=profile,
            knowledge=knowledge,
            reminders={"due_items": []},
            open_resources=resources,
            limit=8,
            exclude_ids=first_ids,
        )
        second_ids = [item["id"] for item in second["items"]]
        self.assertEqual(len(second_ids), 8)
        self.assertFalse(set(first_ids) & set(second_ids))
        allowed_kinds = {"open_article", "open_textbook", "open_lesson", "open_paper", "external_book", "open_video"}
        self.assertTrue(all(item["resource_kind"] in allowed_kinds for item in second["items"]))

    def test_open_queries_come_only_from_profile_and_knowledge(self):
        self.assertEqual(
            collect_open_resource_queries({}, {"concepts": [], "relations": [], "deleted_concepts": []}),
            [],
        )

        queries = collect_open_resource_queries(
            profile={"interests": ["织物组织"]},
            knowledge={"concepts": [{"concept": "导数", "mastery": 0.3}], "relations": [], "deleted_concepts": []},
            reminders={"due_items": [{"concept": "极限", "mastery": 0.4, "overdue_days": 1}]},
            limit=4,
        )
        self.assertIn("导数", queries)
        self.assertIn("极限", queries)
        self.assertIn("织物组织", queries)
        self.assertLessEqual(len(queries), 4)


if __name__ == "__main__":
    unittest.main()
