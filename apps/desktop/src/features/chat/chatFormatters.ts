import type { ChatMessage, Citation } from "../../types";

export function formatCitationSourceLabel(citations: Citation[]): string {
  const sourceScope = citations[0]?.source_scope;
  if (sourceScope === "personal_memory") {
    return "记忆";
  }
  if (sourceScope === "diary_objects") {
    return "结构化日记";
  }
  if (sourceScope === "daily_chat") {
    return "聊天日记";
  }
  if (sourceScope === "knowledge_base") {
    return "资料";
  }
  if (sourceScope === "pending_memory") {
    return "待确认记忆";
  }
  return "记忆/资料";
}

export function formatRunStatus(status: NonNullable<ChatMessage["status"]>): string {
  const labels: Record<NonNullable<ChatMessage["status"]>, string> = {
    partial: "生成中",
    completed: "已完成",
    failed: "失败，请查看消息",
    cancelled: "已取消",
  };
  return labels[status];
}

export function formatMessageRole(role: ChatMessage["role"]): string {
  const labels: Record<ChatMessage["role"], string> = {
    user: "用户",
    assistant: "助手",
    system: "系统",
  };
  return labels[role];
}
