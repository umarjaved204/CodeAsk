import type { ReactNode } from "react";

import { fragmentMono, instrumentSans, newsreader } from "./fonts";
import "./globals.css";

export const metadata = { title: "CodeAsk" };

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
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="min-h-dvh bg-page font-ui text-text antialiased">{children}</body>
    </html>
  );
}
