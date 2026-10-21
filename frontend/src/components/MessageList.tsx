import { useEffect, useRef } from "react";
import type { ChatItem } from "../hooks/useChat";
import { CitationList } from "./CitationList";

interface MessageListProps {
  messages: ChatItem[];
  pendingQuestion: string | null;
  isPending: boolean;
}

export function MessageList({ messages, pendingQuestion, isPending }: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const nearBottomRef = useRef(true);

  useEffect(() => {
    if (nearBottomRef.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, pendingQuestion, isPending]);

  function updateScrollPosition() {
    const element = scrollRef.current;
    if (!element) {
      return;
    }
    nearBottomRef.current =
      element.scrollHeight - element.scrollTop - element.clientHeight < 120;
  }

  return (
    <div
      className="conversation-scroll"
      ref={scrollRef}
      onScroll={updateScrollPosition}
      aria-label="הודעות בשיחה"
    >
      {messages.length === 0 && !pendingQuestion ? (
        <section className="welcome" aria-labelledby="welcome-title">
          <div className="welcome__icon" aria-hidden="true">
            <svg viewBox="0 0 48 48">
              <path d="M24 5 40 11v12c0 10-6.5 16-16 20C14.5 39 8 33 8 23V11l16-6Z" />
              <path d="m17 24 5 5 10-11" />
            </svg>
          </div>
          <p className="eyebrow">העוזר הדיגיטלי של הפניקס</p>
          <h1 id="welcome-title">שלום, במה אפשר לעזור?</h1>
          <p className="welcome__description">
            אפשר לשאול שאלה על המידע באתר, וננסה לכוון אתכם למידע הרלוונטי.
          </p>
          <p className="welcome__suggestion-hint">אפשר להתחיל למשל עם אחת מהשאלות למטה</p>
        </section>
      ) : (
        <div className="message-list" aria-live="off">
          {messages.map((message, index) => (
            <article
              className={`message message--${message.role}`}
              key={`${message.role}-${index}`}
            >
              {message.role === "assistant" && (
                <div className="assistant-avatar" aria-hidden="true">
                  ה
                </div>
              )}
              <div className="message__content">
                {message.role === "assistant" && (
                  <span className="message__author">העוזר הדיגיטלי</span>
                )}
                <div className="message__bubble" dir="auto">
                  {message.content}
                </div>
                {message.role === "assistant" && message.citations && (
                  <CitationList citations={message.citations} />
                )}
              </div>
            </article>
          ))}
          {pendingQuestion && (
            <>
              <article className="message message--user">
                <div className="message__content">
                  <div className="message__bubble" dir="auto">
                    {pendingQuestion}
                  </div>
                </div>
              </article>
              {isPending && (
                <article className="message message--assistant" aria-label="העוזר מקליד">
                  <div className="assistant-avatar" aria-hidden="true">
                    ה
                  </div>
                  <div className="typing-indicator" aria-hidden="true">
                    <span />
                    <span />
                    <span />
                  </div>
                </article>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
