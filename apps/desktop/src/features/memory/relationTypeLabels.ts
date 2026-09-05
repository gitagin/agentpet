/** 关系类型 → 中文标签的唯一来源。
 *
 * 之前在 MemoryGraphWorkspace / MemoryTimelineWorkspace / MemoryEvidenceRail
 * 各复制了一份相同映射，新增/改名关系类型时要同步三处，容易漏。这里统一为
 * 单一常量，三个组件共用。键顺序也作为下拉框等处的稳定展示顺序。
 */
export const relationLabels: Record<string, string> = {
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

export function relationLabelOf(type: string): string {
  return relationLabels[type] || "关系";
}
