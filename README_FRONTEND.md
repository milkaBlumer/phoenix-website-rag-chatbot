# Frontend plan — Hebrew RAG chatbot

This document is the implementation roadmap for the chatbot frontend. It is
intentionally split into small, verifiable tasks so the frontend can be built
incrementally without changing the existing chat API contract.

## Product goal

Build a responsive, accessible, Hebrew right-to-left chat interface that lets a
visitor submit a question, see the answer, and open its source citations. Keep
the first version focused: no user accounts, persistent chat storage, or
streaming responses.

## Technology choices

- **React** for the interactive chat interface.
- **TypeScript** for typed API and UI state.
- **Vite** for the frontend development server and production build.
- **CSS** (or CSS modules) for a lightweight responsive layout and RTL support.
- **Vitest and React Testing Library** for frontend unit/component tests.
- **Playwright** for a small end-to-end smoke test, if browser-test tooling is
  available in the project environment.

The frontend is a separate application from the existing Python project. Keep
its dependencies and scripts in a frontend-specific `package.json`; do not add
frontend packages to `pyproject.toml`.

## Architecture

```text
Browser
  └── React UI
       ├── Chat state (messages, pending request, error)
       ├── Chat components (header, message list, composer, citations)
       └── API client
            └── POST /chat
                 └── FastAPI
                      └── ChatService → retrieval and grounded generation
```

Suggested frontend modules:

```text
frontend/
  src/
    api/
      chat.ts          # Typed request/response and POST /chat
    components/
      ChatHeader.tsx
      MessageList.tsx
      ChatMessage.tsx
      ChatComposer.tsx
      CitationList.tsx
    hooks/
      useChat.ts       # Conversation state and submit/retry behavior
    App.tsx
    main.tsx
    styles/
      global.css
  index.html
  package.json
  vite.config.ts
```

Names and component boundaries can be adjusted to match the implementation,
but keep API transport separate from rendering and conversation state.

### Request lifecycle

1. The visitor submits a non-empty question.
2. The composer disables duplicate submission and displays a loading state.
   Guard the submit handler as well as the button so rapid clicks or Enter
   events cannot start concurrent requests.
3. The API client sends the question and the most recent six _previous_
   successful messages (individual user/assistant messages, not six turns) as
   `history`, in chronological order.
4. On success, append the user's question and assistant answer to the visible
   conversation; render any valid citations from the response.
5. On failure, retain the question and show a clear error with a retry action
   that resends that exact question with the same history snapshot. Do not add
   a failed turn to the history sent with later requests.
6. Abort the in-flight fetch when the chat view is disposed. If the visitor
   navigates away or reloads the page, the request may be cancelled and the
   unsent/in-flight question is not persisted; do not claim that the server
   operation was rolled back.

Keep the complete conversation visible in the UI for the current browser
session. The backend currently uses at most six history messages for follow-up
question rewriting, so send only those six previous messages. Do not persist
the conversation across reloads in the first version. A successful answer with
no citations is still a successful turn: include both its user question and
assistant answer in later history. A failed request is not a successful turn
and neither its question nor an error/loading placeholder goes into history.

## Existing API contract

The frontend should integrate with the existing FastAPI API; do not change the
contract for frontend convenience.

### `POST /chat`

Request:

```json
{
  "question": "מה השירות כולל?",
  "history": [
    { "role": "user", "content": "ספר לי על השירות" },
    { "role": "assistant", "content": "..." }
  ]
}
```

Response:

```json
{
  "answer": "תשובה בעברית...",
  "citations": [{ "title": "שם המקור", "url": "https://example.com/page" }]
}
```

Relevant behavior and constraints:

- `question` is required, non-blank, and limited to 4,000 characters.
- `history` contains `{role, content}` messages, where `role` is `user` or
  `assistant`; the API accepts up to 20 messages and the chat service uses the
  latest six.
- The response contains an answer and zero or more citations.
- `GET /health` provides a basic API liveness check.
- FastAPI returns `422` when the request body fails schema validation (for
  example, an empty question or an invalid history item). The controller may
  return `400` for application-level invalid input, `503` when the chatbot
  cannot complete a request, or `502` when a required upstream service is
  unavailable. The UI should show a helpful message without exposing raw
  server/provider details.

The source of truth is
[`backend/models/schemas.py`](backend/models/schemas.py) and
[`backend/controllers/chat_controller.py`](backend/controllers/chat_controller.py).

## Backend/frontend compatibility notes

- The chat request/response contract and bounded conversation history are
  already supported by the backend. The frontend must still enforce its own
  interaction rules: send no more than the latest six successful prior
  messages, in chronological order, and exclude failed turns.
