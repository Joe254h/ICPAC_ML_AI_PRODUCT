"use client";
import { useCallback, useEffect, useState } from "react";
import { ApiError, request } from "@/services/api";

export type Loaded<T> = {
  data?: T;
  error?: string;
  status?: number;
  loading: boolean;
  reload: () => void;
};

/** GET a backend resource; a null path waits (for example, for an identifier). */
export function useApi<T>(path: string | null): Loaded<T> {
  const [state, setState] = useState<Omit<Loaded<T>, "reload">>({
    loading: path !== null,
  });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (path === null) {
      setState({ loading: false });
      return;
    }
    const abort = new AbortController();
    setState((old) => ({ ...old, loading: true, error: undefined }));
    request<T>(path, { signal: abort.signal })
      .then((data) => setState({ data, loading: false }))
      .catch((e: Error) => {
        if (e.name === "AbortError") return;
        setState({
          error: e.message,
          status: e instanceof ApiError ? e.status : undefined,
          loading: false,
        });
      });
    return () => abort.abort();
  }, [path, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, reload };
}
