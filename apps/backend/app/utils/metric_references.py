from __future__ import annotations

import re


PUBLIC_REFERENCE_PATTERN = (
    r"^(?:answer[-_]|recall[-_]|claim_|candidate_|fact_|entity_|wiki_|source_|"
    r"reminder_|action_|lookup_|message_|run_|sidecar_|citation_)"
    r"[A-Za-z0-9][A-Za-z0-9._:-]{7,159}$"
)
_PUBLIC_REFERENCE_RE = re.compile(PUBLIC_REFERENCE_PATTERN)


def is_public_reference(value: object) -> bool:
    return bool(_PUBLIC_REFERENCE_RE.fullmatch(str(value or "").strip()))
