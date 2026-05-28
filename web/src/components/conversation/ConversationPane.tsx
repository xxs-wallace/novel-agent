import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpenCheck, CheckCircle2, ClipboardCheck, LoaderCircle, Send, WandSparkles } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { postCommand } from "../../api/actions";
import { ANALYZER_MESSAGE_TIMEOUT_MS, getMessages, postMessage } from "../../api/messages";
import type {
  ConversationMessage,
  DecisionAction,
  DecisionCardModel,
  JobEventView,
  JobSummary,
  TaskSummary,
  WriterArtifactReview,
  WriterDraftReview,
  WriterQuestionSet,
  WriterReviewAction,
  TaskProgress
} from "../../api/types";
import { toPublicStatusText } from "../../utils/status";
import { publicDecisionLabel } from "./DecisionCard";
import { MessageList } from "./MessageList";
import { WriterIntentWizard } from "./WriterIntentWizard";

interface ConversationPaneProps {
  selectedTask: TaskSummary | null;
  jobEvents: JobEventView[];
  decisionCards: DecisionCardModel[];
  actionPending?: boolean;
  writerWizardSignal?: number;
  onOpenArtifactDetail?: (artifactId: string) => void;
  onAction: (action: string, payload?: Record<string, unknown>) => Promise<unknown> | void;
  onRequestWriterStart?: () => Promise<boolean> | boolean;
}

