"use client";

import { useSyncExternalStore } from "react";

const README = "https://github.com/umarjaved204/codeask#readme";

function subscribe(onChange: () => void) {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => observer.disconnect();
}

function ThemeToggle() {
  // data-theme is set before first paint by the script in layout.tsx.
  const theme = useSyncExternalStore(
    subscribe, () => document.documentElement.dataset.theme ?? "light", () => "light");
  const next = theme === "dark" ? "light" : "dark";

  function toggle() {
    const root = document.documentElement;
    root.dataset.theme = next;
    root.style.colorScheme = next;
    try {
      localStorage.setItem("theme", next);
    } catch {
      // Storage can be blocked: the choice then lasts only for this page view.
    }
  }

  return (
    <button type="button" onClick={toggle} aria-label={`Switch to ${next} theme`}
            className="grid size-9 cursor-pointer place-items-center text-text-muted">
      <svg viewBox="0 0 24 24" aria-hidden="true" className="size-5">
        <circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" strokeWidth="1.8" />
        <path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor" />
      </svg>
    </button>
  );
}

export function Header() {
  return (
    <header className="flex h-14 shrink-0 items-center justify-between px-5 lg:h-16 lg:px-8">
      <span className="flex items-center gap-2">
        <svg viewBox="0 0 24 24" aria-hidden="true" className="size-5.5 text-citation">
          <path d="M8 3H4v18h4M16 3h4v18h-4" fill="none" stroke="currentColor" strokeWidth="2.2" />
        </svg>
        <span className="font-serif text-lead font-semibold tracking-tight">CodeAsk</span>
      </span>
      <nav aria-label="Site" className="flex items-center gap-4">
        <a href={README} className="text-meta text-text-muted no-underline hover:underline">
          How it works
        </a>
        <ThemeToggle />
      </nav>
    </header>
  );
}
