"""阶段 D 消融驱动(验收准则的取证入口):检索臂 × 候选准入语义。

**检索臂**(Qdrant 纪律「Confirm Fusion Beats Either Prefetch」):

- `bm25`    : 不注入嵌入器 —— 纯词法单路;
- `fusion`  : 词法 + 语义(本地 ONNX 嵌入)以既有 `reciprocal_rank_fusion` 融合;
- `semantic`: 只留语义通道(消融对照,用于证明融合**优于任一单路**)。

**候选分数语义**(score 缺陷修复的对照):

- `baseline`: 旧语义 `float(value or 1.0)` = 团队改动前的行为;
- `current` : 当前生产代码(0.0 不再被抬成默认;未知相关性显式;置换与准入同源三因子)。

注:动态相关性下限(截断)曾按 ratio 0.4 实施,但节点级实测使 Phase D 通过率从 45/48
降到 43/48(two_hop_001/003 的第二跳页被截断),按验收准则**已回退**;本驱动的
`admission` 开关保留 `baseline`/`current` 两档用于复现该结论。

用法:

    cd apps/backend
    $env:RRF_ARM='fusion'; $env:RRF_ADMISSION='current'; $env:RRF_OUT='fusion.json'
    .venv\Scripts\python.exe tests/phase_d_fusion_ablation.py

本模块不以 `test_` 开头,故 pytest 不会收集它;它只产出确定性指标 JSON。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

# 直接以脚本方式运行(`python tests/phase_d_fusion_ablation.py`)时,后端根目录不在
# sys.path 上,补一次以便 `app.*` 与 `tests.*` 都可导入。
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.agents.nodes import wiki_retrieval as node_module
from app.config import get_settings
from app.evals.phase_d_questions import DEFAULT_QUESTIONS_PATH, load_questions
from app.services.embeddings import build_local_onnx_embeddings
from tests.phase_d_corpus import build_corpus
from tests.phase_d_eval import run_question

# ---------------------------------------------------------------------------
# 产物归属（第九条）：把「不可变载荷」与「可变说明」显式拆开
#   payload_sha256     = 只对测量结果取规范化哈希（不可变）
#   attestation_sha256 = 对整个信封取哈希（可增补 provenance 而不动载荷）
# ---------------------------------------------------------------------------
_TREE_SCOPE_DIRS = ("app", "tests", "migrations")
_TREE_SCOPE_EXTS = {".py", ".json", ".sql"}
_TREE_SCOPE_NOTE = (
    "口径 = apps/backend/{app,tests,migrations} × {py,json,sql}，排除 __pycache__/.pytest_cache；"
    "**模型文件（models/**）与 app/resources/wiki/AGENTS.md 不在口径内**，故另在 model_inputs_sha256 单列。"
    "「口径相同」不等于「输入相同」。"
)


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _file_sha256(relative: str) -> str | None:
    path = _BACKEND_ROOT / relative
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _live_tree_sha256() -> tuple[str, int]:
    """按声明口径对活动树求树哈希。

    算法（显式写出，便于他人复算）：按相对路径排序后，逐行 "relpath|sha256"
    以 \n 拼接，再对该文本取 sha256。**与 scout 的 t18_freeze.ps1 算法可能不同**，
    故字段名为 live_tree_sha256（本驱动口径），不要与清单里的 TREE_SHA256 混用。
    """
    lines: list[str] = []
    for top in _TREE_SCOPE_DIRS:
        base = _BACKEND_ROOT / top
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in _TREE_SCOPE_EXTS:
                continue
            if "__pycache__" in path.parts or ".pytest_cache" in path.parts:
                continue
            rel = path.relative_to(_BACKEND_ROOT).as_posix()
            lines.append(f"{rel}|{hashlib.sha256(path.read_bytes()).hexdigest()}")
    blob = "\n".join(sorted(lines)).encode("utf-8")
    return hashlib.sha256(blob).hexdigest(), len(lines)


def _attestation_block(arm: str, admission: str) -> dict:
    tree_sha, tree_files = _live_tree_sha256()
    criterion = _file_sha256("tests/phase_d_eval.py")
    return {
        "arm": arm,
        "admission": admission,
        "criterion_version": f"phase_d_eval.py@{(criterion or '')[:16]}",
        "criterion_sha256": criterion,
        "driver_sha256": _file_sha256("tests/phase_d_fusion_ablation.py"),
        "corpus_builder_sha256": _file_sha256("tests/phase_d_corpus.py"),
        "fixture_full_sha256": _file_sha256("tests/fixtures/phase_d_questions.json"),
        "model_inputs_sha256": {
            rel: _file_sha256(rel)
            for rel in ("models/embedding/model.onnx", "models/embedding/tokenizer.json")
        },
        "live_tree_sha256": tree_sha,
        "live_tree_file_count": tree_files,
        "tree_sha256_scope_note": _TREE_SCOPE_NOTE,
    }


ARMS = ("bm25", "fusion", "semantic")
ADMISSION_SEMANTICS = ("baseline", "current")


@contextmanager
def admission_semantics(name: str):
    """把候选准入恢复/切换到指定语义(仅评测用,不改生产代码)。

    `baseline` 用 `_candidate_score` 的旧实现 `float(value or 1.0)` 精确复原「团队改动前」
    的分数语义;`current` 是当前生产代码(不 patch)。
    """
    if name not in ADMISSION_SEMANTICS:
        raise ValueError(f"unknown admission semantics: {name!r}")
    original_score = node_module._candidate_score
    if name == "baseline":
        node_module._candidate_score = lambda value: float(value or 1.0)
    try:
        yield
    finally:
        node_module._candidate_score = original_score


def semantic_only_patch(reader):
    """只保留语义通道:把词法候选池置空后再融合(消融对照,不改生产代码)。"""
    original = reader._fuse_semantic_channel

    def only_semantic(conn, pin, query, collected, limit):
        return original(conn, pin, query, {}, limit)

    reader._fuse_semantic_channel = only_semantic


def run_arm(
    arm: str, *, admission: str = "current", limit: int = 0, output: Path | None = None,
) -> dict:
    if arm not in ARMS:
        raise ValueError(f"unknown arm: {arm!r}")
    embedder = None
    patch = None
    if arm in {"fusion", "semantic"}:
        embedder = build_local_onnx_embeddings(get_settings().local_embedding_dir)
        if embedder is None:
            raise RuntimeError("local embedding model unavailable; arm needs an embedder")
    if arm == "semantic":
        patch = semantic_only_patch

    root = Path(tempfile.mkdtemp(prefix=f"phase_d_ablation_{arm}_"))
    document = load_questions()
    fingerprint = hashlib.sha256(Path(DEFAULT_QUESTIONS_PATH).read_bytes()).hexdigest()[:16]
    questions = document["quality"]
    if limit:
        questions = questions[:limit]
    by_fixture: dict[str, list] = {}
    for question in questions:
        by_fixture.setdefault(str(question["vault_fixture"]), []).append(question)

    outcomes = []
    started = time.time()
    with admission_semantics(admission):
        for fixture, group in by_fixture.items():
            corpus = build_corpus(fixture, root / fixture)
            for question in group:
                outcomes.append(run_question(
                    corpus, question, mode="new", semantic_embedder=embedder, reader_patch=patch,
                ))
    by_scenario: dict[str, list[int]] = {}
    for outcome in outcomes:
        bucket = by_scenario.setdefault(outcome.scenario, [0, 0])
        bucket[0] += int(outcome.passed)
        bucket[1] += 1
    summary = {
        "arm": arm,
        "admission": admission,
        "fixture_sha256": fingerprint,
        "questions": len(outcomes),
        "passed": sum(1 for outcome in outcomes if outcome.passed),
        "failures": [outcome.question_id for outcome in outcomes if not outcome.passed],
        "total_reads": sum(outcome.read_count for outcome in outcomes),
        "total_replaced": sum(outcome.replaced for outcome in outcomes),
        "mean_latency_ms": round(
            sum(outcome.latency_ms for outcome in outcomes) / max(1, len(outcomes))
        ),
        "by_scenario_pass": {key: f"{value[0]}/{value[1]}" for key, value in sorted(by_scenario.items())},
        "elapsed_s": round(time.time() - started, 1),
        "per_question": [
            {
                "id": outcome.question_id, "scenario": outcome.scenario, "passed": outcome.passed,
                "recall": outcome.citation_recall, "precision": outcome.citation_precision,
                "coverage": outcome.conclusion_coverage, "reads": outcome.read_count,
                "replaced": outcome.replaced, "latency_ms": outcome.latency_ms,
                "stop_reason": outcome.stop_reason, "cited": outcome.cited_paths,
            }
            for outcome in outcomes
        ],
    }
    # 载荷哈希必须在**加入 attestation 之前**算 —— 这样以后增补 provenance 不会改变它。
    payload_sha256 = _canonical_sha256(summary)
    attestation = _attestation_block(arm, admission)
    document = {
        **summary,
        "payload_sha256": payload_sha256,
        "attestation": attestation,
        "attestation_sha256": _canonical_sha256({**summary, "attestation": attestation}),
    }
    if output is not None:
        output.write_text(json.dumps(document, ensure_ascii=False, indent=1), encoding="utf-8")
    return document


def main() -> int:
    arm = os.environ.get("RRF_ARM", "bm25")
    admission = os.environ.get("RRF_ADMISSION", "current")
    output = Path(os.environ.get("RRF_OUT", f"phase_d_ablation_{arm}_{admission}.json"))
    limit = int(os.environ.get("RRF_LIMIT", "0"))
    summary = run_arm(arm, admission=admission, limit=limit, output=output)
    print("SUMMARY", json.dumps(
        {key: value for key, value in summary.items()
         if key not in ("per_question", "attestation")},
        ensure_ascii=False,
    ))
    print("WROTE", output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
