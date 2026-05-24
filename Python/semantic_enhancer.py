"""
Blueprint Semantic Enhancer — LLM-powered annotation and Q&A for blueprint graphs.

将蓝图 JSON / 伪代码传给 LLM，生成子图自然语言摘要，并支持蓝图问答。
核心设计：
  - 伪代码是 LLM 的上下文（比原始 JSON 省约 60-80% Token）
  - 按子图粒度调用 LLM，避免单次 Token 过长
  - 结果可缓存（同一蓝图 + 同一模型 → 同一摘要）
  - LLM 调用通过 OpenAI-compatible API（支持本地/云端）

Usage:
  # CLI
  python -m semantic_enhancer blueprint.json --summarize
  python -m semantic_enhancer blueprint.json --ask "BeginPlay 做了什么?"

  # Python API
  from semantic_enhancer import summarize_blueprint, ask_blueprint
  summaries = summarize_blueprint(graph_data)
  answer = ask_blueprint(graph_data, "BP_Enemy 死亡时做了什么?")
"""

import json
import os
import sys
import hashlib
import tempfile
from typing import Optional


# ============================================================================
# 配置
# ============================================================================

# OpenAI-compatible API 配置（可通过环境变量覆盖）
DEFAULT_BASE_URL = os.environ.get(
    "OPENAI_BASE_URL", "https://api.openai.com/v1"
)
DEFAULT_API_KEY = os.environ.get("OPENAI_API_KEY", "")
DEFAULT_MODEL = os.environ.get(
    "SEMANTIC_ENHANCER_MODEL", "gpt-4o-mini"
)
DEFAULT_MAX_TOKENS = int(os.environ.get(
    "SEMANTIC_ENHANCER_MAX_TOKENS", "1024"
))

# 缓存目录（默认系统临时目录）
CACHE_DIR = os.environ.get(
    "SEMANTIC_ENHANCER_CACHE_DIR",
    os.path.join(tempfile.gettempdir(), "bp_semantic_cache")
)

# 子图最大行数（超过则截断，避免超过上下文窗口）
MAX_SUBGRAPH_LINES = int(os.environ.get(
    "SEMANTIC_ENHANCER_MAX_LINES", "200"
))


# ============================================================================
# 伪代码分段 — 将完整伪代码按 graph/function 切片
# ============================================================================

def split_pseudocode_by_subgraph(pseudocode: str) -> list[dict]:
    """将伪代码按子图（graph/function）切分为独立段落。

    Returns:
        list of {"name": str, "type": str, "code": str}
        type: "header" (蓝图元数据+变量), "graph" (图/函数体)
    """
    sections = []
    lines = pseudocode.split("\n")

    current_name = None
    current_type = None
    current_lines = []

    def flush():
        if current_lines:
            sections.append({
                "name": current_name or "__header__",
                "type": current_type or "header",
                "code": "\n".join(current_lines).strip(),
            })

    for line in lines:
        stripped = line.strip()

        # 检测 graph/function 起始行
        # 格式: "graph EventGraph (ubergraph)" 或 "function TakeDamage(Amount: float):"
        if stripped.startswith("graph ") or stripped.startswith("function "):
            flush()
            current_type = "graph" if stripped.startswith("graph ") else "graph"
            current_name = stripped.split("(")[0].strip() if "(" in stripped else stripped
            current_lines = [line]
            continue

        # 检测 "variables:" 块
        if stripped == "variables:":
            flush()
            current_name = "__variables__"
            current_type = "header"
            current_lines = [line]
            continue

        # 检测蓝图头 "blueprint ..."
        if stripped.startswith("blueprint "):
            flush()
            current_name = "__header__"
            current_type = "header"
            current_lines = [line]
            continue

        if current_lines or stripped:  # 跳过前导空行
            current_lines.append(line)

    flush()
    return sections


# ============================================================================
# LLM 调用（OpenAI-compatible）
# ============================================================================

