import type { DecisionCardModel } from "../../api/types";

interface DecisionCardProps {
  card: DecisionCardModel;
  pending?: boolean;
  onAction: (action: string, payload?: Record<string, unknown>) => Promise<unknown> | void;
}

export function DecisionCard({ card, pending = false, onAction }: DecisionCardProps) {
  async function submitAction(action: string, payload: Record<string, unknown> = {}) {
    await onAction(action, payload);
  }

  return (
    <article className="decision-card">
      <div className="decision-card-header">
        <span>下一步</span>
        <h3>{card.title}</h3>
      </div>
      {card.body ? <p>{card.body}</p> : null}
      <div className="decision-actions">
        {card.actions.map((action) => (
          <button
            key={`${card.card_id}:${action.action}:${action.label}`}
            type="button"
            className={action.variant === "danger" ? "danger-button" : action.variant === "primary" ? "primary-button" : "secondary-button"}
            disabled={pending}
            title={action.description}
            onClick={() => void submitAction(action.action, action.payload ?? {})}
          >
            {publicDecisionLabel(action.label)}
          </button>
        ))}
      </div>
    </article>
  );
}

export function publicDecisionLabel(label: string): string {
  if (label === "确认并继续") {
    return "接受并继续";
  }
  if (label === "调整字数后重写") {
    return "基于反馈重写";
  }
  return label;
}
