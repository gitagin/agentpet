"""保证 AGENTS.md 是唯一规则来源，contracts.py 与其一致，LLM 审查读它。"""
from __future__ import annotations

import re
from pathlib import Path

from app.services.wiki.contracts import PAGE_TYPE_CONTRACTS
from app.services.wiki.review import _review_system_prompt


def _schema_markdown() -> str:
    resource = Path(__file__).resolve().parents[1] / "app" / "resources" / "wiki" / "AGENTS.md"
    return resource.read_text(encoding="utf-8")


def _schema_page_types(markdown: str) -> set[str]:
    return set(re.findall(r"^###\s+(\w+)", markdown, flags=re.MULTILINE))


def test_page_type_contracts_mirror_agents_md() -> None:
    """contracts.py 的页面类型必须与 AGENTS.md 的页面类型一致，防止硬编码漂移。"""
    assert set(PAGE_TYPE_CONTRACTS) == _schema_page_types(_schema_markdown())


def test_review_prompt_includes_agents_md_schema() -> None:
    """LLM 审查 prompt 必须注入 AGENTS.md 内容，而不是盲审。"""
    schema = _schema_markdown()
    prompt = _review_system_prompt()
    assert "权威边界" in prompt
    assert "页面类型" in prompt
    # 注入的是真实规范内容（不只是路径/标题）
    assert schema.splitlines()[0] in prompt


def test_vault_schema_copy_tracks_canonical_resource(tmp_path) -> None:
    """Vault 内的 schema 副本必须跟随规范资源。

    既有 Vault 曾经永远停在旧版本：ensure_core_files 只做 write-if-missing，
    而本文件的一致性测试只校验规范资源，所以规范新增的安全约束（例如
    「助手摘要和问答报告不能独立支持其所述事实」）不会进入既有 Vault，且漂移
    无法被发现。
    """
    from app.services.memory import SafeMarkdownWriter
    from app.services.wiki import WikiService

    vault = tmp_path / "vault"
    (vault / "Wiki").mkdir(parents=True)
    safety_sentence = "助手摘要和问答报告不能独立支持其所述事实。"
    stale = _schema_markdown().replace(safety_sentence, "")
    (vault / "Wiki" / "AGENTS.md").write_text(stale, encoding="utf-8")

    service = WikiService(SafeMarkdownWriter(vault))
    service.ensure_core_files()

    copy = (vault / "Wiki" / "AGENTS.md").read_text(encoding="utf-8")
    assert safety_sentence in copy
    assert service.schema_drift is False

    # 再次同步保持幂等
    service.ensure_core_files()
    assert (vault / "Wiki" / "AGENTS.md").read_text(encoding="utf-8") == copy


def test_vault_schema_copy_preserves_user_edits_and_reports_drift(tmp_path) -> None:
    """用户改过的 Vault 副本不得被静默覆盖，但漂移必须可见。"""
    from app.services.memory import SafeMarkdownWriter
    from app.services.wiki import WikiService

    vault = tmp_path / "vault"
    service = WikiService(SafeMarkdownWriter(vault))
    service.ensure_core_files()
    path = vault / "Wiki" / "AGENTS.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n用户自定义补充\n", encoding="utf-8")

    service.ensure_core_files()

    assert "用户自定义补充" in path.read_text(encoding="utf-8")
    assert service.schema_drift is True