def _call_llm(
    prompt: str,
    system: str = "",
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
) -> str:
    """调用 OpenAI-compatible Chat Completion API。

    支持 OpenAI、Azure、本地 Ollama/vLLM/LM Studio 等，通过环境变量配置。
    """
    import urllib.request
    import urllib.error

    url = (base_url or DEFAULT_BASE_URL).rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"

    key = api_key or DEFAULT_API_KEY
    mdl = model or DEFAULT_MODEL
    mt = max_tokens or DEFAULT_MAX_TOKENS

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    body = json.dumps({
        "model": mdl,
        "messages": messages,
        "max_tokens": mt,
        "temperature": 0.3,  # 低温度，追求确定性摘要
    }).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
    }
    if key:
        headers["Authorization"] = f"Bearer {key}"

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"LLM API HTTP {e.code}: {error_body[:500]}"
        ) from e
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"LLM API connection failed: {e.reason}. "
            f"Check OPENAI_BASE_URL ({base_url or DEFAULT_BASE_URL})"
        ) from e


# ============================================================================
# 缓存
# ============================================================================

def _cache_key(blueprint_id: str, section_name: str, model: str, task: str) -> str:
    """生成缓存文件名。task = 'summary' | 'answer'"""
    raw = f"{blueprint_id}::{section_name}::{model}::{task}"
    h = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return os.path.join(CACHE_DIR, f"{h}.json")


