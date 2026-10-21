import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useChat } from "./useChat";

function apiResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

let root: Root;
let container: HTMLDivElement;
let snapshot: ReturnType<typeof useChat>;

function Harness(): ReactNode {
  snapshot = useChat();
  return (
    <div>
      <button onClick={() => void snapshot.send("שאלה ראשונה")}>send-first</button>
      <button onClick={() => void snapshot.send("שאלת המשך")}>send-follow-up</button>
      <button onClick={() => void snapshot.retry()}>retry</button>
      <output data-testid="snapshot">
        {JSON.stringify({
          messages: snapshot.messages,
          failure: snapshot.failure,
          isPending: snapshot.isPending,
        })}
      </output>
    </div>
  );
}

async function renderHarness() {
  await act(async () => {
    root.render(<Harness />);
  });
}

async function clickButton(name: string) {
  const button = Array.from(container.querySelectorAll("button")).find(
    (item) => item.textContent === name,
  );
  if (!button) {
    throw new Error(`Missing test button: ${name}`);
  }
  await act(async () => {
    button.click();
  });
}

function getSnapshot() {
  const output = container.querySelector("output");
  if (!output) {
    throw new Error("Missing state output.");
  }
  return JSON.parse(output.textContent ?? "{}") as {
    messages: unknown[];
    failure: null | { question: string };
    isPending: boolean;
  };
}

beforeEach(() => {
  Reflect.set(globalThis, "IS_REACT_ACT_ENVIRONMENT", true);
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

describe("useChat", () => {
  it("includes a successful answer without citations in later history", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(apiResponse(200, { answer: "תשובה ללא מקור", citations: [] }))
      .mockResolvedValueOnce(apiResponse(200, { answer: "תשובת המשך", citations: [] }));
    vi.stubGlobal("fetch", fetchMock);
    await renderHarness();

    await clickButton("send-first");
    await clickButton("send-follow-up");

    const followUpBody = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(followUpBody.history).toEqual([
      { role: "user", content: "שאלה ראשונה" },
      { role: "assistant", content: "תשובה ללא מקור" },
    ]);
    expect(getSnapshot().messages).toHaveLength(4);
  });

  it("does not send failed turns in later history", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(apiResponse(503, { detail: "private" }))
      .mockResolvedValueOnce(apiResponse(200, { answer: "הצלחה", citations: [] }));
    vi.stubGlobal("fetch", fetchMock);
    await renderHarness();

    await clickButton("send-first");
    expect(getSnapshot().failure?.question).toBe("שאלה ראשונה");
    await clickButton("send-follow-up");

    expect(JSON.parse(fetchMock.mock.calls[1][1].body).history).toEqual([]);
  });

  it("retries the same question with the original history snapshot", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(apiResponse(200, { answer: "קודם", citations: [] }))
      .mockResolvedValueOnce(apiResponse(503, { detail: "private" }))
      .mockResolvedValueOnce(apiResponse(200, { answer: "אחרי ניסיון", citations: [] }));
    vi.stubGlobal("fetch", fetchMock);
    await renderHarness();

    await clickButton("send-first");
    await clickButton("send-follow-up");
    await clickButton("retry");

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual(
      JSON.parse(fetchMock.mock.calls[1][1].body),
    );
  });

  it("prevents concurrent duplicate requests and aborts on unmount", async () => {
    let requestSignal: AbortSignal | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, options: RequestInit) => {
        requestSignal = options.signal ?? undefined;
        return new Promise<Response>((_resolve, reject) => {
          requestSignal?.addEventListener("abort", () => {
            reject(new DOMException("Aborted", "AbortError"));
          });
        });
      }),
    );
    await renderHarness();

    await act(async () => {
      container.querySelectorAll("button")[0].click();
      container.querySelectorAll("button")[0].click();
    });
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
    expect(getSnapshot().isPending).toBe(true);

    act(() => root.unmount());
    expect(requestSignal?.aborted).toBe(true);
  });
});
