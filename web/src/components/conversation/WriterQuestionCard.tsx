import { CheckCircle2, MessageSquareText, PauseCircle } from "lucide-react";

import type { WriterQuestionSet } from "../../api/types";

interface WriterQuestionCardProps {
  questionSet: WriterQuestionSet;
  active?: boolean;
  pending?: boolean;
  latestAnswerText?: string;
  hideActions?: boolean;
  onUseInput: (questionSet: WriterQuestionSet) => void;
  onSubmit: (questionSet: WriterQuestionSet) => void;
  onDefer: (questionSet: WriterQuestionSet) => void;
}

export function WriterQuestionCard({
  questionSet,
  active = false,
  pending = false,
  latestAnswerText = "",
  hideActions = false,
  onUseInput,
  onSubmit,
  onDefer
}: WriterQuestionCardProps) {
  const canSubmit = Boolean(latestAnswerText.trim());
  const researchLabel = questionSet.stage === "draft_research_user_input" ? "正文研究" : "大纲研究";

  return (
    <article className="writer-question-card">
      <div className="writer-question-card-header">
        <span>{researchLabel}</span>
        <h3>需要你补充几个关键问题</h3>
      </div>
      <ol className="writer-question-list">
        {questionSet.questions.map((question, index) => (
          <li key={question.question_id}>
            <div className="writer-question-line">
              <span>{index + 1}</span>
              <p>{question.prompt}</p>
              {question.required ? <strong>必答</strong> : null}
            </div>
            {question.hint ? <p className="writer-question-hint">{question.hint}</p> : null}
          </li>
        ))}
      </ol>
      {latestAnswerText ? <p className="writer-answer-preview">已记录回答：{latestAnswerText}</p> : null}
      {hideActions ? null : (
        <div className="decision-actions">
          <button type="button" className="secondary-button" disabled={pending || active} onClick={() => onUseInput(questionSet)}>
            <MessageSquareText size={15} aria-hidden="true" />
            {active ? "正在回答" : "用输入框回答"}
          </button>
          <button type="button" className="primary-button" disabled={pending || !canSubmit} onClick={() => onSubmit(questionSet)}>
            <CheckCircle2 size={15} aria-hidden="true" />
            提交回答并继续研究
          </button>
          <button type="button" className="secondary-button" disabled={pending} onClick={() => onDefer(questionSet)}>
            <PauseCircle size={15} aria-hidden="true" />
            稍后继续
          </button>
        </div>
      )}
    </article>
  );
}
