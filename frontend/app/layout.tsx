import type { Metadata } from "next";
import type { ReactNode } from "react";

import { readSiteConfig } from "../lib/site-config";
import { fragmentMono, instrumentSans, newsreader } from "./fonts";
import "./globals.css";

// Link previews (Q77): metadataBase from NEXT_PUBLIC_SITE_URL, so the M6 domain is config only.
// The image is app/opengraph-image.png (1200x630, rendered by design/render-og.mjs), which Next
// turns into og:image tags; Twitter/X falls back to it for summary_large_image.
const { siteUrl } = readSiteConfig(process.env, process.env.NODE_ENV === "production");
const DESCRIPTION = "Ask questions about a GitHub codebase. Answers cite the files and lines they use.";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: "CodeAsk",
  description: DESCRIPTION,
  openGraph: { title: "CodeAsk", description: DESCRIPTION, url: "/", siteName: "CodeAsk",
               type: "website" },
  twitter: { card: "summary_large_image" },
};

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
