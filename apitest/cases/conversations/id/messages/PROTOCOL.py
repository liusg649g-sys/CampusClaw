import io
import json
import unittest
from unittest.mock import patch
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[5]/'backend'))
from ai_gateway import stream_chat,AIGatewayError

class StreamProtocolTests(unittest.TestCase):
    def stream(self,content):
        return io.BytesIO(content.encode())
    def test_real_client_parses_chinese_deltas(self):
        raw='data: '+json.dumps({'choices':[{'delta':{'content':'中文提示'}}]},ensure_ascii=False)+'\n\ndata: '+json.dumps({'choices':[{'delta':{},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n'
        with patch('ai_gateway.get_chat_config',return_value={'base_url':'https://test.invalid/v1','api_key':'test-only','model':'course-chat'}),patch('urllib.request.urlopen',return_value=self.stream(raw)) as call:
            self.assertEqual(list(stream_chat([{'role':'user','content':'问题'}])),['中文提示'])
            payload=json.loads(call.call_args.args[0].data)
            self.assertTrue(payload['stream']);self.assertEqual(payload['messages'][0]['content'],'问题')
    def test_abrupt_end_and_malformed_stream_fail(self):
        for raw in ['data: [DONE]\n','data: broken\n','data: {"choices":[{"delta":{"content":"partial"}}]}\n','data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n']:
            with patch('ai_gateway.get_chat_config',return_value={'base_url':'https://test.invalid','api_key':'test-only','model':'test'}),patch('urllib.request.urlopen',return_value=self.stream(raw)):
                with self.assertRaises(AIGatewayError):list(stream_chat([]))
