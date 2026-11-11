import { expect, test } from "@playwright/test";
import { renderToStaticMarkup } from "react-dom/server";

import { Answer } from "../../components/Answer";
import { citeNumber, citeUrlTransform, safeGithubUrl } from "../../lib/markdown";
import type { Citation } from "../../lib/types";

const verified: Citation = {
  n: 1, path: "src/a.py", start: 2, end: 3, valid: true, block: 0,
  url: "https://github.com/o/r/blob/abc/src/a.py#L2-L3",
};
const unverified: Citation = {
  n: 2, path: "src/z.py", start: 1, end: 2, valid: false, url: null, block: null,
};

function render(markdown: string, openN: number | null = null): string {
  return renderToStaticMarkup(
    <Answer markdown={markdown} citations={[verified, unverified]} openN={openN}
            onOpen={() => {}} />,
  );
}

test.describe("url rules", () => {
  test("only cite:<digits> survives the transform", () => {
    expect(citeUrlTransform("cite:12")).toBe("cite:12");
    for (const url of ["cite:abc", "cite:1 ", "CITE:1", "javascript:alert(1)",
                       "https://evil.example", "data:text/html,x", "cite:12345"]) {
      expect(citeUrlTransform(url)).toBe("");
    }
  });

  test("citeNumber reads only citation links", () => {
    expect(citeNumber("cite:7")).toBe(7);
    expect(citeNumber("https://example.com/cite:7")).toBeNull();
    expect(citeNumber(undefined)).toBeNull();
  });

  test("only https://github.com/ permalinks pass", () => {
    expect(safeGithubUrl(verified.url)).toBe(verified.url);
    for (const url of ["http://github.com/o/r", "https://github.com.evil.example/o/r",
                       "//github.com/o/r", "javascript:alert(1)", null, undefined]) {
      expect(safeGithubUrl(url)).toBeNull();
    }
  });
});

test.describe("rendering model text", () => {
  test("citation markers become chips, and the open one is marked", () => {
    const html = render("It does X [1](cite:1).", 1);
    expect(html).toContain('aria-label="Citation 1: src/a.py, lines 2 to 3"');
    expect(html).toContain('aria-current="true"');
    expect(html).not.toContain("<a ");
  });

  test("an unverified citation says so in its accessible name", () => {
    expect(render("Y [2](cite:2).")).toContain('aria-label="Citation 2, unverified"');
  });

  test("a cite: number with no matching citation is plain text", () => {
    const html = render("Z [9](cite:9).");
    expect(html).not.toContain("<button");
    expect(html).toContain("Z 9.");
  });

  test.describe("chips stay with their words (round 1 C6, round 2 R2-1)", () => {
    const GROUP = '<span class="whitespace-nowrap">';

    test("the word before, the chip and the punctuation after form one no-wrap group", () => {
      const html = render("ordered from oldest to newest [1](cite:1). Next [2](cite:2) word.");
      expect(html).toMatch(new RegExp(`ordered from oldest to ${GROUP}newest <button[^]*?</button>\\.</span> `));
      expect(html).toMatch(new RegExp(`${GROUP}Next <button[^]*?</button></span> word\\.`));
    });

    test("inline code before a chip joins the group", () => {
      const html = render("stored in `self.secret_keys` [1](cite:1). The");
      expect(html).toMatch(new RegExp(`stored in ${GROUP}<code>self.secret_keys</code> <button[^]*?</button>\\.</span> The`));
    });

    test("adjacent chips share one group, with or without a space", () => {
      for (const md of ["order [1](cite:1) [2](cite:2) and", "order [1](cite:1)[2](cite:2) and"]) {
        const html = render(md);
        expect(html.match(/whitespace-nowrap/g), md).toHaveLength(1);
        expect(html).toMatch(new RegExp(`${GROUP}order <button[^]*?</button> ?<button[^]*?</button></span> and`));
      }
    });

    test("text without citations is untouched", () => {
      expect(render("Plain text, no citations.")).not.toContain("whitespace-nowrap");
    });
  });

  test("raw HTML is shown as text and never becomes elements", () => {
    const html = render('<script>alert(1)</script>\n\nA <img src=x onerror="alert(1)"> B');
    expect(html).not.toContain("<script");
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;script&gt;");
  });

  test("model links, autolinks and images never become links or images", () => {
    const html = render("[click](https://evil.example) <https://evil.example/2> " +
                        "[x](javascript:alert(1)) ![alt](https://evil.example/i.png)");
    expect(html).not.toContain("<a");
    expect(html).not.toContain("<img");
    expect(html).not.toContain("href=");
    expect(html).toContain("click");
  });

  test("the elements an answer needs render, with headings one level down", () => {
    const html = render("# T\n\n- **b** and `c`\n\n```\nx = 1\n```\n");
    expect(html).toContain("<h2>T</h2>");
    expect(html).toContain("<strong>b</strong>");
    expect(html).toContain("<code>c</code>");
    expect(html).toContain("<pre><code>x = 1");
  });

  test("a citation inside bold or a list item is still a chip", () => {
    const html = render("- **see [1](cite:1)**");
    expect(html).toMatch(/<li><strong><span class="whitespace-nowrap">see <button/);
  });
});
