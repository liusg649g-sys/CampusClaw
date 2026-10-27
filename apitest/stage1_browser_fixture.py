"""Run the browser checks against disposable HTTP/storage, never port 5000/8080."""
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit
from support import APITest, ROOT, server, store


class Handler(server.CampusClawAPI):
    def do_GET(self):
        route=urlsplit(self.path).path
        if route=='/assistant.html/':route='/assistant.html'
        paths={'/':'index.html','/assistant.html':'assistant.html','/assistant.js':'assistant.js',
               '/teaching-management.js':'teaching-management.js','/mcp-management.js':'mcp-management.js'}
        if route in paths:
            file=ROOT/'frontend'/paths[route]
            body=file.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type','application/javascript; charset=utf-8' if file.suffix=='.js' else 'text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        else:super().do_GET()


def main():
    reports=Path(os.environ.get('CAMPUSCLAW_BROWSER_REPORT_DIR') or ROOT/'apitest/reports');reports.mkdir(exist_ok=True,parents=True)
    fixture=APITest()
    fixture.setUp()
    try:
        fixture.httpd.RequestHandlerClass=Handler
        # Empty class preparation scenario, only inside this temporary database.
        with store.connect() as db:
            db.execute('DELETE FROM prompts')
            db.execute('DELETE FROM members')
            db.execute('DELETE FROM classes')
        (reports/'stage1-browser-fixture.json').write_text(json.dumps({'url':fixture.url}),encoding='utf-8')
        result=subprocess.run(['node',str(ROOT/'apitest/stage1_browser_check.cjs')],cwd=ROOT,env=dict(os.environ,CAMPUSCLAW_TEST_PASSWORD=fixture.password),timeout=200)
        return result.returncode
    finally:
        fixture.cleanup()

if __name__=='__main__':sys.exit(main())
