import type { ReactNode } from "react";

export const metadata = { title: "CodeAsk" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: "system-ui", margin: "2rem", maxWidth: "48rem" }}>{children}</body>
    </html>
  );
}
