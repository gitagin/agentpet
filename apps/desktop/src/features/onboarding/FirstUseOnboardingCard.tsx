import { Loader2, Send } from "lucide-react";
import type { FormEvent } from "react";

export type FirstUseOnboardingDraft = {
  currentFocus: string;
  preferredName: string;
  longTermContext: string;
  savePreference: string;
};

type FirstUseOnboardingCardProps = FirstUseOnboardingDraft & {
  connected: boolean;
  streaming: boolean;
  submitting: boolean;
  onCurrentFocusChange: (value: string) => void;
  onPreferredNameChange: (value: string) => void;
  onLongTermContextChange: (value: string) => void;
  onSavePreferenceChange: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
  onSkip: () => void;
};

export function buildFirstUseOnboardingMessage(draft: FirstUseOnboardingDraft): string | null {
  const currentFocus = draft.currentFocus.trim();
  const preferredName = draft.preferredName.trim();
  const longTermContext = draft.longTermContext.trim();
  const savePreference = draft.savePreference.trim();
  if (!currentFocus) {
    return null;
  }
  return [
    "这是我的首次使用引导回答。请先自然回应用户，接住用户今天想继续的事，不要先要求配置系统。",
    "记忆边界：只沉淀高价值、非敏感、可复用的长期记忆；低置信、敏感或关系身份类内容必须等待用户确认或跳过；不要编造或确认用户没有明确表达的内容。",
    "",
    `今天想让我从哪里陪你继续：${currentFocus}`,
    `希望我怎么称呼你：${preferredName || "未填写"}`,
    `以后希望我多留意什么：${longTermContext || "未填写"}`,
    `记忆保存偏好：${savePreference || "未填写"}`,
  ].join("\n");
}

export function FirstUseOnboardingCard({
  currentFocus,
  preferredName,
  longTermContext,
  savePreference,
  connected,
  streaming,
  submitting,
  onCurrentFocusChange,
  onPreferredNameChange,
  onLongTermContextChange,
  onSavePreferenceChange,
  onSubmit,
  onSkip,
}: FirstUseOnboardingCardProps) {
  const hasRequiredAnswer = Boolean(currentFocus.trim());
  return (
    <section className="first-use-onboarding" aria-label="首次使用引导">
      <div className="section-heading">
        <strong>今天想让我从哪里陪你继续？</strong>
        <span>先告诉我一句现在最想接上的事；称呼、长期留意内容和记忆偏好都可以之后再补。</span>
      </div>
      <form className="first-use-onboarding-form" onSubmit={onSubmit}>
        <label>
          <span>今天想让我从哪里陪你继续？</span>
          <textarea
            rows={2}
            value={currentFocus}
            onChange={(event) => onCurrentFocusChange(event.target.value)}
            placeholder="例如：我今天有点累，想把昨天没说完的事接上"
            required
            disabled={submitting || streaming}
          />
        </label>
        <details className="first-use-onboarding-extra">
          <summary>可选补充</summary>
          <label>
            <span>怎么称呼你（可选）</span>
            <textarea
              rows={1}
              value={preferredName}
              onChange={(event) => onPreferredNameChange(event.target.value)}
              placeholder="例如：叫我小林"
              disabled={submitting || streaming}
            />
          </label>
          <label>
            <span>以后希望我多留意什么（可选）</span>
            <textarea
              rows={2}
              value={longTermContext}
              onChange={(event) => onLongTermContextChange(event.target.value)}
              placeholder="例如：重要承诺、长期目标、容易忘的偏好"
              disabled={submitting || streaming}
            />
          </label>
          <label>
            <span>记忆保存偏好（可选）</span>
            <textarea
              rows={2}
              value={savePreference}
              onChange={(event) => onSavePreferenceChange(event.target.value)}
              placeholder="例如：先留在本机，以后需要时再调整"
              disabled={submitting || streaming}
            />
          </label>
        </details>
        <div className="button-row">
          <button type="submit" disabled={!connected || streaming || submitting || !hasRequiredAnswer}>
            {submitting ? <Loader2 className="spin" size={16} /> : <Send size={16} />}
            {submitting ? "正在开始" : "开始第一次聊天"}
          </button>
          <button type="button" className="secondary" onClick={onSkip} disabled={submitting || streaming}>
            跳过
          </button>
        </div>
        <p className="field-note">
          记下的内容之后可以在记忆里查看和撤回；敏感、不确定或关系身份类内容会先确认或跳过。
        </p>
      </form>
    </section>
  );
}
