import type { EmbeddingDraft, GlobalModelDraft } from "./settingsTypes";

// 草稿是用户的:服务端状态可以刷新,但不得覆盖用户还没保存的输入。
// 这里集中定义"哪些算未保存的输入",以及刷新时怎么合并——四张卡共用同一条规则,
// 免得每张卡各写一份比较(曾因此把密钥输入框清空)。

export function hasUnsavedGlobalModelDraft(draft: GlobalModelDraft): boolean {
  return (
    draft.provider.trim() !== draft.saved_provider ||
    draft.base_url.trim() !== draft.saved_base_url ||
    draft.model.trim() !== draft.saved_model ||
    Boolean(draft.api_key.trim())
  );
}

export function hasUnsavedEmbeddingDraft(draft: EmbeddingDraft): boolean {
  return (
    draft.base_url.trim() !== draft.saved_base_url ||
    draft.model.trim() !== draft.saved_model ||
    Boolean(draft.api_key.trim())
  );
}

export function mergeGlobalModelDraft(
  current: GlobalModelDraft,
  fromStatus: GlobalModelDraft,
): GlobalModelDraft {
  if (!hasUnsavedGlobalModelDraft(current)) {
    return fromStatus;
  }
  return {
    ...current,
    configured: fromStatus.configured,
    saved_provider: fromStatus.saved_provider,
    saved_base_url: fromStatus.saved_base_url,
    saved_model: fromStatus.saved_model,
  };
}

export function mergeEmbeddingDraft(current: EmbeddingDraft, fromStatus: EmbeddingDraft): EmbeddingDraft {
  if (!hasUnsavedEmbeddingDraft(current)) {
    return fromStatus;
  }
  return {
    ...current,
    configured: fromStatus.configured,
    saved_base_url: fromStatus.saved_base_url,
    saved_model: fromStatus.saved_model,
  };
}

/**
 * Keep a draft that differs from the last status the server reported.
 *
 * Drafts without saved-value mirrors (automation, TTS, negotiation) use the
 * previously loaded status as their baseline: equal means nothing unsaved, so
 * the fresh server value wins.
 */
export function keepUnsavedDraft<T extends object>(current: T, previous: T | null, fromStatus: T): T {
  if (previous === null || sameDraft(current, previous)) {
    return fromStatus;
  }
  return current;
}

function sameDraft(left: object, right: object): boolean {
  const keys = new Set([...Object.keys(left), ...Object.keys(right)]);
  return [...keys].every(
    (key) =>
      ((left as Record<string, unknown>)[key] ?? null) ===
      ((right as Record<string, unknown>)[key] ?? null),
  );
}
