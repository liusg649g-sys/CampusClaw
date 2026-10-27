"""Real Windows launcher integration checks; no mocks, isolated business data.

Run with an installed Python. Requires free ports 5000/8080 and the real Nginx.
Report: logs/launcher-tests.json. Never prints configuration values or tokens.
"""
import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
NGINX=Path(os.environ.get('CAMPUSCLAW_TEST_NGINX','D:/sp/nginx-1.31.6/nginx-1.31.6/nginx.exe'))
RESULTS=[]
ENV=dict(os.environ,CAMPUSCLAW_NO_PAUSE='1',PYTHONIOENCODING='utf-8')
FIXTURE_PASSWORD=secrets.token_urlsafe(24)

def launch(root,action='Start',expect=0,open_browser=False):
    bat='启动CampusClaw.bat' if action=='Start' else '停止CampusClaw.bat'
    command=f'"{root/bat}"'+(' -NoBrowser' if action=='Start' and not open_browser else '')
    result=subprocess.run(command,shell=True,cwd=root,env=ENV,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=100)
    output=result.stdout.decode('utf-8',errors='replace')
    if result.returncode!=expect:
        raise AssertionError(f'{action}: exit {result.returncode} expected {expect}\n{output}')
    return output

def record(name,fn):
    start=time.monotonic()
    try:
        fn();RESULTS.append({'test':name,'passed':True,'seconds':round(time.monotonic()-start,2)})
        print('PASS '+name,flush=True)
    except Exception as exc:
        RESULTS.append({'test':name,'passed':False,'reason':str(exc),'seconds':round(time.monotonic()-start,2)})
        print('FAIL '+name+': '+str(exc),flush=True)
        raise

def request(path,port=8080,token=None,body=None):
    headers={} if not token else {'Authorization':'Bearer '+token}
    if body is not None:headers['Content-Type']='application/json'
    req=urllib.request.Request(f'http://127.0.0.1:{port}'+path,headers=headers,data=None if body is None else json.dumps(body).encode())
    with urllib.request.urlopen(req,timeout=5) as response:return json.load(response)

def state(root):return json.loads((root/'temp/launcher/processes.json').read_text(encoding='utf-8-sig'))
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def check(condition,message='assertion failed'):
    if not condition:raise AssertionError(message)

