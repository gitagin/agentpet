from typing import Literal, get_args


# Describes available grounding, not factual truth or semantic completeness.
AnswerBasis = Literal[
    "not_assessed",
    "general_unverified",
    "local_evidence_context",
    "insufficient_local_evidence",
    "validation_failed",
]


def normalize_answer_basis(value: object) -> AnswerBasis:
    return value if isinstance(value, str) and value in get_args(AnswerBasis) else "not_assessed"
