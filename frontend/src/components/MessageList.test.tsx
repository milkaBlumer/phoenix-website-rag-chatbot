import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { ChatItem } from "../hooks/useChat";
import { MessageList } from "./MessageList";

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

async function renderMessages(messages: ChatItem[]) {
  await act(async () => {
    root.render(
      <MessageList messages={messages} pendingQuestion={null} isPending={false} />,
    );
  });
}

describe("MessageList", () => {
  it("renders assistant Markdown headings, emphasis, and lists", async () => {
    await renderMessages([
      {
        role: "assistant",
        content: "### מסלול ביטוח\n* **אופן התשלום:** לפי קילומטרים\n* יתרון נוסף",
      },
    ]);

    expect(container.querySelector("h3")?.textContent).toBe("מסלול ביטוח");
    expect(container.querySelector("strong")?.textContent).toBe("אופן התשלום:");
    expect(container.querySelectorAll("ul li")).toHaveLength(2);
  });

  it("does not interpret raw HTML in assistant Markdown", async () => {
    await renderMessages([
      { role: "assistant", content: "טקסט <img src=x onerror=alert(1)>" },
    ]);

    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector(".message__bubble")?.textContent).toContain(
      "<img src=x onerror=alert(1)>",
    );
  });

  it("keeps user messages as plain text", async () => {
    await renderMessages([{ role: "user", content: "**שאלה**" }]);

    expect(container.querySelector("strong")).toBeNull();
    expect(container.querySelector(".message__bubble")?.textContent).toBe("**שאלה**");
  });
});
