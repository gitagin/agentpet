"""记忆 API：按域拆分的路由包（backlog #12，替代原 1600+ 行的 memory.py）。

拆分约束：
- 所有 URL 与端点函数名保持不变——openapi operationId、代理白名单契约测试
  （tests/test_renderer_allowlist_contract.py）与前端类型生成都锚定它们。
- 每个子模块自带 ``APIRouter(prefix="/memory", tags=["memory"])``，
  契约测试按文件独立解析 prefix，聚合路由本身不再加前缀。
"""

from __future__ import annotations

from fastapi import APIRouter

from ..wiring import memory_lifecycle_service
from . import diary, feedback, graph, maintenance, profile, proposals, search
from .shared import RAW_EVIDENCE_REDACTION_NOTE

router = APIRouter()
# 注册顺序沿用拆分前的端点声明顺序，避免任何路径匹配顺序差异。
router.include_router(search.router)
router.include_router(diary.router)
router.include_router(profile.router)
router.include_router(graph.router)
router.include_router(feedback.router)
router.include_router(maintenance.router)
router.include_router(proposals.router)

__all__ = ["RAW_EVIDENCE_REDACTION_NOTE", "memory_lifecycle_service", "router"]
