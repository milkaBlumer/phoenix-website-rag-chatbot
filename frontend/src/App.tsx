import { useEffect, useRef, useState } from "react";
import { checkApiHealth } from "./api/chat";
import { ChatComposer } from "./components/ChatComposer";
import { MessageList } from "./components/MessageList";
import { useChat } from "./hooks/useChat";
import "./App.css";

const exampleQuestions = [
  "איך אפשר לקבל מידע על השירותים?",
  "איפה אפשר למצוא מידע באתר?",
  "אפשר לעזור לי להבין נושא מסוים?",
];

function App() {
  const { messages, pendingQuestion, failure, isPending, send, retry } = useChat();
  const [draft, setDraft] = useState("");
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const composerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    void checkApiHealth(controller.signal).then((online) => {
      if (active) {
        setApiOnline(online);
      }
    });
    return () => {
      active = false;
      controller.abort();
    };
  }, []);

  useEffect(() => {
    if (isPending) {
      setAnnouncement("השאלה נשלחת, מחפשים מידע רלוונטי.");
    } else if (messages.length > 0) {
      setAnnouncement("התשובה התקבלה.");
    } else {
      setAnnouncement("");
    }
  }, [isPending, messages.length]);

  async function handleRetry() {
    if (!failure) {
      return;
    }
    const question = failure.question;
    const succeeded = await retry();
    if (succeeded) {
      setDraft((current) => (current.trim() === question ? "" : current));
      setAnnouncement("התשובה התקבלה.");
    }
  }

  function useExample(question: string) {
    setDraft(question);
    composerRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    window.setTimeout(() => {
      composerRef.current?.querySelector("textarea")?.focus();
    }, 180);
  }

  return (
    <div className="app-shell" dir="rtl">
      <header className="topbar">
        <a className="brand" href="/" aria-label="הפניקס, עוזר דיגיטלי">
          <span className="brand__mark" aria-hidden="true">
            <svg viewBox="0 0 40 40">
              <path d="M20 3 34 8v11c0 9-5.6 14.5-14 18-8.4-3.5-14-9-14-18V8l14-5Z" />
              <path d="M11.5 14.5a4 4 0 0 1 4-4h9a4 4 0 0 1 4 4v5a4 4 0 0 1-4 4H19l-5 4v-4.2a4 4 0 0 1-2.5-3.8v-5Z" />
              <path d="M17 17h.01m3.5 0h.01m3.5 0h.01" />
            </svg>
          </span>
          <span className="brand__text">
            <strong>הפניקס</strong>
            <span>העוזר הדיגיטלי</span>
          </span>
        </a>
        <div
          className={`connection-status${apiOnline === false ? " connection-status--offline" : ""}`}
          role="status"
          aria-live="polite"
        >
          <span className="connection-status__dot" aria-hidden="true" />
          <span>
            {apiOnline === null
              ? "בודקים חיבור"
              : apiOnline
                ? "השירות זמין"
                : "לא ניתן לבדוק זמינות"}
          </span>
        </div>
      </header>

      <main className="main-content">
        {apiOnline === false && (
          <div className="connection-notice" role="status">
            כרגע לא הצלחנו לבדוק את זמינות השירות. אפשר עדיין לנסות לשלוח שאלה.
          </div>
        )}

        <MessageList
          messages={messages}
          pendingQuestion={pendingQuestion}
          isPending={isPending}
        />

        {messages.length === 0 && !pendingQuestion && (
          <div className="example-actions">
            {exampleQuestions.map((question) => (
              <button
                className="example-action"
                key={question}
                type="button"
                onClick={() => useExample(question)}
              >
                <span>{question}</span>
                <svg viewBox="0 0 20 20" aria-hidden="true">
                  <path d="M4 10h12m-5-5 5 5-5 5" />
                </svg>
              </button>
            ))}
          </div>
        )}

        {failure && (
          <div className="request-error" role="alert" aria-live="assertive">
            <div className="request-error__icon" aria-hidden="true">
              !
            </div>
            <div className="request-error__text">
              <strong>לא הצלחנו לקבל תשובה</strong>
              <span>{failure.message}</span>
            </div>
            <button
              className="retry-button"
              type="button"
              onClick={() => void handleRetry()}
              disabled={isPending}
            >
              <svg viewBox="0 0 20 20" aria-hidden="true">
                <path d="M16 9a6 6 0 0 0-10.8-3L3 8m0-4v4h4m-3 3a6 6 0 0 0 10.8 3L17 12m0 4v-4h-4" />
              </svg>
              ניסיון חוזר
            </button>
          </div>
        )}

        <div className="composer-wrap" ref={composerRef}>
          <ChatComposer
            value={draft}
            isPending={isPending}
            onChange={setDraft}
            onSubmit={send}
          />
          <p className="disclaimer">
            תשובות העוזר מבוססות על המידע הזמין באתר. מומלץ לבדוק את המקורות
            המצורפים.
          </p>
        </div>
      </main>

      <div className="sr-only" role="status" aria-live="polite">
        {announcement}
      </div>

    </div>
  );
}

export default App;
