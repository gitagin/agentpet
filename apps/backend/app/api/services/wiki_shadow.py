"""App-owned scheduling for opt-in, disposable Wiki query evaluations."""

import asyncio
import logging

from app.agents.services import AgentRuntimeServices
from app.agents.state import AgentState
from app.models.enums import AgentId
from app.services.chat_model import AgentModelRegistry
from app.services.wiki.shadow import ShadowMetricStore, WikiShadowEvaluator, shadow_eligible

from .factory import active_vault_id, database, settings_store


logger = logging.getLogger(__name__)


class WikiShadowRuntime:
    def __init__(self, context):
        self.context = context
        self.evaluator = WikiShadowEvaluator(ShadowMetricStore(database(context)))
        self._foreground = 0
        self._task = None
        self._cancel_requested = False
        self._closed = False

    def _scope(self):
        store = settings_store(self.context)
        try:
            settings = store.get_automation_settings()
            if not settings.wiki_shadow_enabled or settings.local_privacy_mode:
                return None
            # Configuration changes revoke use of clients created before the change.
            revisions = tuple(
                tuple(tuple(row) for row in store.conn.execute(f"SELECT * FROM {table} ORDER BY 1"))
                for table in ("model_config", "model_keys", "agent_model_configs")
            )
            return active_vault_id(self.context), revisions
        finally:
            store.close()

    def preempt(self):
        if self._task and not self._task.done() and not self._cancel_requested:
            self._cancel_requested = True
            self._task.cancel()

    def foreground_started(self):
        self._foreground += 1
        self.preempt()
        try:
            return self._scope()
        except Exception:
            return None

    def _permitted(self, scope):
        if self._closed or self._foreground or scope is None:
            return False
        app_state = self.context.app.state
        with app_state.chat_runs_lock:
            if app_state.chat_runs:
                return False
        try:
            return self._scope() == scope
        except Exception:
            return False

    def foreground_finished(self, completed_state, scope):
        self._foreground = max(0, self._foreground - 1)
        if (
            completed_state is None
            or not shadow_eligible(completed_state, enabled=scope is not None)
            or (self._task is not None and not self._task.done())
            or not self._permitted(scope)
        ):
            return
        # Keep only the input necessary for the isolated reader, not the answer.
        candidate = AgentState(
            conversation_id="shadow", message_id="shadow",
            agent_run_id=completed_state.agent_run_id,
            user_message=completed_state.user_message,
            semantic_analysis=completed_state.semantic_analysis.model_copy(deep=True),
        )
        self._cancel_requested = False
        self._task = asyncio.create_task(self._run(candidate, scope, len(completed_state.citations)))
        self._task.add_done_callback(self._finished)

    def _services(self):
        from .adapters import RuntimeRetrievalAdapter, RuntimeWikiReadAdapter
        from .factory import chat_model_client

        model = chat_model_client(self.context, AgentId.RETRIEVAL_AGENT.value)
        return AgentRuntimeServices(
            wiki_reader=RuntimeWikiReadAdapter(self.context),
            retrieval=RuntimeRetrievalAdapter(self.context),
            model_registry=AgentModelRegistry(
                clients={AgentId.RETRIEVAL_AGENT: model} if model is not None else {},
            ),
        )

    async def _run(self, candidate, scope, old_citation_count):
        # A foreground request arriving immediately after completion wins.
        await asyncio.sleep(0)
        if not self._permitted(scope):
            return
        await self.evaluator.evaluate(
            candidate, self._services(), permitted=lambda: self._permitted(scope),
            old_citation_count=old_citation_count,
        )

    def _finished(self, task):
        if self._task is task:
            self._task = None
        if not task.cancelled() and task.exception() is not None:
            logger.warning("Wiki Shadow evaluation failed; foreground reply is unchanged")

    async def shutdown(self):
        self._closed = True
        self.preempt()
        task = self._task
        if task:
            await asyncio.gather(task, return_exceptions=True)
