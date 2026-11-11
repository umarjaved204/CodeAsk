import type { ReactNode } from "react";

import { fragmentMono, instrumentSans, newsreader } from "./fonts";
import "./globals.css";

export const metadata = { title: "CodeAsk" };

// The browser bar matches the page (step 5, W4): the `page` token of each theme. It follows the
// system setting, not the theme toggle; accepted as cosmetic (mentor review).
export const viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#F5F6F3" },
    { media: "(prefers-color-scheme: dark)", color: "#1A212A" },
  ],
};

// Runs before first paint, so the page never flashes the wrong theme: the saved choice
// ("light" / "dark"), else the system setting. localStorage can throw (privacy modes,
// blocked storage), so it is wrapped. A static string: no user input reaches it.
const THEME_SCRIPT = `(function () {
  var theme;
  try { theme = localStorage.getItem("theme"); } catch (e) {}
  if (theme !== "light" && theme !== "dark") {
    theme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  var root = document.documentElement;
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
})();`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    // The theme script changes data-theme and style on <html> before React hydrates.
    <html
      lang="en"
      suppressHydrationWarning
      className={`${newsreader.variable} ${instrumentSans.variable} ${fragmentMono.variable}`}
    >
      <head>
        {/* The one allowed exception to react/no-danger: a static constant (no user or model
            text) that must run before first paint. A strict CSP would need its hash or a
            nonce (PLAN.md slice 3, build step 3). */}
        {/* eslint-disable-next-line react/no-danger -- static theme script, see above */}
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="min-h-dvh bg-page font-ui text-text antialiased">{children}</body>
    </html>
  );
}
