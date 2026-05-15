import ReactMarkdown from "react-markdown";

import type { ArtifactView } from "../../api/types";
import { PersonEntryView } from "./PersonEntryView";
import { TechnicalDetailsDrawer } from "./TechnicalDetailsDrawer";
import { WriterArtifactView } from "./WriterArtifactView";

interface ArtifactDetailProps {
  view: ArtifactView | undefined;
  isLoading?: boolean;
}

export function ArtifactDetail({ view, isLoading = false }: ArtifactDetailProps) {
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
        <WriterArtifactView view={view} />
        <TechnicalDetailsDrawer artifactId={view.artifact_id} available={view.technical_available} />
      </div>
    );
  }

  return (
    <article className="artifact-detail">
      <header className="artifact-detail-header">
        <span>{view.kind}</span>
        <h2>{view.title}</h2>
      </header>
      <div className="artifact-section-grid">
        {view.sections.map((section) => (
          <section className="artifact-section" key={section.title}>
            <h3>{section.title}</h3>
            <p>{section.body || "暂无内容。"}</p>
          </section>
        ))}
      </div>
      {view.cards.length ? (
        <div className="artifact-card-grid">
          {view.cards.map((card) => (
            <article className="artifact-card" key={`${card.title}:${card.subtitle}`}>
              <h3>{card.title}</h3>
              {card.subtitle ? <p className="muted">{card.subtitle}</p> : null}
              {card.body ? <p>{card.body}</p> : null}
              {Object.entries(card.fields).map(([key, value]) => (
                <dl key={key}>
                  <dt>{key}</dt>
                  <dd>{value}</dd>
                </dl>
              ))}
            </article>
          ))}
        </div>
      ) : null}
      {view.tables.map((table) => (
        <div className="artifact-table-wrap" key={table.title}>
          <h3>{table.title}</h3>
          <table>
            <thead>
              <tr>
                {table.columns.map((column) => (
                  <th key={column}>{column}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row, index) => (
                <tr key={index}>
                  {table.columns.map((column) => (
                    <td key={column}>{row[column]}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      {view.markdown ? (
        <div className="markdown-body">
          <ReactMarkdown>{view.markdown}</ReactMarkdown>
        </div>
      ) : null}
      <TechnicalDetailsDrawer artifactId={view.artifact_id} available={view.technical_available} />
    </article>
  );
}
