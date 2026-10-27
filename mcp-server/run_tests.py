"""Standalone report; never imports or initializes CampusClaw business modules."""
import html
import os
import json
from pathlib import Path
import time
import unittest

ROOT=Path(__file__).resolve().parent


class Result(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.records=[]
    def addSuccess(self,test):super().addSuccess(test);self.records.append((test.id(),'通过',''))
    def addFailure(self,test,err):super().addFailure(test,err);self.records.append((test.id(),'失败',self._exc_info_to_string(err,test)))
    def addError(self,test,err):super().addError(test,err);self.records.append((test.id(),'错误',self._exc_info_to_string(err,test)))
    def addSkip(self,test,reason):super().addSkip(test,reason);self.records.append((test.id(),'跳过',reason))


if __name__=='__main__':
    start=time.monotonic()
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
    result=unittest.TextTestRunner(verbosity=2,resultclass=Result).run(suite)
    report=Path(os.environ.get('CAMPUSCLAW_MCP_REPORT_DIR') or ROOT.parent/'apitest/reports/lesson6-stage1');report.mkdir(parents=True,exist_ok=True)
    stats=dict(total=result.testsRun,passed=result.testsRun-len({t.id() for t,_ in result.failures+result.errors+result.skipped}),failed=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),seconds=round(time.monotonic()-start,2),model_calls=0)
    (report/'result.json').write_text(json.dumps(stats,indent=2),encoding='utf-8')
    rows=''.join('<tr><td>'+html.escape(n)+'</td><td>'+s+'</td><td><pre>'+html.escape(d)+'</pre></td></tr>' for n,s,d in result.records)
    (report/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>第6课独立MCP测试</title><h1>独立 MCP 实际工具测试</h1><p>'+html.escape(json.dumps(stats,ensure_ascii=False))+'</p><p>随机端口，临时测试令牌，无真实模型调用；不修改业务数据。</p><table border="1">'+rows+'</table>',encoding='utf-8')
    raise SystemExit(0 if result.wasSuccessful() else 1)
