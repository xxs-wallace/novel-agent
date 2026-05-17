import type { ConversationMessage, JobEventView, WriterArtifactReview, WriterDraftReview, WriterQuestionSet } from "../../api/types";
import { toPublicStatusText } from "../../utils/status";
import { DraftReviewCard } from "./DraftReviewCard";
import { WriterArtifactReviewCard } from "./WriterArtifactReviewCard";
import { WriterQuestionCard } from "./WriterQuestionCard";

interface MessageListProps {
  messages: ConversationMessage[];
  jobEvents: JobEventView[];
  pending?: boolean;
  activeQuestionSetId?: string;
  activeArtifactReview?: { reviewId: string; mode: "supplement" | "revision" } | null;
  activeDraftReview?: { reviewId: string; action: string } | null;
  answersByQuestionSet?: Record<string, { messageId: string; answerText: string }>;
  artifactInputsByReview?: Record<string, { supplement?: { messageId: string; text: string }; revision?: { messageId: string; text: string } }>;
  draftInputsByReview?: Record<string, Record<string, { messageId: string; text: string }>>;
  onUseQuestionInput?: (questionSet: WriterQuestionSet) => void;
  onSubmitQuestionSet?: (questionSet: WriterQuestionSet) => void;
  onDeferQuestionSet?: (questionSet: WriterQuestionSet) => void;
  onUseArtifactInput?: (review: WriterArtifactReview, mode: "supplement" | "revision") => void;
  onApproveArtifact?: (review: WriterArtifactReview) => void;
  onRequestArtifactRevision?: (review: WriterArtifactReview) => void;
  onDeferArtifact?: (review: WriterArtifactReview) => void;
  onUseDraftInput?: (review: WriterDraftReview, action: string) => void;
  onSubmitDraftAction?: (review: WriterDraftReview, action: string) => void;
  onOpenArtifactDetail?: (artifactId: string) => void;
  onAction?: (action: string, payload?: Record<string, unknown>) => Promise<unknown> | void;
}

const ROLE_LABELS: Record<string, string> = {
  user: "你",
  assistant: "Agent",
  system: "系统",
  job: "进度",
  error: "错误"
};

export function MessageList({
  messages,
  jobEvents,
  pending = false,
  activeQuestionSetId = "",
  activeArtifactReview = null,
  activeDraftReview = null,
  answersByQuestionSet = {},
  artifactInputsByReview = {},
  draftInputsByReview = {},
  onUseQuestionInput,
  onSubmitQuestionSet,
  onDeferQuestionSet,
  onUseArtifactInput,
  onApproveArtifact,
  onRequestArtifactRevision,
  onDeferArtifact,
  onUseDraftInput,
  onSubmitDraftAction,
  onOpenArtifactDetail
}: MessageListProps) {
  return (
    <div className="message-list" role="log" aria-live="polite">
      {messages.length === 0 && jobEvents.length === 0 ? <div className="empty-state">选择任务后，可以在这里和 Agent 交流。</div> : null}
      {messages.map((message) => (
        <div key={message.message_id} className={`message-bubble role-${message.role}`}>
          <span className="message-role">{ROLE_LABELS[message.role] ?? message.role}</span>
          <p>{toPublicStatusText(message.content, "")}</p>
          {message.writer_question_set ? (
            <WriterQuestionCard
              questionSet={message.writer_question_set}
              active={activeQuestionSetId === message.writer_question_set.question_set_id}
              pending={pending}
              latestAnswerText={answersByQuestionSet[message.writer_question_set.question_set_id]?.answerText ?? ""}
              hideActions
              onUseInput={(questionSet) => onUseQuestionInput?.(questionSet)}
              onSubmit={(questionSet) => onSubmitQuestionSet?.(questionSet)}
              onDefer={(questionSet) => onDeferQuestionSet?.(questionSet)}
            />
          ) : null}
          {message.writer_artifact_review ? (
            <WriterArtifactReviewCard
              review={message.writer_artifact_review}
              activeMode={
                activeArtifactReview?.reviewId === message.writer_artifact_review.review_id ? activeArtifactReview.mode : ""
              }
              pending={pending}
              latestSupplementText={artifactInputsByReview[message.writer_artifact_review.review_id]?.supplement?.text ?? ""}
              latestRevisionFeedback={artifactInputsByReview[message.writer_artifact_review.review_id]?.revision?.text ?? ""}
              hideActions
              onUseInput={(review, mode) => onUseArtifactInput?.(review, mode)}
              onApprove={(review) => onApproveArtifact?.(review)}
              onRequestRevision={(review) => onRequestArtifactRevision?.(review)}
              onDefer={(review) => onDeferArtifact?.(review)}
              onOpenDetail={onOpenArtifactDetail}
            />
          ) : null}
          {message.writer_draft_review ? (
            <DraftReviewCard
              review={message.writer_draft_review}
              activeAction={activeDraftReview?.reviewId === message.writer_draft_review.review_id ? activeDraftReview.action : ""}
              pending={pending}
              feedbackByAction={Object.fromEntries(
                Object.entries(draftInputsByReview[message.writer_draft_review.review_id] ?? {}).map(([action, value]) => [
                  action,
                  value.text
                ])
              )}
              hideActions
              onUseInput={(review, action) => onUseDraftInput?.(review, action)}
              onAction={(review, action) => onSubmitDraftAction?.(review, action)}
              onOpenDetail={onOpenArtifactDetail}
            />
          ) : null}
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
