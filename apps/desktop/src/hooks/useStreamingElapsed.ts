import { useEffect, useState } from "react";

/** 流式回答进行中的秒表：streaming 开始后每秒 +1，结束回到 null。 */
export function useStreamingElapsed(streaming: boolean): number | null {
  const [elapsed, setElapsed] = useState<number | null>(null);

  useEffect(() => {
    if (!streaming) {
      setElapsed(null);
      return;
    }
    setElapsed(0);
    const timer = window.setInterval(() => {
      setElapsed((value) => (value ?? 0) + 1);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [streaming]);

  return elapsed;
}
