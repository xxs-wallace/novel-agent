import type { ArtifactView } from "../../api/types";

interface PersonEntryViewProps {
  view: ArtifactView;
}

const ORDER = ["基本信息", "当前目标", "关系网络", "性格与说话方式", "已知秘密", "禁止误写点", "最近变化"];

export function PersonEntryView({ view }: PersonEntryViewProps) {
  const sections = ORDER.map((title) => view.sections.find((section) => section.title === title)).filter(Boolean);
  const extras = view.sections.filter((section) => !ORDER.includes(section.title));

  return (
    <article className="person-entry-view">
      <header>
        <span>人物百科</span>
        <h2>{view.title}</h2>
      </header>
      <div className="person-section-grid">
        {[...sections, ...extras].map((section) =>
          section ? (
            <section key={section.title} className="artifact-section">
              <h3>{section.title}</h3>
              <p>{section.body || "暂无明确记录。"}</p>
            </section>
          ) : null
        )}
      </div>
    </article>
  );
}
