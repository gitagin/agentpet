import { Loader2, RefreshCw, ShieldCheck } from "lucide-react";
import type { AsyncStatus, AutomationSettingsDraft } from "./settingsTypes";

type AutomationSettingsCardProps = {
  draft: AutomationSettingsDraft;
  saveStatus: AsyncStatus;
  loadingSettingsStatus: boolean;
  onUpdateDraft: (patch: Partial<AutomationSettingsDraft>) => void;
  onSave: () => void;
  onRefresh: () => void;
};

type AutomationToggleKey =
  | "auto_chat_diary"
  | "auto_structured_memory"
  | "auto_long_term_memory"
  | "local_privacy_mode"
  | "use_negotiation";

type AutomationToggle = {
  key: AutomationToggleKey;
  title: string;
  description: string;
};

const automationToggles: AutomationToggle[] = [
  {
    key: "auto_chat_diary",
    title: "日常聊天日记自动归档",
    description: "对话结束后自动写入每日聊天日记，形成可追溯的聊天记录。",
  },
  {
    key: "auto_structured_memory",
    title: "结构化日记自动提取",
    description: "从日常聊天中提取主题、情绪、人物和关键词，方便后续检索。",
  },
  {
    key: "auto_long_term_memory",
    title: "长期记忆自动沉淀",
    description: "低风险、高置信内容可自动进入长期记忆；敏感或冲突内容仍会拦截。",
  },
  {
    key: "local_privacy_mode",
    title: "本地隐私模式",
    description: "敏感输入只做本机关键词检索，不发送到外部模型服务；回复会更保守，智能程度会下降。",
  },
  {
    key: "use_negotiation",
    title: "复杂问题有界协作",
    description: "复杂请求最多复核两轮；超时、低置信或解析失败时回退到稳定主链。",
  },
];

function formatAutomationSaveStatus(status: AsyncStatus): string {
  if (status === "loading") {
    return "正在保存记忆整理设置。";
  }
  if (status === "success") {
    return "记忆整理设置已保存。";
  }
  if (status === "error") {
    return "保存失败，请检查后重试。";
  }
  return "低风险自动整理可自动执行；高风险操作始终需要确认。";
}

export function AutomationSettingsCard({
  draft,
  saveStatus,
  loadingSettingsStatus,
  onUpdateDraft,
  onSave,
  onRefresh,
}: AutomationSettingsCardProps) {
  const saving = saveStatus === "loading";
  const statusText = formatAutomationSaveStatus(saveStatus);

  return (
    <section className="agent-model-section settings-card automation-settings-card" aria-label="记忆整理和主动提醒">
      <div className="section-heading">
        <strong>记忆整理和主动提醒</strong>
        <span>控制低风险整理和低打扰主动开口；删除、移动、批量改写和保存位置变更仍必须确认。</span>
      </div>

      <div className="automation-toggle-grid">
        {automationToggles.map((item) => (
          <label key={item.key} className="automation-toggle-row">
            <input
              type="checkbox"
              checked={draft[item.key]}
              onChange={(event) => onUpdateDraft(
                item.key === "use_negotiation"
                  ? { use_negotiation: event.target.checked, max_rounds: 2 }
                  : { [item.key]: event.target.checked },
              )}
            />
            <span>
              <strong>{item.title}</strong>
              <small>{item.description}</small>
            </span>
          </label>
        ))}
      </div>

      <div className="automation-locked-row" aria-label="有界协作最多两轮">
        <ShieldCheck size={16} />
        <span>
          <strong>协作上限固定为 2 轮</strong>
          <small>最多调用两个子 Agent；达到上限或发生异常时立即结束，不允许无限循环。</small>
        </span>
        <b>最多 2 轮</b>
      </div>

      <div className="automation-locked-row" aria-label="高风险确认强制开启">
        <ShieldCheck size={16} />
        <span>
          <strong>高风险操作必须确认</strong>
          <small>强制开启，不可关闭。包括真实保存位置绑定、删除、移动、批量改写、底层数据结构和高风险记忆合并。</small>
        </span>
        <b>强制开启</b>
      </div>

      <div className="settings-action-row">
        <div className="button-row">
          <button type="button" onClick={onSave} disabled={saving}>
            {saving ? <Loader2 className="spin" size={16} /> : <ShieldCheck size={16} />}
            保存设置
          </button>
          <button
            type="button"
            className="secondary"
            onClick={onRefresh}
            disabled={loadingSettingsStatus || saving}
          >
            {loadingSettingsStatus ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
            刷新设置
          </button>
        </div>
        <p className={`field-note ${saveStatus === "error" ? "error" : ""}`}>{statusText}</p>
      </div>
    </section>
  );
}
