"""Mock gateway transport verifies actual OpenAI-compatible wire payloads."""
import io
import json
import unittest
import urllib.error
from unittest.mock import patch
import ai_gateway


class ToolGatewayTests(unittest.TestCase):
    def invoke(self,data):
        body=io.BytesIO(json.dumps(data).encode())
        env={'CHAT_BASE_URL':'https://example.invalid/v1','CHAT_API_KEY':'isolated-gateway-test-key','CHAT_MODEL':'test'}
        with patch.dict('os.environ',env),patch.object(ai_gateway.urllib.request,'urlopen',return_value=body) as request:
            result=ai_gateway.chat_tool_turn([{'role':'user','content':'test'}],[{'type':'function','function':{'name':'test','parameters':{'type':'object'}}}])
            return result,json.loads(request.call_args.args[0].data)

    def test_tools_payload_and_finish_reason(self):
        result,payload=self.invoke({'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,'tool_calls':[{'id':'c1','type':'function','function':{'name':'test','arguments':'{}'}}]}}]})
        self.assertEqual(result['tool_calls'][0]['id'],'c1');self.assertFalse(payload['stream']);self.assertEqual(payload['tool_choice'],'auto')
        self.assertEqual(payload['tools'][0]['function']['name'],'test')

    def test_plain_text_decision(self):
        result,_=self.invoke({'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':'normal'}}]})
        self.assertEqual(result['tool_calls'],[])
        raw=b'data: {"choices":[{"delta":{"content":"final"},"finish_reason":null}]}\n\ndata: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
        with patch.dict('os.environ',{'CHAT_BASE_URL':'https://example.invalid','CHAT_API_KEY':'isolated-test-key'}),patch.object(ai_gateway.urllib.request,'urlopen',return_value=io.BytesIO(raw)):
            self.assertEqual(list(ai_gateway.stream_agent_final([])),['final'])

    def test_malformed_tool_protocol_is_explicit_error(self):
        for message,reason in [({'role':'assistant','content':'x'},'length'),({'role':'assistant','tool_calls':[]},'tool_calls'),({'role':'assistant','tool_calls':[{'id':'x','type':'function','function':{'name':'tool','arguments':{}}}]},'tool_calls')]:
            with self.assertRaises(ai_gateway.AIGatewayError):self.invoke({'choices':[{'finish_reason':reason,'message':message}]})

    def test_gateway_does_not_silently_fallback(self):
        with patch.dict('os.environ',{'CHAT_BASE_URL':'https://example.invalid','CHAT_API_KEY':'isolated-test-key'}),patch.object(ai_gateway.urllib.request,'urlopen',side_effect=urllib.error.HTTPError('url',400,'unsupported',{},None)):
            with self.assertRaises(ai_gateway.AIGatewayError):ai_gateway.chat_tool_turn([],[])

    def test_tool_role_and_call_id_forwarded_unchanged(self):
        response=io.BytesIO(json.dumps({'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':'answer'}}]}).encode())
        messages=[{'role':'assistant','tool_calls':[{'id':'c1','type':'function','function':{'name':'f','arguments':'{}'}}]}, {'role':'tool','tool_call_id':'c1','content':'untrusted data'}]
        with patch.dict('os.environ',{'CHAT_BASE_URL':'https://example.invalid','CHAT_API_KEY':'isolated-test-key'}),patch.object(ai_gateway.urllib.request,'urlopen',return_value=response) as request:
            ai_gateway.chat_tool_turn(messages,[])
            payload=json.loads(request.call_args.args[0].data)
            self.assertEqual(payload['messages'],messages);self.assertNotIn('tools',payload)

    def test_oversized_response_rejected(self):
        with patch.dict('os.environ',{'CHAT_BASE_URL':'https://example.invalid','CHAT_API_KEY':'isolated-test-key'}),patch.object(ai_gateway.urllib.request,'urlopen',return_value=io.BytesIO(b'x'*131073)):
            with self.assertRaises(ai_gateway.AIGatewayError):ai_gateway.chat_tool_turn([],[])
