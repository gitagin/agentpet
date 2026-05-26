import type { MemoryProposalType } from "../../types";

export const memoryTypes: MemoryProposalType[] = ["preference", "fact", "event", "goal", "rule"];
export const defaultMemoryTargetPath = "Inbox/Pending Memories.md";

export const memoryTypeLabels: Record<MemoryProposalType, string> = {
  preference: "偏好",
  fact: "事实",
  event: "事件",
  goal: "目标",
  rule: "规则",
};
