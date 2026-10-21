import { act, useState, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChatComposer } from "./ChatComposer";

let root: Root;
let container: HTMLDivElement;
let submitQuestion: ReturnType<typeof vi.fn>;

function Harness(): ReactNode {
  const [value, setValue] = useState("");
  return (
    <ChatComposer
      value={value}
      isPending={false}
      onChange={setValue}
      onSubmit={submitQuestion}
    />
  );
}

async function renderComposer() {
  await act(async () => {
    root.render(<Harness />);
  });
}

beforeEach(() => {
  Reflect.set(globalThis, "IS_REACT_ACT_ENVIRONMENT", true);
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  submitQuestion = vi.fn().mockResolvedValue(true);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("ChatComposer", () => {
  it("sends on Enter and clears only after a successful request", async () => {
    await renderComposer();
    const textarea = container.querySelector("textarea");
    if (!textarea) {
      throw new Error("Question textarea was not rendered.");
    }

    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLTextAreaElement.prototype,
        "value",
      )?.set;
      setter?.call(textarea, "  שאלה לבדיקה  ");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => {
      textarea.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    });

    expect(submitQuestion).toHaveBeenCalledWith("שאלה לבדיקה");
    expect(textarea.value).toBe("");
  });

  it("retains the question after a failed submission", async () => {
    submitQuestion.mockResolvedValue(false);
    await renderComposer();
    const textarea = container.querySelector("textarea");
    if (!textarea) {
      throw new Error("Question textarea was not rendered.");
    }

    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLTextAreaElement.prototype,
        "value",
      )?.set;
      setter?.call(textarea, "שאלה שנכשלה");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => {
      container.querySelector("form")?.requestSubmit();
    });

    expect(submitQuestion).toHaveBeenCalledWith("שאלה שנכשלה");
    expect(textarea.value).toBe("שאלה שנכשלה");
  });

  it("does not submit when Shift+Enter is pressed", async () => {
    await renderComposer();
    const textarea = container.querySelector("textarea");
    if (!textarea) {
      throw new Error("Question textarea was not rendered.");
    }

    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLTextAreaElement.prototype,
        "value",
      )?.set;
      setter?.call(textarea, "שאלה בשתי שורות");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      textarea.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "Enter",
          shiftKey: true,
          bubbles: true,
        }),
      );
    });

    expect(submitQuestion).not.toHaveBeenCalled();
  });
});
