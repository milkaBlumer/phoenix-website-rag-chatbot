import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ChatApiError,
  checkApiHealth,
  getConversationHistory,
  safeCitationUrl,
  sendChatMessage,
  stripSourceMarkers,
  type ChatMessage,
} from "./chat";

describe("stripSourceMarkers", () => {
  it("removes single and grouped source markers", () => {
    expect(
      stripSourceMarkers("בוואטסאפ [SOURCE 1, SOURCE 2]. בטלפון [SOURCE 3]."),
    ).toBe("בוואטסאפ. בטלפון.");
  });
});

function apiResponse(status: number, body: unknown, jsonError = false): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => {
      if (jsonError) {
        throw new SyntaxError("bad json");
      }
      return body;
    },
  } as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("chat API client", () => {
  it("submits a question and returns a valid response with citations", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      apiResponse(200, {
        answer: "תשובה בעברית",
        citations: [{ title: "מידע", url: "https://example.com/info" }],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await sendChatMessage("מה השירות?", []);

    expect(result).toEqual({
      answer: "תשובה בעברית",
      citations: [{ title: "מידע", url: "https://example.com/info" }],
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/chat",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: "מה השירות?", history: [] }),
      }),
    );
  });

  it("accepts a successful answer without citations", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(apiResponse(200, { answer: "תשובה", citations: [] })),
    );

    await expect(sendChatMessage("שאלה", [])).resolves.toEqual({
      answer: "תשובה",
      citations: [],
    });
  });

  it.each([400, 422, 502, 503])("surfaces HTTP %s without exposing response details", async (status) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(apiResponse(status, { detail: "private" })));

    await expect(sendChatMessage("שאלה", [])).rejects.toMatchObject({
      status,
      kind: "http",
    });
  });

  it("reports invalid JSON explicitly", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(apiResponse(200, null, true)));

    await expect(sendChatMessage("שאלה", [])).rejects.toMatchObject({
      kind: "invalid-response",
    });
  });

  it.each([
    null,
    {},
    { answer: "", citations: [] },
    { answer: "תשובה" },
    { answer: "תשובה", citations: [{ title: "חסר קישור" }] },
  ])("rejects malformed response shapes: %j", async (body) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(apiResponse(200, body)));

    await expect(sendChatMessage("שאלה", [])).rejects.toBeInstanceOf(ChatApiError);
  });

  it("sends follow-up history in chronological order", async () => {
    const history: ChatMessage[] = Array.from({ length: 8 }, (_, index) => ({
      role: index % 2 === 0 ? "user" : "assistant",
      content: `message-${index}`,
    })) as ChatMessage[];
    const fetchMock = vi.fn().mockResolvedValue(
      apiResponse(200, { answer: "תשובה", citations: [] }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const recentHistory = getConversationHistory(history);

    await sendChatMessage("שאלת המשך", recentHistory);

    expect(recentHistory.map(({ content }) => content)).toEqual([
      "message-2",
      "message-3",
      "message-4",
      "message-5",
      "message-6",
      "message-7",
    ]);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).history).toEqual(recentHistory);
  });

  it("keeps invalid or unsafe citation URLs non-clickable", () => {
    expect(safeCitationUrl("https://example.com/page")).toBe("https://example.com/page");
    expect(safeCitationUrl("http://example.com/page")).toBe("http://example.com/page");
    expect(safeCitationUrl("javascript:alert(1)")).toBeNull();
    expect(safeCitationUrl("data:text/html,unsafe")).toBeNull();
    expect(safeCitationUrl("not a url")).toBeNull();
  });

  it("treats a cancelled health check as an unavailable status without rejecting", async () => {
    const controller = new AbortController();
    controller.abort();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new DOMException("Aborted", "AbortError")),
    );

    await expect(checkApiHealth(controller.signal)).resolves.toBe(false);
  });
});
