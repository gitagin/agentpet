import { Archive, Check, ChevronRight, ExternalLink, FileText, GitBranch, ShieldAlert, Undo2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type {
  MemoryGraphActionRequest,
  MemoryGraphActionResponse,
  MemoryGraphClaimDetail,
  MemoryGraphEdgeDetail,
  MemoryGraphNodeDetail,
} from "../../types";
import type { MemoryGraphEdgeItem, MemoryGraphNodeItem } from "./useMemoryGraphWorkspace";

type MemoryEvidenceRailProps = {
  node: MemoryGraphNodeItem | null;
  edge: MemoryGraphEdgeItem | null;
  nodeDetail: MemoryGraphNodeDetail | null;
  edgeDetail: MemoryGraphEdgeDetail | null;
  claimDetail: MemoryGraphClaimDetail | null;
  endpointDetails: Record<string, MemoryGraphNodeDetail>;
  loading: boolean;
  error: string;
  actionBusy: boolean;
  actionError: string;
  actionMessage: string;
  onClose: () => void;
  onApplyAction: (request: MemoryGraphActionRequest) => Promise<MemoryGraphActionResponse | null>;
  onOpenSource: (relativePath: string) => void;
};

const relationLabels: Record<string, string> = {
  prefers: "偏好",
  avoids: "避免",
  works_on: "正在做",
  knows: "了解",
  related_to: "关联",
  occurred_in: "发生于",
  supports: "支持",
  contradicts: "冲突",
  supersedes: "替代",
  derived_from: "派生自",
  documented_in: "记录于",
};

const entityTypes = ["self", "person", "project", "preference", "boundary", "goal", "event", "concept", "source", "wiki_page", "decision"];
const relationTypes = Object.keys(relationLabels);
const unsafeText = /candidate|fact|evidence|source_text|source_excerpt|agent_run_id|token|authorization|fts|vector|[A-Za-z]:[\\/]|\\\\/i;

function safe(value: string | null | undefined, fallback: string): string {
  const text = value?.trim();
  return text && !unsafeText.test(text) ? text : fallback;
}

function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "时间未记录";
  }
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) {
    return "时间未记录";
  }
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(parsed));
}

function lifecycleText(status: string | undefined, active: boolean | undefined): string {
  if (active) {
    return "当前允许召回";
  }
  if (status === "candidate" || status === "pending") {
    return "等待确认，不会进入回答";
  }
  if (status === "wrong" || status === "rejected" || status === "sensitive_blocked") {
    return "已隔离，不会进入回答";
  }
  return "当前不会进入回答上下文";
}

function claimSentence(claim: MemoryGraphClaimDetail | null): string {
  if (!claim) {
    return "尚未返回事实文本";
  }
  return `${safe(claim.subject_label, "实体")} ${safe(claim.predicate, "关系")} ${safe(claim.literal_value, "值")}`;
}

