// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import Markdown from "./Markdown";

describe("Markdown", () => {
  afterEach(() => cleanup());

  it("renders a GFM table with semantic elements", () => {
    const md = `| Name | Status |\n|------|--------|\n| alpha | ok |\n| beta | fail |`;
    const { container } = render(<Markdown content={md} />);
    const table = container.querySelector("table");
    expect(table).toBeInTheDocument();
    const rows = container.querySelectorAll("tr");
    expect(rows.length).toBe(3);
  });

  it("renders fenced code blocks with a language label", () => {
    const md = "```python\nprint('hello')\n```";
    const { container } = render(<Markdown content={md} />);
    const code = container.querySelector("code");
    expect(code).toBeInTheDocument();
    expect(code?.textContent).toContain("print('hello')");
    expect(container.textContent).toContain("python");
  });

  it("renders inline code", () => {
    render(<Markdown content="Use `foo()` here" />);
    const code = screen.getByText("foo()");
    expect(code.tagName).toBe("CODE");
  });

  it("renders links with safe attributes", () => {
    render(<Markdown content="[example](https://example.com)" />);
    const link = screen.getByText("example") as HTMLAnchorElement;
    expect(link.tagName).toBe("A");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
  });

  it("renders unordered lists", () => {
    const { container } = render(<Markdown content={"- one\n- two\n- three"} />);
    const items = container.querySelectorAll("li");
    expect(items.length).toBe(3);
  });

  it("renders ordered lists", () => {
    const { container } = render(<Markdown content={"1. first\n2. second"} />);
    const ol = container.querySelector("ol");
    expect(ol).toBeInTheDocument();
  });

  it("does not render raw HTML", () => {
    const { container } = render(
      <Markdown content='<script>alert("xss")</script><div id="injected">bad</div>' />,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("#injected")).toBeNull();
  });

  it("renders bold and italic text", () => {
    const { container } = render(<Markdown content="**bold** and *italic*" />);
    expect(container.querySelector("strong")?.textContent).toBe("bold");
    expect(container.querySelector("em")?.textContent).toBe("italic");
  });

  it("renders headings", () => {
    const { container } = render(<Markdown content={"# H1\n## H2\n### H3"} />);
    expect(container.querySelector("h1")?.textContent).toBe("H1");
    expect(container.querySelector("h2")?.textContent).toBe("H2");
    expect(container.querySelector("h3")?.textContent).toBe("H3");
  });
});
