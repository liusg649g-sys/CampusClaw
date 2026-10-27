"""Focused static-route regression; no business initialization or authentication."""
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
from http.server import ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'apitest/reports/site-route-recheck'


def main():
    REPORT.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT/'temp') as temporary:
        os.environ['CAMPUSCLAW_DATA_DIR']=temporary
        from serve_acceptance import AcceptanceHandler
        server=ThreadingHTTPServer(('127.0.0.1',0),AcceptanceHandler)
        thread=threading.Thread(target=server.serve_forever);thread.start()
        records=[]
        try:
            for route in ['/assistant.html','/assistant.html?probe=1','/assistant.html/',
                          '/assistant.js?probe=1','/swagger','/swagger?probe=1',
                          'http://127.0.0.1:%d/assistant.html'%server.server_port,
                          'http://127.0.0.1:%d/swagger'%server.server_port]:
                conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
                conn.request('GET',route);response=conn.getresponse();body=response.read().decode('utf-8');conn.close()
                assert response.status==200,(route,response.status)
                if 'assistant.html' in route:assert '<title>CampusClaw · AI 解题助手</title>' in body
                if 'swagger' in route:assert 'SwaggerUIBundle' in body
                records.append({'request_target':route,'status':response.status})
            (REPORT/'route-unit.json').write_text(json.dumps({'passed':True,'passedChecks':len(records),'business_data_initialized':False,'checks':records},ensure_ascii=False,indent=2),encoding='utf-8')
            print('Focused route regression: %d passed'%len(records))
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':main()
