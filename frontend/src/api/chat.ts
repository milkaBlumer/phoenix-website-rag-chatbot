export type ChatRole = "user" | "assistant";

export interface ChatMessage {
  role: ChatRole;
  content: string;
}

export interface Citation {
  title: string;
  url: string;
}

export interface ChatResponse {
  answer: string;
  citations: Citation[];
}

export interface ChatRequest {
  question: string;
  history: ChatMessage[];
}

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";

export class ChatApiError extends Error {
  readonly status?: number;
  readonly kind: "http" | "network" | "invalid-response";

  constructor(
    message: string,
    status?: number,
    kind: "http" | "network" | "invalid-response" = "http",
  ) {
    super(message);
    this.name = "ChatApiError";
    this.status = status;
    this.kind = kind;
  }
}

export function getConversationHistory(messages: ChatMessage[]): ChatMessage[] {
  return messages.slice(-6).map(({ role, content }) => ({ role, content }));
}

function parseChatResponse(value: unknown): ChatResponse {
  if (!value || typeof value !== "object") {
    throw new ChatApiError("Invalid response body.", undefined, "invalid-response");
  }

  const response = value as Record<string, unknown>;
  if (typeof response.answer !== "string" || !response.answer.trim()) {
    throw new ChatApiError("Response is missing an answer.", undefined, "invalid-response");
  }
  if (!Array.isArray(response.citations)) {
    throw new ChatApiError("Response is missing citations.", undefined, "invalid-response");
  }

  const citations = response.citations.map((item): Citation => {
    if (!item || typeof item !== "object") {
      throw new ChatApiError("Response contains an invalid citation.", undefined, "invalid-response");
    }
    const citation = item as Record<string, unknown>;
    if (
      typeof citation.title !== "string" ||
      typeof citation.url !== "string" ||
      !citation.url.trim()
    ) {
      throw new ChatApiError("Response contains an invalid citation.", undefined, "invalid-response");
    }
    return { title: citation.title, url: citation.url };
  });

  const answer = stripSourceMarkers(response.answer) || response.answer;
  return { answer, citations };
}

const SOURCE_MARKER = /\s*\[\s*SOURCE\s*\d+(?:\s*,\s*SOURCE\s*\d+)*\s*\]/gi;

export function stripSourceMarkers(text: string): string {
  return text.replace(SOURCE_MARKER, "").trim();
}

async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}${path}`, { signal });
  } catch (error) {
    if (signal?.aborted) {
      throw error;
    }
    throw new ChatApiError("Unable to reach the chat API.", undefined, "network");
  }

  if (!response.ok) {
    throw new ChatApiError("The chat API returned an error.", response.status);
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw new ChatApiError("The API response was not valid JSON.", response.status, "invalid-response");
  }
}

export async function sendChatMessage(
  question: string,
  history: ChatMessage[],
  signal?: AbortSignal,
): Promise<ChatResponse> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, history } satisfies ChatRequest),
      signal,
    });
  } catch (error) {
    if (signal?.aborted) {
      throw error;
    }
    throw new ChatApiError("Unable to reach the chat API.", undefined, "network");
  }

  if (!response.ok) {
    throw new ChatApiError("The chat API returned an error.", response.status);
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ChatApiError("The API response was not valid JSON.", response.status, "invalid-response");
  }
  return parseChatResponse(body);
}

export async function checkApiHealth(signal?: AbortSignal): Promise<boolean> {
  try {
    const body = await request<unknown>("/health", signal);
    return Boolean(
      body &&
        typeof body === "object" &&
        "status" in body &&
        body.status === "ok",
    );
  } catch {
    return false;
  }
}

export function safeCitationUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}
