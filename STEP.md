# STEP.md - Build steps for a Hebrew RAG chatbot

Status: IN PROGRESS

## Part A - Terminal bot on ~5 pages

| #   | Step                        | Status | Notes                                                                                                                                                                                      |
| --- | --------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | Setup                       | DONE   | Added pyproject.toml, .gitignore, README.md, and backend.check_setup. Installed dependencies; credentials and SOURCE_URL still need to be configured in the local .env.                    |
| 2   | Scraper                     | DONE   | Added a same-host sample crawler with robots.txt checks, throttling, HTML text extraction, JSON output, and CLI options. Target URL still needs to be configured in .env.                  |
| 3   | Chunker                     | DONE   | Added text cleaning, paragraph/sentence-aware splitting, configurable overlap, stable chunk IDs and source metadata, plus JSON CLI output to data/chunks/chunks.json.                      |
| 4   | Embeddings                  | DONE   | Added Gemini embedding service with batched document vectors, retrieval-query vectors, configurable model/dimensions, validation, and JSON CLI output to data/chunks/embedded_chunks.json. |
| 5   | Supabase table + repository | DONE   | Added pgvector schema with 768-dimensional cosine search and a validated Supabase repository for batched upserts and vector search. Apply supabase/schema.sql in the Supabase SQL Editor.  |
| 6   | Embed and upload            | DONE   | Added batched Gemini embedding and Supabase upsert CLI with input validation and dry-run. Requires Gemini/Supabase credentials and the schema applied in Supabase.                         |
| 7   | Retrieval                   | DONE   | Added query embedding, Supabase vector search, result validation, and configurable similarity threshold/top-k in backend/services/retrieval_service.py. Requires populated Supabase data.  |
| 8   | Generation                  | DONE   | Added Hebrew Gemini generation grounded only in retrieved excerpts, fixed no-context response, bounded context, and citations restricted to supplied source URLs.                          |
| 9   | Chat service with history   | DONE   | Added Pydantic chat schemas, bounded conversation history, Gemini follow-up question rewriting, and orchestration of retrieval plus grounded generation.                                   |

## Part B - Backend API

| #   | Step                          | Status | Notes                                                                                                                                               |
| --- | ----------------------------- | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| 10  | FastAPI /chat                 | DONE   | Added FastAPI POST /chat, GET /health, request/response schemas, lazy chat-service initialization, and documented local run command.                |
| 11  | Retry with backoff on 429/503 | DONE   | Added configurable exponential backoff with jitter for Gemini embedding/generation and Supabase upsert/search calls; retries only HTTP 429 and 503. |

## Part C - Full data

| #   | Step                             | Status | Notes                                                                                                                                                                              |
| --- | -------------------------------- | ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 12  | Full crawl from the sitemap      | DONE   | Added XML sitemap and sitemap-index discovery, same-host filtering, robots.txt checks, throttling, and explicit --all mode; default remains limited to 5 pages.                    |
| 13  | One-command incremental pipeline | DONE   | Streams sitemap pages through chunking/embedding/upload, checkpoints each successful page, resumes after interruption, and deletes removed pages only after a complete full crawl. |

## Part D - Quality

| #   | Step                     | Status | Notes                                                                                                                                                                                                                          |
| --- | ------------------------ | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 14  | Eval set (~30 questions) | DONE   | Added 20 source-grounded Phoenix questions and 10 abstention/safe-referral cases, plus a retrieval runner for expected-source recall and unanswerable-query abstention.                                                        |
| 15  | Tune retrieval           | DONE   | Uploaded 242 chunks and verified all five expected evaluation pages. Live sweep selected TOP_K=3 and threshold=0.74 (70% answerable recall, 90% unanswerable abstention); see data/eval/retrieval_results.json. |
| 16  | Safeguards + backup LLM  | DONE   | Added deterministic guardrails for personal policy/claim data, medical/legal advice, and instruction overrides; optional OpenRouter fallback for transient Gemini failures. Phrase guards require review against real traffic. |
| 17  | Tests and logging        | DONE   | Added privacy-safe JSON request/pipeline logs and expanded unit tests across API, chunker, embeddings, retrieval, repository, eval, safeguards, retries, and ingestion.                                                        |
| 18  | Refresh job + README     | TODO   | Scheduled refresh with log of added/updated/removed pages.                                                                                                                                                                     |

## Part E - Frontend and hosting

| #   | Step                 | Status | Notes                                                                                                                                                                        |
| --- | -------------------- | ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 19  | Frontend and hosting | IN PROGRESS | Implemented Hebrew RTL React chat UI, API integration, bounded history/retry/cancellation, responsive citations, and 24 frontend tests. Production hosting/CORS decision remains. |
