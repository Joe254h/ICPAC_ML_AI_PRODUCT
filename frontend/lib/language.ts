"use client";
/**
 * One language for the whole site: the Copilot answers in it and the bulletin page offers
 * the draft in it. Choosing a language in either place changes it in both (and in other
 * open tabs).
 */
import { useCallback, useEffect, useState } from "react";

const KEY = "icpac-language";
/** Where the Copilot kept its own choice before the site shared one. */
const EARLIER_KEY = "icpac-copilot-language";
const EVENT = "icpac-language";

function stored(): string {
  try {
    return (
      localStorage.getItem(KEY) ?? localStorage.getItem(EARLIER_KEY) ?? "en"
    );
  } catch {
    return "en"; // Storage blocked: English until chosen.
  }
}

/** The site's language code ("en", "sw", ...) and a setter shared by every page. */
export function useLanguage(): [string, (code: string) => void] {
  const [language, setLanguage] = useState("en");
  useEffect(() => {
    const update = () => setLanguage(stored());
    update();
    window.addEventListener(EVENT, update);
    window.addEventListener("storage", update);
    return () => {
      window.removeEventListener(EVENT, update);
      window.removeEventListener("storage", update);
    };
  }, []);
  const choose = useCallback((code: string) => {
    setLanguage(code);
    try {
      localStorage.setItem(KEY, code);
    } catch {
      // The choice lasts for this page.
    }
    window.dispatchEvent(new Event(EVENT));
  }, []);
  return [language, choose];
}
