"""FastAPI route modules."""
from fastapi import APIRouter, Depends

from ..auth import require_bearer_token
from . import agent, chat, continuity, diagnostics, memory, settings, tasks, vaults, wiki

api_router = APIRouter(prefix="/api", dependencies=[Depends(require_bearer_token)])
api_router.include_router(vaults.router)
api_router.include_router(agent.router)
api_router.include_router(memory.router)
api_router.include_router(tasks.router)
api_router.include_router(settings.router)
api_router.include_router(chat.router)
api_router.include_router(continuity.router)
api_router.include_router(diagnostics.router)
api_router.include_router(wiki.router)
