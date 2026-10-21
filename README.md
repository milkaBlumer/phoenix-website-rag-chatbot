# Hebrew RAG Chatbot

A Hebrew retrieval-augmented generation chatbot. Initial setup and a small, same-site web scraper are implemented.

## Requirements

- Python 3.11 or newer
- Node.js and npm (for the frontend)
- A Google Gemini API key
- Supabase project credentials (needed for vector storage)

## Setup

1. Create and activate a virtual environment:

   ```powershell
   py -3.11 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install the project and development tools:

   ```powershell
   python -m pip install --upgrade pip
   pip install -e ".[dev]"
   ```

3. Create or edit `.env` in the project root and fill in `GEMINI_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`, and `SOURCE_URL`. Keep secret values in this local file only.

4. Run the initial configuration check:

   ```powershell
   python -m backend.check_setup
   ```

## Scrape a small sample

Set `SOURCE_URL` in `.env` to the site's starting page, then run:

```powershell
python -m backend.ingestion.scraper --limit 5
```

The scraper follows same-host links, checks `robots.txt`, waits between pages, and saves extracted page data as JSON under `data/raw/`. You can provide a start URL directly or change the page limit and output directory with `--limit` and `--output`. Review the site's terms and crawling policy before running it.

To read page URLs from an XML sitemap or sitemap index, pass its URL with `--sitemap`. The default remains limited to five pages; `--all` explicitly requests every same-host page URL discovered in the sitemap:

```powershell
python -m backend.ingestion.scraper https://example.com/sitemap.xml --sitemap --limit 20
python -m backend.ingestion.scraper https://example.com/sitemap.xml --all
```

Replace the example URL with the site's sitemap. Full crawls can take a long time and are still subject to `robots.txt` and the one-second delay between pages.

## Run the incremental ingestion pipeline

Preview up to five pages without calling Gemini or Supabase:

```powershell
python -m backend.ingestion.run --dry-run
```

After configuring Gemini and Supabase and applying the SQL schema, start with a small real sync:

```powershell
python -m backend.ingestion.run --max-pages 5
```

Confirm `select count(*) from public.documents;` is greater than zero in the Supabase SQL Editor. Then run `python -m backend.ingestion.run --full` for the full sitemap. The pipeline streams pages into chunking/embedding/upload and saves a fingerprint after each successful page in `data/state/ingestion.json`; restarting skips embeddings for unchanged pages. Updated pages have stale chunks removed. Pages removed from the sitemap are deleted only when a full crawl fetched every listed page successfully; incomplete full crawls skip removals. Use `--sitemap-url` when the sitemap is not at `/sitemap.xml`, or `--state-file` to choose a different resume-state path.

## Build text chunks

After scraping pages, split them into overlapping chunks for later embedding and retrieval:

```powershell
python -m backend.ingestion.chunker
```

The default reads page JSON files from `data/raw/` and writes `data/chunks/chunks.json`. Adjust `--chunk-size` and `--overlap` to change chunk lengths and context overlap.

## Generate embeddings

Configure `GEMINI_API_KEY` in `.env`, then create document vectors from the chunk file:

```powershell
python -m backend.services.embedding_service
```

The embedding service supports batched document embeddings and individual retrieval-query embeddings. Set `GEMINI_EMBEDDING_MODEL` and `EMBEDDING_DIMENSIONS` in `.env` to control the model and vector size (default: `gemini-embedding-001`, 768 dimensions). Vectors are returned to the caller and are not saved or uploaded by this step.

## Configure Supabase vector storage

In the Supabase SQL Editor, run [`supabase/schema.sql`](supabase/schema.sql) to enable pgvector, create the `documents` table, and add the cosine-similarity search function. The schema uses 768-dimensional vectors, which must match `EMBEDDING_DIMENSIONS`.

The repository in `backend/repositories/vector_repository.py` reads `SUPABASE_URL` and `SUPABASE_KEY` from the environment or `.env`, validates vector records, supports batched upserts, and calls the SQL search function. Use a server-side secret key only in this backend; never expose it in a frontend or commit it to source control.

## Embed and upload chunks

After applying the schema and configuring Gemini and Supabase credentials, run:

```powershell
python -m backend.ingestion.embed_upload
```

This embeds the chunk JSON in batches and upserts it to Supabase. The default batch is five chunks, and requests are spaced using a conservative text-length estimate to target no more than 20,000 tokens per minute. These are estimates rather than provider token counts; Gemini may still reject requests if another process uses the same quota. Use `--batch-size` and `--max-estimated-tokens-per-minute` to adjust the pace, or `--dry-run` to validate the input file without calling external services.

## Retrieve relevant context

Once the vector table contains uploaded chunks, use `RetrievalService` from `backend.services.retrieval_service` to embed a Hebrew question, search Supabase by cosine similarity, and filter results using `RELEVANCE_THRESHOLD`. Configure the number of candidates with `TOP_K` in `.env`. The service returns source text, URL, title, and similarity for each relevant result.

## Generate grounded answers

Use `GenerationService` from `backend.services.generation_service` with the user question and retrieved results. It asks Gemini to answer in Hebrew only from the supplied excerpts, returns the corresponding source URLs as citations, and gives a fixed no-information response when no usable excerpts are supplied. Configure `GEMINI_MODEL` in `.env` to change the generation model.

## Chat with conversation history

Use `ChatService` from `backend.services.chat_service` to connect retrieval and generation for a chat turn. Pass the current question and recent `{role, content}` messages (`role` is `user` or `assistant`). When history is present, Gemini rewrites the follow-up as a standalone search query; history is bounded to the six most recent messages and 12,000 characters.

## Run the API

Start the FastAPI app with:

```powershell
python -m uvicorn backend.main:app --reload
```

The API provides `GET /health` and `POST /chat`. Interactive API documentation is available at `http://127.0.0.1:8000/docs`. The chat endpoint accepts a question and an optional bounded history of user/assistant messages.

