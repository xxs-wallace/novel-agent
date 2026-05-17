import { CheckCircle2, MessageSquareText, PauseCircle, RotateCcw, Trash2 } from "lucide-react";

import type { WriterDraftReview } from "../../api/types";

interface DraftReviewCardProps {
  review: WriterDraftReview;
  activeAction?: string;
  pending?: boolean;
  feedbackByAction?: Record<string, string>;
  hideActions?: boolean;
  onUseInput: (review: WriterDraftReview, action: string) => void;
  onAction: (review: WriterDraftReview, action: string) => void;
  onOpenDetail?: (artifactId: string) => void;
}

export function DraftReviewCard({
  review,
  activeAction = "",
  pending = false,
  feedbackByAction = {},
  hideActions = false,
  onUseInput,
  onAction,
  onOpenDetail
}: DraftReviewCardProps) {
  const rewriteFeedback = feedbackByAction.rewrite_chapter ?? "";
  const replanFeedback = feedbackByAction.replan_chapter ?? "";
  const discardReason = feedbackByAction.discard_chapter ?? "";

  return (
    <article className="writer-review-card draft-review-card">
      <div className="writer-review-card-header">
        <span>章节验收</span>
        <h3>{review.title}</h3>
      </div>
      <div className="draft-review-stats">
        <span>当前字数：{review.word_count}</span>
        {review.target_word_count ? <span>目标字数：{review.target_word_count}</span> : null}
      </div>
      {review.preview ? <p className="draft-preview">{review.preview}</p> : null}
      {review.continuity_summary ? <p className="writer-card-hint">{review.continuity_summary}</p> : null}
      {rewriteFeedback ? <p className="writer-answer-preview">重写反馈：{rewriteFeedback}</p> : null}
      {replanFeedback ? <p className="writer-answer-preview">梗概调整：{replanFeedback}</p> : null}
      {discardReason ? <p className="writer-answer-preview">作废说明：{discardReason}</p> : null}
      {hideActions ? null : <div className="decision-actions">
        {review.detail_artifact_id ? (
          <button type="button" className="secondary-button" disabled={pending} onClick={() => onOpenDetail?.(review.detail_artifact_id)}>
            查看完整正文
          </button>
        ) : null}
        <button type="button" className="primary-button" disabled={pending} onClick={() => onAction(review, "accept_chapter")}>
          <CheckCircle2 size={15} aria-hidden="true" />
          接受本章
        </button>
        <button
          type="button"
          className="secondary-button"
          disabled={pending || activeAction === "rewrite_chapter"}
          onClick={() => onUseInput(review, "rewrite_chapter")}
        >
          <MessageSquareText size={15} aria-hidden="true" />
          {activeAction === "rewrite_chapter" ? "正在写反馈" : "输入重写反馈"}
        </button>
        <button
          type="button"
          className="secondary-button"
          disabled={pending || !rewriteFeedback.trim()}
          onClick={() => onAction(review, "rewrite_chapter")}
        >
          <RotateCcw size={15} aria-hidden="true" />
          基于反馈重写
        </button>
        <button
          type="button"
          className="secondary-button"
          disabled={pending || activeAction === "replan_chapter"}
          onClick={() => onUseInput(review, "replan_chapter")}
        >
          修改章节梗概后重写
        </button>
        <button
          type="button"
          className="secondary-button"
          disabled={pending || !replanFeedback.trim()}
          onClick={() => onAction(review, "replan_chapter")}
        >
          提交梗概调整
        </button>
        <button
          type="button"
          className="danger-button"
          disabled={pending}
          onClick={() => (discardReason.trim() ? onAction(review, "discard_chapter") : onUseInput(review, "discard_chapter"))}
        >
          <Trash2 size={15} aria-hidden="true" />
          作废本次草稿
        </button>
        <button type="button" className="secondary-button" disabled={pending} onClick={() => onAction(review, "defer_chapter_acceptance")}>
          <PauseCircle size={15} aria-hidden="true" />
          稍后再决定
        </button>
      </div>}
    </article>
  );
}
