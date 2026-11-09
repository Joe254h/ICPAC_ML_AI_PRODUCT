"use client";
import { useCallback, useEffect, useRef, useState } from "react";
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
  const previousPath = useRef(path);
  useEffect(() => {
    const changed = () => setTick((t) => t + 1);
    window.addEventListener("staff-access", changed);
    return () => window.removeEventListener("staff-access", changed);
  }, []);
  useEffect(() => {
    if (path === null) {
      setState({ loading: false });
      return;
    }
    const abort = new AbortController();
    let active = true;
    const samePath = previousPath.current === path;
    previousPath.current = path;
    setState((old) =>
      samePath
        ? { ...old, loading: true, error: undefined, status: undefined }
        : { loading: true },
    );
    request<T>(path, { signal: abort.signal })
      .then((data) => {
        if (active) setState({ data, loading: false });
      })
      .catch((e: Error) => {
        if (!active || e.name === "AbortError") return;
        setState({
          error: e.message,
          status: e instanceof ApiError ? e.status : undefined,
          loading: false,
        });
      });
    return () => {
      active = false;
      abort.abort();
    };
  }, [path, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, reload };
}
