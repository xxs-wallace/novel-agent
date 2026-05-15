import type { ConversationMessage, JobEventView } from "../../api/types";
import { toPublicStatusText } from "../../utils/status";
import { DecisionCard } from "./DecisionCard";

interface MessageListProps {
  messages: ConversationMessage[];
  jobEvents: JobEventView[];
  pending?: boolean;
  onAction: (action: string, payload?: Record<string, unknown>) => Promise<unknown> | void;
}

const ROLE_LABELS: Record<string, string> = {
  user: "你",
  assistant: "Agent",
  system: "系统",
  job: "进度",
  error: "错误"
};

export function MessageList({ messages, jobEvents, pending = false, onAction }: MessageListProps) {
  return (
    <div className="message-list" role="log" aria-live="polite">
      {messages.length === 0 && jobEvents.length === 0 ? <div className="empty-state">选择任务后，可以在这里和 Agent 交流。</div> : null}
      {messages.map((message) => (
        <div key={message.message_id} className={`message-bubble role-${message.role}`}>
          <span className="message-role">{ROLE_LABELS[message.role] ?? message.role}</span>
          <p>{toPublicStatusText(message.content, "")}</p>
          {message.decision_cards?.map((card) => (
            <DecisionCard key={card.card_id} card={card} pending={pending} onAction={onAction} />
          ))}
        </div>
      ))}
      {jobEvents.map((event) => (
        <div key={`${event.job_id}:${event.event_id}`} className={`message-bubble role-job event-${event.kind}`}>
          <span className="message-role">进度</span>
          <p>{toPublicStatusText(event.message, "")}</p>
          {event.payload?.recovery_suggestion ? <p className="recovery-text">{String(event.payload.recovery_suggestion)}</p> : null}
        </div>
      ))}
    </div>
  );
}
