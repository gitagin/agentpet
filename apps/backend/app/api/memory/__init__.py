"""记忆 API：按领域组织的路由包。

拆分约束：
- 所有 URL 与端点函数名保持稳定，OpenAPI operationId、代理白名单与前端类型生成都锚定它们。
- 每个子模块自带 ``APIRouter(prefix="/memory", tags=["memory"])``，
  聚合路由本身不再重复添加前缀。
"""

from __future__ import annotations

from fastapi import APIRouter

from ..wiring import memory_lifecycle_service
from . import diary, feedback, graph, maintenance, proposals, search

router = APIRouter()
# 注册顺序沿用拆分前的端点声明顺序，避免任何路径匹配顺序差异。
router.include_router(search.router)
router.include_router(diary.router)
router.include_router(graph.router)
router.include_router(feedback.router)
router.include_router(maintenance.router)
router.include_router(proposals.router)

__all__ = ["memory_lifecycle_service", "router"]
