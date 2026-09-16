"""检索调参测量脚本(第一轮→第二轮):验证聊天日记回声降权 + 连续性守卫。

用法(在项目根、已安装后端的环境中):
    python scripts/tune-retrieval-params.py

第一轮结论:在真实语料的自然语句查询上,rrf_k(30/60/90)与 FTS 精确权重
(1.5-4.0)全部平手——精确权重门只对"精确词/标识符"查询开启,自然语句
不进该分支;rrf_k 在通道结果离散时只是整体缩放。真正的排序问题是聊天
日记回声(逐字回放旧提问)霸占榜首。

第二轮:扫描 AGENT_PET_TUNING_DAILY_ECHO_WEIGHT,同时加入"连续性"查询
(答案只在日记里)作为守卫,验证降权不会弄丢"我上次问过什么"的召回。
指标:diary#1(回声霸榜数,应下降)、visible@5(答案词可见,应持平)、
continuity hit(守卫,必须保持 1.0)。

第三轮:把默认值 0.6 放进网格(此前网格是 1.0/0.7/0.5/0.3,不含被写进
config 注释的那个值)。结果:1.0/0.7/0.6/0.5 完全同分(visible@5 0.92、
hit@5 1.00、diary#1 4、cont@5 1.00),0.3 开始伤连续性(cont@5 0.00、
hit@5 0.92、visible@5 0.85)。排序指标看不出降权的收益。

第四轮(回答层面):排序指标看不见的东西,在"模型最终被喂到什么作为答案上下文"
这一层能看见。走真实链路(证据门 → 引用 → split_recall_prompt_sections 的
used_for_answer_context),并跟踪"被回放的那一条日记块":
  - 有上一轮(逐字回放)时,最近轮次规则把它从 13 条降到 5 条(权重 1.0)/ 7 降到 1(0.6);
  - 没有上一轮时,降权本身把日记答案上下文从 13 条降到 7(0.6)、0(0.3);
  - 0.3 同时把知识上下文从 13 降到 12、连续性守卫从 1.00 掉到 0.00。
结论:0.6 的正当理由不是"排名更好",而是"日记回声的注入面减半、而知识与连续性
不受影响";真正逐字剔除回声的是最近轮次规则,降权是它之外的第二道(不加区分)。
"""

from __future__ import annotations

import os
import re
import tempfile
import time
from pathlib import Path

VAULT_PATH = Path(r"E:\agentproject\vault")

# (查询, 期望文件, 答案锚词, 类别)。期望文件以 "/" 结尾表示前缀匹配。
LABELED_QUERIES = [
    ("黑色修士", "酒馆/卡.md", "黑色修士", "direct"),
    ("给我黑色修士酒馆卡的访问链接", "酒馆/卡.md", "黑色修士", "echo"),
    ("无眠旅馆", "酒馆/卡.md", "无眠旅馆", "direct"),
    ("世界书里有什么", "酒馆/世界书.md", "世界书", "direct"),
    ("真实动态感官", "酒馆/世界书.md", "真实动态感官", "direct"),
    ("酒馆插件", "酒馆/插件.md", "插件", "direct"),
    ("露出", "酒馆/卡.md", "露出", "ambiguous"),
    ("墨墨", "酒馆/卡.md", "墨墨", "ambiguous"),
    ("状态栏", "酒馆/世界书.md", "状态栏", "ambiguous"),
    ("找ntr类的卡", "酒馆/卡.md", "ntr", "hard"),
    ("帮我找写卡的资料", "酒馆/制卡工具.md", "写卡", "hard"),
    ("上次问过黑色修士,这次给我无眠旅馆的链接", "酒馆/卡.md", "无眠旅馆", "echo-mixed"),
    # 守卫:答案只存在于聊天日记(前缀匹配当日日记文件),降权不得伤到它。
    ("我上次问过黑色修士的什么问题", "Memories/Daily/", "黑色修士", "continuity"),
]

NEGATIVE_ANCHOR = "zzq不存在的卡"

