import base64
import json
import secrets
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
import assistant_store


USE_CURRENT_TOKEN = object()


class KnowledgeApiEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        root = Path(cls.temp_dir.name)
        cls.patches = [
            patch.object(server, "ACCOUNT_FILE", root / "teacher_account.json"),
            patch.object(assistant_store, "DB_FILE", root / "assistant.sqlite3"),
            patch.object(server, "MATERIALS_FILE", root / "materials.json"),
            patch.object(server, "MATERIAL_FILES_DIR", root / "files"),
            patch.object(knowledge_base, "KNOWLEDGE_FILE", root / "knowledge.json"),
        ]
        for item in cls.patches:
            item.start()
        cls.teacher_password = secrets.token_urlsafe(24)
        server.save_account({
            "username": "teacher", "password": cls.teacher_password,
            "name": "隔离测试教师", "role": "教师",
        })
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
        server.MATERIALS_FILE.write_text("[]", encoding="utf-8")
        knowledge_base.save_knowledge([])
        self.client = urllib.request.build_opener()
        self.token = ""
        status, login = self.request_json(
            "/login", "POST", {"username": "teacher", "password": self.teacher_password},
            authorization=None,
        )
        self.assertEqual(status, 200)
        self.token = login["token"]

    def request_json(self, path, method="GET", body=None, authorization=USE_CURRENT_TOKEN):
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if authorization is USE_CURRENT_TOKEN and self.token:
            headers["Authorization"] = "Bearer " + self.token
        elif authorization is not None:
            headers["Authorization"] = authorization
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers=headers,
        )
        try:
            with self.client.open(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def test_login_and_bearer_token_validation(self):
        status, login = self.request_json(
            "/login", "POST", {"username": "teacher", "password": self.teacher_password},
            authorization=None,
        )
        self.assertEqual(status, 200)
        self.assertTrue(login["token"])
        self.assertNotIn("password", login)
        self.assertEqual(server.verify_access_token(login["token"])["sub"], "teacher")

        status, _ = self.request_json("/materials", authorization=None)
        self.assertEqual(status, 401)
        status, _ = self.request_json(
            "/materials", authorization="Bearer invalid.invalid.invalid"
        )
        self.assertEqual(status, 401)
        status, _ = self.request_json(
            "/materials", authorization="Token " + self.token
        )
        self.assertEqual(status, 401)

        expired = server.create_access_token("teacher", ttl_seconds=-1)
        status, _ = self.request_json(
            "/materials", authorization="Bearer " + expired
        )
        self.assertEqual(status, 401)

        status, materials = self.request_json("/materials")
        self.assertEqual(status, 200)
        self.assertTrue(materials["success"])
        status, knowledge = self.request_json(
            "/knowledge/search?classId=default&q=OpenSpec"
        )
        self.assertEqual(status, 200)
        self.assertTrue(knowledge["success"])

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
        self.assertEqual(result_a["results"][0]["materialId"], upload_a["material"]["id"])
        self.assertEqual(result_a["results"][0]["sourceFile"], "a.md")
        self.assertEqual(result_a["results"][0]["chunkIndex"], 0)

        _, isolated = self.search("class-a", "量子计算")
        self.assertEqual(isolated["results"], [])
        self.assertIn("没有相关内容", isolated["message"])

        material_id = upload_b["material"]["id"]
        request = urllib.request.Request(
            self.base_url + "/materials/%s/download" % material_id,
            headers={"Authorization": "Bearer " + self.token},
        )
        with self.client.open(request) as response:
            self.assertEqual(response.read().decode("utf-8"), "量子计算是 B 班专属材料")

    def test_search_syncs_historical_materials_before_querying(self):
        server.save_materials([
            {
                "id": "historical-openspec",
                "classId": "default",
                "title": "OpenSpec 历史课件",
                "fileName": "test-openspec.md",
                "storedName": "historical-openspec__test-openspec.md",
                "type": "text/markdown",
                "size": 64,
                "time": "2026/09/28 14:54:23",
                "isMd": True,
                "text": "OpenSpec 是一种规范驱动的软件开发工具。",
            },
            {
                "id": "historical-java",
                "classId": "class-2026-software-1",
                "title": "Java 历史课件",
                "fileName": "test-java.md",
                "storedName": "historical-java__test-java.md",
                "type": "text/markdown",
                "size": 48,
                "time": "2026/09/28 14:58:58",
                "isMd": True,
                "text": "Java 是一种面向对象的编程语言。",
            },
        ])
        knowledge_base.save_knowledge([])

        _, openspec = self.search("default", "OpenSpec")
        self.assertEqual(openspec["results"][0]["sourceFile"], "test-openspec.md")
        self.assertEqual(openspec["results"][0]["materialId"], "historical-openspec")
        self.assertIsNone(openspec["results"][0]["page"])
        self.assertEqual(openspec["results"][0]["chunkIndex"], 0)

        _, java = self.search("class-2026-software-1", "Java")
        self.assertEqual(java["results"][0]["sourceFile"], "test-java.md")
        _, programming = self.search("class-2026-software-1", "编程")
        self.assertEqual(programming["results"][0]["sourceFile"], "test-java.md")
        _, isolated = self.search("default", "Java")
        self.assertEqual(isolated["results"], [])

    def test_rag_answer_uses_top_sources_and_preserves_class_isolation(self):
        server.save_materials([
            {
                "id": "rag-openspec", "classId": "default",
                "title": "OpenSpec", "fileName": "test-openspec.md",
                "storedName": "rag-openspec__test-openspec.md",
                "type": "text/markdown", "size": 64, "time": "2026/09/28 14:54:23",
                "isMd": True, "text": "OpenSpec 是一种规范驱动的软件开发工具。",
            },
            {
                "id": "rag-java", "classId": "class-2026-software-1",
                "title": "Java", "fileName": "test-java.md",
                "storedName": "rag-java__test-java.md",
                "type": "text/markdown", "size": 48, "time": "2026/09/28 14:58:58",
                "isMd": True, "text": "Java 是一种面向对象的编程语言。",
            },
        ])
        captured = {}

        def fake_answer(question, sources):
            captured["question"] = question
            captured["sources"] = sources
            return "OpenSpec 是一种规范驱动的软件开发工具。[1]"

        with patch.object(server, "answer_from_sources", side_effect=fake_answer):
            status, answer = self.request_json(
                "/knowledge/answer", "POST",
                {"classId": "default", "question": "OpenSpec 是什么？"},
            )
        self.assertEqual(status, 200)
        self.assertTrue(answer["answered"])
        self.assertIn("[1]", answer["answer"])
        self.assertLessEqual(len(answer["sources"]), 4)
        self.assertEqual(captured["sources"], answer["sources"])
        self.assertEqual([source["ref"] for source in answer["sources"]], list(range(1, len(answer["sources"]) + 1)))
        for field in ("materialId", "classId", "sourceFile", "page", "chunkIndex", "text"):
            self.assertIn(field, answer["sources"][0])
        self.assertEqual(answer["sources"][0]["sourceFile"], "test-openspec.md")

        with patch.object(server, "answer_from_sources", return_value="Java 是面向对象的语言。[1]"):
            _, java = self.request_json(
                "/knowledge/answer", "POST",
                {"classId": "class-2026-software-1", "question": "Java 是什么？"},
            )
        self.assertTrue(java["answered"])
        self.assertEqual(java["sources"][0]["sourceFile"], "test-java.md")

        with patch.object(server, "answer_from_sources") as gateway:
            _, isolated = self.request_json(
                "/knowledge/answer", "POST",
                {"classId": "default", "question": "Java 是什么？"},
            )
        self.assertFalse(isolated["answered"])
        self.assertEqual(isolated["sources"], [])
        gateway.assert_not_called()

    def test_rag_gateway_error_returns_json_without_crashing(self):
        server.save_materials([{
            "id": "rag-error", "classId": "default", "title": "OpenSpec",
            "fileName": "test-openspec.md", "storedName": "rag-error.md",
            "type": "text/markdown", "size": 20, "time": "2026/09/28 14:54:23",
            "isMd": True, "text": "OpenSpec 是规范驱动开发工具。",
        }])
        with patch.object(
            server, "answer_from_sources",
            side_effect=server.AIGatewayError("AI 服务暂时不可用", 503),
        ):
            status, result = self.request_json(
                "/knowledge/answer", "POST",
                {"classId": "default", "question": "OpenSpec 是什么？"},
            )
        self.assertEqual(status, 503)
        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "AI 服务暂时不可用")

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
            "item.materialId",
            "item.page!=null",
            "item.chunkIndex",
            "所属班级：",
            "查看原材料",
            "async function openKnowledgeMaterial(materialId)",
            "await previewMaterial(materialId,material)",
            "await showMaterialDetail(materialId,material)",
            "catch(e)",
        ):
            self.assertIn(marker, html)

    def test_frontend_and_nginx_use_bearer_authorization(self):
        html = (BACKEND_DIR.parent / "frontend" / "index.html").read_text(encoding="utf-8")
        for marker in (
            "const TOKEN_KEY='campusclaw_token'",
            "async function apiFetch(",
            "headers.set('Authorization','Bearer '+token)",
            "setAccessToken(data.token)",
            "setAccessToken('')",
        ):
            self.assertIn(marker, html)

        nginx = (BACKEND_DIR.parent / "nginx" / "nginx.conf").read_text(encoding="utf-8")
        self.assertGreaterEqual(
            nginx.count("proxy_set_header Authorization $http_authorization;"), 5
        )

    def test_frontend_contains_rag_mode_and_local_answer_endpoint(self):
        html = (BACKEND_DIR.parent / "frontend" / "index.html").read_text(encoding="utf-8")
        for marker in (
            "知识检索", "知识问答", 'id="knowledgeAnswerClass"',
            'id="knowledgeQuestion"', "async function askKnowledge()",
            "'/knowledge/answer'", "source.ref", "source.materialId",
            "openKnowledgeMaterial", "当前班级资料中没有找到相关内容",
        ):
            self.assertIn(marker, html)
        self.assertNotIn("AI_GATEWAY_API_KEY", html)
        self.assertNotIn("EMBEDDING_API_KEY", html)


if __name__ == "__main__":
    unittest.main()
