import { useCallback, useEffect, useRef, useState } from "react";
import {
  ChatApiError,
  getConversationHistory,
  sendChatMessage,
  type ChatMessage,
} from "../api/chat";

export interface ChatFailure {
  question: string;
  history: ChatMessage[];
  message: string;
}

export interface ChatItem extends ChatMessage {
  citations?: { title: string; url: string }[];
}

function getErrorMessage(error: unknown): string {
  if (error instanceof ChatApiError) {
    if (error.status === 400 || error.status === 422) {
      return "נראה שהשאלה לא נשלחה בצורה תקינה. כדאי לבדוק אותה ולנסות שוב.";
    }
    if (error.status === 502 || error.status === 503) {
      return "השירות לא זמין כרגע. אפשר לנסות שוב בעוד רגע.";
    }
    if (error.kind === "network") {
      return "לא הצלחנו להתחבר לשירות. כדאי לבדוק את החיבור ולנסות שוב.";
    }
    if (error.kind === "invalid-response") {
      return "קיבלנו תשובה לא תקינה מהשירות. אפשר לנסות שוב.";
    }
  }
  return "משהו השתבש בשליחת השאלה. אפשר לנסות שוב.";
}

export function useChat() {
  const [messages, setMessages] = useState<ChatItem[]>([]);
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [failure, setFailure] = useState<ChatFailure | null>(null);
  const [isPending, setIsPending] = useState(false);
  const messagesRef = useRef<ChatItem[]>([]);
  const pendingRef = useRef(false);
  const mountedRef = useRef(false);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      controllerRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  const send = useCallback(async (question: string, history?: ChatMessage[]) => {
    if (pendingRef.current) {
      return false;
    }

    const normalizedQuestion = question.trim();
    if (!normalizedQuestion || normalizedQuestion.length > 4_000) {
      return false;
    }

    const requestHistory = history ?? getConversationHistory(messagesRef.current);
    const snapshot = requestHistory.map(({ role, content }) => ({ role, content }));
    const controller = new AbortController();
    controllerRef.current = controller;
    pendingRef.current = true;
    setIsPending(true);
    setPendingQuestion(normalizedQuestion);
    setFailure(null);

    try {
      const response = await sendChatMessage(normalizedQuestion, snapshot, controller.signal);
      if (!mountedRef.current || controller.signal.aborted) {
        return false;
      }

      const nextMessages = [
        ...messagesRef.current,
        { role: "user" as const, content: normalizedQuestion },
        {
          role: "assistant" as const,
          content: response.answer,
          citations: response.citations,
        },
      ];
      messagesRef.current = nextMessages;
      setMessages(nextMessages);
      return true;
    } catch (error) {
      if (!controller.signal.aborted && mountedRef.current) {
        setFailure({
          question: normalizedQuestion,
          history: snapshot,
          message: getErrorMessage(error),
        });
      }
      return false;
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null;
      }
      pendingRef.current = false;
      if (mountedRef.current) {
        setIsPending(false);
        setPendingQuestion(null);
      }
    }
  }, []);

  const retry = useCallback(() => {
    if (!failure) {
      return Promise.resolve(false);
    }
    return send(failure.question, failure.history);
  }, [failure, send]);

  return { messages, pendingQuestion, failure, isPending, send, retry };
}
