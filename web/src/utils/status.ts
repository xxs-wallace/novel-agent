import type { TaskProgress, TaskSummary } from "../api/types";

const INTERNAL_STAGE_LABELS: Record<string, string> = {
  freeze_a_review: "等待你审阅规划",
  freeze_b_review: "等待你审阅本批大纲",
  freeze_c_review: "等待你审阅章节安排",
  freeze_d_review: "等待你审阅正文草稿",
  wait_length_review: "等待你确认章节长度",
  wait_chapter_acceptance: "等待你验收本章",
  wait_chapter_review: "等待你审阅章节",
  writeback_review: "等待你确认写回记忆",
  batch_review: "等待你审阅本批剧情"
};

const INTERNAL_PATTERNS = [/freeze_[a-z]_review/i, /wait_[a-z_]+/i, /batch_review/i, /checkpoint/i, /artifact saved/i];

export function toPublicStatusText(value: string | undefined | null, fallback = "待开始"): string {
  const normalized = String(value ?? "").trim();
  if (!normalized) {
    return fallback;
  }
  const direct = INTERNAL_STAGE_LABELS[normalized];
  if (direct) {
    return direct;
  }
  if (INTERNAL_PATTERNS.some((pattern) => pattern.test(normalized))) {
    return "等待你处理下一步";
  }
  return normalized;
}

export function percent(completed: number | undefined, total: number | undefined): number {
  if (!total || total <= 0) {
    return 0;
  }
  return Math.max(0, Math.min(100, Math.round(((completed ?? 0) / total) * 100)));
}

export function kbStatus(progress: TaskProgress | null | undefined): string {
  const ready = progress?.modeling_ready ?? {};
  const values = Object.values(ready);
  if (!values.length) {
    return "未生成";
  }
  if (values.every(Boolean)) {
    return "已就绪";
  }
  return `待补齐 ${values.filter((value) => !value).length} 项`;
}

export function writerStatus(task: TaskSummary): string {
  return toPublicStatusText(task.progress?.step, task.close_read_done ? "可开始续写" : "未开始");
}

export function blockingBadge(progress: TaskProgress | null | undefined): string {
  const nextAction = toPublicStatusText(progress?.next_action, "");
  if (nextAction) {
    return nextAction;
  }
  const step = toPublicStatusText(progress?.step, "");
  return step.includes("等待你") ? step : "";
}