- Treat an answer with an empty citations array as a successful response.
  Citations are not required for a successful turn, and that turn's user and
  assistant messages remain eligible for later history.
- Handle `400`, `422`, `502`, and `503` responses, network failures, malformed
  JSON, and invalid response shapes explicitly. Do not display raw provider
  error text to the visitor.
- The backend currently checks that a citation URL is non-empty, but does not
  enforce an `http:` or `https:` protocol. The frontend must validate citation
  URLs before making them clickable, render answer text as text rather than
  active HTML, and use `rel="noopener noreferrer"` for links opened in a new
  tab.
- Browser cancellation only aborts the frontend's fetch and prevents stale UI
  updates; it does not guarantee that FastAPI or its upstream AI/data calls
  stop processing the request. Do not mark a cancelled request as a confirmed
  server-side rollback.
- The existing backend does not currently configure CORS middleware. Local
  development should use the Vite `/chat` and `/health` proxy. If production
  serves the frontend and API from different origins, either configure
  explicit allowed origins in FastAPI or route both through a same-origin
  reverse proxy; do not rely on wildcard CORS.

## Implementation tasks

Complete tasks in order unless a dependency is explicitly marked otherwise.
Keep these checkboxes current as implementation proceeds.

### 1. Bootstrap the frontend

- [x] Create the Vite React TypeScript app under `frontend/`.
- [x] Add frontend-specific development, build, preview, and test scripts.
- [x] Add a Vite development proxy for `/chat` and `/health` to the local
      FastAPI server at `http://127.0.0.1:8000`.
- [x] Add or verify ignores for `node_modules/` and generated build output.
- [x] Confirm the app starts and the production build completes.

**Done when:** a clean frontend install can start the Vite server and produce a
build without changing the Python dependency manifest.

### 2. Define API types and transport

- [x] Define TypeScript types for chat messages, requests, citations, and
      responses matching the API contract.
- [x] Implement a small API client for `POST /chat`.
- [x] Validate HTTP status and response shape; surface failures to the caller
      rather than returning an empty or success-shaped fallback.
- [x] Treat malformed JSON, missing/invalid required fields, and malformed
      citation entries (including a missing URL) as explicit response errors; do
      not silently fabricate answer text or source URLs.
- [x] Keep the API base URL configurable for development and deployment; never
      put Gemini, Supabase, or other server credentials in frontend configuration.
- [x] Support an `AbortSignal` so in-flight requests can be cancelled when the
      owning view is disposed.
- [x] Add contract tests for valid answers with and without citations, `400`,
      `422`, `502`, and `503` responses, malformed JSON, missing fields, follow-up
      history, and citation payloads with missing URLs. Also verify that a
      structurally valid citation with an unsafe or malformed URL is not rendered
      as a clickable link.

**Done when:** API behavior can be tested independently of React components.

### 3. Build the chat layout and visual foundation

- [x] Set the page language to Hebrew and document direction to RTL.
- [x] Create a compact header with the chatbot name and a short description.
- [x] Add an empty-state welcome message and optional example question.
- [x] Create a scrollable conversation area and a composer anchored to the
      bottom on small screens.
- [x] Style readable user/assistant messages, spacing, focus indicators, and
      responsive mobile/desktop layouts.
- [x] Verify keyboard navigation and accessible names for interactive controls.

**Done when:** the layout is usable at mobile and desktop widths and supports
RTL text without reversing URLs or citation links.

### 4. Implement the message composer

- [x] Add a multiline text input with a clear placeholder and visible send
      button.
- [x] Disable sending for blank input and while a request is pending.
- [x] Enforce the API's 4,000-character question limit and communicate the
      remaining/maximum length accessibly.
- [x] Support Enter to send and Shift+Enter for a new line.
- [x] Clear the input only after the request has been accepted for processing;
      retain the question if the request fails.
- [x] After a successful send, keep focus in the composer and place the caret
      predictably for the next message; do not steal focus if the visitor moved it
      while the request was running.
- [x] Add component tests for keyboard behavior, validation, and disabled
      states.

**Done when:** a visitor can submit a valid question by keyboard or button and
cannot accidentally submit a blank or duplicate request.

### 5. Implement conversation state and submission

- [x] Create a chat hook or equivalent state module for successful messages,
      pending status, and request errors.
- [x] Keep all successful turns in the visible conversation, but send only the
      latest six successful prior messages (up to three complete turns) as
      `history`, excluding the question currently being submitted.
- [x] Preserve chronological order in `history` (oldest to newest within the
      selected six messages).
