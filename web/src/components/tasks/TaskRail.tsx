import { Plus, RefreshCw } from "lucide-react";
import { type MouseEvent, useState } from "react";

import type { CreateTaskRequest, DeleteTaskPreview, TaskSummary } from "../../api/types";
import { blockingBadge, kbStatus, percent, toPublicStatusText, writerStatus } from "../../utils/status";
import { CreateTaskDialog } from "./CreateTaskDialog";
import { TaskActionMenu } from "./TaskActionMenu";

interface TaskRailProps {
  tasks: TaskSummary[];
  selectedTaskId: string;
  isLoading?: boolean;
  isBusy?: boolean;
  onCreateTask: (request: CreateTaskRequest) => Promise<unknown>;
  onSelectTask: (taskId: string) => void;
  onAction: (action: string, payload?: Record<string, unknown>) => void;
  onStartWriter: () => void;
  onResetCloseRead: (taskId: string) => Promise<unknown>;
  onDeleteTask: (taskId: string, confirm: boolean) => Promise<DeleteTaskPreview>;
}

export function TaskRail({
  tasks,
  selectedTaskId,
  isLoading = false,
  isBusy = false,
  onCreateTask,
  onSelectTask,
  onAction,
  onStartWriter,
  onResetCloseRead,
  onDeleteTask
}: TaskRailProps) {
  const [createOpen, setCreateOpen] = useState(false);
  const [deletePreview, setDeletePreview] = useState<{ taskId: string; preview: DeleteTaskPreview } | null>(null);

  async function previewDelete(taskId: string) {
    const preview = await onDeleteTask(taskId, false);
    setDeletePreview({ taskId, preview });
  }

  async function confirmDelete() {
    if (!deletePreview) {
      return;
    }
    await onDeleteTask(deletePreview.taskId, true);
    setDeletePreview(null);
  }

  function selectTask(taskId: string) {
    if (taskId === selectedTaskId) {
      return;
    }
    onSelectTask(taskId);
  }

  function selectTaskFromButton(event: MouseEvent<HTMLButtonElement>, taskId: string) {
    event.stopPropagation();
    selectTask(taskId);
  }

  return (
    <div className="task-rail">
      <div className="rail-header">
        <div>
          <h1>任务</h1>
          <p>{isLoading ? "加载中" : `${tasks.length} 个任务`}</p>
        </div>
        <button type="button" className="primary-icon-button" onClick={() => setCreateOpen(true)} aria-label="快速创建任务">
          <Plus size={18} aria-hidden="true" />
        </button>
      </div>

      <button type="button" className="wide-primary-button" onClick={() => setCreateOpen(true)}>
        创建任务
      </button>

      <div className="task-list" aria-live="polite">
        {tasks.length === 0 && !isLoading ? <div className="empty-state">还没有任务。</div> : null}
        {tasks.map((task) => {
          const selected = task.task_id === selectedTaskId;
          const readPct = percent(task.read_completed, task.total_documents);
          const closeReadPct = percent(task.close_read_completed, task.total_documents);
          const badge = blockingBadge(task.progress);
          return (
            <article
              key={task.task_id}
              className={`task-card ${selected ? "selected" : ""}`}
              aria-current={selected ? "true" : undefined}
              onClick={() => selectTask(task.task_id)}
            >
              <div className="task-card-topline">
                <button type="button" className="link-button task-id-button" onClick={(event) => selectTaskFromButton(event, task.task_id)}>
                  {task.task_id}
                </button>
                <TaskActionMenu
                  taskId={task.task_id}
                  disabled={isBusy}
                  onAction={(action, payload) => onAction(action, payload)}
                  onStartWriter={onStartWriter}
                  onResetCloseRead={() => void onResetCloseRead(task.task_id)}
                  onDeletePreview={() => void previewDelete(task.task_id)}
                />
              </div>
              <p className="source-path" title={task.source_path}>
                {task.source_path || "未绑定原文路径"}
              </p>
              {badge ? <span className="blocking-badge">{badge}</span> : null}
              <div className="progress-stack">
                <ProgressLine label="粗读" value={readPct} detail={`${task.read_completed}/${task.total_documents || 0}`} />
                <ProgressLine label="精读" value={closeReadPct} detail={`${task.close_read_completed}/${task.total_documents || 0}`} />
              </div>
              <div className="task-status-grid">
                <span>KB</span>
                <strong>{kbStatus(task.progress)}</strong>
                <span>Writer</span>
                <strong>{writerStatus(task)}</strong>
              </div>
              {task.progress?.message ? <p className="task-message">{toPublicStatusText(task.progress.message)}</p> : null}
            </article>
          );
        })}
      </div>

      <button type="button" className="secondary-button refresh-button" onClick={() => window.location.reload()}>
        <RefreshCw size={16} aria-hidden="true" />
        刷新
      </button>

      <CreateTaskDialog open={createOpen} pending={isBusy} onClose={() => setCreateOpen(false)} onSubmit={onCreateTask} />

      {deletePreview ? (
        <div className="dialog-backdrop">
          <div role="dialog" aria-modal="true" aria-labelledby="delete-task-title" className="dialog-card">
            <div className="dialog-header">
              <h2 id="delete-task-title">删除任务预览</h2>
            </div>
            <p>将删除任务 {deletePreview.taskId} 的本地建模产物。</p>
            <pre className="preview-box">{JSON.stringify(deletePreview.preview.would_delete ?? deletePreview.preview, null, 2)}</pre>
            <div className="dialog-actions">
              <button type="button" className="secondary-button" onClick={() => setDeletePreview(null)}>
                取消
              </button>
              <button type="button" className="danger-button" onClick={() => void confirmDelete()}>
                确认删除
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ProgressLine({ label, value, detail }: { label: string; value: number; detail: string }) {
  return (
    <div className="progress-line">
      <div>
        <span>{label}</span>
        <span>{detail}</span>
      </div>
      <div className="progress-track" aria-label={`${label}进度 ${value}%`}>
        <span style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}
