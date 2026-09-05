import { Loader2, RefreshCw, ShieldCheck } from "lucide-react";
import type {
  AsyncStatus,
  AutomationSettingsDraft,
  SettingsStatusLoadState,
} from "./settingsTypes";

type AutomationSettingsCardProps = {
  draft: AutomationSettingsDraft;
  saveStatus: AsyncStatus;
  settingsStatusLoadState: SettingsStatusLoadState;
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
    description: "后台记录慢记忆候选和证据；明确要求记住的低风险偏好或边界可激活，敏感或冲突内容会被拦截。",
  },
  {
    key: "local_privacy_mode",
    title: "本地隐私模式",
    description: "敏感输入只在本机处理，不发送到外部模型服务；语义检索使用随应用分发的本地模型。",
  },
  {
    key: "use_negotiation",
    title: "记忆检索有界复核",
    description: "记忆或资料检索请求最多复核两轮；普通聊天继续使用轻量主链。",
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
  return "日记可自动整理；慢记忆默认先记录候选和证据，高风险操作需要确认。";
}

export function AutomationSettingsCard({
  draft,
  saveStatus,
  settingsStatusLoadState,
  onUpdateDraft,
  onSave,
  onRefresh,
}: AutomationSettingsCardProps) {
  const saving = saveStatus === "loading";
  const settingsReady = settingsStatusLoadState === "ready";
  const loadingSettingsStatus = settingsStatusLoadState === "loading";
  const statusText = formatAutomationSaveStatus(saveStatus);

  return (
    <section className="agent-model-section settings-card automation-settings-card" aria-label="记忆整理和主动提醒">
      <div className="section-heading">
        <strong>记忆整理和主动提醒</strong>
        <span>控制低风险整理和低打扰主动开口；删除、移动、批量改写和保存位置变更仍必须确认。</span>
      </div>

      {settingsReady ? (
        <div className="automation-toggle-grid">
          {automationToggles.map((item) => (
            <label key={item.key} className="automation-toggle-row">
              <input
                type="checkbox"
                checked={draft[item.key] === true}
                onChange={(event) => onUpdateDraft({ [item.key]: event.target.checked })}
              />
              <span>
                <strong>{item.title}</strong>
                <small>{item.description}</small>
              </span>
            </label>
          ))}
        </div>
      ) : (
        <div className="settings-load-state" role={settingsStatusLoadState === "error" ? "alert" : "status"}>
          {loadingSettingsStatus ? "正在从本机服务读取设置..." : "尚未取得本机服务中的设置，编辑已停用。"}
        </div>
      )}

      {settingsReady && draft.max_rounds !== null ? (
        <label className="automation-locked-row" aria-label="证据复核轮次上限">
          <ShieldCheck size={16} />
          <span>
            <strong>证据复核轮次上限</strong>
            <small>每轮只执行一个只读检索步骤；达到上限或发生异常时立即结束。</small>
          </span>
          <input
            type="number"
            aria-label="证据复核轮次上限"
            min={2}
            max={10}
            step={1}
            value={draft.max_rounds}
            onChange={(event) => {
              const value = event.currentTarget.valueAsNumber;
              if (Number.isInteger(value) && value >= 2 && value <= 10) {
                onUpdateDraft({ max_rounds: value });
              }
            }}
          />
        </label>
      ) : null}

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
          <button type="button" onClick={onSave} disabled={saving || !settingsReady}>
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
