from __future__ import annotations

from app.models.enums import AgentId
from app.services.wiki import WikiService
from app.storage.database import Database

from .common import ReviewModelResolver, WikiReviewModelProtocol
from .ingest import WikiIngestWorkflowMixin
from .metadata import WikiMetadataWorkflowMixin
from .query import WikiQueryWorkflowMixin
from .synthesis import WikiSynthesisWorkflowMixin


class WikiWorkflowService(
    WikiIngestWorkflowMixin,
    WikiQueryWorkflowMixin,
    WikiSynthesisWorkflowMixin,
    WikiMetadataWorkflowMixin,
):
    def __init__(
        self,
        database: Database,
        wiki: WikiService,
        *,
        review_model: WikiReviewModelProtocol | None = None,
        review_agent_id: AgentId | str | None = None,
        review_model_resolver: ReviewModelResolver | None = None,
    ) -> None:
        self.database = database
        self.wiki = wiki
        self.review_model = review_model
        self.review_agent_id = AgentId(review_agent_id or AgentId.ACTION_AGENT)
        self.review_model_resolver = review_model_resolver