def _read_cache(key_path: str) -> Optional[str]:
    if os.path.exists(key_path):
        try:
            with open(key_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("content")
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _write_cache(key_path: str, content: str):
    os.makedirs(os.path.dirname(key_path), exist_ok=True)
    with open(key_path, "w", encoding="utf-8") as f:
        json.dump({"content": content}, f, ensure_ascii=False)


# ============================================================================
# 子图摘要（5.1）
# ============================================================================

SUMMARY_SYSTEM_PROMPT = """\
You are a technical writer analyzing Unreal Engine Blueprint pseudocode.
For each graph/function section, write a ONE-LINE natural language summary in Chinese.
The summary should describe WHAT the code DOES, not HOW it does it.
Be concise (under 80 chars). Use active voice.
Format: one summary per line, prefixed with the graph name.

Example:
EventGraph: 游戏开始时检查玩家引用，有效则初始化 HUD 并启动定时生成敌人
TakeDamage: 扣减生命值，死亡时调用 Die()，否则播放受击特效\
"""


def summarize_blueprint(
    graph_data: dict,
    use_cache: bool = True,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> dict[str, str]:
    """为蓝图的每个子图生成自然语言摘要。

    Args:
        graph_data: 蓝图 JSON 数据
        use_cache: 是否使用缓存（默认 true）
        base_url/api_key/model: LLM API 配置（None 则用默认值/环境变量）

    Returns:
        dict of {子图名: 摘要文本}
        例如: {"EventGraph": "游戏开始时检查玩家引用，有效则初始化HUD", ...}
    """
    from graph_to_pseudocode import graph_to_pseudocode

    pseudocode = graph_to_pseudocode(graph_data)
    sections = split_pseudocode_by_subgraph(pseudocode)

    # 过滤掉 header 和空 section
    graph_sections = [s for s in sections if s["type"] == "graph" and s["code"].strip()]
    if not graph_sections:
        return {}

    mdl = model or DEFAULT_MODEL
    bp_id = graph_data.get("asset_path", "unknown")

    # 合并所有子图为一次 LLM 调用（节省 API 调用次数）
    # 如果单个子图超过 MAX_SUBGRAPH_LINES，截断
    combined = []
    for s in graph_sections:
        code_lines = s["code"].split("\n")
        if len(code_lines) > MAX_SUBGRAPH_LINES:
            code_lines = code_lines[:MAX_SUBGRAPH_LINES]
            code_lines.append(f"  # ... (truncated, {len(s['code'].split(chr(10)))} lines total)")
        combined.append(f"### {s['name']}\n```\n" + "\n".join(code_lines) + "\n```")

    combined_text = "\n\n".join(combined)
    prompt = f"Summarize each graph/function in this blueprint pseudocode:\n\n{combined_text}"

    # 缓存
    cache_path = _cache_key(bp_id, "__all__", mdl, "summary")
    if use_cache:
        cached = _read_cache(cache_path)
        if cached is not None:
            return _parse_summaries(cached)

    # 调用 LLM
    raw_response = _call_llm(
        prompt, system=SUMMARY_SYSTEM_PROMPT,
        base_url=base_url, api_key=api_key, model=model,
    )

    if use_cache:
        _write_cache(cache_path, raw_response)

    return _parse_summaries(raw_response)


def _parse_summaries(raw: str) -> dict[str, str]:
    """解析 LLM 返回的摘要文本为 {name: summary} dict。"""
    summaries = {}
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # 格式: "EventGraph: 游戏开始时..."
        # 或 "- EventGraph: 游戏开始时..."
        if ":" in line:
            # 去掉前缀标记
            line = line.lstrip("- •*0123456789. ")
            parts = line.split(":", 1)
            if len(parts) == 2 and parts[0].strip():
                summaries[parts[0].strip()] = parts[1].strip()
    return summaries


# ============================================================================
# 蓝图问答（5.2）
# ============================================================================

QA_SYSTEM_PROMPT = """\
You are an expert in Unreal Engine Blueprint development.
Answer the user's question based on the provided blueprint pseudocode and summaries.
Be specific — reference function names, variable names, and control flow.
Answer in Chinese. Keep responses under 200 words.
If the question cannot be answered from the provided context, say so.\
"""


def ask_blueprint(
    graph_data: dict,
    question: str,
    use_cache: bool = True,
    summaries: Optional[dict[str, str]] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> str:
    """对蓝图提问，基于伪代码 + 摘要回答。

    Args:
        graph_data: 蓝图 JSON 数据
        question: 自然语言问题
        use_cache: 是否缓存回答
        summaries: 预生成的摘要（None 则自动生成）
        base_url/api_key/model: LLM API 配置

    Returns:
        LLM 的回答文本
    """
    from graph_to_pseudocode import graph_to_pseudocode

    # 生成摘要（如果未提供）
    if summaries is None:
        try:
            summaries = summarize_blueprint(
                graph_data, use_cache=use_cache,
                base_url=base_url, api_key=api_key, model=model,
            )
        except Exception:
            summaries = {}  # 摘要失败不阻塞问答

    pseudocode = graph_to_pseudocode(graph_data)

    # 构建上下文 — 优先摘要，伪代码作为详细参考
    context_parts = []

    if summaries:
        context_parts.append("## 子图摘要")
        for name, summary in summaries.items():
            context_parts.append(f"- {name}: {summary}")
        context_parts.append("")

    # 截断伪代码（避免超过上下文窗口）
    pc_lines = pseudocode.split("\n")
    if len(pc_lines) > MAX_SUBGRAPH_LINES * 3:
        pc_lines = pc_lines[:MAX_SUBGRAPH_LINES * 3]
        pc_lines.append(f"# ... (truncated, {len(pseudocode.split(chr(10)))} lines total)")
    context_parts.append("## 伪代码\n```\n" + "\n".join(pc_lines) + "\n```")

    context = "\n".join(context_parts)
    prompt = f"蓝图上下文：\n\n{context}\n\n问题：{question}"

    # 缓存
    mdl = model or DEFAULT_MODEL
    bp_id = graph_data.get("asset_path", "unknown")
    q_hash = hashlib.sha256(question.encode()).hexdigest()[:8]
    cache_path = _cache_key(bp_id, f"qa_{q_hash}", mdl, "answer")

    if use_cache:
        cached = _read_cache(cache_path)
        if cached is not None:
            return cached

    # 调用 LLM
    response = _call_llm(
        prompt, system=QA_SYSTEM_PROMPT,
        base_url=base_url, api_key=api_key, model=model,
    )

    if use_cache:
        _write_cache(cache_path, response)

    return response


# ============================================================================
# 增强伪代码 — 将摘要注回伪代码（5.1 补充）
# ============================================================================

def enhance_pseudocode(
    graph_data: dict,
    summaries: Optional[dict[str, str]] = None,
    use_cache: bool = True,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> str:
    """将 LLM 摘要注回伪代码，在 graph/function 行上方添加自然语言注释。

    Returns:
        增强后的伪代码字符串
    """
    from graph_to_pseudocode import graph_to_pseudocode

    pseudocode = graph_to_pseudocode(graph_data)

    if summaries is None:
        try:
            summaries = summarize_blueprint(
                graph_data, use_cache=use_cache,
                base_url=base_url, api_key=api_key, model=model,
            )
        except Exception:
            return pseudocode  # 摘要失败则返回原始伪代码

    if not summaries:
        return pseudocode

    # 在对应 graph/function 行上方插入摘要注释
    lines = pseudocode.split("\n")
    result_lines = []

    for line in lines:
        stripped = line.strip()

        # 匹配 "graph EventGraph" 或 "function TakeDamage"
        matched_name = None
        if stripped.startswith("graph "):
            matched_name = stripped.split("(")[0].strip() if "(" in stripped else stripped
        elif stripped.startswith("function "):
            matched_name = stripped.split("(")[0].strip() if "(" in stripped else stripped

        if matched_name and matched_name in summaries:
            indent = len(line) - len(line.lstrip())
            result_lines.append(" " * indent + f"# [摘要] {summaries[matched_name]}")

        result_lines.append(line)

    return "\n".join(result_lines)


# ============================================================================
# 按需子图提取（5.3 Token 效率优化）
# ============================================================================

def extract_subgraph_context(
    graph_data: dict,
    target_names: Optional[list[str]] = None,
    max_lines: int = 200,
) -> str:
    """只提取指定子图的伪代码上下文，降低 Token 消耗。

    Args:
        graph_data: 蓝图 JSON 数据
        target_names: 目标子图名列表（None = 全部）
        max_lines: 单个子图最大行数

    Returns:
        过滤后的伪代码字符串
    """
    from graph_to_pseudocode import graph_to_pseudocode

    pseudocode = graph_to_pseudocode(graph_data)

    if target_names is None:
        # 全部提取，但截断
        lines = pseudocode.split("\n")
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines.append(f"# ... (truncated, total {len(pseudocode.split(chr(10)))} lines)")
        return "\n".join(lines)

    sections = split_pseudocode_by_subgraph(pseudocode)
    result = []

    # 始终包含 header（蓝图名 + 变量声明）
    for s in sections:
        if s["type"] == "header":
            result.append(s["code"])

    # 只包含目标子图
    for s in sections:
        if s["type"] == "graph" and s["name"] in target_names:
            code_lines = s["code"].split("\n")
            if len(code_lines) > max_lines:
                code_lines = code_lines[:max_lines]
                code_lines.append(f"# ... (truncated, {len(s['code'].split(chr(10)))} lines total)")
            result.append("\n".join(code_lines))

    return "\n\n".join(result)


# ============================================================================
# CLI
# ============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Blueprint Semantic Enhancer — LLM-powered annotation and Q&A"
    )
    parser.add_argument("json_file", help="Path to blueprint JSON file")
    parser.add_argument(
        "--summarize", action="store_true",
        help="Generate sub-graph summaries"
    )
    parser.add_argument(
        "--enhance", action="store_true",
        help="Enhance pseudocode with LLM summaries (annotations)"
    )
    parser.add_argument(
        "--ask", type=str, default=None,
        help="Ask a question about the blueprint"
    )
    parser.add_argument(
        "--subgraph", type=str, nargs="*", default=None,
        help="Only extract specific sub-graphs (by name)"
    )
    parser.add_argument(
        "--no-cache", action="store_true",
        help="Disable caching"
    )
    parser.add_argument(
        "--base-url", type=str, default=None,
        help="OpenAI-compatible API base URL"
    )
    parser.add_argument(
        "--api-key", type=str, default=None,
        help="API key (or set OPENAI_API_KEY env)"
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help="Model name (default: gpt-4o-mini or SEMANTIC_ENHANCER_MODEL env)"
    )
    parser.add_argument(
        "--output", "-o", type=str, default=None,
        help="Output file path (default: stdout)"
    )

    args = parser.parse_args()

    if not args.summarize and not args.enhance and not args.ask and not args.subgraph:
        parser.print_help()
        print("\nError: specify at least one of --summarize, --enhance, --ask, or --subgraph")
        sys.exit(1)

    with open(args.json_file, "r", encoding="utf-8") as f:
        graph_data = json.load(f)

    use_cache = not args.no_cache
    output = None

    if args.subgraph is not None:
        output = extract_subgraph_context(
            graph_data, target_names=args.subgraph if args.subgraph else None
        )
    elif args.summarize:
        summaries = summarize_blueprint(
            graph_data, use_cache=use_cache,
            base_url=args.base_url, api_key=args.api_key, model=args.model,
        )
        lines = []
        for name, summary in summaries.items():
            lines.append(f"{name}: {summary}")
        output = "\n".join(lines) if lines else "(no graphs to summarize)"
    elif args.enhance:
        output = enhance_pseudocode(
            graph_data, use_cache=use_cache,
            base_url=args.base_url, api_key=args.api_key, model=args.model,
        )
    elif args.ask:
        output = ask_blueprint(
            graph_data, args.ask, use_cache=use_cache,
            base_url=args.base_url, api_key=args.api_key, model=args.model,
        )

    if args.output and output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Written to {args.output}")
    elif output:
        print(output)


if __name__ == "__main__":
    main()
