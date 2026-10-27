from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote, quote
from datetime import datetime
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import time

from knowledge_base import extract_text_pages, rebuild_knowledge, search_knowledge
from ai_gateway import AIGatewayError, answer_from_sources
from assistant_api import AssistantMixin, APIError
import assistant_store

HOST = "0.0.0.0" if os.environ.get('CAMPUSCLAW_CONTAINER_MODE')=='1' else "127.0.0.1"
PORT = 5000

BASE_DIR = Path(__file__).resolve().parent
from runtime_paths import DATA_DIR
ACCOUNT_FILE = DATA_DIR / "teacher_account.json"
MATERIALS_FILE = DATA_DIR / "materials.json"
MATERIAL_FILES_DIR = DATA_DIR / "material_files"
MATERIAL_FILES_DIR.mkdir(exist_ok=True,parents=True)

DEFAULT_ACCOUNT = {
    "username": "teacher",
    "password": os.environ.get('CAMPUSCLAW_INITIAL_TEACHER_PASSWORD') or secrets.token_urlsafe(24),
    "name": "任课教师",
    "role": "教师"
}

TOKEN_TTL_SECONDS = 8 * 60 * 60
_configured_token_secret = os.environ.get("CAMPUSCLAW_TOKEN_SECRET", "")
TOKEN_SECRET = (
    _configured_token_secret.encode("utf-8")
    if _configured_token_secret
    else secrets.token_bytes(32)
)


