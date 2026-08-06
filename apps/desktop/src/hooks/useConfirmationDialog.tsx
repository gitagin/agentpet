import { useCallback, useEffect, useRef, useState } from "react";
import {
  ConfirmationDialog,
  type ConfirmationDialogRequest,
} from "../components/ConfirmationDialog";

type PendingConfirmation = {
  request: ConfirmationDialogRequest;
  resolve: (confirmed: boolean) => void;
};

export function useConfirmationDialog() {
  const [pending, setPending] = useState<PendingConfirmation | null>(null);
  const pendingRef = useRef<PendingConfirmation | null>(null);

  const resolveConfirmation = useCallback((confirmed: boolean) => {
    const current = pendingRef.current;
    pendingRef.current = null;
    setPending(null);
    current?.resolve(confirmed);
  }, []);

  const confirm = useCallback((request: ConfirmationDialogRequest) => {
    return new Promise<boolean>((resolve) => {
      pendingRef.current?.resolve(false);
      const next = { request, resolve };
      pendingRef.current = next;
      setPending(next);
    });
  }, []);

  useEffect(() => () => {
    pendingRef.current?.resolve(false);
    pendingRef.current = null;
  }, []);

  return {
    confirm,
    confirmationDialog: pending
      ? <ConfirmationDialog request={pending.request} onResolve={resolveConfirmation} />
      : null,
  };
}
