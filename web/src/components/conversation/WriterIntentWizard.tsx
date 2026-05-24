import { X } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

interface WriterIntentWizardProps {
  open: boolean;
  initialGoal?: string;
  pending?: boolean;
  onClose: () => void;
  onSubmit: (payload: Record<string, unknown>) => Promise<unknown> | void;
}

function positiveNumber(value: string, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function optionalPositiveNumber(value: string): number | undefined {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
}

export function WriterIntentWizard({ open, initialGoal = "", pending = false, onClose, onSubmit }: WriterIntentWizardProps) {
  const [userPrompt, setUserPrompt] = useState(initialGoal);
  const [chapters, setChapters] = useState("3");
  const [defaultChapterChars, setDefaultChapterChars] = useState("3000");

  useEffect(() => {
    if (open) {
      setUserPrompt(initialGoal);
    }
  }, [initialGoal, open]);

  if (!open) {
    return null;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const targetChapterCount = positiveNumber(chapters, 1);
    const chapterTargetChars = optionalPositiveNumber(defaultChapterChars);
    const targetTotalChars = chapterTargetChars ? targetChapterCount * chapterTargetChars : undefined;
    const goalText = userPrompt.trim();
    await onSubmit({
      continuation_goal: goalText,
      desired_actions: goalText ? [goalText] : [],
      target_chapters: targetChapterCount,
      target_chapter_count: targetChapterCount,
      target_total_chars: targetTotalChars,
      default_chapter_target_chars: chapterTargetChars,
      story_scale: {
        target_chapter_count: targetChapterCount,
        target_total_chars: targetTotalChars,
        default_chapter_target_chars: chapterTargetChars
      }
    });
    onClose();
  }

  return (
    <div className="dialog-backdrop">
      <div role="dialog" aria-modal="true" aria-labelledby="writer-wizard-title" className="dialog-card wizard-card">
        <div className="dialog-header">
          <h2 id="writer-wizard-title">创建续写任务</h2>
          <button className="icon-button" type="button" aria-label="关闭 Writer wizard" onClick={onClose}>
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <form className="dialog-form" onSubmit={handleSubmit}>
          <label>
            User prompt
            <textarea value={userPrompt} rows={6} onChange={(event) => setUserPrompt(event.target.value)} />
          </label>
          <div className="form-grid-two">
            <label>
              续写章节数
              <input value={chapters} inputMode="numeric" onChange={(event) => setChapters(event.target.value)} />
            </label>
            <label>
              每章字数
              <input value={defaultChapterChars} inputMode="numeric" onChange={(event) => setDefaultChapterChars(event.target.value)} />
            </label>
          </div>
          <div className="dialog-actions">
            <button type="button" className="secondary-button" onClick={onClose}>
              取消
            </button>
            <button type="submit" className="primary-button" disabled={pending}>
              创建续写任务
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
