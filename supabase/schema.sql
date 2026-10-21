-- Enable pgvector for storing Gemini embeddings.
create extension if not exists vector
with schema extensions;

create table if not exists public.documents (
    id text primary key,
    url text not null,
    title text not null default '',
    chunk_index integer not null check (chunk_index >= 0),
    content text not null check (length(trim(content)) > 0),
    embedding extensions.vector(768) not null,
    created_at timestamptz not null default now(),
    unique (url, chunk_index)
);

create index if not exists documents_embedding_hnsw_idx
    on public.documents
    using hnsw (embedding extensions.vector_cosine_ops);

create index if not exists documents_url_idx
    on public.documents (url);

create or replace function public.match_documents(
    query_embedding extensions.vector(768),
    match_count integer default 5,
    filter_url text default null
)
returns table (
    id text,
    url text,
    title text,
    chunk_index integer,
    content text,
    similarity double precision
)
language sql
stable
as $$
    select
        documents.id,
        documents.url,
        documents.title,
        documents.chunk_index,
        documents.content,
        1 - (documents.embedding <=> query_embedding) as similarity
    from public.documents
    where filter_url is null or documents.url = filter_url
    order by documents.embedding <=> query_embedding
    limit greatest(match_count, 0);
$$;