export function ConversationPane({
  selectedTask,
  jobEvents,
  decisionCards,
  actionPending = false,
  writerWizardSignal = 0,
  onOpenArtifactDetail,
  onAction,
  onRequestWriterStart
}: ConversationPaneProps) {
  const queryClient = useQueryClient();
  const [input, setInput] = useState("");
  const [wizardOpen, setWizardOpen] = useState(false);
  const [analyzerMode, setAnalyzerMode] = useState(false);
  const [activeQuestionSetId, setActiveQuestionSetId] = useState("");
  const [activeArtifactReview, setActiveArtifactReview] = useState<{
    reviewId: string;
    mode: "supplement" | "revision";
  } | null>(null);
  const [activeDraftReview, setActiveDraftReview] = useState<{ reviewId: string; action: string } | null>(null);
  const [activeDecisionAction, setActiveDecisionAction] = useState<{ cardId: string; action: DecisionAction } | null>(null);
  const [localAnswersByQuestionSet, setLocalAnswersByQuestionSet] = useState<
    Record<string, { messageId: string; answerText: string }>
  >({});
  const [localArtifactInputsByReview, setLocalArtifactInputsByReview] = useState<
    Record<string, { supplement?: { messageId: string; text: string }; revision?: { messageId: string; text: string } }>
  >({});
  const [localDraftInputsByReview, setLocalDraftInputsByReview] = useState<
    Record<string, Record<string, { messageId: string; text: string }>>
  >({});
  const [dismissedActionMessageIds, setDismissedActionMessageIds] = useState<Set<string>>(() => new Set());
  const [pendingAnalyzerQuestion, setPendingAnalyzerQuestion] = useState("");
  const [analyzerError, setAnalyzerError] = useState("");
  const taskId = selectedTask?.task_id ?? "";

  const messagesQuery = useQuery({
    queryKey: ["messages", taskId],
    queryFn: () => getMessages(taskId),
    enabled: Boolean(taskId)
  });

  const submitMutation = useMutation({
    mutationFn: async (content: string) => {
      if (!taskId) {
        throw new Error("请先选择任务。");
      }
      if (analyzerMode) {
        return postMessage(taskId, {
          content,
          payload: {
            channel: "outline_analyzer",
            question: content
          }
        }, {
          timeoutMs: ANALYZER_MESSAGE_TIMEOUT_MS,
          timeoutMessage: "Analyzer 分析超时，请稍后重试；本次问题没有推进 Writer 流程。"
        });
      }
      if (content.trim().startsWith("/")) {
        return postCommand(taskId, { command: content.trim() });
      }
      const activeQuestionSet = questionSets.find((item) => item.question_set_id === activeQuestionSetId);
      if (activeQuestionSet) {
        return postMessage(taskId, {
          content,
          payload: {
            channel: "writer_question_answer",
            run_id: activeQuestionSet.run_id,
            question_set_id: activeQuestionSet.question_set_id,
            answer_text: content
          }
        });
      }
      const activeArtifact = artifactReviews.find((item) => item.review_id === activeArtifactReview?.reviewId);
      if (activeArtifact && activeArtifactReview) {
        const isSupplement = activeArtifactReview.mode === "supplement";
        return postMessage(taskId, {
          content,
          payload: {
            channel: isSupplement ? "writer_artifact_supplement" : "writer_artifact_revision_feedback",
            run_id: activeArtifact.run_id,
            review_id: activeArtifact.review_id,
            artifact_kind: activeArtifact.artifact_kind,
            input_role: isSupplement ? "artifact_supplement" : "artifact_revision_feedback",
            [isSupplement ? "supplement_text" : "revision_feedback"]: content
          }
        });
      }
      const activeDraft = draftReviews.find((item) => item.review_id === activeDraftReview?.reviewId);
      if (activeDraft && activeDraftReview) {
        return postMessage(taskId, {
          content,
          payload: {
            channel: "writer_draft_review_feedback",
            run_id: activeDraft.run_id,
            review_id: activeDraft.review_id,
            chapter_id: activeDraft.chapter_id,
            draft_id: activeDraft.draft_id,
            action: activeDraftReview.action,
            feedback_text: content
          }
        });
      }
      return postMessage(taskId, { content, payload: { channel: "natural_language" } });
    },
    onSuccess: (result) => {
      const activeQuestionSet = questionSets.find((item) => item.question_set_id === activeQuestionSetId);
      if (activeQuestionSet && isConversationMessage(result)) {
        setLocalAnswersByQuestionSet((current) => ({
          ...current,
          [activeQuestionSet.question_set_id]: {
            messageId: result.message_id,
            answerText: result.content
          }
        }));
      }
      const activeArtifact = artifactReviews.find((item) => item.review_id === activeArtifactReview?.reviewId);
      if (activeArtifact && activeArtifactReview && isConversationMessage(result)) {
        setLocalArtifactInputsByReview((current) => ({
          ...current,
          [activeArtifact.review_id]: {
            ...(current[activeArtifact.review_id] ?? {}),
            [activeArtifactReview.mode]: {
              messageId: result.message_id,
              text: result.content
            }
          }
        }));
      }
      const activeDraft = draftReviews.find((item) => item.review_id === activeDraftReview?.reviewId);
      if (activeDraft && activeDraftReview && isConversationMessage(result)) {
        setLocalDraftInputsByReview((current) => ({
          ...current,
          [activeDraft.review_id]: {
            ...(current[activeDraft.review_id] ?? {}),
            [activeDraftReview.action]: {
              messageId: result.message_id,
              text: result.content
            }
          }
        }));
      }
      setPendingAnalyzerQuestion("");
      setAnalyzerError("");
      void queryClient.invalidateQueries({ queryKey: ["messages", taskId] });
    }
  });

  const messages = messagesQuery.data ?? [];
  const displayMessages = useMemo(
    () => [
      ...messages,
      ...localAnalyzerMessages({
        taskId,
        pendingQuestion: pendingAnalyzerQuestion,
        error: analyzerError
      })
    ],
    [analyzerError, messages, pendingAnalyzerQuestion, taskId]
  );
  const questionSets = useMemo(
    () => messages.map((message) => message.writer_question_set).filter(Boolean) as WriterQuestionSet[],
    [messages]
  );
  const artifactReviews = useMemo(
    () => messages.map((message) => message.writer_artifact_review).filter(Boolean) as WriterArtifactReview[],
    [messages]
  );
  const draftReviews = useMemo(
    () => messages.map((message) => message.writer_draft_review).filter(Boolean) as WriterDraftReview[],
    [messages]
  );
  const answersByQuestionSet = useMemo(() => {
    const fromMessages: Record<string, { messageId: string; answerText: string }> = {};
    for (const message of messages) {
      const questionSetId = String(message.payload?.question_set_id ?? "");
      const channel = String(message.payload?.channel ?? "");
      if (message.role === "user" && channel === "writer_question_answer" && questionSetId) {
        fromMessages[questionSetId] = { messageId: message.message_id, answerText: message.content };
      }
    }
    return { ...fromMessages, ...localAnswersByQuestionSet };
  }, [localAnswersByQuestionSet, messages]);
  const artifactInputsByReview = useMemo(() => {
    const fromMessages: Record<string, { supplement?: { messageId: string; text: string }; revision?: { messageId: string; text: string } }> = {};
    for (const message of messages) {
      if (message.role !== "user") {
        continue;
      }
      const reviewId = String(message.payload?.review_id ?? "");
      const channel = String(message.payload?.channel ?? "");
      if (!reviewId) {
        continue;
      }
      if (channel === "writer_artifact_supplement") {
        fromMessages[reviewId] = { ...(fromMessages[reviewId] ?? {}), supplement: { messageId: message.message_id, text: message.content } };
      }
      if (channel === "writer_artifact_revision_feedback") {
        fromMessages[reviewId] = { ...(fromMessages[reviewId] ?? {}), revision: { messageId: message.message_id, text: message.content } };
      }
    }
    return mergeArtifactInputs(fromMessages, localArtifactInputsByReview);
  }, [localArtifactInputsByReview, messages]);
  const draftInputsByReview = useMemo(() => {
    const fromMessages: Record<string, Record<string, { messageId: string; text: string }>> = {};
    for (const message of messages) {
      const reviewId = String(message.payload?.review_id ?? "");
      const channel = String(message.payload?.channel ?? "");
      const action = String(message.payload?.action ?? "");
      if (message.role === "user" && channel === "writer_draft_review_feedback" && reviewId && action) {
        fromMessages[reviewId] = {
          ...(fromMessages[reviewId] ?? {}),
          [action]: { messageId: message.message_id, text: message.content }
        };
      }
    }
    return mergeDraftInputs(fromMessages, localDraftInputsByReview);
  }, [localDraftInputsByReview, messages]);
  const activeQuestionSet = useMemo(
    () => questionSets.find((questionSet) => questionSet.question_set_id === activeQuestionSetId) ?? null,
    [activeQuestionSetId, questionSets]
  );
  const activeArtifactContext = useMemo(
    () => (activeArtifactReview ? artifactReviews.find((review) => review.review_id === activeArtifactReview.reviewId) ?? null : null),
    [activeArtifactReview, artifactReviews]
  );
  const activeDraftContext = useMemo(
    () => (activeDraftReview ? draftReviews.find((review) => review.review_id === activeDraftReview.reviewId) ?? null : null),
    [activeDraftReview, draftReviews]
  );
  const activeTaskJob = isActiveJob(selectedTask?.active_job) ? selectedTask.active_job : null;
  const activeWriterJob = activeTaskJob && isWriterJob(activeTaskJob) ? activeTaskJob : null;

  useEffect(() => {
    if (writerWizardSignal > 0 && selectedTask) {
      void requestWriterStart();
    }
  }, [selectedTask, writerWizardSignal]);

  useEffect(() => {
    setAnalyzerMode(false);
  }, [taskId]);

  useEffect(() => {
    if (analyzerMode) {
      setActiveQuestionSetId("");
      return;
    }
    if (!questionSets.length) {
      setActiveQuestionSetId("");
      return;
    }
    if (activeArtifactReview || activeDraftReview) {
      return;
    }
    if (!activeQuestionSetId || !questionSets.some((item) => item.question_set_id === activeQuestionSetId)) {
      setActiveQuestionSetId(questionSets[questionSets.length - 1].question_set_id);
      setActiveArtifactReview(null);
      setActiveDraftReview(null);
    }
  }, [activeArtifactReview, activeDraftReview, activeQuestionSetId, analyzerMode, questionSets]);

  const latestActionMessage = useMemo(
    () => {
      for (const message of [...messages].reverse()) {
        if (isActionMessage(message)) {
          return dismissedActionMessageIds.has(message.message_id) ? null : message;
        }
      }
      return null;
    },
    [dismissedActionMessageIds, messages]
  );
  const composerQuestionSet = analyzerMode || activeWriterJob ? null : latestActionMessage?.writer_question_set ?? null;
  const latestMessageDecisionCards = useMemo(() => latestActionMessage?.decision_cards ?? [], [latestActionMessage]);
  const hasDecisionCardContext = !analyzerMode && !activeWriterJob && (latestMessageDecisionCards.length > 0 || decisionCards.length > 0);
  const composerArtifactReview =
    analyzerMode || activeWriterJob || hasDecisionCardContext ? null : activeArtifactContext ?? latestActionMessage?.writer_artifact_review ?? null;
  const composerDraftReview =
    analyzerMode || activeWriterJob || hasDecisionCardContext ? null : activeDraftContext ?? latestActionMessage?.writer_draft_review ?? null;
  const composerDecisionCards = useMemo(() => {
    if (analyzerMode || activeWriterJob) {
      return [];
    }
    const ordered = [...latestMessageDecisionCards, ...decisionCards];
    const deduped = new Map<string, DecisionCardModel>();
    for (const card of ordered) {
      deduped.set(card.card_id, card);
    }
    return [...deduped.values()];
  }, [activeWriterJob, analyzerMode, decisionCards, latestMessageDecisionCards]);

  const latestNaturalGoal = useMemo(() => {
    const latest = [...messages].reverse().find((message) => message.role === "user" && !message.content.trim().startsWith("/"));
    return input.trim() && !input.trim().startsWith("/") ? input : latest?.content ?? "";
  }, [input, messages]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = input.trim();
    if (!content) {
      return;
    }
    const wasAnalyzerMode = analyzerMode;
    setInput("");
    if (wasAnalyzerMode) {
      setPendingAnalyzerQuestion(content);
      setAnalyzerError("");
    }
    try {
      await submitMutation.mutateAsync(content);
    } catch (error) {
      if (wasAnalyzerMode) {
        setPendingAnalyzerQuestion("");
        setAnalyzerError(error instanceof Error ? error.message : "Analyzer 暂时无法完成分析，请稍后重试。");
        setInput(content);
        return;
      }
      throw error;
    }
  }

  async function submitWriterIntent(payload: Record<string, unknown>) {
    await onAction("start_writer", payload);
  }

  async function requestWriterStart() {
    if (onRequestWriterStart) {
      const canOpen = await onRequestWriterStart();
      if (!canOpen) {
        return;
      }
    }
    setAnalyzerMode(false);
    setWizardOpen(true);
  }

  async function submitQuestionSet(questionSet: WriterQuestionSet) {
    const answer = answersByQuestionSet[questionSet.question_set_id];
    dismissLatestActionMessage();
    await onAction(questionSet.submit_action || "submit_outline_research_answers", {
      run_id: questionSet.run_id,
      question_set_id: questionSet.question_set_id,
      source_message_id: answer?.messageId ?? "",
      answer_text: answer?.answerText ?? ""
    });
  }

  async function deferQuestionSet(questionSet: WriterQuestionSet) {
    dismissLatestActionMessage();
    await onAction(questionSet.defer_action || "defer_outline_research_answers", {
      run_id: questionSet.run_id,
      question_set_id: questionSet.question_set_id
    });
  }

  function useQuestionInput(questionSet: WriterQuestionSet) {
    setAnalyzerMode(false);
    setActiveQuestionSetId(questionSet.question_set_id);
    setActiveArtifactReview(null);
    setActiveDraftReview(null);
    setActiveDecisionAction(null);
  }

  async function recordQuestionAnswer(questionSet: WriterQuestionSet, content: string): Promise<{ messageId: string; answerText: string } | null> {
    const trimmed = content.trim();
    if (!trimmed) {
      return null;
    }
    const result = await postMessage(taskId, {
      content: trimmed,
      payload: {
        channel: "writer_question_answer",
        run_id: questionSet.run_id,
        question_set_id: questionSet.question_set_id,
        answer_text: trimmed
      }
    });
    if (!isConversationMessage(result)) {
      return null;
    }
    const recorded = { messageId: result.message_id, answerText: result.content };
    setLocalAnswersByQuestionSet((current) => ({
      ...current,
      [questionSet.question_set_id]: recorded
    }));
    void queryClient.invalidateQueries({ queryKey: ["messages", taskId] });
    return recorded;
  }

  async function submitQuestionComposerDecision(questionSet: WriterQuestionSet) {
    const existing = answersByQuestionSet[questionSet.question_set_id];
    const content = input.trim();
    if (!content && !existing?.answerText.trim()) {
      useQuestionInput(questionSet);
      return;
    }
    setInput("");
    const recorded = await recordQuestionAnswer(questionSet, content);
    const answer = recorded ?? existing;
    dismissLatestActionMessage();
    await onAction(questionSet.submit_action || "submit_outline_research_answers", {
      run_id: questionSet.run_id,
      question_set_id: questionSet.question_set_id,
      source_message_id: answer?.messageId ?? "",
      answer_text: answer?.answerText ?? ""
    });
    setActiveQuestionSetId("");
  }

  function useArtifactInput(review: WriterArtifactReview, mode: "supplement" | "revision") {
    setAnalyzerMode(false);
    setActiveQuestionSetId("");
    setActiveArtifactReview({ reviewId: review.review_id, mode });
    setActiveDraftReview(null);
    setActiveDecisionAction(null);
  }

  async function recordArtifactInput(
    review: WriterArtifactReview,
    mode: "supplement" | "revision",
    content: string
  ): Promise<{ messageId: string; text: string } | null> {
    const trimmed = content.trim();
    if (!trimmed) {
      return null;
    }
    const isSupplement = mode === "supplement";
    const result = await postMessage(taskId, {
      content: trimmed,
      payload: {
        channel: isSupplement ? "writer_artifact_supplement" : "writer_artifact_revision_feedback",
        run_id: review.run_id,
        review_id: review.review_id,
        artifact_kind: review.artifact_kind,
        input_role: isSupplement ? "artifact_supplement" : "artifact_revision_feedback",
        [isSupplement ? "supplement_text" : "revision_feedback"]: trimmed
      }
    });
    if (!isConversationMessage(result)) {
      return null;
    }
    const recorded = { messageId: result.message_id, text: result.content };
    setLocalArtifactInputsByReview((current) => ({
      ...current,
      [review.review_id]: {
        ...(current[review.review_id] ?? {}),
        [mode]: recorded
      }
    }));
    void queryClient.invalidateQueries({ queryKey: ["messages", taskId] });
    return recorded;
  }

  async function approveArtifact(review: WriterArtifactReview, override?: { messageId: string; text: string } | null) {
    const stored = override ?? artifactInputsByReview[review.review_id]?.supplement;
    await onAction("approve_writer_artifact", {
      ...reviewActionPayload(review, "approve_writer_artifact"),
      supplement_text: stored?.text ?? "",
      source_message_id: stored?.messageId ?? ""
    });
  }

  async function requestArtifactRevision(review: WriterArtifactReview, override?: { messageId: string; text: string } | null) {
    const stored = override ?? artifactInputsByReview[review.review_id]?.revision;
    await onAction("request_writer_artifact_revision", {
      ...reviewActionPayload(review, "request_writer_artifact_revision"),
      revision_feedback: stored?.text ?? "",
      source_message_id: stored?.messageId ?? ""
    });
  }

  async function deferArtifact(review: WriterArtifactReview) {
    dismissLatestActionMessage();
    await onAction("defer_writer_artifact_review", reviewActionPayload(review, "defer_writer_artifact_review"));
  }

  async function runArtifactReviewer(review: WriterArtifactReview, reviewerAction: WriterReviewAction) {
    await onAction("run_reviewer", reviewReviewerActionPayload(review, reviewerAction));
  }

  function useDraftInput(review: WriterDraftReview, action: string) {
    setAnalyzerMode(false);
    setActiveQuestionSetId("");
    setActiveArtifactReview(null);
    setActiveDraftReview({ reviewId: review.review_id, action });
    setActiveDecisionAction(null);
  }

  async function recordDraftInput(review: WriterDraftReview, action: string, content: string): Promise<{ messageId: string; text: string } | null> {
    const trimmed = content.trim();
    if (!trimmed) {
      return null;
    }
    const result = await postMessage(taskId, {
      content: trimmed,
      payload: {
        channel: "writer_draft_review_feedback",
        run_id: review.run_id,
        review_id: review.review_id,
        chapter_id: review.chapter_id,
        draft_id: review.draft_id,
        action,
        feedback_text: trimmed
      }
    });
    if (!isConversationMessage(result)) {
      return null;
    }
    const recorded = { messageId: result.message_id, text: result.content };
    setLocalDraftInputsByReview((current) => ({
      ...current,
      [review.review_id]: {
        ...(current[review.review_id] ?? {}),
        [action]: recorded
      }
    }));
    void queryClient.invalidateQueries({ queryKey: ["messages", taskId] });
    return recorded;
  }

  async function submitDraftAction(review: WriterDraftReview, action: string, override?: { messageId: string; text: string } | null) {
    const stored = override ?? draftInputsByReview[review.review_id]?.[action];
    dismissLatestActionMessage();
    await onAction(action, {
      ...draftActionPayload(review, action),
      feedback_text: stored?.text ?? "",
      source_message_id: stored?.messageId ?? ""
    });
  }

  async function runDraftReviewer(review: WriterDraftReview, reviewerAction: WriterReviewAction) {
    await onAction("run_reviewer", draftReviewerActionPayload(review, reviewerAction));
  }

  async function submitDraftComposerDecision(review: WriterDraftReview, action: string) {
    const existing = draftInputsByReview[review.review_id]?.[action];
    const content = input.trim();
    if (["rewrite_chapter", "replan_chapter"].includes(action) && !content && !existing?.text.trim()) {
      useDraftInput(review, action);
      return;
    }
    setInput("");
    const recorded = await recordDraftInput(review, action, content);
    await submitDraftAction(review, action, recorded);
    setActiveDraftReview(null);
  }

  function clearComposerContext() {
    setAnalyzerMode(false);
    setActiveQuestionSetId("");
    setActiveArtifactReview(null);
    setActiveDraftReview(null);
    setActiveDecisionAction(null);
  }

  async function submitArtifactReviewDecision(review: WriterArtifactReview, decision: "approve" | "revision") {
    const mode = decision === "approve" ? "supplement" : "revision";
    const existing = artifactInputsByReview[review.review_id]?.[mode];
    const content = input.trim();
    if (decision === "revision" && !content && !existing?.text.trim()) {
      useArtifactInput(review, "revision");
      return;
    }
    setInput("");
    const recorded = await recordArtifactInput(review, mode, content);
    if (decision === "approve") {
      dismissLatestActionMessage();
      await approveArtifact(review, recorded);
    } else {
      dismissLatestActionMessage();
      await requestArtifactRevision(review, recorded);
    }
    setActiveArtifactReview(null);
  }

  async function submitArtifactComposerDecision(decision: "approve" | "revision") {
    if (!activeArtifactContext) {
      return;
    }
    await submitArtifactReviewDecision(activeArtifactContext, decision);
  }

  async function submitComposerDecisionAction(card: DecisionCardModel, action: DecisionAction) {
    const needsInput = decisionActionNeedsInput(action);
    const content = input.trim();
    if (needsInput && !content) {
      setActiveQuestionSetId("");
      setActiveArtifactReview(null);
      setActiveDraftReview(null);
      setActiveDecisionAction({ cardId: card.card_id, action });
      return;
    }

    setInput("");
    let sourceMessageId = "";
    if (content) {
      const result = await postMessage(taskId, {
        content,
        payload: {
          channel: "writer_decision_feedback",
          card_id: card.card_id,
          action: action.action,
          feedback_text: content
        }
      });
      if (isConversationMessage(result)) {
        sourceMessageId = result.message_id;
      }
      void queryClient.invalidateQueries({ queryKey: ["messages", taskId] });
    }

    dismissLatestActionMessage();
    await onAction(action.action, {
      ...(action.payload ?? {}),
      feedback_text: content,
      revision_feedback: content,
      user_feedback: content,
      supplement_text: content,
      source_message_id: sourceMessageId
    });
    setActiveDecisionAction(null);
  }

  function dismissLatestActionMessage() {
    if (!latestActionMessage) {
      return;
    }
    setDismissedActionMessageIds((current) => new Set(current).add(latestActionMessage.message_id));
  }

  const composerContextLabel = analyzerMode
    ? "正在和小说专家讨论剧情"
    : activeQuestionSet
      ? `正在回答${questionResearchLabel(activeQuestionSet)}问题`
      : activeArtifactContext || composerArtifactReview
        ? `正在审阅：${(activeArtifactContext ?? composerArtifactReview)?.title ?? ""}`
        : (activeDraftContext || composerDraftReview) && activeDraftReview
          ? draftContextLabel(activeDraftReview.action)
          : activeDecisionAction
            ? `正在准备：${publicDecisionLabel(activeDecisionAction.action.label)}`
            : "";
  const composerMode = analyzerMode
    ? "analyzer"
    : composerDraftReview
      ? "draft"
      : composerArtifactReview
        ? "artifact"
        : composerQuestionSet
          ? "question"
          : composerDecisionCards.length
            ? "decision"
            : "plain";
  const statusLine = useMemo(
    () =>
      buildCurrentStatusLine({
        jobEvents,
        progress: selectedTask?.progress ?? null,
        activeJob: activeTaskJob,
        analyzerMode,
        composerQuestionSet,
        composerArtifactReview,
        composerDraftReview,
        composerDecisionCards,
        activeDecisionAction
      }),
    [
      activeDecisionAction,
      activeTaskJob,
      analyzerMode,
      composerArtifactReview,
      composerDecisionCards,
      composerDraftReview,
      composerQuestionSet,
      jobEvents,
      selectedTask?.progress
    ]
  );

  return (
    <div className="conversation-pane">
      <div className="pane-title-row">
        <div>
          <h2>会话</h2>
          <p>{selectedTask ? `任务 ${selectedTask.task_id}` : "请选择左侧任务"}</p>
        </div>
        <div className="pane-title-actions">
          <button
            type="button"
            className={analyzerMode ? "primary-button" : "secondary-button"}
            disabled={!selectedTask || submitMutation.isPending}
            onClick={() => {
              setAnalyzerMode((current) => !current);
              setActiveQuestionSetId("");
              setActiveArtifactReview(null);
              setActiveDraftReview(null);
              setActiveDecisionAction(null);
            }}
          >
            <BookOpenCheck size={16} aria-hidden="true" />
            {analyzerMode ? "退出专家意见" : "小说专家意见"}
          </button>
          <button
            type="button"
            className="primary-button"
            disabled={!selectedTask || actionPending}
            onClick={() => void requestWriterStart()}
          >
            <WandSparkles size={16} aria-hidden="true" />
            开始续写
          </button>
        </div>
      </div>

      <MessageList
        messages={displayMessages}
        pending={actionPending}
        activeQuestionSetId={activeQuestionSetId}
        activeArtifactReview={activeArtifactReview}
        activeDraftReview={activeDraftReview}
        answersByQuestionSet={answersByQuestionSet}
        artifactInputsByReview={artifactInputsByReview}
        draftInputsByReview={draftInputsByReview}
        onUseQuestionInput={useQuestionInput}
        onSubmitQuestionSet={submitQuestionSet}
        onDeferQuestionSet={deferQuestionSet}
        onUseArtifactInput={useArtifactInput}
        onApproveArtifact={approveArtifact}
        onRequestArtifactRevision={requestArtifactRevision}
        onDeferArtifact={deferArtifact}
        onUseDraftInput={useDraftInput}
        onSubmitDraftAction={submitDraftAction}
        onOpenArtifactDetail={onOpenArtifactDetail}
      />

      <CurrentTaskStatus status={statusLine} />

      <form className={`composer composer-${composerMode}`} onSubmit={handleSubmit}>
        {composerContextLabel ? (
          <div className="writer-answer-context">
            <span>{composerContextLabel}</span>
            <button type="button" className="link-button" onClick={() => clearComposerContext()}>
              取消
            </button>
          </div>
        ) : null}
        <label className="sr-only" htmlFor="conversation-input">
          输入给 Agent 的自然语言
        </label>
        <textarea
          id="conversation-input"
          aria-label="输入给 Agent 的自然语言"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder={
            analyzerMode
              ? "向小说专家提问，例如：当前未解之谜哪条最适合下一阶段回收？"
              : activeQuestionSet || composerQuestionSet
                ? `回答当前${questionResearchLabel(activeQuestionSet ?? composerQuestionSet)}问题，然后点击右侧分支按钮继续。`
                : activeWriterJob
                  ? "后台任务正在处理你的上一项决策，完成后会刷新审阅入口。"
                : activeArtifactContext || composerArtifactReview
                  ? "输入通过补充或调整反馈，然后点击右侧分支按钮。"
                  : activeDraftContext || composerDraftReview
                    ? "输入草稿调整反馈，然后点击右侧分支按钮。"
                    : activeDecisionAction
                      ? "输入本次分支需要的反馈，然后点击右侧分支按钮。"
              : "输入自然语言方向。只有明确以 / 开头时才进入高级命令兼容路径。"
          }
          rows={composerDraftReview ? 2 : 4}
          disabled={!selectedTask || Boolean(activeWriterJob)}
        />
        {composerQuestionSet ? (
          <div className="composer-actions composer-decision-actions" aria-label="当前问题分支">
            <button
              type="submit"
              className="primary-icon-button send-button"
              disabled={!selectedTask || submitMutation.isPending || !input.trim()}
              aria-label="发送"
              title="先记录回答"
            >
              <Send size={18} aria-hidden="true" />
            </button>
            <button
              type="button"
              className="primary-button"
              disabled={!selectedTask || actionPending || submitMutation.isPending}
              onClick={() => void submitQuestionComposerDecision(composerQuestionSet)}
            >
              提交回答并继续研究
            </button>
            <button
              type="button"
              className="secondary-button"
              disabled={!selectedTask || actionPending || submitMutation.isPending}
              onClick={() => void deferQuestionSet(composerQuestionSet)}
            >
              稍后继续
            </button>
          </div>
        ) : composerArtifactReview ? (
          <div className="composer-actions">
            {composerArtifactReview.detail_artifact_id ? (
              <button
                type="button"
                className="secondary-button"
                disabled={!selectedTask || actionPending || submitMutation.isPending}
                onClick={() => onOpenArtifactDetail?.(composerArtifactReview.detail_artifact_id)}
              >
                查看详情
              </button>
            ) : null}
            {reviewerActions(composerArtifactReview.actions).map((reviewerAction) => (
              <button
                key={`${reviewerAction.action}:${reviewerAction.label}:${String(reviewerAction.payload?.reviewer_id ?? "")}`}
                type="button"
                className="secondary-button"
                disabled={!selectedTask || actionPending || submitMutation.isPending}
                title={reviewerAction.description}
                onClick={() => void runArtifactReviewer(composerArtifactReview, reviewerAction)}
              >
                <ClipboardCheck size={15} aria-hidden="true" />
                {reviewerAction.label}
              </button>
            ))}
            <button
              type="button"
              className="primary-button"
              disabled={!selectedTask || actionPending || submitMutation.isPending}
              onClick={() => void submitArtifactReviewDecision(composerArtifactReview, "approve")}
            >
              通过并继续
            </button>
            <button
              type="button"
              className="secondary-button"
              disabled={
                !selectedTask ||
                actionPending ||
                submitMutation.isPending ||
                (!input.trim() && !artifactInputsByReview[composerArtifactReview.review_id]?.revision?.text.trim())
              }
              onClick={() => void submitArtifactReviewDecision(composerArtifactReview, "revision")}
            >
              不通过并调整
            </button>
            <button
              type="button"
              className="secondary-button"
              disabled={!selectedTask || actionPending || submitMutation.isPending}
              onClick={() => void deferArtifact(composerArtifactReview)}
            >
              稍后继续
            </button>
          </div>
        ) : composerDraftReview ? (
          <div className="composer-actions composer-decision-actions" aria-label="当前草稿分支">
            {composerDraftReview.detail_artifact_id ? (
              <button
                type="button"
                className="secondary-button"
                disabled={!selectedTask || actionPending || submitMutation.isPending}
                onClick={() => onOpenArtifactDetail?.(composerDraftReview.detail_artifact_id)}
              >
                查看完整正文
              </button>
            ) : null}
            {reviewerActions(composerDraftReview.actions).map((reviewerAction) => (
              <button
                key={`${reviewerAction.action}:${reviewerAction.label}:${String(reviewerAction.payload?.reviewer_id ?? "")}`}
                type="button"
                className="secondary-button"
                disabled={!selectedTask || actionPending || submitMutation.isPending}
                title={reviewerAction.description}
                onClick={() => void runDraftReviewer(composerDraftReview, reviewerAction)}
              >
                <ClipboardCheck size={15} aria-hidden="true" />
                {reviewerAction.label}
              </button>
            ))}
            <button
              type="button"
              className="primary-button"
              disabled={!selectedTask || actionPending || submitMutation.isPending}
              onClick={() => void submitDraftComposerDecision(composerDraftReview, "accept_chapter")}
            >
              接受本章
            </button>
            <button
              type="button"
              className="secondary-button"
              disabled={!selectedTask || actionPending || submitMutation.isPending}
              onClick={() => void submitDraftComposerDecision(composerDraftReview, "rewrite_chapter")}
            >
              基于反馈重写
            </button>
            <button
              type="button"
              className="secondary-button"
              disabled={!selectedTask || actionPending || submitMutation.isPending}
              onClick={() => void submitDraftComposerDecision(composerDraftReview, "replan_chapter")}
            >
              修改章节梗概后重写
            </button>
          </div>
        ) : composerDecisionCards.length ? (
          <div className="composer-actions composer-decision-actions" aria-label="当前分支选择">
            <button
              type="submit"
              className="primary-icon-button send-button"
              disabled={!selectedTask || submitMutation.isPending || !input.trim() || Boolean(activeDecisionAction)}
              aria-label="发送"
              title="作为普通消息发送"
            >
              <Send size={18} aria-hidden="true" />
            </button>
            {composerDecisionCards.flatMap((card) =>
              card.actions.map((action) => (
                <button
                  key={`${card.card_id}:${action.action}:${action.label}`}
                  type="button"
                  className={action.variant === "danger" ? "danger-button" : action.variant === "primary" ? "primary-button" : "secondary-button"}
                  disabled={!selectedTask || actionPending || submitMutation.isPending}
                  title={action.description}
                  onClick={() => void submitComposerDecisionAction(card, action)}
                >
                  {activeDecisionAction?.cardId === card.card_id && activeDecisionAction.action.action === action.action
                    ? `提交：${publicDecisionLabel(action.label)}`
                    : publicDecisionLabel(action.label)}
                </button>
              ))
            )}
          </div>
        ) : (
          <button type="submit" className="primary-icon-button send-button" disabled={!selectedTask || submitMutation.isPending || !input.trim()} aria-label="发送">
            <Send size={18} aria-hidden="true" />
          </button>
        )}
      </form>

      <WriterIntentWizard
        open={wizardOpen}
        initialGoal={latestNaturalGoal}
        pending={actionPending}
        onClose={() => setWizardOpen(false)}
        onSubmit={submitWriterIntent}
      />
    </div>
  );
}

