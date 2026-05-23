import { CheckCircle2, ClipboardCheck, MessageSquareText, PauseCircle, RotateCcw } from "lucide-react";

import type { WriterArtifactReview, WriterReviewAction } from "../../api/types";

interface WriterArtifactReviewCardProps {
  review: WriterArtifactReview;
  activeMode?: "supplement" | "revision" | "";
  pending?: boolean;
  latestSupplementText?: string;
  latestRevisionFeedback?: string;
  hideActions?: boolean;
  onUseInput: (review: WriterArtifactReview, mode: "supplement" | "revision") => void;
  onApprove: (review: WriterArtifactReview) => void;
  onRequestRevision: (review: WriterArtifactReview) => void;
  onDefer: (review: WriterArtifactReview) => void;
  onReviewerAction?: (review: WriterArtifactReview, action: WriterReviewAction) => void;
  onOpenDetail?: (artifactId: string) => void;
}

export function WriterArtifactReviewCard({
  review,
  activeMode = "",
  pending = false,
  latestSupplementText = "",
  latestRevisionFeedback = "",
  hideActions = false,
  onUseInput,
  onApprove,
  onRequestRevision,
  onDefer,
  onReviewerAction,
  onOpenDetail
}: WriterArtifactReviewCardProps) {
  const hasRevisionFeedback = Boolean(latestRevisionFeedback.trim());
  const detailArtifactId = review.detail_artifact_id || review.artifact_id;
  const reviewerActions = review.actions.filter((action) => action.action === "run_reviewer");

  return (
    <article className="writer-review-card">
      <div className="writer-review-card-header">
        <span>Writer 审阅</span>
        <h3>{review.title}</h3>
      </div>
      {review.summary ? <p className="writer-review-summary">{review.summary}</p> : null}
      {review.next_prompt ? <p className="writer-card-hint">{review.next_prompt}</p> : null}
      {latestSupplementText ? <p className="writer-answer-preview">通过补充：{latestSupplementText}</p> : null}
      {latestRevisionFeedback ? <p className="writer-answer-preview">调整反馈：{latestRevisionFeedback}</p> : null}
      {hideActions ? null : <div className="decision-actions">
        {detailArtifactId ? (
          <button type="button" className="secondary-button" disabled={pending} onClick={() => onOpenDetail?.(detailArtifactId)}>
            查看详情
          </button>
        ) : null}
        {reviewerActions.map((action) => (
          <button
            key={`${action.action}:${action.label}:${String(action.payload?.reviewer_id ?? "")}`}
            type="button"
            className="secondary-button"
            disabled={pending}
            title={action.description}
            onClick={() => onReviewerAction?.(review, action)}
          >
            <ClipboardCheck size={15} aria-hidden="true" />
            {action.label}
          </button>
        ))}
        <button
          type="button"
          className="secondary-button"
          disabled={pending || activeMode === "supplement"}
          onClick={() => onUseInput(review, "supplement")}
        >
          <MessageSquareText size={15} aria-hidden="true" />
          {activeMode === "supplement" ? "正在补充" : "用输入框补充"}
        </button>
        <button type="button" className="primary-button" disabled={pending} onClick={() => onApprove(review)}>
          <CheckCircle2 size={15} aria-hidden="true" />
          通过并继续
        </button>
        <button
          type="button"
          className="secondary-button"
          disabled={pending || activeMode === "revision"}
          onClick={() => onUseInput(review, "revision")}
        >
          <RotateCcw size={15} aria-hidden="true" />
          {activeMode === "revision" ? "正在写反馈" : "输入调整反馈"}
        </button>
        <button
          type="button"
          className="secondary-button"
          disabled={pending || !hasRevisionFeedback}
          onClick={() => onRequestRevision(review)}
        >
          不通过并调整
        </button>
        <button type="button" className="secondary-button" disabled={pending} onClick={() => onDefer(review)}>
          <PauseCircle size={15} aria-hidden="true" />
          稍后继续
        </button>
      </div>}
    </article>
  );
}
