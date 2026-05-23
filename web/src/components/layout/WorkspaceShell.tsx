import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Menu, PanelRightOpen, Settings, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { postAction } from "../../api/actions";
import { streamJobEvents } from "../../api/jobs";
import { createTask, deleteLatestWriterRun, deleteTask, getTasks, resetCloseRead, selectTask } from "../../api/tasks";
import type {
  CreateTaskRequest,
  DecisionCardModel,
  DeleteTaskPreview,
  JobEventView,
  JobSummary,
  TaskSummary,
  WebActionResult
} from "../../api/types";
import { ConversationPane } from "../conversation/ConversationPane";
import { ResultExplorer } from "../results/ResultExplorer";
import { TaskRail } from "../tasks/TaskRail";
import { toPublicStatusText } from "../../utils/status";

type MobilePanel = "tasks" | "conversation" | "results";

function shouldRefreshArtifactsForEvent(event: JobEventView) {
  const payload = event.payload ?? {};
  return (
    payload.event === "batch_done" ||
    payload.phase === "fragment_card_document_done" ||
    payload.phase === "creative_kb_complete" ||
    Array.isArray(payload.decision_cards)
  );
}

export function WorkspaceShell() {
  const queryClient = useQueryClient();
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>("conversation");
  const [activeJobs, setActiveJobs] = useState<JobSummary[]>([]);
  const [jobEvents, setJobEvents] = useState<JobEventView[]>([]);
  const [decisionCards, setDecisionCards] = useState<DecisionCardModel[]>([]);
  const [lastActionMessage, setLastActionMessage] = useState("");
  const [writerWizardSignal, setWriterWizardSignal] = useState(0);
  const [focusedArtifactId, setFocusedArtifactId] = useState("");

  const tasksQuery = useQuery({
    queryKey: ["tasks"],
    queryFn: getTasks
  });

  const tasks = tasksQuery.data ?? [];
  const selectedTask = useMemo(
    () => tasks.find((task) => task.task_id === selectedTaskId) ?? tasks[0] ?? null,
    [selectedTaskId, tasks]
  );

  useEffect(() => {
    if (!selectedTaskId && tasks.length > 0) {
      setSelectedTaskId(tasks.find((task) => task.active)?.task_id ?? tasks[0].task_id);
    }
  }, [selectedTaskId, tasks]);

  useEffect(() => {
    const activeTaskJobs = tasks
      .map((task) => task.active_job)
      .filter((job): job is JobSummary => job != null && !["succeeded", "failed", "cancelled"].includes(job.status));
    if (!activeTaskJobs.length) {
      return;
    }
    setActiveJobs((current) => {
      let changed = false;
      const next = [...current];
      for (const job of activeTaskJobs) {
        if (!next.some((existing) => existing.job_id === job.job_id)) {
          next.push(job);
          changed = true;
        }
      }
      return changed ? next : current;
    });
  }, [tasks]);

  useEffect(() => {
    const cleanups = activeJobs.map((job) =>
      streamJobEvents(
        job.job_id,
        (event) => {
          setJobEvents((current) =>
            current.some((existing) => existing.job_id === event.job_id && existing.event_id === event.event_id)
              ? current
              : [...current, event]
          );
          if (["succeeded", "failed", "cancelled", "error"].includes(event.kind)) {
            refreshTaskArtifacts(job.task_id);
            void queryClient.invalidateQueries({ queryKey: ["messages", job.task_id] });
            setActiveJobs((current) => current.filter((activeJob) => activeJob.job_id !== job.job_id));
          } else if (shouldRefreshArtifactsForEvent(event)) {
            refreshTaskArtifacts(job.task_id);
          }
          const eventCards = event.payload?.decision_cards;
          if (Array.isArray(eventCards)) {
            setDecisionCards(eventCards as DecisionCardModel[]);
          }
        },
        () => undefined
      )
    );
    return () => cleanups.forEach((cleanup) => cleanup());
  }, [activeJobs, queryClient]);

  const createMutation = useMutation({
    mutationFn: (request: CreateTaskRequest) => createTask(request),
    onSuccess: async (task) => {
      setSelectedTaskId(task.task_id);
      setMobilePanel("conversation");
      await queryClient.invalidateQueries({ queryKey: ["tasks"] });
      const result = await postAction(task.task_id, {
        action: "start_read",
        payload: { requested_from: "create_task" }
      });
      rememberActionResult(result);
    }
  });

  const selectMutation = useMutation({
    mutationFn: (taskId: string) => selectTask(taskId),
    onSuccess: (result) => {
      setSelectedTaskId(result.task_id);
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
      void queryClient.invalidateQueries({ queryKey: ["messages", result.task_id] });
    }
  });

  const actionMutation = useMutation({
    mutationFn: ({ taskId, action, payload }: { taskId: string; action: string; payload?: Record<string, unknown> }) =>
      postAction(taskId, { action, payload }),
    onSuccess: (result) => {
      rememberActionResult(result);
    }
  });

  const resetMutation = useMutation({
    mutationFn: (taskId: string) => resetCloseRead(taskId),
    onSuccess: (result) => {
      rememberActionResult(result);
    }
  });

  const deleteMutation = useMutation({
    mutationFn: ({ taskId, confirm }: { taskId: string; confirm: boolean }) => deleteTask(taskId, { confirm }),
    onSuccess: (_result, variables) => {
      if (variables.confirm && selectedTaskId === variables.taskId) {
        setSelectedTaskId("");
      }
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
    }
  });

  const deleteWriterRunMutation = useMutation({
    mutationFn: ({ taskId, confirm }: { taskId: string; confirm: boolean }) => deleteLatestWriterRun(taskId, { confirm }),
    onSuccess: (_result, variables) => {
      refreshTaskArtifacts(variables.taskId);
      void queryClient.invalidateQueries({ queryKey: ["messages", variables.taskId] });
    }
  });

  function rememberActionResult(result: WebActionResult) {
    setLastActionMessage(result.message);
    const resultJob = result.job;
    if (resultJob) {
      setActiveJobs((current) => (current.some((job) => job.job_id === resultJob.job_id) ? current : [...current, resultJob]));
    }
    if (result.decision_cards?.length) {
      setDecisionCards(result.decision_cards);
    }
    refreshTaskArtifacts(result.task_id);
    void queryClient.invalidateQueries({ queryKey: ["messages", result.task_id] });
  }

  function refreshTaskArtifacts(taskId: string) {
    void queryClient.invalidateQueries({ queryKey: ["tasks"] });
    void queryClient.invalidateQueries({ queryKey: ["artifact-tree", taskId] });
    void queryClient.invalidateQueries({ queryKey: ["artifact-view"] });
  }

  function handleSelectTask(taskId: string) {
    if (taskId === selectedTaskId || taskId === selectedTask?.task_id) {
      setMobilePanel("conversation");
      return;
    }
    setSelectedTaskId(taskId);
    setMobilePanel("conversation");
    selectMutation.mutate(taskId);
  }

  async function handleAction(action: string, payload: Record<string, unknown> = {}) {
    if (!selectedTask) {
      throw new Error("请先选择任务。");
    }
    return actionMutation.mutateAsync({ taskId: selectedTask.task_id, action, payload });
  }

  async function handleTaskAction(taskId: string, action: string, payload: Record<string, unknown> = {}) {
    return actionMutation.mutateAsync({ taskId, action, payload });
  }

  async function refreshTasks() {
    await queryClient.invalidateQueries({ queryKey: ["tasks"] });
    if (selectedTask?.task_id) {
      refreshTaskArtifacts(selectedTask.task_id);
    }
  }

  async function handleResetCloseRead(taskId: string) {
    return resetMutation.mutateAsync(taskId);
  }

  async function handleDeletePreview(taskId: string, confirm: boolean): Promise<DeleteTaskPreview> {
    return deleteMutation.mutateAsync({ taskId, confirm });
  }

  async function handleDeleteLatestWriterRun(taskId: string, confirm: boolean) {
    return deleteWriterRunMutation.mutateAsync({ taskId, confirm });
  }

  function openWriterWizard() {
    setMobilePanel("conversation");
    setWriterWizardSignal((current) => current + 1);
  }

  const shellStatus = selectedTask
    ? toPublicStatusText(selectedTask.progress?.step, selectedTask.close_read_done ? "可开始续写" : "进行中")
    : "未选择任务";
  const selectedJobIds = new Set(activeJobs.filter((job) => job.task_id === selectedTask?.task_id).map((job) => job.job_id));

  return (
    <div className="workspace-shell" data-testid="workspace-shell">
      <header className="top-bar">
        <div className="brand-lockup">
          <Sparkles aria-hidden="true" className="brand-icon" />
          <div>
            <strong>Novel Agent</strong>
            <span>Web 工作台</span>
          </div>
        </div>
        <div className="task-context" aria-live="polite">
          <span>当前任务</span>
          <strong>{selectedTask?.task_id ?? "未选择"}</strong>
          <span className="status-pill">{shellStatus}</span>
        </div>
        <div className="top-actions">
          {lastActionMessage ? <span className="action-toast">{lastActionMessage}</span> : null}
          <button className="icon-button" type="button" aria-label="设置">
            <Settings aria-hidden="true" size={18} />
          </button>
        </div>
      </header>

      <div className="mobile-switch" aria-label="移动端面板切换">
        <button type="button" className={mobilePanel === "tasks" ? "active" : ""} onClick={() => setMobilePanel("tasks")}>
          <Menu size={16} aria-hidden="true" />
          任务
        </button>
        <button
          type="button"
          className={mobilePanel === "conversation" ? "active" : ""}
          onClick={() => setMobilePanel("conversation")}
        >
          会话
        </button>
        <button type="button" className={mobilePanel === "results" ? "active" : ""} onClick={() => setMobilePanel("results")}>
          <PanelRightOpen size={16} aria-hidden="true" />
          结果
        </button>
      </div>

      <main className="workspace-grid">
        <section className={`workspace-panel task-panel mobile-${mobilePanel === "tasks" ? "visible" : "hidden"}`} aria-label="任务列表">
          <TaskRail
            tasks={tasks}
            selectedTaskId={selectedTask?.task_id ?? ""}
            isLoading={tasksQuery.isLoading}
            isBusy={createMutation.isPending || selectMutation.isPending || actionMutation.isPending || deleteWriterRunMutation.isPending}
            onCreateTask={(request) => createMutation.mutateAsync(request)}
            onSelectTask={handleSelectTask}
            onAction={(taskId, action, payload) => handleTaskAction(taskId, action, payload)}
            onStartWriter={openWriterWizard}
            onResetCloseRead={handleResetCloseRead}
            onDeleteTask={handleDeletePreview}
            onDeleteLatestWriterRun={handleDeleteLatestWriterRun}
            onRefresh={refreshTasks}
          />
        </section>

        <section
          className={`workspace-panel conversation-panel mobile-${mobilePanel === "conversation" ? "visible" : "hidden"}`}
          aria-label="会话"
        >
          <ConversationPane
            selectedTask={selectedTask}
            jobEvents={jobEvents.filter((event) => selectedJobIds.has(event.job_id))}
            decisionCards={decisionCards}
            actionPending={actionMutation.isPending}
            writerWizardSignal={writerWizardSignal}
            onOpenArtifactDetail={setFocusedArtifactId}
            onAction={handleAction}
          />
        </section>

        <section className={`workspace-panel result-panel mobile-${mobilePanel === "results" ? "visible" : "hidden"}`} aria-label="结果浏览器">
          <ResultExplorer
            selectedTaskId={selectedTask?.task_id ?? ""}
            focusedArtifactId={focusedArtifactId}
            actionPending={actionMutation.isPending}
            onAction={handleAction}
          />
        </section>
      </main>
    </div>
  );
}
