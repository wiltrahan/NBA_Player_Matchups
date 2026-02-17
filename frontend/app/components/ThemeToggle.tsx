"use client";

import { useEffect, useState } from "react";

type Theme = "light" | "dark";

const STORAGE_KEY = "nba-matchup-theme";

function getPreferredTheme(): Theme {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme: Theme): void {
  document.documentElement.setAttribute("data-theme", theme);
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    const resolvedTheme: Theme = stored === "light" || stored === "dark" ? stored : getPreferredTheme();
    setTheme(resolvedTheme);
    applyTheme(resolvedTheme);
  }, []);

  const onToggle = () => {
    const nextTheme: Theme = theme === "dark" ? "light" : "dark";
    setTheme(nextTheme);
    applyTheme(nextTheme);
    window.localStorage.setItem(STORAGE_KEY, nextTheme);
  };

  return (
    <button type="button" className="theme-toggle" onClick={onToggle} aria-label="Toggle dark mode">
      <span>{theme === "dark" ? "Dark" : "Light"}</span>
    </button>
  );
}
