import { X } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";

interface WriterIntentWizardProps {
  open: boolean;
  mode?: "continuation" | "original_creation";
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

export function WriterIntentWizard({
  open,
  mode = "continuation",
  initialGoal = "",
  pending = false,
  onClose,
  onSubmit
}: WriterIntentWizardProps) {
  const [userPrompt, setUserPrompt] = useState(initialGoal);
  const [referenceTaskId, setReferenceTaskId] = useState("");
  const [chapters, setChapters] = useState(mode === "original_creation" ? "5" : "3");
  const [defaultChapterChars, setDefaultChapterChars] = useState(mode === "original_creation" ? "10000" : "3000");

  useEffect(() => {
    if (open) {
      setUserPrompt(initialGoal);
      setReferenceTaskId("");
      setChapters(mode === "original_creation" ? "5" : "3");
      setDefaultChapterChars(mode === "original_creation" ? "10000" : "3000");
    }
  }, [initialGoal, mode, open]);

  if (!open) {
    return null;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const targetChapterCount = positiveNumber(chapters, 1);
    const chapterTargetChars = optionalPositiveNumber(defaultChapterChars);
    const targetTotalChars = chapterTargetChars ? targetChapterCount * chapterTargetChars : undefined;
    const goalText = userPrompt.trim();
    const sourceTaskId = referenceTaskId.trim();
    const payload: Record<string, unknown> = {
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
    };
    if (mode === "original_creation" && sourceTaskId) {
      payload.reference_task_id = sourceTaskId;
      payload.reference_work = {
        source_task_id: sourceTaskId,
        mode: "reference_guided_original_creation",
        usage_scope: "outline_advice_and_final_prose_style_reference",
        truth_policy: "reference_advice_only",
        style_policy: "use_fragments_only_as_prose_style_reference_at_draft_stage"
      };
    }
    await onSubmit(payload);
    onClose();
  }

  const isOriginalCreation = mode === "original_creation";
  const title = isOriginalCreation ? "创建原创/仿写任务" : "创建续写任务";
  const promptLabel = isOriginalCreation ? "原创大纲" : "续写方向";
  const promptPlaceholder = isOriginalCreation ? "输入新故事的大纲、人物设定、题材和希望避免的内容。" : "输入后续剧情方向、主要人物、希望避免的内容。";
  const chapterLabel = isOriginalCreation ? "章节数" : "续写章节数";
  const submitLabel = isOriginalCreation ? "创建原创/仿写任务" : "创建续写任务";

  return (
    <div className="dialog-backdrop">
      <div role="dialog" aria-modal="true" aria-labelledby="writer-wizard-title" className="dialog-card wizard-card">
        <div className="dialog-header">
          <h2 id="writer-wizard-title">{title}</h2>
          <button className="icon-button" type="button" aria-label="关闭 Writer wizard" onClick={onClose}>
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <form className="dialog-form" onSubmit={handleSubmit}>
          <label>
            {promptLabel}
            <textarea value={userPrompt} rows={6} onChange={(event) => setUserPrompt(event.target.value)} placeholder={promptPlaceholder} />
          </label>
          {isOriginalCreation ? (
            <label>
              借鉴任务 ID
              <input
                value={referenceTaskId}
                onChange={(event) => setReferenceTaskId(event.target.value)}
                placeholder="longzu-前三部"
              />
            </label>
          ) : null}
          <div className="form-grid-two">
            <label>
              {chapterLabel}
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
              {submitLabel}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
