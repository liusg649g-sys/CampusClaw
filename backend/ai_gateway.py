"""Backend-only client for the course AI gateway."""

import json
import os
import re
import socket
import time
import urllib.error
import urllib.request


SYSTEM_PROMPT = """你是一个课程知识库问答助手。
你只能依据提供的参考资料回答问题，禁止使用参考资料之外的知识补充答案。
每个关键结论必须标注对应来源，例如 [1]、[2]。
引用编号只能使用参考资料中实际存在的编号。
如果参考资料不足以回答问题，请明确说明“根据当前班级资料无法确定”，不要猜测。
回答应简洁、直接。"""


class AIGatewayError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


class EmbeddingDimensionError(AIGatewayError):
    """The gateway returned a vector that cannot be used by the local index."""


def _first_environment_value(*names):
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def get_embedding_config():
    """Return teacher gateway settings, with legacy names kept as fallbacks."""
    raw_dimension = os.environ.get("EMBEDDING_DIM", "2048").strip() or "2048"
    try:
        dimension = int(raw_dimension)
        if dimension <= 0:
            raise ValueError
    except ValueError:
        raise AIGatewayError("EMBEDDING_DIM 必须是正整数", 503)
    return {
        "base_url": _first_environment_value(
            "EMBEDDING_BASE_URL", "AI_GATEWAY_BASE_URL"
        ),
        "api_key": _first_environment_value(
            "EMBEDDING_API_KEY", "AI_GATEWAY_API_KEY"
        ),
        "model": _first_environment_value(
            "EMBEDDING_MODEL", "AI_EMBEDDING_MODEL"
        ) or "course-embedding",
        "dimension": dimension,
    }


def embedding_is_configured():
    config = get_embedding_config()
    return bool(config["base_url"] and config["api_key"])


def get_chat_config():
    return {
        "base_url": _first_environment_value(
            "CHAT_BASE_URL", "EMBEDDING_BASE_URL", "AI_GATEWAY_BASE_URL"
        ),
        "api_key": _first_environment_value(
            "CHAT_API_KEY", "EMBEDDING_API_KEY", "AI_GATEWAY_API_KEY"
        ),
        "model": _first_environment_value("CHAT_MODEL", "AI_CHAT_MODEL")
        or "course-chat",
    }


def _gateway_endpoint(base_url, resource):
    base = str(base_url or "").rstrip("/")
    if base.endswith("/v1"):
        return base + "/" + resource
    return base + "/v1/" + resource


def _gateway_request(base_url, api_key, resource, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        _gateway_endpoint(base_url, resource),
        data=body,
        method="POST",
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        },
    )
    try:
        timeout = float(os.environ.get("AI_GATEWAY_TIMEOUT_SECONDS", "20"))
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        if error.code == 401:
            raise AIGatewayError("课程 AI 网关认证失败，请检查 API Key", 502)
        if error.code == 429:
            raise AIGatewayError("AI 服务请求过于频繁，请稍后重试", 429)
        if 500 <= error.code <= 599:
            raise AIGatewayError("AI 服务暂时不可用", 503)
        raise AIGatewayError("课程 AI 网关请求失败", 502)
    except (urllib.error.URLError, socket.timeout, TimeoutError):
        raise AIGatewayError("课程 AI 网关请求超时，请稍后重试", 504)


def create_embedding(text):
    """Create one embedding using the course OpenAI-compatible endpoint."""
    config = get_embedding_config()
    if not config["base_url"] or not config["api_key"]:
        raise AIGatewayError(
            "课程向量网关未配置，请设置 EMBEDDING_BASE_URL 和 EMBEDDING_API_KEY",
            503,
        )
    raw = _gateway_request(
        config["base_url"],
        config["api_key"],
        "embeddings",
        {"model": config["model"], "input": str(text or "")},
    )
    try:
        vector = json.loads(raw)["data"][0]["embedding"]
        if not isinstance(vector, list) or not all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in vector
        ):
            raise TypeError
    except (ValueError, TypeError, KeyError, IndexError):
        raise AIGatewayError("课程向量网关返回了无法解析的数据", 502)
    if len(vector) != config["dimension"]:
        raise EmbeddingDimensionError(
            "Embedding 维度不一致：期望 %s，实际 %s"
            % (config["dimension"], len(vector)),
            502,
        )
    return [float(value) for value in vector]


