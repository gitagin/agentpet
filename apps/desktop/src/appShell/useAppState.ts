import { useEffect, useRef, useState } from "react";
import type { HalfbodyPetPortraitHandle } from "../features/halfbody/HalfbodyPetPortrait";
import type { PetInputMode } from "../features/chat/petInputModes";
import { useDesktopWindowRouting } from "../features/desktop/useDesktopWindowRouting";
import type { ChatMessage, DiagnosticsExportResponse } from "../types";
import { scrollToWorkflowTarget } from "./appShellUtils";
import type { Notice } from "./types";

export function useAppState() {
  const [notice, setNotice] = useState<Notice | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [controlInput, setControlInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [diagnostics, setDiagnostics] = useState<DiagnosticsExportResponse | null>(null);
  const [petInputMode, setPetInputMode] = useState<PetInputMode>("chat");
  const routing = useDesktopWindowRouting({ onControlTargetRequested: scrollToWorkflowTarget });
  const streamAbortRef = useRef<AbortController | null>(null);
  const activeChatRequestIdRef = useRef<string | null>(null);
  const streamingRef = useRef(false);
  const conversationIdRef = useRef<string | null>(conversationId);
  const messagesRef = useRef<ChatMessage[]>(messages);
  const petCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const halfbodyPortraitRef = useRef<HalfbodyPetPortraitHandle | null>(null);

  useEffect(() => {
    conversationIdRef.current = conversationId;
  }, [conversationId]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    streamingRef.current = streaming;
  }, [streaming]);

  return {
    notice,
    setNotice,
    conversationId,
    setConversationId,
    controlInput,
    setControlInput,
    messages,
    setMessages,
    streaming,
    setStreaming,
    diagnostics,
    setDiagnostics,
    petInputMode,
    setPetInputMode,
    routing,
    streamAbortRef,
    activeChatRequestIdRef,
    streamingRef,
    conversationIdRef,
    messagesRef,
    petCanvasRef,
    halfbodyPortraitRef,
  };
}

export type AppState = ReturnType<typeof useAppState>;
