import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api";

interface PollingResult<T> {
  data: T | null;
  error: string | null;
  errorCode: string | null;
  requestId: string | null;
  retryable: boolean;
  loading: boolean;
  reload: () => void;
}

/**
 * Runs `fetcher` on mount and whenever `key` or `intervalMs` changes.
 * `fetcher` is read through a ref so callers do not need to memoise it.
 */
export function usePolling<T>(
  key: string,
  fetcher: () => Promise<T>,
  intervalMs = 0,
): PollingResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [requestId, setRequestId] = useState<string | null>(null);
  const [retryable, setRetryable] = useState(false);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);
  const fetcherRef = useRef(fetcher);
  const mountedRef = useRef(true);

  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    const run = async () => {
      try {
        const next = await fetcherRef.current();
        if (cancelled) return;
        setData(next);
        setError(null);
        setErrorCode(null);
        setRequestId(null);
        setRetryable(false);
      } catch (cause) {
        if (cancelled) return;
        if (cause instanceof ApiError) {
          setError(cause.message);
          setErrorCode(cause.code);
          setRequestId(cause.requestId);
          setRetryable(cause.retryable);
        } else {
          setError("Unexpected error while loading data.");
          setErrorCode(null);
          setRequestId(null);
          setRetryable(false);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    setLoading(true);
    void run();
    if (intervalMs <= 0) {
      return () => {
        cancelled = true;
      };
    }
    const timer = window.setInterval(() => void run(), intervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [key, intervalMs, nonce]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  return { data, error, errorCode, requestId, retryable, loading, reload };
}
