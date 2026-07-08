import { BellRing, Loader2, RefreshCw, ShieldCheck } from "lucide-react";
import type { AsyncStatus, AutomationSettingsDraft } from "./settingsTypes";
import type { ProactiveTriggerFrequency } from "../../types";

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
  | "auto_wiki_organize"
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
    key: "auto_wiki_organize",
    title: "资料页自动整理",
    description: "允许低风险资料总结、补充和报告自动执行，并记录可追溯活动。",
  },
  {
    key: "local_privacy_mode",
    title: "本地隐私模式",
    description: "敏感输入只做本机关键词检索，不发送到外部模型服务；回复会更保守，智能程度会下降。",
  },
  {
    key: "use_negotiation",
    title: "多轮结果复核",
    description: "让复杂请求经过多轮检查和合成，再输出最终答案。",
  },
];

const proactiveFrequencyOptions: Array<{
  value: ProactiveTriggerFrequency;
  label: string;
  description: string;
}> = [
  {
    value: "off",
    label: "关闭",
    description: "不主动开口。",
  },
  {
    value: "low",
    label: "低频",
    description: "低频每天最多 1 次，间隔至少 8 小时。",
  },
  {
    value: "normal",
    label: "中频",
    description: "中频每天最多 2 次，间隔至少 4 小时。",
  },
  {
    value: "high",
    label: "高频",
    description: "高频每天最多 3 次，间隔至少 2 小时。",
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
              onChange={(event) => onUpdateDraft({ [item.key]: event.target.checked })}
            />
            <span>
              <strong>{item.title}</strong>
              <small>{item.description}</small>
            </span>
          </label>
        ))}
      </div>

      <div className="automation-frequency-field" role="group" aria-label="日常主动开口">
        <div>
          <span>
            <BellRing size={16} />
            日常主动开口
          </span>
          <small>只在有待办、记忆、日记或资料线索时触发，并避开夜间与刚聊完的时段。</small>
        </div>
        <div className="automation-frequency-options">
          {proactiveFrequencyOptions.map((option) => (
            <label key={option.value} className="automation-frequency-option">
              <input
                type="radio"
                name="proactive_trigger_frequency"
                checked={draft.proactive_trigger_frequency === option.value}
                onChange={() => onUpdateDraft({ proactive_trigger_frequency: option.value })}
              />
              <span>{option.label}</span>
            </label>
          ))}
        </div>
        <small>{proactiveFrequencyOptions.find((option) => option.value === draft.proactive_trigger_frequency)?.description}</small>
      </div>

      <label className="automation-number-field">
        <span>复杂回答检查轮数</span>
        <input
          type="number"
          min={2}
          max={10}
          step={1}
          value={draft.max_rounds}
          onChange={(event) => {
            const value = Number.parseInt(event.target.value, 10);
            if (Number.isFinite(value)) {
              onUpdateDraft({ max_rounds: value });
            }
          }}
        />
      </label>

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
