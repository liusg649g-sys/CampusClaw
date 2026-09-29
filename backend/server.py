from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote, quote
from datetime import datetime
import base64
import json
import mimetypes
import re
import secrets
import time

from knowledge_base import extract_text_pages, rebuild_knowledge, search_knowledge

HOST = "127.0.0.1"
PORT = 5000

BASE_DIR = Path(__file__).resolve().parent
ACCOUNT_FILE = BASE_DIR / "teacher_account.json"
MATERIALS_FILE = BASE_DIR / "materials.json"
MATERIAL_FILES_DIR = BASE_DIR / "material_files"
MATERIAL_FILES_DIR.mkdir(exist_ok=True)

DEFAULT_ACCOUNT = {
    "username": "teacher",
    "password": "123456",
    "name": "任课教师",
    "role": "教师"
}

SESSIONS = {}
SESSION_TTL_SECONDS = 8 * 60 * 60


def load_account():
    if not ACCOUNT_FILE.exists():
        save_account(DEFAULT_ACCOUNT.copy())
        return DEFAULT_ACCOUNT.copy()
    try:
        data = json.loads(ACCOUNT_FILE.read_text(encoding="utf-8"))
        return {
            "username": str(data.get("username", DEFAULT_ACCOUNT["username"])),
            "password": str(data.get("password", DEFAULT_ACCOUNT["password"])),
            "name": str(data.get("name", DEFAULT_ACCOUNT["name"])),
            "role": str(data.get("role", DEFAULT_ACCOUNT["role"])),
        }
    except Exception:
        return DEFAULT_ACCOUNT.copy()


