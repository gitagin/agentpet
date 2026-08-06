import { useCallback, useLayoutEffect, useRef } from "react";

type AnyFunction = (...args: never[]) => unknown;

export function useLatestCallback<T extends AnyFunction>(callback: T): T {
  const callbackRef = useRef(callback);

  useLayoutEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  return useCallback(
    ((...args: Parameters<T>) => callbackRef.current(...args)) as T,
    [],
  );
}
