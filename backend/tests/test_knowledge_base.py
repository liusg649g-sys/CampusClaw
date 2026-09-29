import json
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

    def tearDown(self):
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


if __name__ == "__main__":
    unittest.main()
