import { readRendererUiState, writeRendererUiState } from "../../services/rendererUiState";
import { wikiArchiveCandidateChannelName, wikiArchiveCandidateStorageKey } from "./wikiConstants";
import type { WikiArchiveCandidate } from "./wikiTypes";
import { normalizeWikiArchiveCandidate } from "./wikiUtils";

export function loadWikiArchiveCandidate(): WikiArchiveCandidate | null {
  try {
    return normalizeWikiArchiveCandidate(readRendererUiState(wikiArchiveCandidateStorageKey));
  } catch (error) {
    console.warn("读取 Wiki 归档候选失败。", error);
    return null;
  }
}

export function saveWikiArchiveCandidate(candidate: WikiArchiveCandidate): void {
  try {
    writeRendererUiState(wikiArchiveCandidateStorageKey, JSON.stringify(candidate));
  } catch (error) {
    console.warn("保存 Wiki 归档候选到桌面状态失败。", error);
  }
  if ("BroadcastChannel" in window) {
    try {
      const channel = new BroadcastChannel(wikiArchiveCandidateChannelName);
      channel.postMessage(candidate);
      channel.close();
    } catch (error) {
      console.warn("同步 Wiki 归档候选到其他窗口失败。", error);
    }
  }
}