export function MemoryEvidenceRail({
  node,
  edge,
  nodeDetail,
  edgeDetail,
  claimDetail,
  endpointDetails,
  loading,
  error,
  actionBusy,
  actionError,
  actionMessage,
  onClose,
  onApplyAction,
  onOpenSource,
}: MemoryEvidenceRailProps) {
  const [confirming, setConfirming] = useState<"forget" | "archive" | null>(null);
  const [correcting, setCorrecting] = useState(false);
  const [replacementName, setReplacementName] = useState("");
  const [replacementType, setReplacementType] = useState("concept");
  const [replacementAliases, setReplacementAliases] = useState("");
  const [replacementRelation, setReplacementRelation] = useState("related_to");
  const [replacementValue, setReplacementValue] = useState("");
  const [correctionRecord, setCorrectionRecord] = useState<{ targetId: string; oldValue: string; newValue: string; at: string; replayed: boolean } | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const selectedTargetId = edge?.edge_id || node?.node_id || null;
  const selectedTargetIdRef = useRef(selectedTargetId);
  selectedTargetIdRef.current = selectedTargetId;

  const activeLifecycle = edgeDetail?.lifecycle || nodeDetail?.lifecycle || claimDetail?.lifecycle || null;
  const selectedStatus = edgeDetail?.status || claimDetail?.status || nodeDetail?.status || node?.status;
  const evidence = useMemo(() => {
    const own = edgeDetail?.evidence || claimDetail?.evidence || nodeDetail?.evidence || [];
    const endpointEvidence = Object.values(endpointDetails).flatMap((detail) => detail.evidence || []);
    const seen = new Set<string>();
    return [...own, ...endpointEvidence].filter((item) => {
      if (seen.has(item.evidence_id)) {
        return false;
      }
      seen.add(item.evidence_id);
      return true;
    }).slice(0, 6);
  }, [claimDetail?.evidence, edgeDetail?.evidence, endpointDetails, nodeDetail?.evidence]);
  const wikiPages = useMemo(() => {
    const pages = [
      ...(nodeDetail?.wiki_pages || []),
      ...Object.values(endpointDetails).flatMap((detail) => detail.wiki_pages || []),
    ];
    return pages.filter((page, index, all) => all.findIndex((item) => item.binding_id === page.binding_id) === index).slice(0, 5);
  }, [endpointDetails, nodeDetail?.wiki_pages]);
  const currentLabel = edge
    ? `${safe(endpointDetails[edge.source_node_id]?.label, "实体")} ${relationLabels[edge.relation_type] || "关联"} ${safe(endpointDetails[edge.target_node_id]?.label, "实体")}`
    : claimDetail
      ? claimSentence(claimDetail)
      : safe(nodeDetail?.label || node?.label, "一条记忆");

  useEffect(() => {
    if (nodeDetail?.label) {
      setReplacementName(nodeDetail.label);
      setReplacementType(entityTypes.includes(nodeDetail.type) ? nodeDetail.type : "concept");
      setReplacementAliases("");
    }
    if (claimDetail) {
      setReplacementValue(claimDetail.literal_value);
    }
    if (edgeDetail?.relation_type && relationTypes.includes(edgeDetail.relation_type)) {
      setReplacementRelation(edgeDetail.relation_type);
    }
    setCorrecting(false);
    setConfirming(null);
    setCorrectionRecord((record) => record && record.targetId === selectedTargetId ? record : null);
  }, [claimDetail, edgeDetail, nodeDetail, selectedTargetId]);

  useEffect(() => {
    if (!selectedTargetId) {
      return;
    }
    closeButtonRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose, selectedTargetId]);

  if (!node && !edge) {
    return (
      <aside className="llmwiki-evidence-rail is-empty" aria-label="证据链轨道">
        <div className="llmwiki-rail-empty-mark"><GitBranch size={18} aria-hidden="true" /></div>
        <strong>选择一个节点或关系</strong>
        <p>这里会按实体、关系、来源、Wiki 页面和生命周期展开证据链。</p>
      </aside>
    );
  }

  const canConfirm = (edgeDetail?.allowed_actions || nodeDetail?.allowed_actions || claimDetail?.allowed_actions || []).includes("confirm");
  const canCorrect = (edgeDetail?.allowed_actions || nodeDetail?.allowed_actions || claimDetail?.allowed_actions || []).includes("correct");
  const canForget = (edgeDetail?.allowed_actions || nodeDetail?.allowed_actions || claimDetail?.allowed_actions || []).includes("forget");
  const canArchive = (edgeDetail?.allowed_actions || nodeDetail?.allowed_actions || claimDetail?.allowed_actions || []).includes("archive");

  async function apply(request: MemoryGraphActionRequest) {
    const oldValue = currentLabel;
    const newValue = request.action === "correct" ? replacementSummary() : null;
    const response = await onApplyAction(request);
    if (!response) {
      return;
    }
    if (request.action === "correct" && newValue && selectedTargetIdRef.current === selectedTargetId) {
      setCorrectionRecord({ targetId: selectedTargetId || "", oldValue, newValue, at: new Date().toISOString(), replayed: response.replayed });
    }
    setConfirming(null);
    setCorrecting(false);
  }

  function replacementSummary(): string {
    if (claimDetail) {
      return `${safe(claimDetail.subject_label, "实体")} ${safe(claimDetail.predicate, "关系")} ${safe(replacementValue, "新值")}`;
    }
    if (edgeDetail) {
      return `${safe(endpointDetails[edgeDetail.source_node_id]?.label, "实体")} ${relationLabels[replacementRelation] || "关联"} ${safe(endpointDetails[edgeDetail.target_node_id]?.label, "实体")}`;
    }
    return safe(replacementName, "新实体");
  }

  function submitCorrection() {
    if (claimDetail) {
      if (!replacementValue.trim()) {
        return;
      }
      void apply({ action: "correct", confirmed: true, replacement: { value: replacementValue.trim() } });
      return;
    }
    if (edgeDetail) {
      void apply({
        action: "correct",
        confirmed: true,
        replacement: {
          relation_type: replacementRelation,
          subject_node_id: edgeDetail.source_node_id,
          object_node_id: edgeDetail.target_node_id,
        },
      });
      return;
    }
    if (!replacementName.trim()) {
      return;
    }
    void apply({
      action: "correct",
      confirmed: true,
      replacement: {
        canonical_name: replacementName.trim(),
        entity_type: replacementType,
        aliases: replacementAliases.split(",").map((item) => item.trim()).filter(Boolean),
      },
    });
  }

  return (
    <aside className="llmwiki-evidence-rail" role="dialog" aria-modal="false" aria-labelledby="llmwiki-evidence-rail-title" aria-label="证据链轨道" aria-live="polite">
      <header className="llmwiki-rail-header">
        <div><p className="llmwiki-eyebrow">证据链轨道</p><h3 id="llmwiki-evidence-rail-title">{currentLabel}</h3></div>
        <button ref={closeButtonRef} type="button" className="icon-button" onClick={onClose} aria-label="关闭证据链" title="关闭证据链"><X size={16} aria-hidden="true" /></button>
      </header>

      {loading ? <div className="llmwiki-rail-loading" role="status">正在读取详情…</div> : null}
      {error ? <div className="llmwiki-inline-error" role="alert">{error}</div> : null}

      <ol className="llmwiki-evidence-steps">
        <li className="llmwiki-evidence-step is-entity">
          <span className="llmwiki-step-index">01</span>
          <div><strong>实体</strong><p>{edge ? `${safe(endpointDetails[edge.source_node_id]?.label, "来源实体")} · ${safe(endpointDetails[edge.target_node_id]?.label, "目标实体")}` : safe(nodeDetail?.label || node?.label, "实体详情未返回")}</p><small>{safe(nodeDetail?.type || node?.type, "类型未返回")}</small></div>
        </li>
        <li className={`llmwiki-evidence-step ${edge?.relation_type === "contradicts" || edgeDetail?.status === "conflict" ? "is-conflict" : ""}`}>
          <span className="llmwiki-step-index">02</span>
          <div><strong>关系</strong><p>{edge ? relationLabels[edge.relation_type] || edge.relation_type : claimDetail ? safe(claimDetail.predicate, "关系") : "实体详情"}</p><small>{safe(edgeDetail?.status || claimDetail?.status || nodeDetail?.status, "状态未返回")}</small></div>
        </li>
        <li className="llmwiki-evidence-step">
          <span className="llmwiki-step-index">03</span>
          <div><strong>原始来源</strong>{evidence.length ? evidence.map((item) => <div key={item.evidence_id} className="llmwiki-source-item"><span>{safe(item.label, "本地来源")}</span><small>{safe(item.excerpt, "原文片段未返回")}</small>{item.relative_path ? <code>{safe(item.relative_path, "相对路径未返回")}</code> : null}</div>) : <p className="llmwiki-muted">暂无可展示的原始来源；没有 evidence 时不会进入回答上下文。</p>}</div>
        </li>
        <li className="llmwiki-evidence-step">
          <span className="llmwiki-step-index">04</span>
          <div><strong>Wiki 页面</strong>{wikiPages.length ? wikiPages.map((page) => <button key={page.binding_id} type="button" className="llmwiki-source-link" onClick={() => onOpenSource(page.relative_path)}><FileText size={14} />{safe(page.title, "Wiki 页面")}<ExternalLink size={13} /></button>) : <p className="llmwiki-muted">暂无 Wiki 绑定。</p>}</div>
        </li>
        <li className="llmwiki-evidence-step">
          <span className="llmwiki-step-index">05</span>
          <div><strong>生命周期</strong><p>{lifecycleText(activeLifecycle?.status || selectedStatus, activeLifecycle?.active_for_recall)}</p><small>{activeLifecycle ? `${safe(activeLifecycle.status, "状态未返回")} · ${formatDate(activeLifecycle.updated_at)}` : "暂无生命周期记录"}</small>{activeLifecycle?.expires_at ? <small>到期：{formatDate(activeLifecycle.expires_at)}</small> : null}</div>
        </li>
        <li className="llmwiki-evidence-step">
          <span className="llmwiki-step-index">06</span>
          <div><strong>纠正记录</strong>{correctionRecord ? <div className="llmwiki-correction-record"><span>旧值：{correctionRecord.oldValue}</span><ChevronRight size={14} /><span>新值：{correctionRecord.newValue}</span><small>{formatDate(correctionRecord.at)} · {correctionRecord.replayed ? "已读取既有 supersedes 回执" : "supersedes 已创建"}</small></div> : claimDetail?.superseded_by_claim_id ? <p>已沿 supersedes 链替代，后继标识：<code>{claimDetail.superseded_by_claim_id}</code><br />更新时间：{formatDate(claimDetail.lifecycle.updated_at)}</p> : <p className="llmwiki-muted">暂无纠正记录。</p>}</div>
        </li>
      </ol>

      {actionError ? <div className="llmwiki-inline-error" role="alert">{actionError}</div> : null}
      {actionMessage ? <div className="llmwiki-inline-success" role="status">{actionMessage}</div> : null}
      {(canConfirm || canCorrect || canForget || canArchive) ? (
        <div className="llmwiki-rail-actions" aria-label="记忆安全操作">
          {canConfirm ? <button type="button" className="secondary" onClick={() => void apply({ action: "confirm", confirmed: true })} disabled={actionBusy}><Check size={15} />确认</button> : null}
          {canCorrect ? <button type="button" className="secondary" onClick={() => setCorrecting((value) => !value)} disabled={actionBusy}><Undo2 size={15} />纠正</button> : null}
          {canArchive ? <button type="button" className="secondary" onClick={() => confirming === "archive" ? void apply({ action: "archive", confirmed: true }) : setConfirming("archive")} disabled={actionBusy}><Archive size={15} />{confirming === "archive" ? "再次点击归档" : "归档"}</button> : null}
          {canForget ? <button type="button" className="danger-button" onClick={() => confirming === "forget" ? void apply({ action: "forget", confirmed: true }) : setConfirming("forget")} disabled={actionBusy}><ShieldAlert size={15} />{confirming === "forget" ? "再次点击忘记" : "忘记"}</button> : null}
        </div>
      ) : null}

      {correcting ? (
        <form className="llmwiki-correction-form" onSubmit={(event) => { event.preventDefault(); submitCorrection(); }}>
          <strong>记录纠正</strong>
          {claimDetail ? <label>新值<input value={replacementValue} onChange={(event) => setReplacementValue(event.target.value)} required /></label> : null}
          {edgeDetail ? <label>新关系<select value={replacementRelation} onChange={(event) => setReplacementRelation(event.target.value)}>{relationTypes.map((type) => <option key={type} value={type}>{relationLabels[type]}</option>)}</select></label> : null}
          {!claimDetail && !edgeDetail ? <><label>规范名称<input value={replacementName} onChange={(event) => setReplacementName(event.target.value)} required /></label><label>实体类型<select value={replacementType} onChange={(event) => setReplacementType(event.target.value)}>{entityTypes.map((type) => <option key={type} value={type}>{type}</option>)}</select></label><label>别名（逗号分隔）<input value={replacementAliases} onChange={(event) => setReplacementAliases(event.target.value)} /></label></> : null}
          <button type="submit" className="primary" disabled={actionBusy}>保存纠正</button>
        </form>
      ) : null}
    </aside>
  );
}
