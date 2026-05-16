import { MoreHorizontal, Trash2 } from "lucide-react";
import { useState } from "react";

interface TaskActionMenuProps {
  taskId: string;
  disabled?: boolean;
  onAction: (action: string, payload?: Record<string, unknown>) => void;
  onStartWriter: () => void;
  onResetCloseRead: () => void;
  onDeletePreview: () => void;
}

export function TaskActionMenu({
  taskId,
  disabled = false,
  onAction,
  onStartWriter,
  onResetCloseRead,
  onDeletePreview
}: TaskActionMenuProps) {
  const [open, setOpen] = useState(false);

  function run(callback: () => void) {
    callback();
    setOpen(false);
  }

  return (
    <div className="menu-root" onClick={(event) => event.stopPropagation()}>
      <button
        className="icon-button"
        type="button"
        aria-label={`打开 ${taskId} 操作菜单`}
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
      >
        <MoreHorizontal size={18} aria-hidden="true" />
      </button>
      {open ? (
        <div className="action-menu" role="menu">
          <button type="button" role="menuitem" onClick={() => run(() => onAction("start_read", { requested_from: "task_menu" }))}>
            导入原文
          </button>
          <button type="button" role="menuitem" onClick={() => run(() => onAction("start_close_read", { requested_from: "task_menu" }))}>
            开始阅读
          </button>
          <button type="button" role="menuitem" onClick={() => run(() => onAction("build_creative_kb", { requested_from: "task_menu" }))}>
            构建 Creative KB
          </button>
          <button type="button" role="menuitem" onClick={() => run(onStartWriter)}>
            开始续写
          </button>
          <button type="button" role="menuitem" onClick={() => run(onResetCloseRead)}>
            重置阅读
          </button>
          <button type="button" role="menuitem" className="danger-menu-item" onClick={() => run(onDeletePreview)}>
            <Trash2 size={15} aria-hidden="true" />
            删除任务
          </button>
        </div>
      ) : null}
    </div>
  );
}
