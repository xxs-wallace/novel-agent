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

function splitItems(value: string): string[] {
  return value
    .replace(/，/g, ",")
    .replace(/；/g, ";")
    .replace(/\n/g, ";")
    .split(/[;,]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function firstPositiveInteger(value: string): number | undefined {
  const match = value.match(/\d+/);
  if (!match) {
    return undefined;
  }
  const parsed = Number(match[0]);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
}

export function WriterIntentWizard({ open, initialGoal = "", pending = false, onClose, onSubmit }: WriterIntentWizardProps) {
  const [goal, setGoal] = useState(initialGoal);
  const [chapters, setChapters] = useState("3");
  const [targetTotalChars, setTargetTotalChars] = useState("9000");
  const [defaultChapterChars, setDefaultChapterChars] = useState("3000");
  const [pacingPreference, setPacingPreference] = useState("延续原作节奏");
  const [lengthDistributionNotes, setLengthDistributionNotes] = useState("");
  const [conflictClimax, setConflictClimax] = useState("");
  const [emotionalClimax, setEmotionalClimax] = useState("");
  const [climaxChapterPosition, setClimaxChapterPosition] = useState("");
  const [setupRequirements, setSetupRequirements] = useState("");
  const [forbiddenEarlyResolution, setForbiddenEarlyResolution] = useState("");
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
    const targetChapterCount = positiveNumber(chapters, 1);
    const goalText = goal.trim();
    const climaxPosition = climaxChapterPosition.trim();
    await onSubmit({
      continuation_goal: goalText,
      desired_actions: goalText ? [goalText] : [],
      target_chapters: targetChapterCount,
      target_chapter_count: targetChapterCount,
      target_total_chars: optionalPositiveNumber(targetTotalChars),
      default_chapter_target_chars: optionalPositiveNumber(defaultChapterChars),
      pacing_preference: pacingPreference,
      length_distribution_notes: lengthDistributionNotes.trim(),
      climax_plan: {
        conflict_climax: conflictClimax.trim(),
        emotional_climax: emotionalClimax.trim(),
        target_chapter_index: firstPositiveInteger(climaxPosition),
        target_chapter_position: climaxPosition,
        must_foreshadow: splitItems(setupRequirements),
        must_not_resolve_before: splitItems(forbiddenEarlyResolution)
      },
      story_scale: {
        target_chapter_count: targetChapterCount,
        target_total_chars: optionalPositiveNumber(targetTotalChars),
        default_chapter_target_chars: optionalPositiveNumber(defaultChapterChars),
        pacing_profile: pacingPreference,
        length_distribution_notes: lengthDistributionNotes.trim()
      },
      pacing_spec: {
        preference: pacingPreference,
        length_distribution_notes: lengthDistributionNotes.trim()
      },
      notes: constraints.trim(),
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
              目标章节数
              <input value={chapters} inputMode="numeric" onChange={(event) => setChapters(event.target.value)} />
            </label>
            <label>
              目标总字数
              <input value={targetTotalChars} inputMode="numeric" onChange={(event) => setTargetTotalChars(event.target.value)} />
            </label>
            <label>
              默认单章字数
              <input value={defaultChapterChars} inputMode="numeric" onChange={(event) => setDefaultChapterChars(event.target.value)} />
            </label>
            <label>
              节奏偏好
              <select value={pacingPreference} onChange={(event) => setPacingPreference(event.target.value)}>
                <option>延续原作节奏</option>
                <option>更紧张</option>
                <option>更慢热</option>
                <option>更抒情</option>
                <option>更轻快</option>
              </select>
            </label>
          </div>
          <label>
            长度分布说明
            <textarea
              value={lengthDistributionNotes}
              onChange={(event) => setLengthDistributionNotes(event.target.value)}
              rows={2}
              placeholder="例如：前两章铺垫略短，高潮章可以更长"
            />
          </label>
          <div className="form-grid-two">
            <label>
              冲突高潮
              <textarea value={conflictClimax} onChange={(event) => setConflictClimax(event.target.value)} rows={3} />
            </label>
            <label>
              情感高潮
              <textarea value={emotionalClimax} onChange={(event) => setEmotionalClimax(event.target.value)} rows={3} />
            </label>
          </div>
          <label>
            目标章节位置
            <input
              value={climaxChapterPosition}
              onChange={(event) => setClimaxChapterPosition(event.target.value)}
              placeholder="例如：接近第 3 章结尾，或最后一章中段"
            />
          </label>
          <label>
            必须铺垫
            <textarea value={setupRequirements} onChange={(event) => setSetupRequirements(event.target.value)} rows={3} />
          </label>
          <label>
            禁止提前解决
            <textarea value={forbiddenEarlyResolution} onChange={(event) => setForbiddenEarlyResolution(event.target.value)} rows={3} />
          </label>
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
