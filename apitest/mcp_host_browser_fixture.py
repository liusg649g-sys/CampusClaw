"""Disposable API + actual stage-one MCP; test token passes via child env only."""
import json
import os
import subprocess
from unittest.mock import patch
from support import APITest,ROOT
from stage1_browser_fixture import Handler
from mcp_host_fixture import IsolatedMCP


def main():
    fixture=APITest();fixture.setUp();mcp=IsolatedMCP()
    from pathlib import Path
    report=Path(os.environ.get('CAMPUSCLAW_BROWSER_REPORT_DIR') or ROOT/'apitest/reports/lesson6-stage2');report.mkdir(exist_ok=True,parents=True)
    try:
        fixture.httpd.RequestHandlerClass=Handler
        (report/'browser-fixture.json').write_text(json.dumps({'url':fixture.url,'mcp_url':mcp.base}),encoding='utf-8')
        environment=dict(os.environ,CAMPUSCLAW_TEST_PASSWORD=fixture.password);environment['CAMPUSCLAW_TEST_MCP_TOKEN']=mcp.secret
        with patch.dict('os.environ',{'CAMPUSCLAW_MCP_ALLOWED_URLS':mcp.base}):
            result=subprocess.run(['node',str(ROOT/'apitest/mcp_host_browser_check.cjs')],env=environment,cwd=ROOT,timeout=150)
        (report/'real-mcp-sequence.json').write_text(json.dumps({'service':'actual stage-one server','methods':mcp.httpd.sequence}),encoding='utf-8')
        return result.returncode
    finally:mcp.close();fixture.cleanup()


if __name__=='__main__':raise SystemExit(main())