ECHO_WEIGHT_GRID = (1.0, 0.7, 0.6, 0.5, 0.3)
SLICE_KS = (3, 4, 5, 6, 8)
FULL_K = 10

DAILY_DIARY_PREFIX = "Memories/Daily/"


def _path_matches(path: str, expected: str) -> bool:
    if expected.endswith("/"):
        return path.startswith(expected)
    return path == expected


def _combo_metrics(results_by_query: dict) -> dict[str, float]:
    hit = {k: [] for k in SLICE_KS}
    visible = {k: [] for k in SLICE_KS}
    reciprocal_ranks = []
    diary_top_count = 0
    continuity_hit = []
    for (query, expected, anchor, kind), rows in results_by_query.items():
        first_rank = next((i for i, row in enumerate(rows) if _path_matches(row["path"], expected)), None)
        if first_rank is not None:
            reciprocal_ranks.append(1.0 / (first_rank + 1))
        if rows and rows[0]["path"].startswith(DAILY_DIARY_PREFIX):
            diary_top_count += 1
        for k in SLICE_KS:
            head = rows[:k]
            hit[k].append(1.0 if any(_path_matches(row["path"], expected) for row in head) else 0.0)
            visible[k].append(1.0 if any(anchor in row["snippet"] for row in head) else 0.0)
        if kind == "continuity":
            continuity_hit.append(1.0 if any(_path_matches(row["path"], expected) for row in rows[:5]) else 0.0)
    return {
        **{f"hit@{k}": sum(hit[k]) / len(hit[k]) for k in SLICE_KS},
        **{f"visible@{k}": sum(visible[k]) / len(visible[k]) for k in SLICE_KS},
        "mrr": sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0,
        "diary_top_count": float(diary_top_count),
        "continuity_hit@5": sum(continuity_hit) / len(continuity_hit) if continuity_hit else 0.0,
    }


def _setup_app():
    os.environ["AGENT_PET_SESSION_TOKEN"] = "tune-token"
    os.environ["AGENT_PET_ALLOW_INSECURE_FILE_CREDENTIALS"] = "1"
    tmp = Path(tempfile.mkdtemp(prefix="agentpet-tune-"))
    os.environ["AGENT_PET_DATA_DIR"] = str(tmp / "data")
    os.environ["AGENT_PET_SQLITE_PATH"] = str(tmp / "state.sqlite3")

    from fastapi.testclient import TestClient

    from app.main import create_app

    client = TestClient(create_app(), raise_server_exceptions=False)
    headers = {"Authorization": "Bearer tune-token"}
    init = client.post(
        "/api/vaults/init",
        headers=headers,
        json={"path": str(VAULT_PATH), "create_if_missing": False, "confirmed": True},
    )
    assert init.status_code == 200, init.text
    vault_id = init.json()["vault_id"]
    index = client.post(f"/api/vaults/{vault_id}/index", headers=headers)
    assert index.status_code == 200, index.text
    return client, vault_id


