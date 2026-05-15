import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Send, WandSparkles } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { postCommand } from "../../api/actions";
import { getMessages, postMessage } from "../../api/messages";
import type { DecisionCardModel, JobEventView, TaskSummary } from "../../api/types";
import { MessageList } from "./MessageList";
import { ScopedRevisionComposer } from "./ScopedRevisionComposer";
import { WriterIntentWizard } from "./WriterIntentWizard";

interface ConversationPaneProps {
  selectedTask: TaskSummary | null;
  jobEvents: JobEventView[];
  decisionCards: DecisionCardModel[];
  actionPending?: boolean;
  writerWizardSignal?: number;
  onAction: (action: string, payload?: Record<string, unknown>) => Promise<unknown> | void;
}

export function ConversationPane({
  selectedTask,
  jobEvents,
  decisionCards,
  actionPending = false,
  writerWizardSignal = 0,
  onAction
}: ConversationPaneProps) {
  const queryClient = useQueryClient();
  const [input, setInput] = useState("");
  const [wizardOpen, setWizardOpen] = useState(false);
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
      if (content.trim().startsWith("/")) {
        return postCommand(taskId, { command: content.trim() });
      }
      return postMessage(taskId, { content, payload: { channel: "natural_language" } });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["messages", taskId] });
    }
  });

  const messages = messagesQuery.data ?? [];

  useEffect(() => {
    if (writerWizardSignal > 0 && selectedTask) {
      setWizardOpen(true);
    }
  }, [selectedTask, writerWizardSignal]);

  const floatingDecisionCards = useMemo(() => {
    const fromMessages = messages.flatMap((message) => message.decision_cards ?? []);
    const ids = new Set(fromMessages.map((card) => card.card_id));
    return decisionCards.filter((card) => !ids.has(card.card_id));
  }, [decisionCards, messages]);

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
    setInput("");
    await submitMutation.mutateAsync(content);
  }

  async function submitWriterIntent(payload: Record<string, unknown>) {
    await onAction("start_writer", payload);
  }

  return (
    <div className="conversation-pane">
      <div className="pane-title-row">
        <div>
          <h2>会话</h2>
          <p>{selectedTask ? `任务 ${selectedTask.task_id}` : "请选择左侧任务"}</p>
        </div>
        <button type="button" className="primary-button" disabled={!selectedTask || actionPending} onClick={() => setWizardOpen(true)}>
          <WandSparkles size={16} aria-hidden="true" />
          开始续写
        </button>
      </div>

      <MessageList
        messages={messages}
        jobEvents={jobEvents}
        pending={actionPending}
        onAction={(action, payload) => onAction(action, payload)}
      />

      {floatingDecisionCards.length ? (
        <div className="floating-decision-stack">
          {floatingDecisionCards.map((card) => (
            <div key={card.card_id} className="decision-card-proxy">
              <MessageList
                messages={[
                  {
                    message_id: `proxy:${card.card_id}`,
                    task_id: taskId,
                    role: "assistant",
                    content: "",
                    payload: {},
                    decision_cards: [card],
                    created_at: new Date().toISOString()
                  }
                ]}
                jobEvents={[]}
                pending={actionPending}
                onAction={onAction}
              />
            </div>
          ))}
        </div>
      ) : null}

      <ScopedRevisionComposer
        disabled={!selectedTask || actionPending}
        onSubmit={(payload) => onAction("request_scoped_artifact_revision", payload)}
      />

      <form className="composer" onSubmit={handleSubmit}>
        <label className="sr-only" htmlFor="conversation-input">
          输入给 Agent 的自然语言
        </label>
        <textarea
          id="conversation-input"
          aria-label="输入给 Agent 的自然语言"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="输入自然语言方向。只有明确以 / 开头时才进入高级命令兼容路径。"
          rows={4}
          disabled={!selectedTask}
        />
        <button type="submit" className="primary-icon-button send-button" disabled={!selectedTask || submitMutation.isPending || !input.trim()} aria-label="发送">
          <Send size={18} aria-hidden="true" />
        </button>
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
