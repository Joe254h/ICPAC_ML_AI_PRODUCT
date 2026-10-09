"use client";
/** The forecaster's name, recorded with every action they start (kept in this browser). */
import { useCallback, useEffect, useState } from "react";

const KEY = "icpac-forecaster";

export function useActor(): [string, (name: string) => void] {
  const [name, setName] = useState("");
  useEffect(() => {
    try {
      setName(localStorage.getItem(KEY) ?? "");
    } catch {
      setName("");
    }
  }, []);
  const save = useCallback((value: string) => {
    setName(value);
    try {
      localStorage.setItem(KEY, value);
    } catch {
      /* private browsing: the name lasts for this page only */
    }
  }, []);
  return [name, save];
}
