import { FormEvent, useState } from "react";

import type { DecisionCardModel } from "../../api/types";

interface DecisionCardProps {
  card: DecisionCardModel;
  pending?: boolean;
  onAction: (action: string, payload?: Record<string, unknown>) => Promise<unknown> | void;
}

export function DecisionCard({ card, pending = false, onAction }: DecisionCardProps) {
  const [feedback, setFeedback] = useState("");

  async function submitAction(action: string, payload: Record<string, unknown> = {}) {
    const mergedPayload = feedback.trim() ? { ...payload, feedback: feedback.trim() } : payload;
    await onAction(action, mergedPayload);
    setFeedback("");
  }

  const wantsFeedback = card.actions.some((action) => action.requires_input || /反馈|修改|重写|调整/.test(action.label));

  return (
    <article className="decision-card">
      <div className="decision-card-header">
        <span>决策</span>
        <h3>{card.title}</h3>
      </div>
      {card.body ? <p>{card.body}</p> : null}
      {wantsFeedback ? (
        <label className="feedback-field">
          我的反馈
          <textarea value={feedback} onChange={(event) => setFeedback(event.target.value)} rows={3} placeholder="补充修改方向、字数要求或章节梗概调整" />
        </label>
      ) : null}
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

function publicDecisionLabel(label: string): string {
  if (label === "确认并继续") {
    return "接受并继续";
  }
  return label;
}

export function InlineDecisionForm({
  action,
  label,
  onAction
}: {
  action: string;
  label: string;
  onAction: (action: string, payload?: Record<string, unknown>) => Promise<unknown> | void;
}) {
  const [value, setValue] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void onAction(action, { feedback: value.trim() });
    setValue("");
  }

  return (
    <form className="inline-decision-form" onSubmit={handleSubmit}>
      <textarea value={value} onChange={(event) => setValue(event.target.value)} rows={3} placeholder={label} />
      <button className="secondary-button" type="submit">
        提交反馈
      </button>
    </form>
  );
}