function localAnalyzerMessages({
  taskId,
  pendingQuestion,
  error
}: {
  taskId: string;
  pendingQuestion: string;
  error: string;
}): ConversationMessage[] {
  if (!taskId) {
    return [];
  }
  const createdAt = new Date().toISOString();
  if (error) {
    return [
      {
        message_id: "local-analyzer-error",
        task_id: taskId,
        role: "error",
        content: error,
        payload: { channel: "outline_analyzer", status: "error" },
        decision_cards: [],
        created_at: createdAt
      }
    ];
  }
  if (!pendingQuestion) {
    return [];
  }
  return [
    {
      message_id: "local-analyzer-user",
      task_id: taskId,
      role: "user",
      content: pendingQuestion,
      payload: { channel: "outline_analyzer", status: "pending" },
      decision_cards: [],
      created_at: createdAt
    },
    {
      message_id: "local-analyzer-pending",
      task_id: taskId,
      role: "assistant",
      content: "Analyzer 正在阅读当前小说记忆并分析剧情，请稍等。",
      payload: { channel: "outline_analyzer", status: "pending" },
      decision_cards: [],
      created_at: createdAt
    }
  ];
}

function isConversationMessage(value: unknown): value is ConversationMessage {
  return Boolean(value && typeof value === "object" && "message_id" in value && "content" in value);
}

