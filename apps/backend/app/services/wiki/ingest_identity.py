from __future__ import annotations

import json
from collections.abc import Sequence

from app.models.wiki import WikiIngestPagePlan, WikiIngestPreviewRequest
from app.utils.hash import sha256_hex


_INGEST_INTENT_SCHEMA_VERSION = "wiki-ingest-intent.v1"


def wiki_ingest_intent_key(
    request: WikiIngestPreviewRequest,
    page_plans: Sequence[WikiIngestPagePlan],
) -> str:
    request_payload = request.model_dump(mode="json")
    content = str(request_payload.pop("content"))
    plans = []
    for plan in page_plans:
        plan_payload = plan.model_dump(mode="json")
        plan_content = str(plan_payload.pop("content"))
        plans.append({**plan_payload, "content_sha256": sha256_hex(plan_content)})
    payload = {
        "schema_version": _INGEST_INTENT_SCHEMA_VERSION,
        "request": {
            **request_payload,
            "content_sha256": sha256_hex(content),
        },
        "page_plans": plans,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256_hex(canonical)
