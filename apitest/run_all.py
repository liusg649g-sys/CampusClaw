"""python apitest/run_all.py -- dependency-free unittest + HTML report."""
import html
import importlib.util
import sys
import time
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))

class ReportResult(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.records=[]
    def addSuccess(self,test):
        super().addSuccess(test);self.records.append((test.id(),'通过',''))
    def addFailure(self,test,err):
        super().addFailure(test,err);self.records.append((test.id(),'失败',self._exc_info_to_string(err,test)))
    def addError(self,test,err):
        super().addError(test,err);self.records.append((test.id(),'错误',self._exc_info_to_string(err,test)))
    def addSkip(self,test,reason):
        super().addSkip(test,reason);self.records.append((test.id(),'未执行',reason))

def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--report-dir',type=Path,default=ROOT/'reports')
    arguments=parser.parse_args()
    # Keep all temporary fixtures under the ignored report directory; never touch
    # the real teacher account or assistant database, including legacy tests.
    report_dir=arguments.report_dir.resolve();report_dir.mkdir(parents=True,exist_ok=True)
    tempfile.tempdir=str(report_dir)
    import support
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as runtime:
        root=Path(runtime)
        account_patch=patch.object(support.server,'ACCOUNT_FILE',root/'teacher.json')
        db_patch=patch.object(support.store,'DB_FILE',root/'assistant.sqlite3')
        account_patch.start();db_patch.start()
        support.server.save_account(support.server.DEFAULT_ACCOUNT.copy())
        try:
            return execute(report_dir)
        finally:
            db_patch.stop();account_patch.stop()

def execute(report_dir):
    suite=unittest.TestSuite()
    loader=unittest.TestLoader()
    for i,path in enumerate(sorted((ROOT/'cases').rglob('*.py'))):
        spec=importlib.util.spec_from_file_location('case_'+str(i),path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        suite.addTests(loader.loadTestsFromModule(module))
    # Preserve and include existing project tests, isolated from business data.
    suite.addTests(loader.discover(str(ROOT.parent/'backend'/'tests')))
    start=time.monotonic()
    result=unittest.TextTestRunner(verbosity=2,resultclass=ReportResult).run(suite)
    body=''.join('<tr><td>'+html.escape(name)+'</td><td>'+status+'</td><td><pre>'+html.escape(reason)+'</pre></td></tr>' for name,status,reason in result.records)
    summary=f'总计 {result.testsRun}；失败 {len(result.failures)}；错误 {len(result.errors)}；未执行 {len(result.skipped)}；耗时 {time.monotonic()-start:.2f}s'
    output='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>CampusClaw API 测试报告</title><style>body{font-family:system-ui;margin:30px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:10px}pre{white-space:pre-wrap}</style><h1>CampusClaw API 测试报告</h1><p>'+summary+'</p><p>外部 AI 使用 mock 验证业务；此报告不表示真实 AI 服务已验证。数据位于临时目录。</p><table><tr><th>测试名称</th><th>结果</th><th>失败原因</th></tr>'+body+'</table></html>'
    path=report_dir/'report.html';path.write_text(output,encoding='utf-8')
    print(summary);print('HTML report:',path)
    return 0 if result.wasSuccessful() else 1

if __name__=='__main__':sys.exit(main())
