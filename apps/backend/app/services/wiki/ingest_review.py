from .common import *
from .review import _complete_model, _deterministic_review_response, _parse_model_review, _review_system_prompt, _review_user_message


class WikiIngestReviewMixin:

    async def review_ingest(self, request: WikiIngestReviewRequest) -> WikiIngestReviewResponse:
        if not request.force_refresh:
            existing = self._latest_review(request.run_id, reviewer_agent_id=request.reviewer_agent_id)
            if existing is not None:
                return existing

        run = self._load_ingest_run(request.run_id)
        reviewer_agent_id, review_model = self._resolve_review_model(request.reviewer_agent_id)

        if review_model is None:
            response = _deterministic_review_response(
                run,
                reviewer_agent_id=reviewer_agent_id.value,
                status="model_not_configured",
                model_error="model_not_configured",
            )
            return self._insert_review(response)

        try:
            model_text = await _complete_model(
                review_model,
                user_message=_review_user_message(run),
                system_prompt=_review_system_prompt(),
            )
            response = _parse_model_review(
                model_text,
                run,
                reviewer_agent_id=reviewer_agent_id.value,
            )
        except ChatModelError as exc:
            response = _deterministic_review_response(
                run,
                reviewer_agent_id=reviewer_agent_id.value,
                status="failed",
                model_error=exc.code,
                summary=f"模型审查失败：{exc.code}。已保留确定性审查结果。",
            )
        except Exception as exc:
            response = _deterministic_review_response(
                run,
                reviewer_agent_id=reviewer_agent_id.value,
                status="failed",
                model_error=getattr(exc, "code", exc.__class__.__name__),
                summary="模型审查失败。已保留确定性审查结果。",
            )
        return self._insert_review(response)
