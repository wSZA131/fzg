import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

try:
    from app.services import open_learning_resources
except Exception as error:  # requests/proxy environment may be unavailable
    open_learning_resources = None
    IMPORT_ERROR = error
else:
    IMPORT_ERROR = None


@unittest.skipIf(open_learning_resources is None, f"open resource module unavailable: {IMPORT_ERROR}")
class OpenLearningResourceTests(unittest.TestCase):
    def setUp(self):
        open_learning_resources.OPEN_RESOURCE_CACHE.clear()

    def test_wikipedia_and_wikibooks_are_normalized(self):
        payload = {
            "query": {
                "pages": {
                    "1": {
                        "pageid": 1,
                        "title": "导数",
                        "extract": "导数描述函数在某一点处的瞬时变化率。",
                        "fullurl": "https://zh.wikipedia.org/wiki/导数",
                        "index": 1,
                        "thumbnail": {"source": "https://upload.wikimedia.org/example.png"},
                    }
                }
            }
        }

        class FakeResponse:
            status_code = 200

            def json(self):
                return payload

        with patch("app.services.open_learning_resources.requests.get", return_value=FakeResponse()):
            articles = open_learning_resources.search_wikipedia("导数", 1)
            textbooks = open_learning_resources.search_wikibooks("导数", 1)

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["resource_kind"], "open_article")
        self.assertEqual(articles[0]["provider"], "Wikipedia")
        self.assertTrue(articles[0]["action"]["url"])

        self.assertEqual(len(textbooks), 1)
        self.assertEqual(textbooks[0]["resource_kind"], "open_textbook")
        self.assertEqual(textbooks[0]["provider"], "Wikibooks")

    def test_youtube_without_key_returns_empty(self):
        with patch.dict("os.environ", {"YOUTUBE_API_KEY": ""}, clear=False):
            self.assertEqual(open_learning_resources.search_youtube("导数", 1), [])

    def test_openstax_maps_chinese_concept_to_books(self):
        books = [{
            "title": "Calculus Volume 1",
            "slug": "calculus-volume-1",
            "url": "https://openstax.org/details/books/calculus-volume-1",
            "cover_url": "https://assets.openstax.org/calculus.svg",
            "description": "An introduction to calculus, derivatives and integrals.",
        }]
        with patch.object(open_learning_resources, "_load_openstax_catalog", return_value=books):
            rows = open_learning_resources.search_openstax("导数", 4)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["provider"], "OpenStax")
        self.assertEqual(rows[0]["resource_kind"], "open_textbook")
        self.assertTrue(rows[0]["action"]["url"].startswith("https://openstax.org/"))

    def test_oak_without_key_returns_empty(self):
        with patch.dict("os.environ", {"OAK_API_KEY": ""}, clear=False):
            self.assertEqual(open_learning_resources.search_oak("导数", 5), [])

    def test_oak_search_result_is_normalized(self):
        payload = [{
            "lessonSlug": "differentiation-introduction",
            "lessonTitle": "Introduction to differentiation",
            "oakUrl": "https://www.thenational.academy/teachers/lessons/differentiation-introduction",
            "similarity": 0.8,
            "units": [{
                "unitSlug": "differentiation",
                "unitTitle": "Differentiation",
                "examBoardTitle": None,
                "keyStageSlug": "ks4",
                "subjectSlug": "maths",
            }],
        }]
        with patch.dict("os.environ", {"OAK_API_KEY": "test-oak-key"}, clear=False), \
             patch.object(open_learning_resources, "_http_get_json", return_value=payload):
            rows = open_learning_resources.search_oak("导数", 5)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["provider"], "Oak National Academy")
        self.assertEqual(rows[0]["resource_kind"], "open_lesson")
        self.assertEqual(rows[0]["action"]["url"], payload[0]["oakUrl"])

    def test_google_play_books_without_key_returns_empty(self):
        with patch.dict("os.environ", {"SERPAPI_API_KEY": ""}, clear=False):
            self.assertEqual(open_learning_resources.search_google_play_books("导数", 5), [])

    def test_google_play_books_parses_nested_results(self):
        payload = {
            "organic_results": [{
                "title": "Mathematics",
                "items": [{
                    "title": "Calculus Made Easy",
                    "link": "https://play.google.com/store/books/details?id=abc123",
                    "product_id": "abc123",
                    "author": "Silvanus Thompson",
                    "category": "Mathematics",
                    "rating": 4.6,
                    "thumbnail": "https://books.google.com/cover.jpg",
                    "description": "A classic calculus book.",
                }],
            }]
        }
        with patch.dict("os.environ", {"SERPAPI_API_KEY": "test-serpapi-key"}, clear=False), \
             patch.object(open_learning_resources, "_http_get_json", return_value=payload):
            rows = open_learning_resources.search_google_play_books("导数", 5)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["provider"], "Google Play Books")
        self.assertEqual(rows[0]["resource_kind"], "external_book")
        self.assertTrue(rows[0]["action"]["url"].startswith("https://play.google.com/store/books/"))

    def test_serpapi_scholar_result_is_normalized(self):
        payload = {
            "organic_results": [{
                "title": "A Study of Derivatives",
                "link": "https://example.org/paper",
                "result_id": "paper-1",
                "snippet": "A paper about derivatives.",
                "publication_info": {"summary": "Author - Journal, 2024"},
            }]
        }
        with patch.dict("os.environ", {"SERPAPI_API_KEY": "test-serpapi-key"}, clear=False), \
             patch.object(open_learning_resources, "_http_get_json", return_value=payload):
            rows = open_learning_resources.search_serpapi("导数", "google_scholar", 4)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["provider"], "Google Scholar")
        self.assertEqual(rows[0]["resource_kind"], "open_paper")

    def test_serpapi_books_result_is_normalized(self):
        payload = {
            "organic_results": [{
                "title": "Calculus",
                "link": "https://books.google.com/books?id=abc",
                "book_id": "abc",
                "thumbnail": "https://books.google.com/cover.jpg",
                "authors": [{"name": "Example Author"}],
                "date": "2020",
                "snippet": "A calculus book.",
            }]
        }
        with patch.dict("os.environ", {"SERPAPI_API_KEY": "test-serpapi-key"}, clear=False), \
             patch.object(open_learning_resources, "_http_get_json", return_value=payload):
            rows = open_learning_resources.search_serpapi("导数", "google_books", 4)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["provider"], "Google Books")
        self.assertEqual(rows[0]["resource_kind"], "external_book")

    def test_serpapi_videos_result_is_normalized(self):
        payload = {
            "video_results": [{
                "title": "Derivatives explained",
                "link": "https://example.org/video",
                "thumbnail": "https://example.org/video.jpg",
                "snippet": "A short lesson.",
                "displayed_link": "example.org",
            }]
        }
        with patch.dict("os.environ", {"SERPAPI_API_KEY": "test-serpapi-key"}, clear=False), \
             patch.object(open_learning_resources, "_http_get_json", return_value=payload):
            rows = open_learning_resources.search_serpapi("导数", "google_videos", 4)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["provider"], "Google Videos")
        self.assertEqual(rows[0]["resource_kind"], "open_video")


if __name__ == "__main__":
    unittest.main()
