import base64
import http.cookiejar
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import patch


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import knowledge_base
import server


class KnowledgeApiEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        root = Path(cls.temp_dir.name)
        cls.patches = [
            patch.object(server, "MATERIALS_FILE", root / "materials.json"),
            patch.object(server, "MATERIAL_FILES_DIR", root / "files"),
            patch.object(knowledge_base, "KNOWLEDGE_FILE", root / "knowledge.json"),
        ]
        for item in cls.patches:
            item.start()
        server.MATERIAL_FILES_DIR.mkdir()
        server.MATERIALS_FILE.write_text("[]", encoding="utf-8")
        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.CampusClawAPI)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = "http://127.0.0.1:%s" % cls.httpd.server_port

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)
        for item in reversed(cls.patches):
            item.stop()
        cls.temp_dir.cleanup()

    def setUp(self):
        server.SESSIONS.clear()
        server.MATERIALS_FILE.write_text("[]", encoding="utf-8")
        knowledge_base.save_knowledge([])
        jar = http.cookiejar.CookieJar()
        self.client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        self.request_json("/login", "POST", {"username": "teacher", "password": "123456"})

    def request_json(self, path, method="GET", body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with self.client.open(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def upload(self, class_id, file_name, text):
        return self.request_json("/materials", "POST", {
            "classId": class_id,
            "title": file_name,
            "fileName": file_name,
            "type": "text/markdown",
            "dataBase64": base64.b64encode(text.encode("utf-8")).decode("ascii"),
        })

    def search(self, class_id, query):
        params = urllib.parse.urlencode({"classId": class_id, "q": query})
        return self.request_json("/knowledge/search?" + params)

    def test_upload_search_isolation_provenance_empty_and_download_regression(self):
        status_a, upload_a = self.upload("class-a", "a.md", "苹果算法是 A 班专属材料")
        status_b, upload_b = self.upload("class-b", "b.md", "量子计算是 B 班专属材料")
        self.assertEqual((status_a, status_b), (201, 201))
        self.assertTrue(upload_a["material"]["knowledgeIndexed"])

        _, result_a = self.search("class-a", "苹果算法")
        self.assertEqual(len(result_a["results"]), 1)
        self.assertEqual(result_a["results"][0]["classId"], "class-a")
        self.assertEqual(result_a["results"][0]["sourceFile"], "a.md")
        self.assertEqual(result_a["results"][0]["chunkIndex"], 0)

        _, isolated = self.search("class-a", "量子计算")
        self.assertEqual(isolated["results"], [])
        self.assertIn("没有相关内容", isolated["message"])

        material_id = upload_b["material"]["id"]
        with self.client.open(self.base_url + "/materials/%s/download" % material_id) as response:
            self.assertEqual(response.read().decode("utf-8"), "量子计算是 B 班专属材料")

    def test_existing_material_list_update_replace_and_delete_still_work(self):
        _, uploaded = self.upload("class-a", "original.md", "初始材料内容")
        material_id = uploaded["material"]["id"]

        _, listed = self.request_json("/materials?classId=class-a")
        self.assertEqual([item["id"] for item in listed["materials"]], [material_id])

        _, renamed = self.request_json("/materials/" + material_id, "PUT", {"title": "新标题"})
        self.assertEqual(renamed["material"]["title"], "新标题")

        replacement = "替换后的向量课程内容"
        _, replaced = self.request_json("/materials/" + material_id, "PUT", {
            "replaceFile": True,
            "fileName": "replacement.txt",
            "type": "text/plain",
            "dataBase64": base64.b64encode(replacement.encode("utf-8")).decode("ascii"),
        })
        self.assertTrue(replaced["material"]["knowledgeIndexed"])
        _, found = self.search("class-a", "向量课程")
        self.assertEqual(found["results"][0]["sourceFile"], "replacement.txt")

        _, deleted = self.request_json("/materials/" + material_id, "DELETE")
        self.assertTrue(deleted["success"])
        _, listed_after = self.request_json("/materials?classId=class-a")
        self.assertEqual(listed_after["materials"], [])
        _, found_after = self.search("class-a", "向量课程")
        self.assertEqual(found_after["results"], [])


class FrontendKnowledgeTests(unittest.TestCase):
    def test_class_page_contains_search_results_sources_and_error_handling(self):
        html = (BACKEND_DIR.parent / "frontend" / "index.html").read_text(encoding="utf-8")
        for marker in (
            'id="knowledgeQuery"',
            'id="knowledgeResults"',
            "function searchKnowledge()",
            "/knowledge/search?",
            "item.sourceFile",
            "item.page!=null",
            "item.chunkIndex",
            "catch(e)",
        ):
            self.assertIn(marker, html)


if __name__ == "__main__":
    unittest.main()
