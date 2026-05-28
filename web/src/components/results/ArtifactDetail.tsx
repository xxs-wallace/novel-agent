import ReactMarkdown from "react-markdown";

import type { ArtifactView } from "../../api/types";
import { normalizePublicTerms } from "../../utils/status";
import { PersonEntryView } from "./PersonEntryView";
import { TechnicalDetailsDrawer } from "./TechnicalDetailsDrawer";
import { WriterArtifactView } from "./WriterArtifactView";

interface ArtifactDetailProps {
  view: ArtifactView | undefined;
  isLoading?: boolean;
  actionPending?: boolean;
  onAction?: (action: string, payload?: Record<string, unknown>) => Promise<unknown> | void;
}

export function ArtifactDetail({ view, isLoading = false, actionPending = false, onAction }: ArtifactDetailProps) {
  if (isLoading) {
    return <div className="empty-state">正在加载产物...</div>;
  }
  if (!view) {
    return <div className="empty-state">从目录树选择一个条目。</div>;
  }
  if (view.kind === "person_encyclopedia") {
    return (
      <div className="artifact-detail">
        <PersonEntryView view={view} />
        <TechnicalDetailsDrawer artifactId={view.artifact_id} available={view.technical_available} />
      </div>
    );
  }
  if (view.kind.startsWith("writer_")) {
    return (
      <div className="artifact-detail">
        <WriterArtifactView view={view} actionPending={actionPending} onAction={onAction} />
        <TechnicalDetailsDrawer artifactId={view.artifact_id} available={view.technical_available} />
      </div>
    );
  }

  return (
    <article className="artifact-detail">
      <header className="artifact-detail-header">
        <span>{normalizePublicTerms(view.kind)}</span>
        <h2>{normalizePublicTerms(view.title)}</h2>
      </header>
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
      {view.actions.length ? (
        <div className="artifact-floating-actions">
          {view.actions.map((action) => (
            <button
              type="button"
              key={`${action.action}:${action.label}`}
              disabled={actionPending}
              title={action.description}
              onClick={() => void onAction?.(action.action, action.payload ?? {})}
            >
              {normalizePublicTerms(action.label)}
            </button>
          ))}
        </div>
      ) : null}
      <TechnicalDetailsDrawer artifactId={view.artifact_id} available={view.technical_available} />
    </article>
  );
}
