import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import knowledge_base


class KnowledgeBaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = Path(self.temp_dir.name) / "knowledge.json"
        self.store_patch = patch.object(knowledge_base, "KNOWLEDGE_FILE", self.store)
        self.store_patch.start()
        self.env_patch = patch.dict(os.environ, {}, clear=True)
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.store_patch.stop()
        self.temp_dir.cleanup()

    def test_text_extraction_and_continuous_chunking(self):
        pages = knowledge_base.extract_text_pages("lesson.txt", "第一章\n向量检索".encode("utf-8"))
        self.assertEqual(pages, [{"page": None, "text": "第一章\n向量检索"}])
        chunks = knowledge_base.split_text("A" * 1100)
        self.assertEqual([len(chunk) for chunk in chunks], [500, 500, 100])
        self.assertEqual("".join(chunks), "A" * 1100)

    def test_vectors_and_metadata_are_persisted_and_readable(self):
        records = knowledge_base.rebuild_knowledge([{
            "id": "material-a",
            "classId": "class-a",
            "fileName": "lesson.pdf",
            "pages": [{"page": 3, "text": "向量检索可以查找相关知识"}],
        }])
        self.assertTrue(self.store.exists())
        saved = json.loads(self.store.read_text(encoding="utf-8"))
        self.assertEqual(saved, records)
        self.assertEqual(saved[0]["metadata"], {
            "class_id": "class-a",
            "source_file": "lesson.pdf",
            "page": 3,
            "chunk_index": 0,
        })
        self.assertEqual(len(saved[0]["vector"]), knowledge_base.VECTOR_DIMENSIONS)
        result = knowledge_base.search_knowledge("class-a", "向量检索")
        self.assertEqual(result[0]["sourceFile"], "lesson.pdf")
        self.assertEqual(result[0]["page"], 3)
        self.assertNotIn("vector", result[0])

    def test_search_never_leaks_another_class(self):
        knowledge_base.rebuild_knowledge([
            {"id": "a", "classId": "class-a", "fileName": "a.md", "text": "苹果课程资料"},
            {"id": "b", "classId": "class-b", "fileName": "b.md", "text": "量子计算高度相关答案"},
        ])
        self.assertEqual(knowledge_base.search_knowledge("class-a", "量子计算"), [])
        found = knowledge_base.search_knowledge("class-b", "量子计算")
        self.assertEqual([item["classId"] for item in found], ["class-b"])
        self.assertEqual(found[0]["chunkIndex"], 0)

    def test_exact_terms_match_historical_materials_with_class_isolation(self):
        knowledge_base.rebuild_knowledge([
            {
                "id": "openspec-material",
                "classId": "default",
                "fileName": "test-openspec.md",
                "text": "OpenSpec 是一种规范驱动的软件开发工具。",
            },
            {
                "id": "java-material",
                "classId": "class-2026-software-1",
                "fileName": "test-java.md",
                "text": "Java 是一种面向对象的编程语言。",
            },
        ])

        openspec = knowledge_base.search_knowledge("default", "OpenSpec")
        self.assertEqual(openspec[0]["sourceFile"], "test-openspec.md")
        self.assertGreaterEqual(openspec[0]["score"], 10.0)
        self.assertEqual(openspec[0]["materialId"], "openspec-material")
        self.assertIsNone(openspec[0]["page"])
        self.assertEqual(openspec[0]["chunkIndex"], 0)

        java = knowledge_base.search_knowledge("class-2026-software-1", "Java")
        self.assertEqual(java[0]["sourceFile"], "test-java.md")
        programming = knowledge_base.search_knowledge("class-2026-software-1", "编程")
        self.assertEqual(programming[0]["sourceFile"], "test-java.md")
        self.assertEqual(knowledge_base.search_knowledge("default", "Java"), [])

    def test_remote_embeddings_are_stored_and_top_four_are_returned(self):
        dimension = 2048
        config = {
            "base_url": "https://gateway.example/v1",
            "api_key": "secret",
            "model": "course-embedding",
            "dimension": dimension,
        }

        def fake_embedding(text):
            # The exact values are unimportant here; all five class-a chunks are
            # semantic candidates, allowing the requested Top K cap to be tested.
            return [1.0] + [0.0] * (dimension - 1)

        materials = [
            {
                "id": "a-%s" % index,
                "classId": "class-a",
                "fileName": "a-%s.md" % index,
                "text": "第 %s 份语义资料" % index,
            }
            for index in range(5)
        ] + [{
            "id": "other",
            "classId": "class-b",
            "fileName": "other.md",
            "text": "其他班级语义资料",
        }]

        with patch.object(knowledge_base, "embedding_is_configured", return_value=True), \
                patch.object(knowledge_base, "get_embedding_config", return_value=config), \
                patch.object(knowledge_base, "create_embedding", side_effect=fake_embedding) as gateway:
            saved = knowledge_base.rebuild_knowledge(materials)
            results = knowledge_base.search_knowledge("class-a", "semantic question", limit=4)

        self.assertEqual(len(results), 4)
        self.assertTrue(all(item["classId"] == "class-a" for item in results))
        self.assertTrue(all(item["embeddingDim"] == 2048 for item in saved))
        self.assertTrue(all(item["embeddingModel"] == "course-embedding" for item in saved))
        self.assertNotIn("embedding", results[0])
        self.assertGreaterEqual(gateway.call_count, len(saved) + 1)

    def test_empty_class_candidate_set_does_not_call_embedding_gateway(self):
        knowledge_base.rebuild_knowledge([{
            "id": "only-b", "classId": "class-b",
            "fileName": "b.md", "text": "仅属于 B 班",
        }])
        with patch.object(knowledge_base, "embedding_is_configured", return_value=True), \
                patch.object(knowledge_base, "create_embedding") as gateway:
            self.assertEqual(
                knowledge_base.search_knowledge("class-a", "任意问题", limit=4),
                [],
            )
        gateway.assert_not_called()

    def test_gateway_failure_falls_back_to_keyword_search(self):
        config = {
            "base_url": "https://gateway.example/v1",
            "api_key": "secret",
            "model": "course-embedding",
            "dimension": 2048,
        }
        with patch.object(knowledge_base, "embedding_is_configured", return_value=True), \
                patch.object(knowledge_base, "get_embedding_config", return_value=config), \
                patch.object(
                    knowledge_base, "create_embedding",
                    side_effect=knowledge_base.AIGatewayError("网关暂时不可用", 503),
                ):
            knowledge_base.rebuild_knowledge([{
                "id": "fallback", "classId": "class-a",
                "fileName": "fallback.md", "text": "OpenSpec 规范驱动开发",
            }])
            results = knowledge_base.search_knowledge("class-a", "OpenSpec")

        self.assertEqual(results[0]["sourceFile"], "fallback.md")
        self.assertGreaterEqual(results[0]["score"], 10.0)


if __name__ == "__main__":
    unittest.main()