def build_chat_messages(question, sources):
    blocks = []
    for source in sources:
        location = (
            "第 %s 页" % source["page"]
            if source.get("page") is not None
            else "片段 %s" % source.get("chunkIndex", 0)
        )
        blocks.append(
            "[%s]\n文件：%s\n位置：%s\n内容：\n%s"
            % (
                source["ref"],
                source.get("sourceFile", "未知材料"),
                location,
                source.get("text", ""),
            )
        )
    user_prompt = (
        "问题：\n%s\n\n参考资料：\n\n%s\n\n"
        "请仅根据以上资料回答，并在对应内容后标注 [1]、[2] 等引用。"
        % (question, "\n\n".join(blocks))
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def answer_from_sources(question, sources):
    """Call an OpenAI-compatible chat completions gateway."""
    config = get_chat_config()
    if not config["base_url"] or not config["api_key"]:
        raise AIGatewayError(
            "课程 AI 网关未配置，请设置 EMBEDDING_BASE_URL 和 EMBEDDING_API_KEY",
            503,
        )

    raw = _gateway_request(config["base_url"], config["api_key"], "chat/completions", {
        "model": config["model"],
        "messages": build_chat_messages(question, sources),
        "temperature": 0.1,
    })

    try:
        data = json.loads(raw)
        content = data["choices"][0]["message"]["content"]
    except (ValueError, TypeError, KeyError, IndexError):
        raise AIGatewayError("课程 AI 网关返回了无法解析的数据", 502)
    if not isinstance(content, str) or not content.strip():
        raise AIGatewayError("AI 模型未返回有效回答", 502)
    answer = content.strip()
    citations = {int(value) for value in re.findall(r"\[(\d+)\]", answer)}
    valid_refs = {int(source["ref"]) for source in sources}
    if not citations or not citations.issubset(valid_refs):
        raise AIGatewayError("AI 模型返回的来源引用缺失或无效", 502)
    return answer


def _read_piece(response, size, deadline):
    remaining=deadline-time.monotonic()
    if remaining<=0:raise AIGatewayError('AI 请求超过总时限',504)
    sock=getattr(getattr(getattr(response,'fp',None),'raw',None),'_sock',None)
    if sock is not None:sock.settimeout(max(.1,min(20,remaining)))
    return response.read1(size) if hasattr(response,'read1') else response.read(size)


def _bounded_lines(response,deadline):
    pending=b'';total=0
    while True:
        chunk=_read_piece(response,8192,deadline)
        if not chunk:
            if pending:yield pending
            return
        total+=len(chunk);pending+=chunk
        if total>262144:raise AIGatewayError('AI 最终回答流超出大小限制')
        while b'\n' in pending:
            line,pending=pending.split(b'\n',1)
            if len(line)>32768:raise AIGatewayError('AI 最终回答流超出大小限制')
            yield line
        if len(pending)>32768:raise AIGatewayError('AI 最终回答流超出大小限制')


def stream_chat(messages, bounded=False):
    """Consume actual OpenAI SSE deltas; require a successful finish and [DONE]."""
    config = get_chat_config()
    if not config['base_url'] or not config['api_key']:
        raise AIGatewayError('AI 服务未配置，请设置 CHAT_BASE_URL 和 CHAT_API_KEY',503)
    timeout=float(os.environ.get('AI_GATEWAY_TIMEOUT_SECONDS','20'))
    if bounded:timeout=min(20,max(1,timeout))
    deadline=time.monotonic()+float(os.environ.get('AI_STREAM_TOTAL_SECONDS','120'))
    if bounded:deadline=min(deadline,time.monotonic()+120)
    request=urllib.request.Request(_gateway_endpoint(config['base_url'],'chat/completions'),
        data=json.dumps({'model':config['model'],'messages':messages,'stream':True,'temperature':0.1},ensure_ascii=False).encode(),
        headers={'Authorization':'Bearer '+config['api_key'],'Content-Type':'application/json','Accept':'text/event-stream'})
    finished=False
    content=False
    try:
        with urllib.request.urlopen(request,timeout=timeout) as response:
            total=0
            incoming=_bounded_lines(response,deadline) if bounded else response
            for raw in incoming:
                total+=len(raw)
                if bounded and (len(raw)>32768 or total>262144):raise AIGatewayError('AI 最终回答流超出大小限制')
                if time.monotonic()>deadline: raise AIGatewayError('AI 生成超过总时限',504)
                line=raw.decode('utf-8').strip()
                if not line.startswith('data:'): continue
                data=line[5:].strip()
                if data=='[DONE]':
                    if not finished or not content: raise AIGatewayError('AI 流未正常完成')
                    return
                event=json.loads(data)
                if 'error' in event: raise AIGatewayError('AI 流返回错误')
                choices=event.get('choices',[])
                if not choices: continue
                choice=choices[0]
                if choice.get('finish_reason'):
                    if choice['finish_reason']!='stop': raise AIGatewayError('AI 回答未完整生成')
                    finished=True
                delta=choice.get('delta',{}).get('content')
                if delta:
                    if not isinstance(delta,str): raise AIGatewayError('AI 流格式错误')
                    content=True
                    yield delta
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError):
        raise AIGatewayError('AI 流连接失败、超时或数据格式错误',502)
    raise AIGatewayError('AI 流意外结束',502)


