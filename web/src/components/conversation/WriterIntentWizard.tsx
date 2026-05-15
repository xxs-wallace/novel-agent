import { X } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

interface WriterIntentWizardProps {
  open: boolean;
  initialGoal?: string;
  pending?: boolean;
  onClose: () => void;
  onSubmit: (payload: Record<string, unknown>) => Promise<unknown> | void;
}

export function WriterIntentWizard({ open, initialGoal = "", pending = false, onClose, onSubmit }: WriterIntentWizardProps) {
  const [goal, setGoal] = useState(initialGoal);
  const [chapters, setChapters] = useState("3");
  const [tone, setTone] = useState("延续原作语气");
  const [constraints, setConstraints] = useState("");

  useEffect(() => {
    if (open) {
      setGoal(initialGoal);
    }
  }, [initialGoal, open]);

  if (!open) {
    return null;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onSubmit({
      continuation_goal: goal.trim(),
      target_chapters: Number(chapters) || 1,
      tone,
      constraints: constraints.trim()
    });
    onClose();
  }

  return (
    <div className="dialog-backdrop">
      <div role="dialog" aria-modal="true" aria-labelledby="writer-wizard-title" className="dialog-card wizard-card">
        <div className="dialog-header">
          <h2 id="writer-wizard-title">Writer intent wizard</h2>
          <button className="icon-button" type="button" aria-label="关闭 Writer wizard" onClick={onClose}>
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <form className="dialog-form" onSubmit={handleSubmit}>
          <label>
            续写目标
            <textarea
              value={goal}
              onChange={(event) => setGoal(event.target.value)}
              rows={5}
              placeholder="例如：接续上一章悬念，让主角进入新地点并暴露一个旧案线索"
            />
          </label>
          <div className="form-grid-two">
            <label>
              章节数
              <input value={chapters} inputMode="numeric" onChange={(event) => setChapters(event.target.value)} />
            </label>
            <label>
              风格
              <select value={tone} onChange={(event) => setTone(event.target.value)}>
                <option>延续原作语气</option>
                <option>更紧张</option>
                <option>更抒情</option>
                <option>更轻快</option>
              </select>
            </label>
          </div>
          <label>
            禁止项与额外约束
            <textarea value={constraints} onChange={(event) => setConstraints(event.target.value)} rows={3} placeholder="避免误写、角色限制、字数偏好" />
          </label>
          <div className="dialog-actions">
            <button type="button" className="secondary-button" onClick={onClose}>
              取消
            </button>
            <button type="submit" className="primary-button" disabled={pending}>
              提交 Writer 意图
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