def _wait_vector_ready(service, vault_id: str, timeout_seconds: float = 90.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            response = service.search(
                query="黑色修士", top_k=5, mode="hybrid", source_scope="all", vault_id=vault_id
            )
        except Exception:
            time.sleep(2.0)
            continue
        if any(result.retrieval_mode == "vector" for result in response.results):
            return True
        time.sleep(2.0)
    return False


def _run_combo(service, vault_id: str, echo_weight: float) -> dict[str, float]:
    from app.config import get_settings

    os.environ["AGENT_PET_TUNING_DAILY_ECHO_WEIGHT"] = str(echo_weight)
    get_settings.cache_clear()
    settings = get_settings()
    assert abs(settings.tuning_daily_echo_weight - echo_weight) < 1e-9
    # 缓存键已包含调参项(本轮修复),清理仅为防御。
    service._cache.clear()

    results_by_query = {}
    for query, expected, anchor, kind in LABELED_QUERIES:
        response = service.search(
            query=query, top_k=FULL_K, mode="hybrid", source_scope="all", vault_id=vault_id
        )
        results_by_query[(query, expected, anchor, kind)] = [
            {"path": result.relative_path, "snippet": result.snippet} for result in response.results
        ]
    negative = service.search(
        query=NEGATIVE_ANCHOR, top_k=FULL_K, mode="hybrid", source_scope="all", vault_id=vault_id
    )
    noise_leaked = any(NEGATIVE_ANCHOR in result.snippet for result in negative.results)

    metrics = _combo_metrics(results_by_query)
    metrics["negative_anchor_leaked"] = 1.0 if noise_leaked else 0.0
    return metrics


def _answer_context_probe(
    service,
    vault_id: str,
    echo_weight: float,
    *,
    with_recent_turns: bool,
) -> dict[str, object]:
    """从一个标注查询集里统计"模型最终被喂到什么作为答案上下文"。

    排序指标看不出回声降权的收益(见文件头的第三轮结论),所以这里换到回答层面,
    走真实链路:
      gate_evidence + _emit_tool_results  → 引用集合
      split_recall_prompt_sections        → 提示词真正使用的答案上下文门

    with_recent_turns=True 时,把日记里那条逐字回放的"用户问题"当成上一轮,复现
    线上"同一段对话既进历史又作为证据回来"的形态。
    """
    from app.agents.events_helpers import MIN_RECENT_TURN_ECHO_CHARS, _emit_tool_results
    from app.agents.state import AgentState
    from app.agents.tools import AgentToolResult
    from app.config import get_settings
    from app.services.memory_permissions import split_recall_prompt_sections
    from app.services.prompt_context_types import PromptRecentTurn

    os.environ["AGENT_PET_TUNING_DAILY_ECHO_WEIGHT"] = str(echo_weight)
    get_settings.cache_clear()
    service._cache.clear()

    counters = {
        "diary_rank1": 0,
        "echo_cases": 0,
        "echo_with_question": 0,
        "echo_cited": 0,
        "echo_in_context": 0,
        "knowledge_in_context": 0,
    }
    context_leaks: list[str] = []
    for query, expected, _anchor, _kind in LABELED_QUERIES:
        response = service.search(
            query=query, top_k=FULL_K, mode="hybrid", source_scope="all", vault_id=vault_id
        )
        results = list(response.results)
        if results and results[0].source_scope == "daily_chat":
            counters["diary_rank1"] += 1

        # 只跟踪"被回放的那一条"日记块:粗粒度的"引用里有没有日记"分不清
        # "回放本身活下来了"和"别的日记块还在"。
        echo_chunk_id = None
        echo_snippet = ""
        for result in results:
            if result.source_scope != "daily_chat":
                continue
            echo_chunk_id = result.chunk_id
            echo_snippet = result.snippet
            break
        if echo_chunk_id is not None:
            counters["echo_cases"] += 1
        echoed = _echoed_question(echo_snippet) if with_recent_turns else None
        if echoed:
            counters["echo_with_question"] += 1
        recent_turns = [PromptRecentTurn(role="user", content=echoed)] if echoed else []

        state = AgentState(
            conversation_id="tuning-probe",
            message_id="tuning-probe",
            agent_run_id="tuning-probe",
            user_message=query,
        )
        state.recent_turns = recent_turns
        _emit_tool_results(
            {"agent_state": state, "events": []},
            [AgentToolResult(name="search_memory", value=response)],
        )
        if any(citation.chunk_id == echo_chunk_id for citation in state.citations):
            counters["echo_cited"] += 1

        # 提示词拿到的是门后的引用,不是原始结果:答案上下文必须在引用集合上判定,
        # 否则会量到一条线上并不存在的通路。
        sections = split_recall_prompt_sections(state.citations, query=query)
        answer_context = [usage.result for usage in sections.usages if usage.used_for_answer_context]
        if any(result.chunk_id == echo_chunk_id for result in answer_context):
            counters["echo_in_context"] += 1
            if with_recent_turns:
                collapsed_snippet = " ".join(echo_snippet.split())
                collapsed_turn = " ".join((echoed or "").split())
                context_leaks.append(
                    {
                        "query": query,
                        "turn_in_snippet": bool(collapsed_turn) and collapsed_turn in collapsed_snippet,
                        "turn_too_short": 0 < len(collapsed_turn) < MIN_RECENT_TURN_ECHO_CHARS,
                        "snippet": collapsed_snippet[:120],
                    }
                )
        if any(_path_matches(result.relative_path, expected) for result in answer_context):
            counters["knowledge_in_context"] += 1

    counters["leaked_queries"] = context_leaks
    return counters


def _echoed_question(snippet: str) -> str | None:
    """片段里的"用户问题：…"——把它当作上一轮,构造逐字回放。

    只看被跟踪的那一块,保证"设的上一轮"和"要剔除的回声"是同一块。
    """
    match = re.search(r"用户问题：(.+?)\s*-\s*桌宠回答：", snippet)
    return match.group(1).strip() if match else None


def main() -> int:
    client, vault_id = _setup_app()
    service = client.app.state.retrieval_service
    vector_ready = _wait_vector_ready(service, vault_id)
    print(f"vector channel ready: {vector_ready}")
    print(f"labeled queries: {len(LABELED_QUERIES)}")

    rows = []
    for echo_weight in ECHO_WEIGHT_GRID:
        rows.append((echo_weight, _run_combo(service, vault_id, echo_weight)))

    header = (
        f"{'echo_w':>6} | "
        + " | ".join(f"{f'visible@{k}':>9}" for k in SLICE_KS)
        + f" | {'hit@5':>5} {'mrr':>5} {'diary#1':>7} {'cont@5':>5} {'noise':>5}"
    )
    print(header)
    print("-" * len(header))
    for echo_weight, metrics in rows:
        line = (
            f"{echo_weight:>6} | "
            + " | ".join(f"{metrics[f'visible@{k}']:>9.2f}" for k in SLICE_KS)
            + f" | {metrics['hit@5']:>5.2f} {metrics['mrr']:>5.2f}"
            + f" {metrics['diary_top_count']:>7.0f} {metrics['continuity_hit@5']:>5.2f}"
            + f" {metrics['negative_anchor_leaked']:>5.0f}"
        )
        print(line)

    print("\n回答层面(真实链路:证据门 → 引用 → 提示词答案上下文)")
    probes = [
        (weight, with_recent_turns)
        for weight in (1.0, 0.6, 0.3)
        for with_recent_turns in (False, True)
    ]
    addressed = {}
    for weight, with_recent_turns in probes:
        addressed[(weight, with_recent_turns)] = _answer_context_probe(
            service,
            vault_id,
            weight,
            with_recent_turns=with_recent_turns,
        )
    answer_header = (
        f"{'echo_w':>6} {'上轮':>4} | {'diary#1':>7} {'有回放':>6} {'可构造':>6} | "
        f"{'回声被引用':>10} {'回声进上下文':>12} {'知识进上下文':>12}"
    )
    print(answer_header)
    print("-" * len(answer_header))
    for weight, with_recent_turns in probes:
        probe = addressed[(weight, with_recent_turns)]
        print(
            f"{weight:>6} {('有' if with_recent_turns else '无'):>4} | "
            f"{probe['diary_rank1']:>7} {probe['echo_cases']:>6} {probe['echo_with_question']:>6} | "
            f"{probe['echo_cited']:>10} {probe['echo_in_context']:>12} "
            f"{probe['knowledge_in_context']:>12}"
        )
    from app.agents.events_helpers import MIN_RECENT_TURN_ECHO_CHARS

    for weight, with_recent_turns in probes:
        if not with_recent_turns:
            continue
        probe = addressed[(weight, with_recent_turns)]
        for leak in probe["leaked_queries"]:
            if leak["turn_too_short"]:
                verdict = f"短轮次按设计豁免(<{MIN_RECENT_TURN_ECHO_CHARS} 字符)"
            elif leak["turn_in_snippet"]:
                verdict = "逐字在片段里却没被剔除(规则漏了)"
            else:
                verdict = "片段不含该轮原话(相似但非回声)"
            print(f"  漏过({weight}): {leak['query']} —— {verdict}")
            print(f"      {leak['snippet']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
