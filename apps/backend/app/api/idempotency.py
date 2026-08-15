from typing import Annotated

from fastapi import Header

from ..utils.idempotency import IDEMPOTENCY_KEY_PATTERN


IdempotencyKeyHeader = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=64,
        max_length=64,
        pattern=IDEMPOTENCY_KEY_PATTERN.pattern,
        description="Stable identifier for one local write intent. Retries must reuse the same value.",
    ),
]
