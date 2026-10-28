import { render } from "@testing-library/react";
import { createElement } from "react";
import { expect, test } from "vitest";
import Markdown, { blocks } from "../components/markdown";

const ANSWER = `### Technical summary
The **MBC + AI/ML** forecast expects heavy rain over *western Kenya*.

- **Kenya:** 45 mm on average
- Uganda: 30 mm
1. First step
2. Second step

| Country | Mean |
|---|---|
| Kenya | 45 mm |`;

test("answers are split into headings, lists, tables and paragraphs", () => {
  expect(blocks(ANSWER).map((b) => b.kind)).toEqual([
    "heading",
    "paragraph",
    "list",
    "list",
    "table",
  ]);
});

test("bold, italic, lists and tables are rendered, never shown as symbols", () => {
  const { container } = render(createElement(Markdown, { text: ANSWER }));
  expect(container.querySelector("h3")?.textContent).toBe("Technical summary");
  expect(container.querySelector("strong")?.textContent).toBe("MBC + AI/ML");
  expect(container.querySelector("em")?.textContent).toBe("western Kenya");
  expect(container.querySelectorAll("ul li")).toHaveLength(2);
  expect(container.querySelectorAll("ol li")).toHaveLength(2);
  expect(container.querySelector("td")?.textContent).toBe("Kenya");
  expect(container.textContent).not.toContain("**");
  expect(container.textContent).not.toContain("###");
});

test("only web and site links become links; no HTML is injected", () => {
  const { container } = render(
    createElement(Markdown, {
      text: "[ICPAC](https://www.icpac.net) [bad](javascript:alert(1)) <b>x</b> [page](/forecasts)",
    }),
  );
  const links = [...container.querySelectorAll("a")].map((a) =>
    a.getAttribute("href"),
  );
  expect(links).toEqual(["https://www.icpac.net/", "/forecasts"]);
  expect(container.querySelector("b")).toBeNull();
  expect(container.textContent).toContain("<b>x</b>");
});
