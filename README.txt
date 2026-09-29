CampusClaw：Nginx + Python 后端 + Session/Cookie 版

目录：
CampusClaw_materials_session/
├── frontend/
│   └── index.html
├── backend/
│   ├── server.py
│   ├── teacher_account.json
│   ├── materials.json
│   └── material_files/
├── nginx/
│   └── nginx.conf
├── logs/
└── temp/

本版主要变化：
1. 教师登录成功后，后端返回 HttpOnly Session Cookie：
   campusclaw_session=随机字符串
2. “课程材料”不再保存在浏览器 IndexedDB，而是保存在 Python 后端。
3. 打开课程材料页面时会真正请求：
   GET /materials
4. 浏览器会自动把 Session Cookie 放进 /materials 的 Request Headers。
5. F12 → Network → Fetch/XHR 中可以看到：
   login
   materials
6. 点开 materials → 标头 → 请求标头，可看到类似：
   Cookie: campusclaw_session=xxxxxxxx
7. 材料上传、查询、详情、重命名、替换、下载、删除均通过后端 API 完成。

教师初始账号：
teacher
123456

启动方法：

【1】项目请放在纯英文路径，避免 Windows Nginx 中文路径问题。

【2】PowerShell 1：进入 backend
py server.py

【3】PowerShell 2：进入项目根目录，例如：
D:\CampusClaw\CampusClaw_materials_session

然后启动 Nginx（把 nginx.exe 路径换成你自己的实际路径）：
& "D:\sp\nginx-1.31.6\nginx-1.31.6\nginx.exe" -p "$((Get-Location).Path.Replace('\','/'))/" -c "nginx/nginx.conf"

【4】浏览器打开：
http://127.0.0.1:8080

检查 Cookie：
先登录 teacher / 123456
→ F12
→ Network
→ Fetch/XHR
→ 点击“课程材料”
→ 点击 materials
→ 标头
→ 请求标头
→ Cookie

注意：
- 不要双击 frontend/index.html。
- Python 后端和 Nginx 必须同时启动。
- 后端重启后，内存中的 Session 会清空，需要重新登录。
- 班级和学生作业目前仍沿用浏览器本地存储；课程材料已经迁移到 Python 后端。


【版本确认】
浏览器打开 http://127.0.0.1:8080 后：
1. 页面底部应看到 “Session API 版 v2.1”
2. 材料页应有 “获取班级材料” 按钮
3. 访问 http://127.0.0.1:8080/app-version
   应返回 {"version":"CampusClaw-materials-session-v2.1", ...}
如果看不到这些，说明 Nginx 仍在提供旧目录。