def _base64url_encode(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _base64url_decode(value):
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def create_access_token(username, ttl_seconds=TOKEN_TTL_SECONDS, now=None):
    """创建不含密码、带过期时间的 HMAC-SHA256 签名 token。"""
    issued_at = int(time.time() if now is None else now)
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": str(username),
        "iat": issued_at,
        "exp": issued_at + int(ttl_seconds),
        "nonce": secrets.token_urlsafe(8),
    }
    encoded_header = _base64url_encode(
        json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    encoded_payload = _base64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signing_input = (encoded_header + "." + encoded_payload).encode("ascii")
    signature = hmac.new(TOKEN_SECRET, signing_input, hashlib.sha256).digest()
    return encoded_header + "." + encoded_payload + "." + _base64url_encode(signature)


def verify_access_token(token, now=None):
    """验证 token 格式、算法、签名、用户和过期时间；失败返回 None。"""
    try:
        encoded_header, encoded_payload, encoded_signature = str(token).split(".")
        signing_input = (encoded_header + "." + encoded_payload).encode("ascii")
        supplied_signature = _base64url_decode(encoded_signature)
        expected_signature = hmac.new(TOKEN_SECRET, signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return None
        header = json.loads(_base64url_decode(encoded_header).decode("utf-8"))
        payload = json.loads(_base64url_decode(encoded_payload).decode("utf-8"))
        if header != {"alg": "HS256", "typ": "JWT"}:
            return None
        current_time = int(time.time() if now is None else now)
        if not isinstance(payload.get("exp"), int) or payload["exp"] <= current_time:
            return None
        if not isinstance(payload.get("iat"), int) or payload["iat"] > current_time:
            return None
        if not str(payload.get("sub", "")).strip():
            return None
        return payload
    except (ValueError, TypeError, UnicodeError, json.JSONDecodeError):
        return None


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


def sync_knowledge_index():
    """让持久化知识索引与全部历史及当前材料保持一致。"""
    return rebuild_knowledge(load_materials())


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


class CampusClawAPI(AssistantMixin, BaseHTTPRequestHandler):
    def teaching_material_source(self):
        return load_materials(), MATERIAL_FILES_DIR

    server_version = "CampusClawBackend/3.0"

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-CampusClaw-Backend", "Python-stdlib")
        self.send_header("X-CampusClaw-Version", "bearer-token-v3")
        super().end_headers()

    def do_GET(self):
        if self.assistant_route('GET'):
            return
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/app-version":
            return self.send_json({"success": True, "version": "CampusClaw-bearer-token-v3"})

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
        if self.assistant_route('POST'):
            return
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
        if path == "/knowledge/answer":
            return self.handle_answer_knowledge()

        return self.send_json({"success": False, "message": "接口不存在"}, 404)

    def do_PUT(self):
        if self.assistant_route('PUT'):
            return
        parsed = urlparse(self.path)
        m = re.fullmatch(r"/materials/([^/]+)", parsed.path)
        if m:
            return self.handle_update_material(unquote(m.group(1)))
        return self.send_json({"success": False, "message": "接口不存在"}, 404)

    def do_DELETE(self):
        if self.assistant_route('DELETE'):
            return
        parsed = urlparse(self.path)
        if parsed.path == "/materials":
            return self.handle_delete_materials_by_class(parsed)

        m = re.fullmatch(r"/materials/([^/]+)", parsed.path)
        if m:
            return self.handle_delete_material(unquote(m.group(1)))

        return self.send_json({"success": False, "message": "接口不存在"}, 404)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > 30 * 1024 * 1024:
            raise ValueError('请求过大')
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(data, dict):
            raise ValueError('请求体必须为对象')
        return data

    def current_access_token(self):
        authorization = self.headers.get("Authorization", "")
        match = re.fullmatch(r"Bearer ([A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)", authorization)
        return match.group(1) if match else None

    def authenticated_user(self):
        payload = verify_access_token(self.current_access_token() or "")
        if not payload:
            return None
        account = load_account()
        if payload.get('sub') == account['username']:
            return dict(payload, role='teacher')
        with assistant_store.connect() as db:
            student=db.execute('SELECT username FROM students WHERE username=?',(payload.get('sub'),)).fetchone()
        return dict(payload,role='student') if student else None

    def teacher_username(self):
        return load_account()['username']

    def check_class(self, class_id):
        # Preserve the legacy teacher's browser-managed class workflow. Registered
        # classes enforce ownership; students must always have a membership.
        if self.auth_payload['role']=='teacher':
            with assistant_store.connect() as db:
                item=db.execute('SELECT teacher FROM classes WHERE id=?',(class_id,)).fetchone()
            if not item or item['teacher']==self.auth_payload['sub']:
                return True
        try:
            self.class_permission(class_id)
            return True
        except APIError as e:
            self.send_json({'success':False,'message':str(e)},e.status)
            return False

    def require_login(self):
        payload = self.authenticated_user()
        if payload:
            self.auth_payload = payload
            path=urlparse(self.path).path
            if payload['role']=='student' and (path=='/change-password' or (path.startswith('/materials') and self.command!='GET')):
                self.send_json({'success':False,'message':'仅教师可操作'},403)
                return False
            return True
        self.send_json({"success": False, "message": "Bearer token 缺失、无效或已过期"}, 401)
        return False

    def handle_login(self):
        try:
            data = self.read_json()
        except Exception:
            return self.send_json({"success": False, "message": "请求数据格式错误"}, 400)

        account = load_account()
        username = str(data.get("username", ""))
        password = str(data.get("password", ""))

        if username != account['username']:
            with assistant_store.connect() as db:
                student=db.execute('SELECT * FROM students WHERE username=?',(username,)).fetchone()
            if student and assistant_store.password_matches(password,student['password']):
                return self.send_json({'success':True,'token':create_access_token(username),'expiresIn':TOKEN_TTL_SECONDS,'username':username,'name':student['name'],'role':'学生'})

        if username != account["username"] or password != account["password"]:
            return self.send_json({"success": False, "message": "教师账号或密码错误"}, 401)

        token = create_access_token(account["username"])
        return self.send_json({
            "success": True,
            "message": "登录成功",
            "token": token,
            "expiresIn": TOKEN_TTL_SECONDS,
            "username": account["username"],
            "name": account["name"],
            "role": account["role"]
        })

    def handle_logout(self):
        return self.send_json({"success": True, "message": "已退出登录"})

    def handle_session(self):
        if not self.require_login():
            return
        account = load_account()
        if self.auth_payload['role']=='student':
            with assistant_store.connect() as db:
                student=db.execute('SELECT username,name FROM students WHERE username=?',(self.auth_payload['sub'],)).fetchone()
            return self.send_json({'success':True,'loggedIn':True,**dict(student),'role':'学生'})
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
        if class_id and not self.check_class(class_id):
            return
        if self.auth_payload['role']=='student':
            with assistant_store.connect() as db:
                allowed={r[0] for r in db.execute('SELECT classId FROM members WHERE username=?',(self.auth_payload['sub'],))}
            items=[m for m in items if m.get('classId') in allowed]
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

        # 每次检索前从 materials.json 同步，兼容启用知识库前已有的历史材料。
        if not self.check_class(class_id):
            return
        sync_knowledge_index()

        # 只在指定班级范围内检索
        results = search_knowledge(
            class_id=class_id,
            query=query,
            limit=4
        )

        return self.send_json({
            "success": True,
            "classId": class_id,
            "query": query,
            "results": results,
            "message": "找到相关内容" if results else "当前班级知识库中没有相关内容"
        })

    def handle_answer_knowledge(self):
        if not self.require_login():
            return
        try:
            data = self.read_json()
        except Exception:
            return self.send_json({"success": False, "message": "请求数据格式错误"}, 400)

        class_id = str(data.get("classId", "")).strip()
        question = str(data.get("question", "")).strip()
        if not class_id:
            return self.send_json({"success": False, "message": "请选择班级"}, 400)
        if not question:
            return self.send_json({"success": False, "message": "请输入问题"}, 400)
        if len(question) > 2000:
            return self.send_json({"success": False, "message": "问题内容过长"}, 400)

        # 复用同一个班级隔离混合检索；没有命中时绝不调用 AI 网关。
        if not self.check_class(class_id):
            return
        sync_knowledge_index()
        matches = search_knowledge(class_id=class_id, query=question, limit=4)
        sources = [
            {
                "ref": index,
                "materialId": item.get("materialId"),
                "classId": item.get("classId"),
                "sourceFile": item.get("sourceFile"),
                "page": item.get("page"),
                "chunkIndex": item.get("chunkIndex"),
                "text": item.get("text", ""),
            }
            for index, item in enumerate(matches, 1)
        ]
        if not sources:
            return self.send_json({
                "success": True,
                "answered": False,
                "answer": "当前班级资料中没有找到相关内容。",
                "sources": [],
            })

        try:
            answer = answer_from_sources(question, sources)
        except AIGatewayError as error:
            return self.send_json({"success": False, "message": str(error)}, error.status)

        return self.send_json({
            "success": True,
            "answered": True,
            "answer": answer,
            "sources": sources,
        })

    def handle_get_material(self, material_id):
        if not self.require_login():
            return
        m = next((x for x in load_materials() if x.get("id") == material_id), None)
        if not m:
            return self.send_json({"success": False, "message": "材料不存在"}, 404)
        if not self.check_class(m.get('classId','default')):
            return
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
        if not self.check_class(m.get('classId','default')):
            return

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
    assistant_store.recover_interrupted()
    account = load_account()
    indexed_chunks = sync_knowledge_index()
    print("=" * 64)
    print("CampusClaw Python 后端")
    print("API：登录 / 修改密码 / 课程材料")
    print(f"监听：http://{HOST}:{PORT}")
    print(f"教师账号：{account['username']}")
    print(f"知识索引：已同步 {len(indexed_chunks)} 个片段")
    print("初始密码来自部署secret文件（不输出）" if os.environ.get('CAMPUSCLAW_CONTAINER_MODE')=='1' else "账号信息仅保存在本机私有账号文件中，日志不显示密码。已有账号保持不变。")
    print("=" * 64)

    httpd = ThreadingHTTPServer((HOST, PORT), CampusClawAPI)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n后端服务器已停止。")
    finally:
        httpd.server_close()
