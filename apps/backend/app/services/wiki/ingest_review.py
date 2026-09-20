from .common import *
from .review import _complete_model, _deterministic_review_response, _parse_model_review, _review_system_prompt, _review_user_message


class WikiIngestReviewMixin:

    async def review_ingest(
        self,
        request: WikiIngestReviewRequest,
        *,
        review_id: str | None = None,
    ) -> WikiIngestReviewResponse:
        if not request.force_refresh:
            existing = self._latest_review(request.run_id, reviewer_agent_id=request.reviewer_agent_id)
            if existing is not None:
                return existing

        run = self._load_ingest_run(request.run_id)
        # draft 生命周期(D1):审查开始即 draft_reviewing(仅命中 draft run 时推进)
        self._mark_draft_status(request.run_id, "draft_reviewing")
        reviewer_agent_id, review_model = self._resolve_review_model(request.reviewer_agent_id)

        if review_model is None:
            response = _deterministic_review_response(
                run,
                reviewer_agent_id=reviewer_agent_id.value,
                status="model_not_configured",
                model_error="model_not_configured",
            )
            return self._insert_review(response, review_id=review_id)

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
        if response.status == "reviewed":
            # draft 生命周期(D1):审查通过 → draft_approved;失败/未配置模型保持 draft_reviewing 待重试
            self._mark_draft_status(request.run_id, "draft_approved")
        return self._insert_review(response, review_id=review_id)

    def _mark_draft_status(self, run_id: str, status: str) -> bool:
        """仅当该 run 存在 staged draft 时推进 result_json.publication.status,返回是否命中。"""
        with self.database.session() as conn:
            draft = conn.execute(
                """SELECT 1 FROM wiki_generations
                   WHERE workflow_run_id = ? AND status = 'staged'""",
                (run_id,),
            ).fetchone()
            if draft is None:
                return False
            conn.execute(
                """UPDATE wiki_workflow_runs
                   SET result_json = json_set(result_json, '$.publication.status', ?)
                   WHERE id = ?""",
                (status, run_id),
            )
            return True
