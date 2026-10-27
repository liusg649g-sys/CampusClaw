"""Dependency-free local vector store for class materials."""

from io import BytesIO
from pathlib import Path
import hashlib
import json
import math
import re
import tempfile

from ai_gateway import (
    AIGatewayError,
    create_embedding,
    embedding_is_configured,
    get_embedding_config,
)


BASE_DIR = Path(__file__).resolve().parent

# 知识片段保存的位置
from runtime_paths import DATA_DIR
KNOWLEDGE_FILE = DATA_DIR / "knowledge_chunks.json"
VECTOR_DIMENSIONS = 256
VECTOR_ONLY_MIN_SCORE = 0.25
TEXT_EXTENSIONS = {".md", ".markdown", ".txt", ".csv", ".json", ".html", ".htm"}


def load_knowledge():
    """
    读取已经建立好的知识库。
    如果文件不存在，则返回空列表。
    """
    if not KNOWLEDGE_FILE.exists():
        return []

    try:
        data = json.loads(
            KNOWLEDGE_FILE.read_text(encoding="utf-8")
        )

        if isinstance(data, list):
            return data

    except Exception:
        pass

    return []


def save_knowledge(chunks):
    """
    把知识片段保存到 knowledge_chunks.json。
    """
    KNOWLEDGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=KNOWLEDGE_FILE.parent,suffix='.tmp',delete=False) as output:
        temporary=Path(output.name)
        output.write(json.dumps(chunks, ensure_ascii=False, indent=2))
    try:
        temporary.replace(KNOWLEDGE_FILE)
    finally:
        temporary.unlink(missing_ok=True)


def _decode_text(file_bytes):
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return file_bytes.decode("utf-8", errors="replace")


def extract_text_pages(file_name, file_bytes):
    """提取可检索文本；PDF 在安装 pypdf 时同时保留一基页码。"""
    suffix = Path(str(file_name or "")).suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        text = _decode_text(file_bytes).strip()
        return [{"page": None, "text": text}] if text else []
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            return []
        pages = []
        try:
            for number, page in enumerate(PdfReader(BytesIO(file_bytes)).pages, 1):
                text = (page.extract_text() or "").strip()
                if text:
                    pages.append({"page": number, "text": text})
        except Exception:
            return []
        return pages
    return []


def split_text(text, chunk_size=500):
    """
    将较长文本切分为多个知识片段。

    chunk_size:
        每个片段最多约 500 个字符。
    """
    text = str(text or "").strip()

    if not text:
        return []

    # 将多个连续空白字符合并
    text = re.sub(r"\s+", " ", text)

    chunks = []

    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        start = end

    return chunks


def _tokens(text):
    normalized = str(text or "").lower()
    tokens = re.findall(r"[a-z0-9_]+", normalized)
    for run in re.findall(r"[\u3400-\u9fff]+", normalized):
        tokens.append(run)
        tokens.extend(run[index:index + 2] for index in range(max(0, len(run) - 1)))
    return tokens


def text_to_vector(text):
    """生成稳定、归一化的哈希词向量，无需联网下载模型。"""
    vector = [0.0] * VECTOR_DIMENSIONS
    for token in _tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % VECTOR_DIMENSIONS
        vector[index] += -1.0 if digest[4] & 1 else 1.0
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


def _cosine(left, right):
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def _keyword_score(query, text):
    """为包含匹配提供确定性高权重，并支持多关键词交集匹配。"""
    normalized_query = str(query or "").casefold().strip()
    normalized_text = str(text or "").casefold()
    if not normalized_query:
        return 0.0
    if normalized_query in normalized_text:
        return 10.0

    ascii_query_tokens = set(re.findall(r"[a-z0-9_]+", normalized_query))
    if ascii_query_tokens:
        ascii_text_tokens = set(re.findall(r"[a-z0-9_]+", normalized_text))
        matched_ascii = ascii_query_tokens.intersection(ascii_text_tokens)
        return (
            4.0 * len(matched_ascii) / len(ascii_query_tokens)
            if matched_ascii else 0.0
        )

    query_tokens = {
        token for token in _tokens(normalized_query)
        if len(token) >= 2
    }
    if not query_tokens:
        return 0.0
    matched_tokens = query_tokens.intersection(_tokens(normalized_text))
    return 2.0 * len(matched_tokens) / len(query_tokens) if matched_tokens else 0.0


def build_material_chunks(material):
    """
    将一份课程材料转换成多个知识片段。
    """

    material_id = str(material.get("id", ""))
    class_id = str(material.get("classId", ""))
    source_file = str(material.get("fileName", ""))
    pages = material.get("pages")
    if not isinstance(pages, list):
        pages = [{"page": None, "text": str(material.get("text", ""))}]
    result = []
    index = 0
    for page_data in pages:
        for chunk_text in split_text(page_data.get("text", "")):
            page = page_data.get("page")
            result.append({
                "id": f"{material_id}_chunk_{index}",
                "materialId": material_id,
                "classId": class_id,
                "sourceFile": source_file,
                "title": str(material.get("title", source_file)),
                "page": page,
                "chunkIndex": index,
                "text": chunk_text,
                "vector": text_to_vector(chunk_text),
                "metadata": {
                    "class_id": class_id,
                    "source_file": source_file,
                    "page": page,
                    "chunk_index": index
                }
            })
            index += 1

    return result


