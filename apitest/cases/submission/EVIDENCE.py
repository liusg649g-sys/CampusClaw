"""Public synthetic acceptance evidence: Mock LLM transport + real local APIs/MCP.

Only explicitly selected JSON bodies are exported. Authorization headers,
temporary credentials, account records and business files are never exported.
"""
import base64
import copy
import io
import json
import secrets
from unittest.mock import patch

from support import APITest, knowledge_base
import ai_gateway
from mcp_host_fixture import IsolatedMCP, service


EVIDENCE = {}
PAYLOAD_FIELDS = frozenset({'model', 'messages', 'temperature', 'stream', 'tools', 'tool_choice'})
SYNTHETIC_REPLY = '合成模型回复：仅用于验证请求结构，不代表真实模型推理质量。'


class SubmissionEvidenceTests(APITest):
    """Five independent checks corresponding to the five assignment questions."""

    def setUp(self):
        super().setUp()
        self.llm_requests = []
        self.llm_responses = []
        self.plan = None
        self.decisions = 0
        self.gateway_credential = secrets.token_hex(24)
        gateway_url = 'https://synthetic-gateway.example.invalid/v1'
        environment = patch.dict('os.environ', {
            'CHAT_BASE_URL': gateway_url,
            'CHAT_API_KEY': self.gateway_credential,
            'CHAT_MODEL': 'synthetic-acceptance-model',
        })
        environment.start()
        self.addCleanup(environment.stop)
        original_urlopen = ai_gateway.urllib.request.urlopen

        def mock_only_llm(request, *args, **kwargs):
            address = request.full_url if hasattr(request, 'full_url') else str(request)
            if not address.startswith(gateway_url + '/'):
                return original_urlopen(request, *args, **kwargs)
            # This is the actual Request.data produced by the production gateway.
            payload = json.loads(request.data.decode('utf-8'))
            self.assertTrue(set(payload) <= PAYLOAD_FIELDS)
            self.assertNotIn(self.gateway_credential, json.dumps(payload))
            self.llm_requests.append(copy.deepcopy(payload))
            if payload.get('stream'):
                frames = [
                    {'choices': [{'delta': {'content': SYNTHETIC_REPLY}, 'finish_reason': None}]},
                    {'choices': [{'delta': {}, 'finish_reason': 'stop'}]},
                ]
                self.llm_responses.append({'mode': 'mock_sse', 'frames': copy.deepcopy(frames), 'end': '[DONE]'})
                wire = ''.join('data: ' + json.dumps(frame, ensure_ascii=False) + '\n\n' for frame in frames)
                return io.BytesIO((wire + 'data: [DONE]\n\n').encode('utf-8'))
            self.decisions += 1
            response = self.plan(payload, self.decisions) if self.plan else {
                'choices': [{'message': {'role': 'assistant', 'content': SYNTHETIC_REPLY}, 'finish_reason': 'stop'}]
            }
            self.llm_responses.append({'mode': 'mock_json', 'body': copy.deepcopy(response)})
            return io.BytesIO(json.dumps(response, ensure_ascii=False).encode('utf-8'))

        transport = patch.object(ai_gateway.urllib.request, 'urlopen', mock_only_llm)
        transport.start()
        self.addCleanup(transport.stop)

    def create_material(self, text, class_id='a', title='合成公开材料'):
        code, body = self.request('/materials', 'POST', {
            'classId': class_id, 'title': title, 'fileName': 'synthetic-public.txt',
            'dataBase64': base64.b64encode(text.encode('utf-8')).decode('ascii'),
        }, self.teacher)
        self.assertEqual(code, 201)
        return body['material']['id']

    def create_skill(self, name='合成解题引导', trigger='验算', description='先核对条件，再提示下一步。', tools='knowledge_search'):
        source = '名称：%s\n适用条件：%s\n资料：\n工具：%s\n启用：是\n\n%s' % (name, trigger, tools, description)
        code, body = self.request('/teaching-skills', 'POST', {'classId': 'a', 'source': source}, self.teacher)
        self.assertEqual(code, 201)
        return body['id'], source

    def create_conversation(self, skills=(), materials=(), prompt='合成角色模板：帮助学生逐步理解课程。'):
        code, body = self.request('/agents', 'POST', {
            'classId': 'a', 'name': '合成验收助手', 'prompt': prompt, 'enabled': True,
            'skill_ids': list(skills), 'material_ids': list(materials),
        }, self.teacher)
        self.assertEqual(code, 201)
        code, body = self.request('/conversations', 'POST', {'classId': 'a', 'agentId': body['id']}, self.alice)
        self.assertEqual(code, 201)
        return body['id']

    def ask(self, conversation, question):
        code, raw = self.request('/conversations/' + conversation + '/messages', 'POST', {'question': question}, self.alice, raw=True, timeout=20)
        self.assertEqual(code, 200)
        events = self.events(raw)
        self.assertEqual(events[-1][0], 'done')
        self.assertEqual(''.join(data['text'] for event, data in events if event == 'delta'), SYNTHETIC_REPLY)
        return events

    def publish(self, key, **selected):
        # Deliberate whitelist: callers supply only synthetic content and public
        # protocol fields, never a raw API response, runtime configuration or log.
        EVIDENCE[key] = {
            'provenance': 'isolated synthetic data; Mock LLM HTTP transport; production request builder',
            'llm_requests': copy.deepcopy(self.llm_requests),
            'llm_responses': copy.deepcopy(self.llm_responses),
            **copy.deepcopy(selected),
        }

    def test_01_llm_payload_and_prompt_template(self):
        template = '合成角色模板：逐步启发，不替学生完成所有步骤。'
        conversation = self.create_conversation(prompt=template)
        self.ask(conversation, '请解释本轮请求的作用。')
        self.assertEqual(len(self.llm_requests), 1)
        payload = self.llm_requests[0]
        self.assertEqual(payload['model'], 'synthetic-acceptance-model')
        self.assertTrue(payload['stream'])
        self.assertEqual(payload['temperature'], 0.1)
        self.assertIn(template, payload['messages'][0]['content'])
        self.assertEqual(payload['messages'][-1]['role'], 'user')
        self.assertNotIn('tools', payload)
        self.publish('question_1_llm_payload', conclusion='角色提示词模板进入system消息；实际请求只包含所示字段。')

    def test_02_rag_sends_top_four_bound_chunks_not_whole_store(self):
        chunks = [('%s 检索验证。' % ('BOUND_CHUNK_%s' % i)).ljust(500, '甲') for i in range(6)]
        bound_text = ''.join(chunks)
        self.assertEqual(len(knowledge_base.split_text(bound_text)), 6)
        bound = self.create_material(bound_text)
        self.create_material('UNBOUND_PRIVATE_SENTINEL 检索验证。', title='未绑定的合成材料')
        self.create_material('OTHER_CLASS_SENTINEL 检索验证。', class_id='b', title='另班合成材料')
        conversation = self.create_conversation(materials=[bound])
        events = self.ask(conversation, '检索验证')
        citations = events[0][1]['citations']
        self.assertEqual(len(citations), 4)
        self.assertTrue(all(item['materialId'] == bound for item in citations))
        user_message = self.llm_requests[-1]['messages'][-1]['content']
        markers = ['BOUND_CHUNK_%s' % i for i in range(6)]
        sent_markers = [marker for marker in markers if marker in user_message]
        self.assertEqual(len(sent_markers), 4)
        self.assertNotIn('UNBOUND_PRIVATE_SENTINEL', user_message)
        self.assertNotIn('OTHER_CLASS_SENTINEL', user_message)
        self.assertNotIn(bound_text, user_message)
        self.publish('question_2_rag_scope', total_bound_chunks=6, transmitted_chunks=len(citations),
                     transmitted_chunk_markers=sent_markers,
                     excluded_chunk_markers=[marker for marker in markers if marker not in sent_markers],
                     class_and_binding_isolation=True,
                     conclusion='整库与整篇未发送；先按班级和材料绑定授权检索，再发送Top4切片。')

    def test_03_only_selected_skill_description_is_in_system(self):
        description = '合成技能正文第一行：先核对学生步骤。\n合成技能正文第二行：只给下一步提示。'
        selected, source = self.create_skill(description=description)
        other_description = 'UNSELECTED_SKILL_SENTINEL：这个技能本轮不得发送。'
        other, _ = self.create_skill(name='另一合成技能', trigger='天文', description=other_description)
        conversation = self.create_conversation(skills=[selected, other])
        events = self.ask(conversation, '请验算我的步骤。')
        system = self.llm_requests[-1]['messages'][0]['content']
        self.assertIn(description, system)
        self.assertNotIn(source, system)
        self.assertNotIn(other_description, system)
        self.assertNotIn('适用条件：', system)
        self.assertEqual(events[0][1]['skill']['name'], '合成解题引导')
        self.publish('question_3_selected_skill', selected_description=description,
                     source_header_example='名称、适用条件、资料、工具、启用（元数据不整文件拼入system）',
                     conclusion='只拼入本轮命中技能名称和完整说明正文；不是所有技能或整个源文件。')

    def test_04_no_skill_hit_still_calls_model_without_skill_body(self):
        description = 'NO_HIT_SKILL_BODY_SENTINEL：仅匹配验算时启用。'
        skill, _ = self.create_skill(description=description)
        conversation = self.create_conversation(skills=[skill])
        events = self.ask(conversation, 'zzzz_unmatched_synthetic_question')
        self.assertEqual(len(self.llm_requests), 1)
        self.assertIsNone(events[0][1]['skill'])
        self.assertEqual(events[0][1]['citations'], [])
        system = self.llm_requests[-1]['messages'][0]['content']
        self.assertNotIn(description, system)
        self.assertIn('没有匹配', system)
        self.assertNotIn('tools', self.llm_requests[-1])
        self.publish('question_4_skill_execution_rules', matched_skill=False, citations=[],
                     conclusion='Skill是规则路由、提示词增强及可选工具授权；未命中不执行脚本，Agent仍请求模型。')

    def test_05_real_mcp_call_result_return_and_final_stream(self):
        mcp = IsolatedMCP()
        self.addCleanup(mcp.close)
        allowance = patch.dict('os.environ', {'CAMPUSCLAW_MCP_ALLOWED_URLS': mcp.base})
        allowance.start()
        self.addCleanup(allowance.stop)
        code, body = self.request('/api/mcp/servers', 'POST', {
            'classId': 'a', 'name': '合成本机MCP', 'server_key': 'evidence-local',
            'base_url': mcp.base, 'auth_token': mcp.secret,
        }, self.teacher)
        self.assertEqual(code, 201)
        self.assertEqual(self.request('/api/mcp/servers/' + str(body['id']) + '/connect', 'POST', {}, self.teacher)[0], 200)
        wire_calls, wire_results = [], []
        original_dispatch = service.dispatch

        def observe_real_mcp(message):
            result = original_dispatch(message)
            if isinstance(message, dict) and message.get('method') == 'tools/call':
                wire_calls.append({key: copy.deepcopy(message[key]) for key in ('jsonrpc', 'id', 'method', 'params')})
                wire_results.append(copy.deepcopy(result))
            return result

        capture = patch.object(service, 'dispatch', observe_real_mcp)
        capture.start()
        self.addCleanup(capture.stop)
        skill, _ = self.create_skill(name='合成计算验证', trigger='计算验证',
                                     description='根据需要调用安全计算器，使用真实结果核对算式。',
                                     tools='calculator@evidence-local')
        conversation = self.create_conversation(skills=[skill])

        def model_plan(payload, turn):
            if turn == 1:
                alias = payload['tools'][0]['function']['name']
                return {'choices': [{'finish_reason': 'tool_calls', 'message': {
                    'role': 'assistant', 'content': None, 'tool_calls': [{
                        'id': 'synthetic_call_1', 'type': 'function',
                        'function': {'name': alias, 'arguments': '{"expression":"2*(3+4)"}'},
                    }],
                }}]}
            return {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': '合成决策：工具已完成。'}}]}

        self.plan = model_plan
        events = self.ask(conversation, '计算验证 2*(3+4)')
        self.assertEqual(len(self.llm_requests), 3)
        first, after_tool, final = self.llm_requests
        self.assertFalse(first['stream'])
        self.assertEqual(first['tool_choice'], 'auto')
        self.assertEqual(len(first['tools']), 1)
        self.assertEqual(len(wire_calls), 1)
        self.assertEqual(wire_calls[0]['params'], {'name': 'calculator', 'arguments': {'expression': '2*(3+4)'}})
        tool_messages = [message for message in after_tool['messages'] if message['role'] == 'tool']
        self.assertEqual(len(tool_messages), 1)
        self.assertEqual(tool_messages[0]['tool_call_id'], 'synthetic_call_1')
        result_data = json.loads(tool_messages[0]['content'])
        self.assertEqual(result_data['status'], 'ok')
        self.assertEqual(json.loads(result_data['data'])['value'], 14.0)
        self.assertTrue(final['stream'])
        self.assertNotIn('tools', final)
        self.assertIn('工具调用阶段已结束', final['messages'][-1]['content'])
        self.assertNotIn(mcp.secret, json.dumps(self.llm_requests))
        statuses = [data for event, data in events if event == 'tool_status']
        self.assertEqual([item['status'] for item in statuses], ['ok'])
        code, audit = self.request('/api/mcp/tool-calls?classId=a', token=self.teacher)
        self.assertEqual(code, 200)
        self.assertEqual(audit['calls'][0]['status'], 'ok')
        # Deliberately omit user IDs, conversation IDs, audit IDs and arguments hashes.
        public_audit = [{key: item[key] for key in ('tool_ref', 'status', 'round')} for item in audit['calls']]
        self.publish('question_5_mcp_loop', provenance='Mock LLM HTTP transport + real isolated MCP server/tools',
                     mcp_requests=wire_calls, mcp_responses=wire_results,
                     audit=public_audit, sse_event_sequence=[event for event, _ in events],
                     conclusion='真实calculator返回14；下一轮LLM收到tool消息；最终单独发起不带tools的SSE生成请求。')
