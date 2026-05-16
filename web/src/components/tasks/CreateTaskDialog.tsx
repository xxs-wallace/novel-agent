import { X } from "lucide-react";
import { FormEvent, useState } from "react";

import type { CreateTaskRequest } from "../../api/types";

interface CreateTaskDialogProps {
  open: boolean;
  pending?: boolean;
  onClose: () => void;
  onSubmit: (request: CreateTaskRequest) => Promise<unknown>;
}

export function CreateTaskDialog({ open, pending = false, onClose, onSubmit }: CreateTaskDialogProps) {
  const [taskId, setTaskId] = useState("");
  const [sourcePath, setSourcePath] = useState("");
  const [error, setError] = useState("");

  if (!open) {
    return null;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (!taskId.trim()) {
      setError("请填写任务 ID。");
      return;
    }
    if (!sourcePath.trim()) {
      setError("请填写原文路径，创建后会立即导入原文。");
      return;
    }
    await onSubmit({ task_id: taskId.trim(), source_path: sourcePath.trim() });
    setTaskId("");
    setSourcePath("");
    onClose();
  }

  return (
    <div className="dialog-backdrop">
      <div role="dialog" aria-modal="true" aria-labelledby="create-task-title" className="dialog-card">
        <div className="dialog-header">
          <h2 id="create-task-title">创建任务</h2>
          <button className="icon-button" type="button" aria-label="关闭创建任务" onClick={onClose}>
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <form className="dialog-form" onSubmit={handleSubmit}>
          <label>
            任务 ID
            <input value={taskId} onChange={(event) => setTaskId(event.target.value)} placeholder="longzu-vol-1" autoFocus />
          </label>
          <label>
            原文路径
            <input value={sourcePath} onChange={(event) => setSourcePath(event.target.value)} placeholder="/path/to/book.txt" />
          </label>
          <p className="form-hint">创建后会立即开始导入原文，左侧进度会自动刷新。</p>
          {error ? <p className="form-error">{error}</p> : null}
          <div className="dialog-actions">
            <button type="button" className="secondary-button" onClick={onClose}>
              取消
            </button>
            <button type="submit" className="primary-button" disabled={pending}>
              创建并导入
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