interface CurrentStatusLine {
  tone: "idle" | "running" | "waiting" | "done" | "error";
  label: string;
  text: string;
  recoverySuggestion?: string;
}

function CurrentTaskStatus({ status }: { status: CurrentStatusLine | null }) {
  if (!status) {
    return null;
  }
  const Icon = status.tone === "running" ? LoaderCircle : status.tone === "done" ? CheckCircle2 : ClipboardCheck;
  return (
    <div className={`current-task-status status-${status.tone}`} role="status" aria-live="polite">
      <Icon size={14} aria-hidden="true" className={status.tone === "running" ? "status-spinner" : ""} />
      <span className="current-status-label">{status.label}</span>
      <span className="current-status-text">{status.text}</span>
      {status.recoverySuggestion ? <span className="current-status-recovery">{status.recoverySuggestion}</span> : null}
    </div>
  );
}

function buildCurrentStatusLine({
  jobEvents,
  progress,
  activeJob,
  analyzerMode,
  composerQuestionSet,
  composerArtifactReview,
  composerDraftReview,
  composerDecisionCards,
  activeDecisionAction
}: {
  jobEvents: JobEventView[];
  progress: TaskProgress | null;
  activeJob: JobSummary | null;
  analyzerMode: boolean;
  composerQuestionSet: WriterQuestionSet | null;
  composerArtifactReview: WriterArtifactReview | null;
  composerDraftReview: WriterDraftReview | null;
  composerDecisionCards: DecisionCardModel[];
  activeDecisionAction: { cardId: string; action: DecisionAction } | null;
}): CurrentStatusLine | null {
  const latestEvent = latestJobEvent(jobEvents);
  if (latestEvent) {
    const eventText = toPublicStatusText(latestEvent.message, "");
    if (latestEvent.kind === "succeeded") {
      return {
        tone: "done",
        label: "已完成",
        text: eventText || "任务已经完成。"
      };
    }
    if (["failed", "error"].includes(latestEvent.kind)) {
      return {
        tone: "error",
        label: "失败",
        text: eventText || "任务执行失败。",
        recoverySuggestion: latestEvent.payload?.recovery_suggestion ? String(latestEvent.payload.recovery_suggestion) : ""
      };
    }
    if (latestEvent.kind === "cancelled") {
      return {
        tone: "idle",
        label: "已暂停",
        text: eventText || "任务已暂停，可以稍后继续。"
      };
    }
    return {
      tone: "running",
      label: latestEvent.kind === "queued" ? "排队中" : "进行中",
      text: eventText || "后台任务正在执行。"
    };
  }

  if (activeJob) {
    return {
      tone: "running",
      label: activeJob.status === "queued" ? "排队中" : "进行中",
      text: toPublicStatusText(activeJob.message, "") || "后台任务正在执行。"
    };
  }

  if (analyzerMode) {
    return {
      tone: "waiting",
      label: "专家意见",
      text: "你可以向小说专家提问；这不会推进 Writer 流程。"
    };
  }
  if (composerQuestionSet) {
    const researchLabel = questionResearchLabel(composerQuestionSet);
    return {
      tone: "waiting",
      label: "等待输入",
      text: `请回答当前${researchLabel}问题，提交后继续研究。`
    };
  }
  if (composerArtifactReview) {
    return {
      tone: "waiting",
      label: "等待审阅",
      text: `请审阅${composerArtifactReview.title || "当前产物"}。`
    };
  }
  if (composerDraftReview) {
    return {
      tone: "waiting",
      label: "等待决策",
      text: "请决定接受、重写、重规划或暂缓本章草稿。"
    };
  }
  if (activeDecisionAction) {
    return {
      tone: "waiting",
      label: "等待反馈",
      text: `请补充“${publicDecisionLabel(activeDecisionAction.action.label)}”需要的反馈。`
    };
  }
  if (composerDecisionCards.length) {
    return {
      tone: "waiting",
      label: "等待选择",
      text: composerDecisionCards[0]?.title ? toPublicStatusText(composerDecisionCards[0].title, "") : "请选择下一步。"
    };
  }

  const progressText = toPublicStatusText(progress?.message || progress?.step, "");
  if (progressText) {
    return {
      tone: "idle",
      label: "当前状态",
      text: progressText
    };
  }
  return null;
}

