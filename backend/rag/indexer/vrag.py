import json
import os
from typing import Any, Dict, List

from dotenv import load_dotenv
from ollama import Client

load_dotenv()

_ollama_client = Client(
    host="https://ollama.com",
    headers={"Authorization": f"Bearer {os.environ.get('OLLAMA_API_KEY', '')}"},
)


def _extract_json(content: str) -> Any:
    if not content:
        return {}

    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return {}
        return {}


def _call_llm(
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.1,
    max_tokens: int = 700,
) -> str:
    """Call Ollama Cloud chat completion API.

    groq_client parameter is no longer used; we rely on a global Ollama client.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # The official ollama Python client ignores max_tokens for now but we keep
    # the argument for API compatibility and future control.
    response = _ollama_client.chat(model=model, messages=messages)

    # Newer versions return an object with .message; older may be dict.
    if hasattr(response, "message"):
        content = getattr(response.message, "content", "")
    else:
        content = response.get("message", {}).get("content", "")
    return (content or "").strip()


def _remove_fields(data: Any, fields: List[str]) -> Any:
    if isinstance(data, dict):
        return {k: _remove_fields(v, fields) for k, v in data.items() if k not in fields}
    if isinstance(data, list):
        return [_remove_fields(item, fields) for item in data]
    return data


def _create_node_mapping(tree: Any) -> Dict[str, Dict[str, Any]]:
    mapping: Dict[str, Dict[str, Any]] = {}

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return

        node_id = node.get("node_id")
        if node_id is not None:
            mapping[str(node_id)] = node

        children = node.get("nodes")
        if isinstance(children, list):
            for child in children:
                walk(child)

    walk(tree)
    return mapping


def _build_source(node: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "node_id": node.get("node_id"),
        "title": node.get("title", "Untitled"),
        "page_index": node.get("page_index"),
        "start_index": node.get("start_index"),
        "end_index": node.get("end_index"),
        "summary": node.get("summary"),
    }


def run_reasoning_rag(
    query: str,
    tree: Dict[str, Any],
    groq_client,
    model: str,
    top_n: int = 3,
    structured: bool = False,
) -> Dict[str, Any]:
    if not query.strip():
        raise ValueError("Query cannot be empty.")

    node_map = _create_node_mapping(tree)
    if not node_map:
        raise ValueError("No nodes found in tree response.")

    tree_without_text = _remove_fields(tree, fields=["text"])
    search_prompt = f"""
You are given a user question and a document tree.
Each tree node may include node_id, title, summary, and structure metadata.
Pick the most relevant node ids for answering the question.

Question: {query}

Tree:
{json.dumps(tree_without_text, ensure_ascii=False)}

Return strict JSON only:
{{
  "thinking": "brief reasoning",
  "node_list": ["id1", "id2"]
}}
"""

    search_raw = _call_llm(
        model=model,
        system_prompt="You perform retrieval planning and return strict JSON.",
        user_prompt=search_prompt,
        temperature=0,
        max_tokens=600,
    )
    search_json = _extract_json(search_raw)

    candidate_ids = [str(n) for n in search_json.get("node_list", []) if str(n) in node_map]
    if not candidate_ids:
        # Fallback to first N nodes if the model does not return valid JSON ids.
        candidate_ids = list(node_map.keys())[:top_n]

    candidate_ids = candidate_ids[:top_n]
    selected_nodes = [node_map[nid] for nid in candidate_ids]
    context_parts = []
    sources = []

    for idx, node in enumerate(selected_nodes, start=1):
        node_text = node.get("text", "")
        if not node_text:
            continue
        title = node.get("title", "Untitled")
        context_parts.append(f"[Node {idx} | {title} | id={node.get('node_id')}]\n{node_text}")
        sources.append(_build_source(node))

    if not context_parts:
        raise ValueError("Selected nodes do not contain text. Re-index with node text enabled.")

    answer_prompt = f"""
Answer the question using only the provided context.
If context is insufficient, say you do not have enough information.

Question: {query}

Context:
{'\n\n'.join(context_parts)}
"""

    answer = _call_llm(
        model=model,
        system_prompt="You are a precise compliance assistant grounded in provided context.",
        user_prompt=answer_prompt,
        temperature=0.1,
        max_tokens=900,
    )

    answer_structured: List[Dict[str, Any]] = []
    if structured:
        structured_prompt = f"""
Based on your previous analysis of the compliance question, extract all violations and remediation points as strict JSON format.

Original question: {query}
Your analysis: {answer}

Return ONLY valid JSON array with no other text:
[
  {{"ref": "specific clause/section number or guideline name", "explanation": "concise description of how/where violation occurs", "remediation": "one-word fix"}},
  ...
]

If no violations, return an empty array: []
"""
        structured_raw = _call_llm(
            model=model,
            system_prompt="Extract compliance violations as structured JSON array. Return only valid JSON, no markdown, no explanation.",
            user_prompt=structured_prompt,
            temperature=0.1,
            max_tokens=800,
        )
        structured_data = _extract_json(structured_raw)
        if isinstance(structured_data, list):
            answer_structured = structured_data
        elif isinstance(structured_data, dict):
            for key in ("violations", "results", "items"):
                value = structured_data.get(key)
                if isinstance(value, list):
                    answer_structured = value
                    break

    result = {
        "answer": answer,
        "sources": sources,
        "reasoning": search_json.get("thinking", ""),
    }

    if structured:
        result["answer_structured"] = answer_structured

    return result