def save_account(account):
    ACCOUNT_FILE.write_text(
        json.dumps(account, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def load_materials():
    if not MATERIALS_FILE.exists():
        MATERIALS_FILE.write_text("[]", encoding="utf-8")
        return []
    try:
        data = json.loads(MATERIALS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_materials(materials):
    MATERIALS_FILE.write_text(
        json.dumps(materials, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def cleanup_sessions():
    now = time.time()
    expired = [
        token for token, created in SESSIONS.items()
        if now - created > SESSION_TTL_SECONDS
    ]
    for token in expired:
        SESSIONS.pop(token, None)


def safe_file_name(name):
    name = Path(str(name)).name
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    return name or "file.bin"


def public_material(m, include_text=False):
    result = {
        "id": m["id"],
        "classId": m.get("classId", "default"),
        "title": m.get("title", ""),
        "fileName": m.get("fileName", ""),
        "type": m.get("type", ""),
        "size": int(m.get("size", 0)),
        "time": m.get("time", ""),
        "isMd": bool(m.get("isMd", False)),
        "knowledgeIndexed": bool(str(m.get("text", "")).strip()),
    }
    if include_text and result["isMd"]:
        result["text"] = m.get("text", "")
    return result


class CampusClawAPI(BaseHTTPRequestHandler):
    server_version = "CampusClawBackend/2.0"

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-CampusClaw-Backend", "Python-stdlib")
        self.send_header("X-CampusClaw-Version", "materials-session-v2.1")
        super().end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/app-version":
            return self.send_json({"success": True, "version": "CampusClaw-materials-session-v2.1"})

        if path == "/health":
            return self.send_json({
                "success": True,
                "service": "CampusClaw backend",
                "status": "ok"
            })

        if path == "/session":
            return self.handle_session()

        if path == "/materials":
            return self.handle_list_materials(parsed)

        if path == "/knowledge/search":
            return self.handle_search_knowledge(parsed)

        m = re.fullmatch(r"/materials/([^/]+)/download", path)
        if m:
            return self.handle_download_material(unquote(m.group(1)))

        m = re.fullmatch(r"/materials/([^/]+)", path)
        if m:
            return self.handle_get_material(unquote(m.group(1)))

        return self.send_json({"success": False, "message": "接口不存在"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/login":
            return self.handle_login()
        if path == "/logout":
            return self.handle_logout()
        if path == "/change-password":
            return self.handle_change_password()
        if path == "/materials":
            return self.handle_upload_material()

        return self.send_json({"success": False, "message": "接口不存在"}, 404)

    def do_PUT(self):
        parsed = urlparse(self.path)
        m = re.fullmatch(r"/materials/([^/]+)", parsed.path)
        if m:
            return self.handle_update_material(unquote(m.group(1)))
        return self.send_json({"success": False, "message": "接口不存在"}, 404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path == "/materials":
            return self.handle_delete_materials_by_class(parsed)

        m = re.fullmatch(r"/materials/([^/]+)", parsed.path)
        if m:
            return self.handle_delete_material(unquote(m.group(1)))

        return self.send_json({"success": False, "message": "接口不存在"}, 404)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8") or "{}")

    def current_session_token(self):
        raw = self.headers.get("Cookie", "")
        cookie = SimpleCookie()
        cookie.load(raw)
        morsel = cookie.get("campusclaw_session")
        return morsel.value if morsel else None

    def is_logged_in(self):
        cleanup_sessions()
        token = self.current_session_token()
        return bool(token and token in SESSIONS)

    def require_login(self):
        if self.is_logged_in():
            return True
        self.send_json({"success": False, "message": "未登录或登录已失效"}, 401)
        return False

    def handle_login(self):
        try:
            data = self.read_json()
        except Exception:
            return self.send_json({"success": False, "message": "请求数据格式错误"}, 400)

        account = load_account()
        username = str(data.get("username", ""))
        password = str(data.get("password", ""))

        if username != account["username"] or password != account["password"]:
            return self.send_json({"success": False, "message": "教师账号或密码错误"}, 401)

        token = secrets.token_urlsafe(24)
        SESSIONS[token] = time.time()
        return self.send_json(
            {
                "success": True,
                "message": "登录成功",
                "username": account["username"],
                "name": account["name"],
                "role": account["role"]
            },
            200,
            extra_headers={
                "Set-Cookie": (
                    f"campusclaw_session={token}; "
                    "Path=/; HttpOnly; SameSite=Lax"
                )
            }
        )

    def handle_logout(self):
        token = self.current_session_token()
        if token:
            SESSIONS.pop(token, None)
        return self.send_json(
            {"success": True, "message": "已退出登录"},
            200,
            extra_headers={
                "Set-Cookie": (
                    "campusclaw_session=; Path=/; Max-Age=0; "
                    "HttpOnly; SameSite=Lax"
                )
            }
        )

    def handle_session(self):
        if not self.require_login():
            return
        account = load_account()
        return self.send_json({
            "success": True,
            "loggedIn": True,
            "username": account["username"],
            "name": account["name"],
            "role": account["role"]
        })

    def handle_change_password(self):
        if not self.require_login():
            return
        try:
            data = self.read_json()
        except Exception:
            return self.send_json({"success": False, "message": "请求数据格式错误"}, 400)

        old_password = str(data.get("oldPassword", ""))
        new_password = str(data.get("newPassword", ""))
        account = load_account()

        if old_password != account["password"]:
            return self.send_json({"success": False, "message": "当前密码不正确"}, 400)
        if len(new_password) < 6:
            return self.send_json({"success": False, "message": "新密码至少 6 位"}, 400)

        account["password"] = new_password
        save_account(account)
        return self.send_json({"success": True, "message": "密码修改成功"})

    def handle_list_materials(self, parsed):
        if not self.require_login():
            return
        qs = parse_qs(parsed.query)
        class_id = (qs.get("classId") or [""])[0].strip()
        q = (qs.get("q") or [""])[0].strip().lower()

        items = load_materials()
        if class_id:
            items = [m for m in items if m.get("classId") == class_id]
        if q:
            items = [
                m for m in items
                if q in (
                    str(m.get("title", "")) + " " +
                    str(m.get("fileName", "")) + " " +
                    str(m.get("type", ""))
                ).lower()
            ]

        items.sort(key=lambda m: m.get("id", ""), reverse=True)
        return self.send_json({
            "success": True,
            "materials": [public_material(m) for m in items]
        })

    def handle_search_knowledge(self, parsed):
        if not self.require_login():
            return

        qs = parse_qs(parsed.query)

        class_id = (qs.get("classId") or [""])[0].strip()
        query = (qs.get("q") or [""])[0].strip()

        if not class_id:
            return self.send_json({
                "success": False,
                "message": "缺少 classId"
            }, 400)

        if not query:
            return self.send_json({
                "success": False,
                "message": "缺少查询内容 q"
            }, 400)

        # 先根据当前材料重新建立知识库
        materials = load_materials()
        rebuild_knowledge(materials)

        # 只在指定班级范围内检索
        results = search_knowledge(
            class_id=class_id,
            query=query,
            limit=5
        )

        return self.send_json({
            "success": True,
            "classId": class_id,
            "query": query,
            "results": results,
            "message": "找到相关内容" if results else "当前班级知识库中没有相关内容"
        })

    def handle_get_material(self, material_id):
        if not self.require_login():
            return
        m = next((x for x in load_materials() if x.get("id") == material_id), None)
        if not m:
            return self.send_json({"success": False, "message": "材料不存在"}, 404)
        return self.send_json({
            "success": True,
            "material": public_material(m, include_text=True)
        })

    def handle_upload_material(self):
        if not self.require_login():
            return
        try:
            data = self.read_json()
            class_id = str(data.get("classId", "")).strip()
            title = str(data.get("title", "")).strip()
            file_name = safe_file_name(data.get("fileName", ""))
            content_type = str(data.get("type", "") or "")
            file_bytes = base64.b64decode(data.get("dataBase64", ""), validate=True)
        except Exception:
            return self.send_json({"success": False, "message": "上传数据格式错误"}, 400)

        if not class_id or not title or not file_name:
            return self.send_json({"success": False, "message": "班级、标题和文件不能为空"}, 400)

        material_id = "m" + str(int(time.time() * 1000)) + secrets.token_hex(2)
        stored_name = material_id + "__" + file_name
        file_path = MATERIAL_FILES_DIR / stored_name
        file_path.write_bytes(file_bytes)

        lower = file_name.lower()
        is_md = lower.endswith(".md") or lower.endswith(".markdown")
        pages = extract_text_pages(file_name, file_bytes)
        text = "\n\n".join(page["text"] for page in pages)

        m = {
            "id": material_id,
            "classId": class_id,
            "title": title,
            "fileName": file_name,
            "storedName": stored_name,
            "type": content_type,
            "size": len(file_bytes),
            "time": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
            "isMd": is_md,
            "text": text,
            "pages": pages
        }
        materials = load_materials()
        materials.append(m)
        save_materials(materials)
        rebuild_knowledge(materials)
        return self.send_json({
            "success": True,
            "message": "材料上传成功" if text else "材料上传成功；此文件暂无可提取的文本，未加入知识检索",
            "material": public_material(m, include_text=True)
        }, 201)

    def handle_update_material(self, material_id):
        if not self.require_login():
            return
        try:
            data = self.read_json()
        except Exception:
            return self.send_json({"success": False, "message": "请求数据格式错误"}, 400)

        materials = load_materials()
        m = next((x for x in materials if x.get("id") == material_id), None)
        if not m:
            return self.send_json({"success": False, "message": "材料不存在"}, 404)

        if "title" in data:
            title = str(data.get("title", "")).strip()
            if not title:
                return self.send_json({"success": False, "message": "材料标题不能为空"}, 400)
            m["title"] = title

        if data.get("replaceFile"):
            try:
                file_name = safe_file_name(data.get("fileName", ""))
                content_type = str(data.get("type", "") or "")
                file_bytes = base64.b64decode(data.get("dataBase64", ""), validate=True)
            except Exception:
                return self.send_json({"success": False, "message": "替换文件数据格式错误"}, 400)

            old_path = MATERIAL_FILES_DIR / str(m.get("storedName", ""))
            if old_path.exists():
                try:
                    old_path.unlink()
                except OSError:
                    pass

            stored_name = material_id + "__" + file_name
            (MATERIAL_FILES_DIR / stored_name).write_bytes(file_bytes)

            lower = file_name.lower()
            is_md = lower.endswith(".md") or lower.endswith(".markdown")
            pages = extract_text_pages(file_name, file_bytes)
            text = "\n\n".join(page["text"] for page in pages)

            m.update({
                "fileName": file_name,
                "storedName": stored_name,
                "type": content_type,
                "size": len(file_bytes),
                "time": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
                "isMd": is_md,
                "text": text,
                "pages": pages
            })

        save_materials(materials)
        rebuild_knowledge(materials)
        return self.send_json({
            "success": True,
            "message": "材料已更新",
            "material": public_material(m, include_text=True)
        })

    def handle_delete_material(self, material_id):
        if not self.require_login():
            return
        materials = load_materials()
        m = next((x for x in materials if x.get("id") == material_id), None)
        if not m:
            return self.send_json({"success": False, "message": "材料不存在"}, 404)

        path = MATERIAL_FILES_DIR / str(m.get("storedName", ""))
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass

        materials = [x for x in materials if x.get("id") != material_id]
        save_materials(materials)
        rebuild_knowledge(materials)
        return self.send_json({"success": True, "message": "材料已删除"})

    def handle_delete_materials_by_class(self, parsed):
        if not self.require_login():
            return
        qs = parse_qs(parsed.query)
        class_id = (qs.get("classId") or [""])[0].strip()
        if not class_id:
            return self.send_json({"success": False, "message": "缺少 classId"}, 400)

        materials = load_materials()
        removed = [m for m in materials if m.get("classId") == class_id]
        for m in removed:
            path = MATERIAL_FILES_DIR / str(m.get("storedName", ""))
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass

        materials = [m for m in materials if m.get("classId") != class_id]
        save_materials(materials)
        rebuild_knowledge(materials)
        return self.send_json({
            "success": True,
            "message": "该班级材料已删除",
            "deletedCount": len(removed)
        })

    def handle_download_material(self, material_id):
        if not self.require_login():
            return
        m = next((x for x in load_materials() if x.get("id") == material_id), None)
        if not m:
            return self.send_json({"success": False, "message": "材料不存在"}, 404)

        path = MATERIAL_FILES_DIR / str(m.get("storedName", ""))
        if not path.exists():
            return self.send_json({"success": False, "message": "原文件不存在"}, 404)

        body = path.read_bytes()
        content_type = m.get("type") or mimetypes.guess_type(m.get("fileName", ""))[0] or "application/octet-stream"
        encoded_name = quote(m.get("fileName", "material"))
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{encoded_name}")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, payload, status=200, extra_headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[Backend] {self.address_string()} - {fmt % args}")


if __name__ == "__main__":
    account = load_account()
    print("=" * 64)
    print("CampusClaw Python 后端")
    print("API：登录 / 修改密码 / 课程材料")
    print(f"监听：http://{HOST}:{PORT}")
    print(f"教师账号：{account['username']}")
    print("初始密码：123456（若已修改，以 teacher_account.json 为准）")
    print("=" * 64)

    httpd = ThreadingHTTPServer((HOST, PORT), CampusClawAPI)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n后端服务器已停止。")
    finally:
        httpd.server_close()
