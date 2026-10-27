"""Isolated browser fixture. AI MOCK ONLY; not a production launcher."""
import json
import time
import threading
from pathlib import Path
from unittest.mock import patch
from support import APITest,server,ROOT

def model(messages):
    yield '请先想一想：'
    time.sleep(0.4)
    yield '质量不变时，力和加速度之间有什么关系？[1]'

class Handler(server.CampusClawAPI):
    def do_GET(self):
        if self.path in ('/assistant.html','/assistant.js'):
            file=ROOT/'frontend'/self.path[1:]
            body=file.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8' if file.suffix=='.html' else 'application/javascript; charset=utf-8')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        else:super().do_GET()

if __name__=='__main__':
    fixture=APITest()
    fixture.setUp()
    fixture.httpd.RequestHandlerClass=Handler
    fixture.material()
    report=ROOT/'apitest'/'reports';report.mkdir(exist_ok=True)
    (report/'browser-fixture.json').write_text(json.dumps({'url':fixture.url,'test_password':fixture.password}),encoding='utf-8')
    print('Browser fixture: '+fixture.url,flush=True)
    stop=threading.Event()
    def watch_input():
        try:input()
        except EOFError:pass
        stop.set()
    threading.Thread(target=watch_input,daemon=True).start()
    try:
        with patch('assistant_api.stream_chat',side_effect=model):
            stop.wait(300)
    except KeyboardInterrupt:pass
    finally:fixture.cleanup()