def rebuild_knowledge(materials):
    """
    根据所有课程材料重新建立知识库。
    """

    existing_chunks = {chunk.get("id"): chunk for chunk in load_knowledge()}
    all_chunks = []

    for material in materials:
        chunks = build_material_chunks(material)
        all_chunks.extend(chunks)

    # Preserve valid cached remote embeddings across the frequent index sync.
    for chunk in all_chunks:
        existing = existing_chunks.get(chunk.get("id"), {})
        same_source = all(
            existing.get(key) == chunk.get(key)
            for key in ("text", "classId", "sourceFile", "page", "chunkIndex")
        )
        if same_source and isinstance(existing.get("embedding"), list):
            for key in ("embedding", "embeddingModel", "embeddingDim"):
                chunk[key] = existing.get(key)

    try:
        remote_config = get_embedding_config()
        use_remote = embedding_is_configured()
    except AIGatewayError as error:
        print("[knowledge] 远程 embedding 配置无效，使用本地检索：%s" % error)
        remote_config = None
        use_remote = False

    if use_remote:
        gateway_available = True
        for chunk in all_chunks:
            cached = (
                chunk.get("embeddingModel") == remote_config["model"]
                and chunk.get("embeddingDim") == remote_config["dimension"]
                and isinstance(chunk.get("embedding"), list)
                and len(chunk["embedding"]) == remote_config["dimension"]
            )
            if cached or not gateway_available:
                continue
            try:
                chunk["embedding"] = create_embedding(chunk["text"])
                chunk["embeddingModel"] = remote_config["model"]
                chunk["embeddingDim"] = remote_config["dimension"]
            except AIGatewayError as error:
                # One failure disables the remaining remote calls in this rebuild.
                # The explicit diagnostic keeps dimension/config errors visible.
                print("[knowledge] 远程 embedding 不可用，使用本地检索：%s" % error)
                gateway_available = False

    save_knowledge(all_chunks)

    return all_chunks


def search_knowledge(class_id, query, limit=4, allowed_material_ids=None):
    """
    在指定班级范围内搜索知识内容。

    使用关键词包含/分词匹配与向量余弦相似度的混合检索，
    并在任何打分前强制按班级过滤。
    """

    class_id = str(class_id or "").strip()
    query = str(query or "").strip()

    if not class_id or not query:
        return []

    # Class isolation happens before query embedding and before all scoring.
    candidates = [
        chunk for chunk in load_knowledge()
        if str(chunk.get("classId", "")) == class_id
        and (allowed_material_ids is None or
             (str(chunk.get('materialId', '')) in allowed_material_ids
              and str(chunk.get('text', '')).strip()))
    ]
    if not candidates:
        return []

    local_query_vector = text_to_vector(query)
    remote_query_vector = None
    remote_config = None
    try:
        if embedding_is_configured():
            remote_config = get_embedding_config()
            if any(
                chunk.get("embeddingModel") == remote_config["model"]
                and chunk.get("embeddingDim") == remote_config["dimension"]
                for chunk in candidates
            ):
                remote_query_vector = create_embedding(query)
    except AIGatewayError as error:
        print("[knowledge] 查询 embedding 不可用，使用本地检索：%s" % error)

    results = []
    for chunk in candidates:
        text = str(chunk.get("text", ""))
        keyword_score = _keyword_score(query, text)
        remote_vector = chunk.get("embedding")
        if (
            remote_query_vector is not None
            and remote_config is not None
            and chunk.get("embeddingModel") == remote_config["model"]
            and chunk.get("embeddingDim") == remote_config["dimension"]
            and isinstance(remote_vector, list)
            and len(remote_vector) == remote_config["dimension"]
        ):
            vector_score = _cosine(remote_query_vector, remote_vector)
        else:
            vector = chunk.get("vector")
            if not isinstance(vector, list) or len(vector) != VECTOR_DIMENSIONS:
                vector = text_to_vector(text)
            vector_score = _cosine(local_query_vector, vector)
        # 负向量分数不能抵消关键词命中；向量仅补充召回与同类结果排序。
        score = keyword_score + max(vector_score, 0.0)
        if keyword_score > 0 or vector_score >= VECTOR_ONLY_MIN_SCORE:
            result = {
                key: value for key, value in chunk.items()
                if key not in ("vector", "embedding")
            }
            result["score"] = round(score, 6)
            results.append(result)

    results.sort(key=lambda item: item.get("score", 0), reverse=True)
    return results[:max(1, int(limit))]
