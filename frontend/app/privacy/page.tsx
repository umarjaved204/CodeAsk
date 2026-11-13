import type { Metadata } from "next";
import Link from "next/link";

import { Header, NewTabLink } from "../../components/Header";
import { PRIVACY, privacyLastChecked } from "../../lib/messages";

// The privacy page (PLAN.md Q60, Q78): static, every word from PRIVACY in lib/messages.ts.
export const metadata: Metadata = { title: "Privacy · CodeAsk" };

export default function Privacy() {
  return (
    <div className="flex min-h-dvh flex-col">
      <Header page="privacy" />
      <main className="px-5 pt-2 pb-16 lg:px-14">
        <div className="max-w-measure">
          <Link href="/" className="text-meta text-citation underline">Back to CodeAsk</Link>
          <h1 className="mt-4 font-serif text-title-sm font-medium lg:text-title">Privacy</h1>
          <p className="mt-4 font-serif text-body">{PRIVACY.summary}</p>
          {PRIVACY.sections.map((section) => (
            <section key={section.heading} className="mt-8">
              <h2 className="font-serif text-lead font-medium">{section.heading}</h2>
              {section.paragraphs.map((text) => <p key={text} className="mt-2 text-ui">{text}</p>)}
            </section>
          ))}
          <section className="mt-8">
            <h2 className="font-serif text-lead font-medium">Their policies</h2>
            <ul className="mt-2 text-ui">
              {PRIVACY.links.map((link) => (
                <li key={link.href} className="py-0.5">
                  <NewTabLink href={link.href} className="text-citation underline">{link.label}</NewTabLink>
                </li>
              ))}
            </ul>
          </section>
          <p className="mt-8 text-ui">
            <NewTabLink href={PRIVACY.contact.href} className="text-citation underline">
              {PRIVACY.contact.text}
            </NewTabLink>
          </p>
          <p className="mt-4 text-meta text-text-muted">{privacyLastChecked()}</p>
        </div>
      </main>
    </div>
  );
}
