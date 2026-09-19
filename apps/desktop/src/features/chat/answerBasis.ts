import type { components } from "../../types.gen";

export type AnswerBasis = NonNullable<components["schemas"]["ChatDailyHistoryMessage"]["answer_basis"]>;

const LABELS: Record<AnswerBasis, string> = {
  not_assessed: "回答依据未评估",
  general_unverified: "通用回答 · 未据本地资料核验",
  local_evidence_context: "使用了本地证据上下文 · 不代表事实已证实",
  insufficient_local_evidence: "本地证据不足",
  validation_failed: "回答依据校验未通过",
};

export function normalizeAnswerBasis(value: unknown): AnswerBasis {
  return typeof value === "string" && Object.prototype.hasOwnProperty.call(LABELS, value)
    ? value as AnswerBasis
    : "not_assessed";
}

export function answerBasisLabel(value: unknown): string {
  return LABELS[normalizeAnswerBasis(value)];
}