- [x] Append a user/assistant pair to the visible history only after a
      successful response.
- [x] Treat an answer with an empty citations array as a successful turn and
      include its user and assistant messages in subsequent history.
- [x] Keep failed questions available for an explicit retry that resends the
      same question and the same history snapshot; never include failed turns in
      subsequent history.
- [x] Cancel the in-flight request on view disposal, and ignore any late
      completion after cancellation or disposal.
- [x] Auto-scroll only if the visitor was already near the bottom before new
      content arrived; otherwise preserve their reading position.
- [x] Test chronological six-message truncation, a follow-up after an
      uncited-but-successful answer, failed-turn exclusion, retries, cancellation,
      and duplicate-submit prevention.

**Done when:** follow-up questions use the expected prior context and failed
requests do not corrupt conversation state; the full successful transcript
remains visible independently of the bounded request history.

### 6. Render answers, citations, loading, and errors

- [x] Render assistant and user messages distinctly while preserving readable
      Hebrew/RTL formatting.
- [x] Display a clear in-progress indicator while the API request is pending.
- [x] Render citation titles as links, falling back to the URL when the title is
      empty; render only `http:` and `https:` URLs and open external links in a new
      tab with `rel="noopener noreferrer"`. Invalid or missing citation URLs must
      not become clickable links.
- [x] Render server-provided answer text as text, not executable HTML. Do not
      use `dangerouslySetInnerHTML`; if Markdown rendering is added later, disable
      raw HTML and sanitize/validate generated link protocols.
- [x] Show an explicit no-citations state only when useful; do not invent
      citations or imply the answer has sources when none were returned.
- [x] Map expected API/network failures to concise Hebrew messages and provide a
      retry action where appropriate.
- [x] Ensure loading and error states are announced through appropriate
      `aria-live` regions without repeatedly announcing the entire conversation.
- [x] Check display of URLs, code snippets, and mixed Hebrew/English text so
      bidirectional rendering remains readable.

**Done when:** all API response states have a clear, accessible representation.

### 7. Connect local development and deployment configuration

- [x] Document how to start the FastAPI backend and frontend in separate
      terminals.
- [x] Verify the Vite proxy sends API requests to the backend during local
      development.
- [ ] For production, choose either same-origin reverse proxying or a separate
      frontend/API origin with an explicit allowed-origin CORS configuration.
- [ ] If using separate origins, add explicit allowed-origin CORS middleware
      to FastAPI and configure the production API origin in the frontend. If using
      a same-origin reverse proxy, verify it forwards `/chat` and `/health`
      correctly.
- [ ] Keep production API origin configuration environment-specific and avoid
      wildcard CORS.
- [ ] Confirm health and chat requests work in the selected deployment setup.

**Done when:** local development and the selected hosting arrangement can
communicate without exposing backend secrets or relying on permissive CORS.

### 8. Verify and document the frontend

- [x] Run frontend unit/component tests and the production build.
- [x] Run an end-to-end smoke test for question submission, answer rendering,
      and citation navigation when browser tooling is available.
- [x] Verify the backend contract for success with and without citations,
      `400`/`422`/`502`/`503`, malformed JSON and missing fields, follow-up history, and
      citations with missing URLs. Verify unsafe/malformed URLs are never clickable.
- [x] Manually check RTL, mobile layout, keyboard interaction, empty input,
      focus/caret behavior, pending state, duplicate-submit prevention, API
      failure, retry, and request cancellation on navigation.
- [x] Check mixed-direction URLs/code, `aria-live` announcements, and that
      auto-scroll preserves position when the visitor is reading older messages.
- [x] Add frontend setup and run instructions to this document or the root
      project README.
- [x] Update [`STEP.md`](STEP.md) when frontend implementation begins and when
      the frontend milestone is complete.

**Done when:** checks pass, the main user flow is verified, and a new
contributor can run the frontend from the documented steps.

## Local development (target workflow)

Run the backend from the project root:

```powershell
python -m uvicorn backend.main:app --reload
```

Run the frontend in another terminal:

```powershell
Set-Location frontend
npm install
npm run dev
```

The Vite proxy routes `/chat` and `/health` to the backend, so local browser
requests can use same-origin relative paths. `VITE_API_BASE_URL` may be set in a
frontend-local `.env` file for a deployment that uses a separate API origin.

## Out of scope for the first version

- User accounts, authentication, and server-side conversation storage.
- Conversation persistence across browser reloads.
- Streaming or token-by-token responses.
- Uploads, voice input, model selection, or user-adjustable retrieval settings.
- Direct browser connections to Gemini, OpenRouter, or Supabase.
