import ReactMarkdown from "react-markdown";
import { ClipboardCheck } from "lucide-react";

import type { ArtifactView } from "../../api/types";
import { normalizePublicTerms } from "../../utils/status";

interface WriterArtifactViewProps {
  view: ArtifactView;
  actionPending?: boolean;
  onAction?: (action: string, payload?: Record<string, unknown>) => Promise<unknown> | void;
}

export function WriterArtifactView({ view, actionPending = false, onAction }: WriterArtifactViewProps) {
  return (
    <article className="writer-artifact-view">
      <header>
        <span>Writer</span>
        <h2>{normalizePublicTerms(view.title)}</h2>
      </header>
      {view.actions.length ? (
        <div className="artifact-toolbar" aria-label="产物工具">
          {view.actions.map((action) => (
            <button
              key={`${action.action}:${action.label}:${String(action.payload?.reviewer_id ?? "")}`}
              type="button"
              className={action.variant === "danger" ? "danger-button" : action.variant === "primary" ? "primary-button" : "secondary-button"}
              disabled={actionPending || !onAction}
              title={action.description}
              onClick={() => void onAction?.(action.action, action.payload ?? {})}
            >
              <ClipboardCheck size={15} aria-hidden="true" />
              {normalizePublicTerms(action.label)}
            </button>
          ))}
        </div>
      ) : null}
      <div className="artifact-section-grid">
        {view.sections.map((section) => (
          <section className="artifact-section" key={section.title}>
            <h3>{normalizePublicTerms(section.title)}</h3>
            <p>{normalizePublicTerms(section.body || "暂无内容。")}</p>
          </section>
        ))}
      </div>
      {view.cards.length ? (
        <div className="artifact-card-grid">
          {view.cards.map((card) => (
            <article className="artifact-card" key={`${card.title}:${card.subtitle}`}>
              <h3>{normalizePublicTerms(card.title)}</h3>
              {card.subtitle ? <p className="muted">{normalizePublicTerms(card.subtitle)}</p> : null}
              {card.body ? <p>{normalizePublicTerms(card.body)}</p> : null}
              {Object.entries(card.fields).map(([key, value]) => (
                <dl key={key}>
                  <dt>{normalizePublicTerms(key)}</dt>
                  <dd>{normalizePublicTerms(value)}</dd>
                </dl>
              ))}
            </article>
          ))}
        </div>
      ) : null}
      {view.tables.map((table) => (
        <div className="artifact-table-wrap" key={table.title}>
          <h3>{normalizePublicTerms(table.title)}</h3>
          <table>
            <thead>
              <tr>
                {table.columns.map((column) => (
                  <th key={column}>{normalizePublicTerms(column)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row, index) => (
                <tr key={index}>
                  {table.columns.map((column) => (
                    <td key={column}>{normalizePublicTerms(row[column])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      {view.markdown ? (
        <div className="markdown-body">
          <ReactMarkdown>{normalizePublicTerms(view.markdown)}</ReactMarkdown>
        </div>
      ) : null}
    </article>
  );
}
