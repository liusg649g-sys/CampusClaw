import json
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import ai_gateway


SOURCES = [
    {"ref": 1, "sourceFile": "one.md", "page": None, "chunkIndex": 0, "text": "第一条资料"},
    {"ref": 2, "sourceFile": "two.pdf", "page": 3, "chunkIndex": 1, "text": "第二条资料"},
]


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class AIGatewayTests(unittest.TestCase):
    def test_prompt_numbering_matches_source_refs(self):
        messages = ai_gateway.build_chat_messages("问题", SOURCES)
        self.assertIn("只能依据", messages[0]["content"])
        self.assertIn("[1]\n文件：one.md", messages[1]["content"])
        self.assertIn("[2]\n文件：two.pdf", messages[1]["content"])
        self.assertLess(messages[1]["content"].index("[1]"), messages[1]["content"].index("[2]"))

    def test_missing_configuration_is_clear(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ai_gateway.AIGatewayError) as raised:
                ai_gateway.answer_from_sources("问题", SOURCES)
        self.assertIn("EMBEDDING_BASE_URL", str(raised.exception))
        self.assertEqual(raised.exception.status, 503)

    def test_embedding_uses_teacher_endpoint_payload_and_default_model(self):
        env = {
            "EMBEDDING_BASE_URL": "https://gateway.example/v1",
            "EMBEDDING_API_KEY": "teacher-secret",
            "AI_GATEWAY_BASE_URL": "https://legacy.example/v1",
            "AI_GATEWAY_API_KEY": "legacy-secret",
        }
        response = FakeResponse({"data": [{"embedding": [0.0] * 2048}]})
        with patch.dict(os.environ, env, clear=True):
            with patch("ai_gateway.urllib.request.urlopen", return_value=response) as request:
                vector = ai_gateway.create_embedding("待向量化文本")

        self.assertEqual(len(vector), 2048)
        sent_request = request.call_args.args[0]
        self.assertEqual(sent_request.full_url, "https://gateway.example/v1/embeddings")
        self.assertEqual(sent_request.get_header("Authorization"), "Bearer teacher-secret")
        sent_body = json.loads(sent_request.data.decode("utf-8"))
        self.assertEqual(sent_body, {
            "model": "course-embedding",
            "input": "待向量化文本",
        })

    def test_embedding_dimension_mismatch_is_explicit(self):
        env = {
            "EMBEDDING_BASE_URL": "https://gateway.example/v1",
            "EMBEDDING_API_KEY": "teacher-secret",
            "EMBEDDING_DIM": "2048",
        }
        response = FakeResponse({"data": [{"embedding": [0.1, 0.2, 0.3]}]})
        with patch.dict(os.environ, env, clear=True):
            with patch("ai_gateway.urllib.request.urlopen", return_value=response):
                with self.assertRaises(ai_gateway.EmbeddingDimensionError) as raised:
                    ai_gateway.create_embedding("文本")
        self.assertIn("期望 2048，实际 3", str(raised.exception))

    def test_chat_reuses_teacher_gateway_and_defaults_to_course_chat(self):
        env = {
            "EMBEDDING_BASE_URL": "https://gateway.example/v1",
            "EMBEDDING_API_KEY": "teacher-secret",
            "AI_GATEWAY_BASE_URL": "https://legacy.example/v1",
            "AI_GATEWAY_API_KEY": "legacy-secret",
        }
        response = FakeResponse({"choices": [{"message": {"content": "回答。[1]"}}]})
        with patch.dict(os.environ, env, clear=True):
            with patch("ai_gateway.urllib.request.urlopen", return_value=response) as request:
                answer = ai_gateway.answer_from_sources("问题", SOURCES)

        self.assertEqual(answer, "回答。[1]")
        sent_request = request.call_args.args[0]
        self.assertEqual(
            sent_request.full_url,
            "https://gateway.example/v1/chat/completions",
        )
        self.assertEqual(sent_request.get_header("Authorization"), "Bearer teacher-secret")
        self.assertEqual(
            json.loads(sent_request.data.decode("utf-8"))["model"],
            "course-chat",
        )

    def test_successful_chat_completion(self):
        """Legacy AI_GATEWAY_* names remain supported."""
        env = {
            "AI_GATEWAY_BASE_URL": "https://gateway.example/v1",
            "AI_GATEWAY_API_KEY": "test-secret",
            "AI_CHAT_MODEL": "course-model",
        }
        response = FakeResponse({"choices": [{"message": {"content": "回答。[1]"}}]})
        with patch.dict(os.environ, env, clear=True):
            with patch("ai_gateway.urllib.request.urlopen", return_value=response) as request:
                answer = ai_gateway.answer_from_sources("问题", SOURCES)
        self.assertEqual(answer, "回答。[1]")
        sent_request = request.call_args.args[0]
        self.assertEqual(sent_request.get_header("Authorization"), "Bearer test-secret")
        sent_body = json.loads(sent_request.data.decode("utf-8"))
        self.assertEqual(sent_body["model"], "course-model")
        self.assertIn("[1]", sent_body["messages"][1]["content"])

    def test_gateway_http_errors_are_mapped(self):
        env = {
            "AI_GATEWAY_BASE_URL": "https://gateway.example",
            "AI_GATEWAY_API_KEY": "test-secret",
            "AI_CHAT_MODEL": "course-model",
        }
        cases = [
            (401, "认证失败", 502),
            (429, "请求过于频繁", 429),
            (500, "暂时不可用", 503),
        ]
        for code, message, status in cases:
            error = urllib.error.HTTPError("url", code, "error", {}, None)
            with self.subTest(code=code):
                with patch.dict(os.environ, env, clear=True):
                    with patch("ai_gateway.urllib.request.urlopen", side_effect=error):
                        with self.assertRaises(ai_gateway.AIGatewayError) as raised:
                            ai_gateway.answer_from_sources("问题", SOURCES)
                self.assertIn(message, str(raised.exception))
                self.assertEqual(raised.exception.status, status)

    def test_answer_must_reference_an_existing_source(self):
        env = {
            "AI_GATEWAY_BASE_URL": "https://gateway.example",
            "AI_GATEWAY_API_KEY": "test-secret",
            "AI_CHAT_MODEL": "course-model",
        }
        for content in ("没有引用的回答", "引用不存在的来源。[9]"):
            response = FakeResponse({"choices": [{"message": {"content": content}}]})
            with self.subTest(content=content):
                with patch.dict(os.environ, env, clear=True):
                    with patch("ai_gateway.urllib.request.urlopen", return_value=response):
                        with self.assertRaises(ai_gateway.AIGatewayError) as raised:
                            ai_gateway.answer_from_sources("问题", SOURCES)
                self.assertIn("引用", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