function latestJobEvent(jobEvents: JobEventView[]): JobEventView | null {
  if (!jobEvents.length) {
    return null;
  }
  return [...jobEvents].sort((left, right) => {
    const leftTime = Date.parse(left.created_at);
    const rightTime = Date.parse(right.created_at);
    if (Number.isFinite(leftTime) && Number.isFinite(rightTime) && leftTime !== rightTime) {
      return rightTime - leftTime;
    }
    return right.event_id.localeCompare(left.event_id);
  })[0] ?? null;
}

function isActiveJob(job: JobSummary | null | undefined): job is JobSummary {
  return Boolean(job && !["succeeded", "failed", "cancelled"].includes(job.status));
}

function isWriterJob(job: JobSummary): boolean {
  return job.type === "writer" || job.type === "writer_resume";
}

function isActionMessage(message: ConversationMessage): boolean {
  return (
    Boolean(message.decision_cards?.length) ||
    Boolean(message.writer_question_set) ||
    Boolean(message.writer_artifact_review) ||
    Boolean(message.writer_draft_review)
  );
}

function mergeArtifactInputs(
  base: Record<string, { supplement?: { messageId: string; text: string }; revision?: { messageId: string; text: string } }>,
  local: Record<string, { supplement?: { messageId: string; text: string }; revision?: { messageId: string; text: string } }>
) {
  const merged = { ...base };
  for (const [reviewId, value] of Object.entries(local)) {
    merged[reviewId] = { ...(merged[reviewId] ?? {}), ...value };
  }
  return merged;
}