def chat_tool_turn(messages, tools, timeout=20):
    """Bounded OpenAI-compatible non-stream tool decision, no fabricated fallback."""
    config=get_chat_config()
    if not config['base_url'] or not config['api_key']:raise AIGatewayError('AI 服务未配置，请设置 CHAT_BASE_URL 和 CHAT_API_KEY',503)
    payload={'model':config['model'],'messages':messages,'tools':tools,'tool_choice':'auto','stream':False,'temperature':0.1}
    if not tools:
        payload.pop('tools');payload.pop('tool_choice')
    body=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode()
    if len(body)>131072:raise AIGatewayError('模型工具请求上下文过大')
    request=urllib.request.Request(_gateway_endpoint(config['base_url'],'chat/completions'),data=body,
        headers={'Authorization':'Bearer '+config['api_key'],'Content-Type':'application/json'})
    try:
        deadline=time.monotonic()+min(20,max(.1,timeout))
        with urllib.request.urlopen(request,timeout=min(20,max(.1,timeout))) as response:
            pieces=[];size=0
            while True:
                piece=_read_piece(response,min(8192,131073-size),deadline)
                if not piece:break
                size+=len(piece)
                if size>131072:raise AIGatewayError('模型工具响应过大')
                pieces.append(piece)
            raw=b''.join(pieces)
        from mcp_client import _object,_constant
        data=json.loads(raw.decode('utf-8'),object_pairs_hook=_object,parse_constant=_constant)
        choice=data['choices'][0];message=choice['message'];reason=choice['finish_reason']
        if not isinstance(message,dict) or message.get('role')!='assistant':raise ValueError()
        calls=message.get('tool_calls',[])
        if not isinstance(calls,list) or len(calls)>16 or reason not in ('stop','tool_calls') or bool(calls)!=(reason=='tool_calls'):raise ValueError()
        content=message.get('content')
        if content is not None and (not isinstance(content,str) or len(content)>16000):raise ValueError()
        ids=set()
        for call in calls:
            if not isinstance(call,dict) or call.get('type')!='function' or not isinstance(call.get('id'),str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',call['id']) or call['id'] in ids:raise ValueError()
            function=call.get('function')
            if not isinstance(function,dict) or not isinstance(function.get('name'),str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',function['name']) or not isinstance(function.get('arguments'),str) or len(function['arguments'])>32768:raise ValueError()
            ids.add(call['id'])
        if not calls and (not isinstance(content,str) or not content.strip()):raise ValueError()
        return {'role':'assistant','content':content,'tool_calls':calls}
    except AIGatewayError:raise
    except urllib.error.HTTPError:raise AIGatewayError('模型工具请求失败；请确认网关支持 tools/tool_calls',502) from None
    except (OSError,urllib.error.URLError,ValueError,TypeError,KeyError,IndexError,RecursionError):raise AIGatewayError('模型工具协议无效或请求超时',502) from None


def stream_agent_final(messages):
    if len(json.dumps(messages,ensure_ascii=False).encode())>131072:raise AIGatewayError('模型最终回答上下文过大')
    yield from stream_chat(messages,bounded=True)
