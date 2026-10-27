"""Audit an explicit public snapshot; never reads .env, accounts or business data.

The candidate list is also used by the isolated Git index publication workflow.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
ROOT_FILES={'.gitignore','.dockerignore','.env.example','compose.yaml',
    'README.md','README.txt','STAGE_ACCEPTANCE_REPORT.md','STAGE_ACCEPTANCE_REPORT.html',
    'SUBMISSION_PRIVACY_AUDIT.md','requirements-deploy.txt','requirements-report.txt',
    '启动CampusClaw.bat','停止CampusClaw.bat'}


def public_paths():
    result=[ROOT/name for name in ROOT_FILES if (ROOT/name).is_file()]
    rules={'backend':{'.py'},'frontend':{'.html','.js'},'nginx':{'.conf'},
        'scripts':{'.py','.ps1','.cjs'},'apitest':{'.py','.cjs'},'mcp-server':{'.py','.md'},
        'deploy':{'.py','.conf','.md','.example'},'docs':{'.md'},
        'openspec':{'.md','.yaml','.yml'}}
    for folder,suffixes in rules.items():
        for p in (ROOT/folder).rglob('*'):
            if not p.is_file() or any((part.startswith('.') and part!='.openspec.yaml') or part in ('reports','__pycache__') for part in p.relative_to(ROOT/folder).parts):continue
            if p.suffix in suffixes or (folder=='deploy' and p.name.startswith('Dockerfile')):result.append(p)
    for p in (ROOT/'submission/evidence').glob('*'):
        if p.is_file() and (p.name.startswith('question_') and p.suffix=='.json' or p.name in {'test_summary.json','verification_summary.json','privacy_scan.json','course_requirements.json','assistant-public.png','swagger-public.png'}):result.append(p)
    for name in ['backend/material_files/.keep','logs/.keep','temp/.keep','output/pdf/STAGE_ACCEPTANCE_REPORT.pdf']:
        p=ROOT/name
        if p.is_file():result.append(p)
    return sorted(set(result))


def audit(paths):
    findings=[];hashes={};texts=0
    credential_patterns={
        'private_key':re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
        'provider_key':re.compile(r'\bsk-[A-Za-z0-9_-]{20,}\b'),
        'github_token':re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})\b'),
        'aws_key':re.compile(r'\bAKIA[A-Z0-9]{16}\b'),
        'jwt':re.compile(r'\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\b'),
        'credential_url':re.compile(r'https?://[^/\s:@]+:[^/@\s]+@'),
    }
    for p in paths:
        relative=p.relative_to(ROOT).as_posix()
        if p.is_symlink() or not p.resolve().is_relative_to(ROOT):
            findings.append({'file':relative,'kind':'symlink_or_external_path'});continue
        data=p.read_bytes();hashes[relative]=hashlib.sha256(data).hexdigest()
        if p.suffix=='.png':continue
        if p.suffix=='.pdf':
            try:
                from pypdf import PdfReader
                text='\n'.join(page.extract_text() or '' for page in PdfReader(p).pages)
            except Exception:
                findings.append({'file':relative,'kind':'pdf_text_audit_unavailable'});continue
        else:
            try:text=data.decode('utf-8-sig')
            except UnicodeError:findings.append({'file':relative,'kind':'non_utf8_text'});continue
        texts+=1
        for kind,pattern in credential_patterns.items():
            for match in pattern.finditer(text):
                line=text.count('\n',0,match.start())+1
                # Intentional rejected URL credentials are a security test, not
                # usable connection settings. Do not remove its negative case.
                if kind=='credential_url' and relative=='apitest/cases/mcp/HOST.py':continue
                findings.append({'file':relative,'line':line,'kind':kind})
        if p.suffix=='.py':
            try:tree=ast.parse(text)
            except SyntaxError as exc:findings.append({'file':relative,'line':exc.lineno,'kind':'syntax'});continue
            for node in ast.walk(tree):
                if not isinstance(node,ast.Dict):continue
                for key,value in zip(node.keys,node.values):
                    if isinstance(key,ast.Constant) and str(key.value).lower() in ('password','newpassword','oldpassword') and isinstance(value,ast.Constant) and isinstance(value.value,str) and value.value:
                        if relative=='apitest/cases/login/POST.py' and len(value.value)<8:continue
                        findings.append({'file':relative,'line':value.lineno,'kind':'literal_password'})
    return {'passed':not findings,'files_scanned':len(paths),'text_files_scanned':texts,
        'findings':findings,'negative_test_exceptions':['rejected credential URL in HOST.py','invalid short password in login test'],
        'scope':'explicit public snapshot only; no real .env/account/database inspected',
        'hashes':hashes}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'temp/submission-audit/scan.json');parser.add_argument('--paths-output',type=Path)
    args=parser.parse_args();paths=public_paths();result=audit(paths)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    if args.paths_output:
        args.paths_output.parent.mkdir(parents=True,exist_ok=True)
        args.paths_output.write_text('\n'.join(p.relative_to(ROOT).as_posix() for p in paths)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('passed','files_scanned','text_files_scanned','findings')},ensure_ascii=False))
    raise SystemExit(0 if result['passed'] else 1)