function mergeDraftInputs(
  base: Record<string, Record<string, { messageId: string; text: string }>>,
  local: Record<string, Record<string, { messageId: string; text: string }>>
) {
  const merged = { ...base };
  for (const [reviewId, byAction] of Object.entries(local)) {
    merged[reviewId] = { ...(merged[reviewId] ?? {}), ...byAction };
  }
  return merged;
}

function reviewActionPayload(review: WriterArtifactReview, action: string): Record<string, unknown> {
  const configured = review.actions.find((item) => item.action === action)?.payload ?? {};
  return {
    run_id: review.run_id,
    review_id: review.review_id,
    artifact_kind: review.artifact_kind,
    artifact_id: review.artifact_id,
    ...configured
  };
}

function draftActionPayload(review: WriterDraftReview, action: string): Record<string, unknown> {
  const configured = review.actions.find((item) => item.action === action)?.payload ?? {};
  return {
    run_id: review.run_id,
    review_id: review.review_id,
    chapter_id: review.chapter_id,
    draft_id: review.draft_id,
    ...configured
  };
}

function reviewerActions(actions: WriterReviewAction[]): WriterReviewAction[] {
  return actions.filter((item) => item.action === "run_reviewer");
}

function reviewReviewerActionPayload(review: WriterArtifactReview, reviewerAction: WriterReviewAction): Record<string, unknown> {
  return {
    run_id: review.run_id,
    review_id: review.review_id,
    artifact_kind: review.artifact_kind,
    artifact_id: review.artifact_id,
    ...(reviewerAction.payload ?? {})
  };
}

function draftReviewerActionPayload(review: WriterDraftReview, reviewerAction: WriterReviewAction): Record<string, unknown> {
  return {
    run_id: review.run_id,
    review_id: review.review_id,
    chapter_id: review.chapter_id,
    draft_id: review.draft_id,
    ...(reviewerAction.payload ?? {})
  };
}

function draftContextLabel(action: string) {
  if (action === "rewrite_chapter") {
    return "正在写本章重写反馈";
  }
  if (action === "replan_chapter") {
    return "正在写章节梗概调整反馈";
  }
  if (action === "discard_chapter") {
    return "正在写作废说明";
  }
  return "正在写草稿调整反馈";
}

function questionResearchLabel(questionSet: WriterQuestionSet | null) {
  return questionSet?.stage === "draft_research_user_input" ? "正文研究" : "大纲研究";
}

function decisionActionNeedsInput(action: DecisionAction): boolean {
  return Boolean(action.requires_input) || ["request_writer_artifact_revision", "rewrite_chapter", "replan_chapter"].includes(action.action);
}
