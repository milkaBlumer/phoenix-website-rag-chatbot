import { safeCitationUrl, type Citation } from "../api/chat";

interface CitationListProps {
  citations: Citation[];
}

export function CitationList({ citations }: CitationListProps) {
  if (citations.length === 0) {
    return null;
  }

  return (
    <div className="citations" aria-label="מקורות מידע">
      <span className="citations__label">מקורות</span>
      <ul>
        {citations.map((citation, index) => {
          const safeUrl = safeCitationUrl(citation.url);
          const label = citation.title.trim() || citation.url;
          return (
            <li key={`${citation.url}-${index}`}>
              {safeUrl ? (
                <a href={safeUrl} target="_blank" rel="noopener noreferrer">
                  <span dir="auto">{label}</span>
                  <svg viewBox="0 0 16 16" aria-hidden="true">
                    <path d="M9.5 2.5h4v4M13.2 2.8 7 9m4-1v5H3v-8h5" />
                  </svg>
                </a>
              ) : (
                <span className="citation-invalid" dir="auto">
                  {label}
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
