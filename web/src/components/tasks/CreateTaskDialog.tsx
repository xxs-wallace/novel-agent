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
  const [originalOnly, setOriginalOnly] = useState(false);
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
    if (!originalOnly && !sourcePath.trim()) {
      setError("请填写原文路径，创建后会立即导入原文。");
      return;
    }
    await onSubmit({ task_id: taskId.trim(), source_path: originalOnly ? "" : sourcePath.trim() });
    setTaskId("");
    setSourcePath("");
    setOriginalOnly(false);
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
            <input
              value={sourcePath}
              disabled={originalOnly}
              onChange={(event) => setSourcePath(event.target.value)}
              placeholder="/path/to/book.txt"
            />
          </label>
          <label className="checkbox-row">
            <input checked={originalOnly} type="checkbox" onChange={(event) => setOriginalOnly(event.target.checked)} />
            原创写作任务（无原文）
          </label>
          <p className="form-hint">{originalOnly ? "创建后可在 Writer 中选择借鉴任务并输入原创大纲。" : "创建后会立即开始导入原文，左侧进度会自动刷新。"}</p>
          {error ? <p className="form-error">{error}</p> : null}
          <div className="dialog-actions">
            <button type="button" className="secondary-button" onClick={onClose}>
              取消
            </button>
            <button type="submit" className="primary-button" disabled={pending}>
              {originalOnly ? "创建任务" : "创建并导入"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
