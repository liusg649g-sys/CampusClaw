"""Privacy regression checks use only a copied public tree and temporary data."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import unittest
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def load_isolated_server(initial_password=""):
    with patch.dict(os.environ, {"CAMPUSCLAW_INITIAL_TEACHER_PASSWORD": initial_password}):
        spec = importlib.util.spec_from_file_location("privacy_server", BACKEND / "server.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


class PrivacyDefaultsTests(unittest.TestCase):
    def test_unconfigured_initial_password_is_random_per_process_import(self):
        first = load_isolated_server().DEFAULT_ACCOUNT["password"]
        second = load_isolated_server().DEFAULT_ACCOUNT["password"]
        self.assertGreaterEqual(len(first), 24)
        self.assertNotEqual(first, second)

    def test_explicit_initial_password_persists_only_to_temporary_account(self):
        password = secrets.token_urlsafe(32)
        module = load_isolated_server(password)
        with tempfile.TemporaryDirectory() as folder:
            module.ACCOUNT_FILE = Path(folder) / "account.json"
            self.assertEqual(module.load_account()["password"], password)
            self.assertEqual(json.loads(module.ACCOUNT_FILE.read_text(encoding="utf-8"))["password"], password)

    def test_existing_account_is_not_overwritten_by_initial_configuration(self):
        module = load_isolated_server(secrets.token_urlsafe(32))
        with tempfile.TemporaryDirectory() as folder:
            module.ACCOUNT_FILE = Path(folder) / "account.json"
            stored = dict(module.DEFAULT_ACCOUNT, password=secrets.token_urlsafe(32))
            module.ACCOUNT_FILE.write_text(json.dumps(stored), encoding="utf-8")
            before = module.ACCOUNT_FILE.read_bytes()
            self.assertEqual(module.load_account()["password"], stored["password"])
            self.assertEqual(module.ACCOUNT_FILE.read_bytes(), before)

    def test_startup_prints_do_not_read_password(self):
        tree = ast.parse((BACKEND / "server.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                for part in ast.walk(node):
                    if isinstance(part, ast.Subscript):
                        self.assertNotEqual(getattr(part.slice, "value", None), "password")


if __name__ == "__main__":
    unittest.main()
