import type { TaskProgress, TaskSummary } from "../api/types";

const INTERNAL_STAGE_LABELS: Record<string, string> = {
  freeze_a_review: "等待你审阅规划",
  freeze_b_review: "等待你审阅本批大纲",
  freeze_c_review: "等待你审阅章节安排",
  freeze_d_review: "等待你审阅正文草稿",
  wait_length_review: "等待你确认章节长度",
  wait_chapter_acceptance: "等待你决定本章草稿",
  wait_chapter_review: "等待你审阅章节",
  writeback_review: "等待你确认写回记忆",
  batch_review: "等待你审阅本批剧情"
};

const INTERNAL_PATTERNS = [/freeze_[a-z]_review/i, /wait_[a-z_]+/i, /batch_review/i, /checkpoint/i, /artifact saved/i];
const PUBLIC_TERM_REPLACEMENTS: Array<[RegExp, string]> = [
  [/粗读/g, "导入原文"],
  [/精读/g, "阅读"],
  [/Close-read/g, "阅读"]
];

export function normalizePublicTerms(value: string): string {
  return PUBLIC_TERM_REPLACEMENTS.reduce((current, [pattern, replacement]) => current.replace(pattern, replacement), value);
}

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
  return normalizePublicTerms(normalized);
}

export function percent(completed: number | undefined, total: number | undefined): number {
  if (!total || total <= 0) {
    return 0;
  }
  return Math.max(0, Math.min(100, Math.round(((completed ?? 0) / total) * 100)));
}

export function kbStatus(progress: TaskProgress | null | undefined): string {
  const ready = progress?.modeling_ready ?? {};
  const explicitReady = ready["桥段 KB"] ?? ready["Creative KB"] ?? ready.creative_kb;
  if (explicitReady === true) {
    return "已就绪";
  }
  const cards = progress?.counts?.fragment_cards ?? 0;
  if (cards > 0) {
    return "已生成部分";
  }
  return "未生成";
}

export interface KbProgressSummary {
  completed: number;
  total: number;
  cards: number;
  clusters: number;
}

export function kbProgress(progress: TaskProgress | null | undefined, fallbackTotal = 0): KbProgressSummary {
  const counts = progress?.counts ?? {};
  const cards = counts.fragment_cards ?? 0;
  const completed = counts.fragment_card_docs ?? cards;
  const total = counts.documents ?? progress?.close_read_progress?.total ?? fallbackTotal;
  return {
    completed: Math.max(0, completed),
    total: Math.max(0, total),
    cards: Math.max(0, cards),
    clusters: Math.max(0, counts.fragment_clusters ?? 0)
  };
}

export function kbProgressDetail(summary: KbProgressSummary): string {
  if (!summary.total) {
    return summary.cards ? `${summary.cards} 卡` : "0/0";
  }
  const base = `${Math.min(summary.completed, summary.total)}/${summary.total}`;
  const cardText = summary.cards && summary.cards !== summary.completed ? ` · ${summary.cards} 卡` : "";
  const clusterText = summary.clusters ? ` · ${summary.clusters} 簇` : "";
  return `${base}${cardText}${clusterText}`;
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