Backend logs are emitted as one JSON object per line and include request method/path/status/duration and ingestion counts. Request bodies, user questions, API keys, and free-form provider error text are not included. Set `LOG_LEVEL` in `.env` to `DEBUG`, `INFO`, `WARNING`, or `ERROR`.

## Safety boundaries and backup model

The chat service short-circuits known requests for personal policy/claim details (including questions about whether a policy covers a user's specific incident), medical or legal advice, and attempts to override source-only answering. It returns a fixed safe response and does not query the index or model for those requests. Generic policy and claim-process questions remain eligible for retrieval, even when phrased as questions about the user's policy. These are deterministic phrase checks, not a general-purpose classifier, so they need review against real user questions.

Gemini remains the primary model. To enable optional OpenRouter fallback for Gemini rate limits, server errors, timeouts, or connection failures, set `OPENROUTER_API_KEY` in `.env`. The default backup model is `google/gemma-4-26b-a4b-it:free`; free-model availability and rate limits are controlled by OpenRouter and may change. If setting `OPENROUTER_MODEL` yourself, use a `:free` model to avoid selecting a paid model. The fallback receives the same source-bounded prompt; source citations are still restricted to retrieved URLs. Leave the key blank to disable fallback. Do not send personal policy or claim information to either provider.

## Retry temporary service failures

Gemini embedding/generation calls and Supabase vector operations retry HTTP 429 and 503 failures with exponential backoff and jitter. Configure `RETRY_MAX_ATTEMPTS`, `RETRY_BASE_DELAY_SECONDS`, and `RETRY_MAX_DELAY_SECONDS` in `.env`; the attempt count includes the initial request. Other errors are not retried.

## Evaluate retrieval

The 30-case Phoenix evaluation set is in `data/eval/questions.json`: 20 questions have expected public source pages and answer points, and 10 test abstention or safe referral. The source pages were checked on 2026-10-20; review expected points if the site changes. With the index populated and Gemini/Supabase configured, run:

```powershell
python -m backend.evaluation.retrieval_eval
```

The runner reports expected-source recall, answer-point term coverage within chunks from the expected source, and the rate at which retrieval returns no results for unanswerable questions. Answer-point coverage is a transparent lexical check, not semantic verification or an automatic judgment of generated-answer correctness; manually review the evidence excerpts and missing terms in `data/eval/retrieval_results.json`.

To compare thresholds and result counts without repeating embeddings/searches for each configuration, run:

```powershell
python -m backend.evaluation.retrieval_eval --sweep
```

The sweep compares `TOP_K` values 3, 5, and 10 with similarity thresholds 0.5 through 0.9. Questions blocked by the chat safety policy bypass candidate search, matching production behavior. Override the sweep values with `--top-k-values 3,5,8 --thresholds 0.55,0.65,0.75`. Its balanced score weights source recall, answer-point term coverage, and unanswerable abstention equally; ties prefer the higher threshold and then fewer chunks. Treat the top result as a candidate and review the detailed metrics before changing `.env`. A real sweep requires an indexed dataset and Gemini/Supabase credentials.

To keep the per-question evidence report and the sweep report separately, write the sweep to `data/eval/retrieval_sweep_results.json` with `--output data/eval/retrieval_sweep_results.json`.

## Run the frontend

Start the backend in one terminal from the project root:

```powershell
python -m uvicorn backend.main:app --reload
```

Start the React app in a second terminal:

```powershell
Set-Location frontend
npm install
npm run dev
```

Vite serves the Hebrew RTL chat UI and proxies `/chat` and `/health` to the
local FastAPI server. See [README_FRONTEND.md](README_FRONTEND.md) for the
frontend architecture, behavior, tests, and deployment considerations.

## Project status

See [STEP.md](STEP.md) for the implementation roadmap and current status.
See [README_FRONTEND.md](README_FRONTEND.md) for the frontend architecture and
task-by-task implementation plan.
