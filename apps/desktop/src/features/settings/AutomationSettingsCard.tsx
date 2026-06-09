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
  | "auto_wiki_organize"
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
    title: "Wiki 自动整理",
    description: "允许低风险资料库总结、补充和报告自动执行，并记录活动账本。",
  },
  {
    key: "use_negotiation",
    title: "多轮结果复核",
    description: "让复杂请求经过多轮检查和合成，再输出最终答案。",
  },
];

function formatAutomationSaveStatus(status: AsyncStatus): string {
  if (status === "loading") {
    return "正在保存自动整理策略。";
  }
  if (status === "success") {
    return "自动整理策略已保存。";
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
    <section className="agent-model-section settings-card automation-settings-card" aria-label="自动整理策略">
      <div className="section-heading">
        <strong>自动整理策略</strong>
        <span>控制低风险整理是否自动执行；删除、移动、批量改写和保存位置变更仍必须确认。</span>
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

      <label className="automation-number-field">
        <span>最大协商轮数</span>
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
          <small>强制开启，不可关闭。包括真实保存位置绑定、删除、移动、批量改写、SQLite schema 和高风险记忆合并。</small>
        </span>
        <b>强制开启</b>
      </div>

      <div className="settings-action-row">
        <div className="button-row">
          <button type="button" onClick={onSave} disabled={saving}>
            {saving ? <Loader2 className="spin" size={16} /> : <ShieldCheck size={16} />}
            保存策略
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
