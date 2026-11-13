"use client";

import { useSyncExternalStore, type ReactNode } from "react";

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
            className="-mr-2 grid size-9 cursor-pointer place-items-center text-text-muted hover:text-text sm:mr-0">
      <svg viewBox="0 0 24 24" aria-hidden="true" className="size-5">
        <circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" strokeWidth="1.8" />
        <path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor" />
      </svg>
    </button>
  );
}

/** A link that opens in a new tab, so the composer draft and a live answer stay where they are
 *  (Q78); screen readers hear that it does. */
export function NewTabLink({ href, className, children }: {
  href: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={className}>
      {children}<span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
}

const NAV_LINK = "text-meta text-text-muted no-underline hover:underline";

/** `privacy`: on the /privacy page, which needs no link to itself. */
export function Header({ page = "app" }: { page?: "app" | "privacy" }) {
  return (
    <header className="flex h-14 shrink-0 items-center justify-between px-5 lg:h-16 lg:px-8">
      <span className="flex items-center gap-2">
        <svg viewBox="0 0 24 24" aria-hidden="true" className="size-5.5 text-citation">
          <path d="M8 3H4v18h4M16 3h4v18h-4" fill="none" stroke="currentColor" strokeWidth="2.2" />
        </svg>
        <span className="font-serif text-lead font-semibold tracking-tight" translate="no">CodeAsk</span>
      </span>
      {/* Under 640 px the gaps tighten and the toggle's own padding takes the edge, so the
          brand, both links and the toggle fit at 320 (Q78; site.spec.ts measures it). */}
      <nav aria-label="Site" className="flex items-center gap-3 sm:gap-4">
        <NewTabLink href={README} className={NAV_LINK}>How it works</NewTabLink>
        {page === "app" && <NewTabLink href="/privacy" className={NAV_LINK}>Privacy</NewTabLink>}
        <ThemeToggle />
      </nav>
    </header>
  );
}
