"""Actual AES-GCM/persistence tests, plus engine-independent deployment contracts."""
import base64
from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from support import ROOT
import mcp_secrets
import mcp_client


def module(name):
    spec=importlib.util.spec_from_file_location('deploy_test_'+name,ROOT/'deploy'/(name+'.py'))
    loaded=importlib.util.module_from_spec(spec);spec.loader.exec_module(loaded);return loaded


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.key=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
        p=patch.dict(os.environ,{'CAMPUSCLAW_SECRET_BACKEND':'aesgcm','CAMPUSCLAW_MCP_ENCRYPTION_KEY':self.key})
        p.start();self.addCleanup(p.stop)
        self.token=secrets.token_hex(24)

    def test_aesgcm_actual_roundtrip_random_nonce(self):
        first=mcp_secrets.protect(self.token);second=mcp_secrets.protect(self.token)
        self.assertNotEqual(first,second);self.assertTrue(first.startswith(mcp_secrets.AES_PREFIX))
        self.assertTrue(self.token.encode() not in first,'plaintext persisted')
        self.assertTrue(mcp_secrets.unprotect(first)==self.token,'roundtrip failed')

    def test_tamper_rejected(self):
        blob=bytearray(mcp_secrets.protect(self.token));blob[-1]^=1
        with self.assertRaises(mcp_secrets.SecretError):mcp_secrets.unprotect(blob)

    def test_missing_and_wrong_key_fail_closed(self):
        blob=mcp_secrets.protect(self.token)
        for key in ['',base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),'not-a-key']:
            with patch.dict(os.environ,{'CAMPUSCLAW_MCP_ENCRYPTION_KEY':key}),self.assertRaises(mcp_secrets.SecretError):mcp_secrets.unprotect(blob)

    def test_missing_key_never_writes_plaintext(self):
        with patch.dict(os.environ,{'CAMPUSCLAW_MCP_ENCRYPTION_KEY':''}),self.assertRaises(mcp_secrets.SecretError):mcp_secrets.protect(self.token)

    def test_dpapi_blob_not_accepted_by_aes(self):
        with self.assertRaises(mcp_secrets.SecretError):mcp_secrets.unprotect(b'opaque-windows-blob')

    def test_native_windows_dpapi_still_works(self):
        with patch.dict(os.environ,{'CAMPUSCLAW_SECRET_BACKEND':'dpapi'}):
            blob=mcp_secrets.protect(self.token)
            self.assertTrue(mcp_secrets.unprotect(blob)==self.token,'DPAPI roundtrip failed')
            self.assertFalse(blob.startswith(mcp_secrets.AES_PREFIX))

    def test_cross_process_restart_decrypts_same_key(self):
        file=self.root/'cipher';file.write_bytes(mcp_secrets.protect(self.token))
        environment=os.environ.copy();environment['PYTHONPATH']=str(ROOT/'backend')+os.pathsep+environment.get('PYTHONPATH','')
        script="import sys,mcp_secrets; from pathlib import Path; value=mcp_secrets.unprotect(Path(sys.argv[1]).read_bytes()); assert len(value)==48; print('authenticated')"
        result=subprocess.run([sys.executable,'-c',script,str(file)],env=environment,capture_output=True,timeout=15)
        self.assertEqual(result.returncode,0);self.assertEqual(result.stdout.strip(),b'authenticated')

    def seed(self):
        data=self.root/'data';data.mkdir();(data/'material_files').mkdir()
        (data/'material_files/material.txt').write_text('原材料',encoding='utf-8')
        (data/'materials.json').write_text('[{"id":"original-id"}]')
        (data/'teacher_account.json').write_text('{"fixture":true}')
        with closing(sqlite3.connect(data/'assistant.sqlite3')) as db:
            db.executescript('CREATE TABLE accounts(id TEXT);INSERT INTO accounts VALUES("original");CREATE TABLE mcp_servers(id INTEGER PRIMARY KEY,token_blob BLOB,status TEXT,process_epoch TEXT,revision INTEGER);CREATE TABLE mcp_tools(server_id INTEGER);')
            db.execute('INSERT INTO mcp_servers VALUES(?,?,?, ?,0)',(1,mcp_secrets.protect(self.token),'connected','old'));db.commit()
        return data

    def test_consistent_backup_restore_and_cipher_persistence(self):
        data=self.seed();archive=self.root/'backup.zip';backup=module('backup_data')
        backup.backup(data,archive);target=self.root/'restored';backup.restore(archive,target)
        self.assertEqual((target/'materials.json').read_bytes(),(data/'materials.json').read_bytes())
        self.assertEqual((target/'material_files/material.txt').read_bytes(),(data/'material_files/material.txt').read_bytes())
        with closing(sqlite3.connect(target/'assistant.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT id FROM accounts').fetchone()[0],'original')
            self.assertTrue(mcp_secrets.unprotect(db.execute('SELECT token_blob FROM mcp_servers').fetchone()[0])==self.token,'restored token failed')

    def test_restore_refuses_nonempty_business_directory(self):
        data=self.seed();backup=module('backup_data');archive=self.root/'backup.zip';backup.backup(data,archive)
        with self.assertRaises(ValueError):backup.restore(archive,data)
        self.assertTrue((data/'materials.json').exists())

    def test_rotation_transaction_and_old_backup(self):
        data=self.seed();oldfile=data/'assistant.sqlite3';copy=self.root/'pre-rotate.sqlite3'
        new=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
        module('rotate_mcp_key').rotate(oldfile,copy,self.key,new)
        with closing(sqlite3.connect(oldfile)) as db:
            blob=db.execute('SELECT token_blob FROM mcp_servers').fetchone()[0]
            self.assertTrue(mcp_secrets.aes_decrypt(blob,mcp_secrets.aes_key(new))==self.token,'rotated decrypt failed')
            self.assertEqual(db.execute('SELECT status FROM mcp_servers').fetchone()[0],'disconnected')
        with closing(sqlite3.connect(copy)) as db:
            self.assertTrue(mcp_secrets.unprotect(db.execute('SELECT token_blob FROM mcp_servers').fetchone()[0])==self.token,'backup lost')

    def test_wrong_rotation_key_preserves_original(self):
        data=self.seed();file=data/'assistant.sqlite3';before=file.read_bytes()
        with self.assertRaises(mcp_secrets.SecretError):module('rotate_mcp_key').rotate(file,self.root/'backup.sqlite3',base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),self.key)
        self.assertEqual(file.read_bytes(),before)

    def test_container_dns_exception_is_exact_and_not_native(self):
        with patch.dict(os.environ,{'CAMPUSCLAW_CONTAINER_MODE':'1','CAMPUSCLAW_MCP_ALLOWED_URLS':'http://mcp:8090'}):
            self.assertEqual(mcp_client.validate_url('http://mcp:8090'),'http://mcp:8090')
            for value in ['http://mcp:8091','http://evil:8090','http://mcp.example:8090','http://mcp:8090/admin','http://127.0.0.1:5000']:
                with self.assertRaises(mcp_client.MCPError):mcp_client.validate_url(value)
        with patch.dict(os.environ,{'CAMPUSCLAW_CONTAINER_MODE':''}),self.assertRaises(mcp_client.MCPError):mcp_client.canonical_url('http://mcp:8090')

    def test_runtime_paths_move_only_with_explicit_data_root(self):
        environment=os.environ.copy();environment['CAMPUSCLAW_DATA_DIR']=str(self.root/'runtime');environment['PYTHONPATH']=str(ROOT/'backend')+os.pathsep+environment.get('PYTHONPATH','')
        script="import server,assistant_store,knowledge_base,os; from pathlib import Path; root=Path(os.environ['CAMPUSCLAW_DATA_DIR']); assert server.ACCOUNT_FILE.parent==root; assert assistant_store.DB_FILE.parent==root; assert knowledge_base.KNOWLEDGE_FILE.parent==root; assert server.HOST=='127.0.0.1'; print('paths-ok')"
        result=subprocess.run([sys.executable,'-c',script],env=environment,capture_output=True,timeout=15)
        self.assertEqual(result.returncode,0);self.assertEqual(result.stdout.strip(),b'paths-ok')

    def test_secret_initializer_never_overwrites(self):
        init=module('init_config');output=self.root/'new';env=init.create(output,18080)
        self.assertTrue(env.exists())
        with self.assertRaises(FileExistsError):init.create(output,18080)
        self.assertNotEqual((output/'secrets/token_secret').read_text(),(output/'secrets/mcp_auth_token').read_text())

    def test_compose_cli_and_exposure_contract(self):
        env=module('init_config').create(self.root/'compose',18080)
        config=module('validate_compose').validate(env,self.root/'normalized.json')
        self.assertEqual(config['services']['nginx']['ports'][0]['published'],'18080')
        self.assertFalse(config['services']['backend'].get('ports'))
        self.assertFalse(config['services']['mcp'].get('ports'))

    def test_image_copy_contract_excludes_business_data(self):
        text=(ROOT/'deploy/Dockerfile.backend').read_text()
        self.assertIn('COPY backend/*.py',text)
        self.assertNotIn('COPY . ',text);self.assertNotIn('.env',text)
        self.assertIn('**',(ROOT/'.dockerignore').read_text())
