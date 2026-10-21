import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { CitationList } from "./CitationList";

let root: Root;
let container: HTMLDivElement;

beforeEach(() => {
  Reflect.set(globalThis, "IS_REACT_ACT_ENVIRONMENT", true);
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("CitationList", () => {
  it("opens safe source links with protective attributes", async () => {
    await act(async () => {
      root.render(
        <CitationList
          citations={[{ title: "מקור", url: "https://example.com/source" }]}
        />,
      );
    });

    const link = container.querySelector("a");
    expect(link?.getAttribute("href")).toBe("https://example.com/source");
    expect(link?.getAttribute("target")).toBe("_blank");
    expect(link?.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("renders unsafe or malformed source URLs as plain text", async () => {
    await act(async () => {
      root.render(
        <CitationList
          citations={[
            { title: "כתובת לא בטוחה", url: "javascript:alert(1)" },
            { title: "כתובת פגומה", url: "not a url" },
          ]}
        />,
      );
    });

    expect(container.querySelectorAll("a")).toHaveLength(0);
    expect(container.textContent).toContain("כתובת לא בטוחה");
    expect(container.textContent).toContain("כתובת פגומה");
  });
});
