import type { FormEvent, KeyboardEvent } from "react";
import { useRef } from "react";

interface ChatComposerProps {
  value: string;
  isPending: boolean;
  onChange: (value: string) => void;
  onSubmit: (question: string) => Promise<boolean>;
}

export function ChatComposer({ value, isPending, onChange, onSubmit }: ChatComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  async function submit() {
    const question = value.trim();
    if (!question || question.length > 4_000 || isPending) {
      return;
    }

    const focusedElement = document.activeElement;
    const succeeded = await onSubmit(question);
    if (succeeded) {
      onChange("");
      if (
        document.activeElement === focusedElement ||
        document.activeElement === document.body
      ) {
        textareaRef.current?.focus();
        textareaRef.current?.setSelectionRange(0, 0);
      }
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submit();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void submit();
    }
  }

  const remaining = 4_000 - value.length;
  const overLimit = remaining < 0;

  return (
    <form className="composer" onSubmit={handleSubmit}>
      <label className="sr-only" htmlFor="question-input">
        כתיבת שאלה
      </label>
      <textarea
        ref={textareaRef}
        id="question-input"
        rows={1}
        maxLength={4_000}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="כתבו כאן את השאלה שלכם..."
        disabled={isPending}
        aria-describedby="composer-hint character-count"
      />
      <div className="composer__bottom">
        <span className="composer__hint" id="composer-hint">
          <kbd>Enter</kbd> לשליחה <span aria-hidden="true">·</span>{" "}
          <kbd>Shift + Enter</kbd> לשורה חדשה
        </span>
        <span
          className={`character-count${overLimit ? " character-count--error" : ""}`}
          id="character-count"
          aria-live="polite"
        >
          {value.length.toLocaleString("he-IL")} / 4,000
        </span>
        <button
          className="send-button"
          type="submit"
          disabled={isPending || !value.trim() || overLimit}
          aria-label={isPending ? "השאלה נשלחת" : "שליחת שאלה"}
        >
          {isPending ? (
            <span className="send-spinner" aria-hidden="true" />
          ) : (
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M5 12h14M13 5l7 7-7 7" />
            </svg>
          )}
        </button>
      </div>
    </form>
  );
}