def snapshot(root):
    files=[root/'backend/teacher_account.json',root/'backend/materials.json']
    files+=sorted((root/'backend/material_files').glob('*'))
    data={str(p.relative_to(root)):digest(p) for p in files if p.is_file()}
    dbpath=root/'backend/assistant.sqlite3'
    if dbpath.exists():
        with closing(sqlite3.connect('file:'+dbpath.as_posix()+'?mode=ro',uri=True)) as db:
            data['sqlite-logical']={name:db.execute('SELECT * FROM "'+name+'" ORDER BY rowid').fetchall() for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return data

def fixtures(parent):
    root=parent/'CampusClaw with spaces'
    for folder in ['backend','frontend','nginx','scripts']:
        shutil.copytree(ROOT/folder,root/folder,ignore=shutil.ignore_patterns('__pycache__','tests','*.sqlite3*','*.json','material_files'))
    for name in ['启动CampusClaw.bat','停止CampusClaw.bat','.env.example']:shutil.copy2(ROOT/name,root/name)
    (root/'backend/material_files').mkdir()
    (root/'backend/material_files/persist.txt').write_text('持久化验收材料',encoding='utf-8')
    (root/'backend/teacher_account.json').write_text(json.dumps({'username':'fixture_teacher','password':FIXTURE_PASSWORD,'name':'隔离教师','role':'教师'}),encoding='utf-8')
    (root/'backend/materials.json').write_text('[]',encoding='utf-8')
    (root/'.env').write_text(f'CAMPUSCLAW_PYTHON={sys.executable}\nCAMPUSCLAW_NGINX={NGINX}\nCHAT_API_KEY=\nCHAT_BASE_URL=\nEMBEDDING_API_KEY=\nEMBEDDING_BASE_URL=\nAI_GATEWAY_API_KEY=\nAI_GATEWAY_BASE_URL=\n',encoding='utf-8')
    return root

def main():
    (ROOT/'logs').mkdir(exist_ok=True)
    (ROOT/'temp').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='launcher-check-',dir=ROOT/'temp') as temp:
        root=fixtures(Path(temp))
        original_env=(root/'.env').read_text(encoding='utf-8')
        try:
            def bad_python():
                (root/'.env').write_text(original_env+'CAMPUSCLAW_PYTHON=Z:/not-installed/python.exe\n',encoding='utf-8')
                output=launch(root,expect=1)
                check('找不到可用的 Python' in output,output)
            record('invalid Python path: Chinese error, no service started',bad_python)
            def bad_nginx():
                (root/'.env').write_text(original_env+'CAMPUSCLAW_NGINX=Z:/not-installed/nginx.exe\n',encoding='utf-8')
                check('找不到 Nginx' in launch(root,expect=1))
            record('invalid Nginx path: Chinese error',bad_nginx)
            (root/'.env').write_text(original_env,encoding='utf-8')
            for port in [5000,8080]:
                def occupied(port=port):
                    with socket.socket() as listener:
                        listener.bind(('127.0.0.1',port));listener.listen()
                        output=launch(root,expect=1)
                        check(f'端口 {port}' in output,output)
                        check(listener.fileno()>=0,'foreign listener was closed')
                record(f'foreign port {port}: refused, owner preserved',occupied)
            def malformed_config():
                path=root/'nginx/nginx.conf';content=path.read_bytes()
                try:
                    path.write_bytes(content+b'\ninvalid_launcher_test_directive;\n')
                    check('Nginx 配置检查或控制失败' in launch(root,expect=1))
                finally:path.write_bytes(content)
            record('invalid Nginx config: refused before starting backend',malformed_config)
            def first_start():
                output=launch(root)
                check('AI 聊天暂不可用' in output)
                check(request('/health')['status']=='ok')
                check(request('/app-version',5000)['success'])
            record('cold start: real Python + Nginx, HTTP healthy, missing AI allowed',first_start)
            saved=state(root)
            env_hash=digest(root/'.env')
            token=request('/login',body={'username':'fixture_teacher','password':FIXTURE_PASSWORD})['token']
            # Persist a real class/student/prompt/conversation via the actual API.
            request('/classes',token=token,body={'id':'persist-class','name':'重启保留班级'})
            request('/students',token=token,body={'classId':'persist-class','username':'persist-student','name':'持久化学生','password':FIXTURE_PASSWORD})
            prompt=request('/prompts',token=token,body={'classId':'persist-class','name':'持久化提示词','content':'请逐步引导学生。'})['id']
            student=request('/login',body={'username':'persist-student','password':FIXTURE_PASSWORD})['token']
            request('/conversations',token=student,body={'classId':'persist-class','promptId':prompt})
            baseline=snapshot(root)
            def repeat():
                output=launch(root);now=state(root)
                check(now['Backend']['Id']==saved['Backend']['Id'])
                check(now['Nginx']['Id']==saved['Nginx']['Id'])
                check('无需重复启动或重载' in output)
                check(digest(root/'.env')==env_hash)
            record('repeat start: same PIDs, same stable secret, no duplicate services',repeat)
            def reload():
                path=root/'nginx/nginx.conf';content=path.read_bytes()
                path.write_bytes(content+b'\n# launcher integration reload check\n')
                output=launch(root)
                check('正在重新加载' in output)
                check(state(root)['Nginx']['Id']==saved['Nginx']['Id'])
                check(request('/health')['success'])
            record('changed Nginx config: syntax check + real reload, same master',reload)
            record('stop: managed services shut down',lambda:launch(root,'Stop'))
            record('repeat stop: safe and idempotent',lambda:launch(root,'Stop'))
            def restart():
                launch(root)
                check(state(root)['Backend']['Id']!=saved['Backend']['Id'])
                check(snapshot(root)==baseline,'business data changed across restart')
                check(request('/session',token=token)['username']=='fixture_teacher','stable token lost on restart')
                check(request('/session',token=student)['username']=='persist-student')
                check(len(request('/conversations',token=student)['conversations'])==1)
            record('restart: SQLite, accounts, JSON, material bytes and old tokens preserved',restart)
            def change_backend_config():
                before=state(root)
                with (root/'.env').open('a',encoding='utf-8') as file:file.write('\nAI_GATEWAY_TIMEOUT_SECONDS=21\n')
                check('本地后端配置变化' in launch(root))
                after=state(root)
                check(after['Backend']['Id']!=before['Backend']['Id'])
                check(after['Nginx']['Id']==before['Nginx']['Id'])
                check(snapshot(root)==baseline)
            record('changed .env: only managed backend restarted, data preserved',change_backend_config)
            record('final managed shutdown',lambda:launch(root,'Stop'))
            # A manually launched same-project backend must not be adopted/stopped.
            stdout=(root/'logs/manual-test.log').open('wb')
            manual=subprocess.Popen([sys.executable,'-u',str(root/'backend/server.py')],cwd=root,env=dict(ENV,CAMPUSCLAW_TOKEN_SECRET=secrets.token_urlsafe(32),CAMPUSCLAW_ASSISTANT_DB=str(root/'backend/assistant.sqlite3')),stdout=stdout,stderr=stdout)
            try:
                for _ in range(50):
                    try:request('/health',5000);break
                    except Exception:time.sleep(.2)
                def manual_reuse():
                    check('复用手动启动' in launch(root))
                    check(not state(root)['Backend']['Managed'])
                    launch(root,'Stop')
                    check(manual.poll() is None,'manual process was stopped')
                    check(request('/health',5000)['status']=='ok')
                record('manual same-project backend: reused, never stopped by stop button',manual_reuse)
            finally:
                manual.terminate();manual.wait(10);stdout.close()
            # Same-project manual Nginx may be reloaded, but never adopted.
            nginx_log=(root/'logs/manual-nginx-test.log').open('wb')
            manual_nginx=subprocess.Popen([str(NGINX),'-p',root.as_posix()+'/','-c','nginx/nginx.conf'],cwd=root,stdout=nginx_log,stderr=nginx_log)
            try:
                for _ in range(50):
                    try:
                        with urllib.request.urlopen('http://127.0.0.1:8080/',timeout=1) as response:response.read(1)
                        break
                    except Exception:time.sleep(.2)
                def manual_nginx_reuse():
                    launch(root)
                    check(not state(root)['Nginx']['Managed'])
                    launch(root,'Stop')
                    check(manual_nginx.poll() is None,'manual Nginx was stopped')
                record('manual same-project Nginx: reload allowed, stop never kills it',manual_nginx_reuse)
                def foreign_nginx():
                    output=launch(ROOT,expect=1)
                    check('端口 8080' in output,output)
                    check(manual_nginx.poll() is None)
                record('other-project real Nginx: port conflict refused and process preserved',foreign_nginx)
            finally:
                subprocess.run([str(NGINX),'-p',root.as_posix()+'/','-c','nginx/nginx.conf','-s','quit'],cwd=root,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                manual_nginx.wait(15);nginx_log.close()
        finally:
            try:launch(root,'Stop')
            except Exception:pass
    return 0

def current_project():
    baseline=snapshot(ROOT)
    record('current project: start + backend/proxy/home health checks',lambda:launch(ROOT))
    original=state(ROOT)
    config=digest(ROOT/'.env')
    def repeated():
        launch(ROOT)
        now=state(ROOT)
        check(now['Backend']['Id']==original['Backend']['Id'])
        check(now['Nginx']['Id']==original['Nginx']['Id'])
    record('current project: repeated start keeps same PIDs',repeated)
    record('current project: stop managed services',lambda:launch(ROOT,'Stop'))
    def restart_with_browser():
        output=launch(ROOT,open_browser=True)
        check('已请求默认浏览器打开' in output,output)
        check(request('/health')['status']=='ok')
        check(snapshot(ROOT)==baseline,'real business data changed')
        check(digest(ROOT/'.env')==config,'stable local configuration changed')
    record('current project: restart + default browser requested + real data unchanged',restart_with_browser)
    return 0

if __name__=='__main__':
    code=0
    try:code=current_project() if '--current-project' in sys.argv else main()
    except Exception as exc:
        code=1
        if not RESULTS or RESULTS[-1]['passed']:
            RESULTS.append({'test':'test setup/cleanup','passed':False,'reason':str(exc)})
            print('FAIL test setup/cleanup: '+str(exc),flush=True)
    finally:
        path=ROOT/'logs'/('launcher-current-tests.json' if '--current-project' in sys.argv else 'launcher-tests.json')
        path.write_text(json.dumps({'passed':sum(r['passed'] for r in RESULTS),'failed':sum(not r['passed'] for r in RESULTS),'results':RESULTS},ensure_ascii=False,indent=2),encoding='utf-8')
        print('Report: '+str(path),flush=True)
    sys.exit(code)
