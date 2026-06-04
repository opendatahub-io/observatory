import { useCallback, useEffect, useSyncExternalStore } from "react";

type ThemeMode = "light" | "dark" | "system";

const STORAGE_KEY = "observatory_theme";
const MEDIA_QUERY = "(prefers-color-scheme: dark)";

let mode: ThemeMode = (localStorage.getItem(STORAGE_KEY) as ThemeMode) || "system";
const listeners = new Set<() => void>();

function notify() {
  listeners.forEach((l) => l());
}

function applyDarkClass() {
  const isDark =
    mode === "dark" || (mode === "system" && window.matchMedia(MEDIA_QUERY).matches);
  document.documentElement.classList.toggle("dark", isDark);
}

function setMode(next: ThemeMode) {
  mode = next;
  localStorage.setItem(STORAGE_KEY, next);
  applyDarkClass();
  notify();
}

window.matchMedia(MEDIA_QUERY).addEventListener("change", () => {
  if (mode === "system") {
    applyDarkClass();
    notify();
  }
});

applyDarkClass();

export function useTheme() {
  const current = useSyncExternalStore(
    useCallback((cb: () => void) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    }, []),
    () => mode,
  );

  const isDark =
    current === "dark" ||
    (current === "system" && window.matchMedia(MEDIA_QUERY).matches);

  const cycleTheme = useCallback(() => {
    const order: ThemeMode[] = ["light", "dark", "system"];
    const idx = order.indexOf(mode);
    const next = order[(idx + 1) % order.length];
    setMode(next!);
  }, []);

  useEffect(() => {
    applyDarkClass();
  }, []);

  return { mode: current, isDark, setMode, cycleTheme };
}
