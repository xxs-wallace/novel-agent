import { delay, http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import type {
  ArtifactSurface,
  ArtifactTreeNode,
  ArtifactView,
  ConversationMessage,
  JobSummary,
  JobEventView,
  TaskSummary,
  WebActionRequest,
  WebActionResult,
  WriterArtifactReview,
  WriterDraftReview,
  WriterQuestionSet
} from "../api/types";

const now = "2026-05-12T00:00:00.000Z";

export const calls: {
  createTask: unknown[];
  actions: Array<{ taskId: string; body: WebActionRequest }>;
  artifactViews: string[];
  messages: Array<{ taskId: string; body: unknown }>;
  commands: Array<{ taskId: string; body: unknown }>;
  deleteWriterRuns: Array<{ taskId: string; confirm: boolean }>;
} = {
  createTask: [],
  actions: [],
  artifactViews: [],
  messages: [],
  commands: [],
  deleteWriterRuns: []
};

let tasks: TaskSummary[] = [];
let messagesByTask: Record<string, ConversationMessage[]> = {};
let messageListCounts: Record<string, number> = {};
let deferredMessagesByTask: Record<string, ConversationMessage> = {};
let deferredMessageJobIds: Record<string, string> = {};
let deferredMessagesReady: Record<string, boolean> = {};
let messageResponseDelayMs = 0;

function progress(step = "freeze_d_review") {
  return {
    task_id: "task-alpha",
    flow: "Writer",
    step,
    next_action: "wait_chapter_acceptance",
    message: "freeze_d_review",
    read_progress: { completed: 2, total: 4 },
    close_read_progress: { completed: 1, total: 4 },
    modeling_ready: { characters: true, world: false, outline: true, "桥段 KB": true },
    counts: { chapters: 2, documents: 4, fragment_cards: 3, fragment_card_docs: 3, fragment_clusters: 2 },
    technical_available: true
  };
}

function makeTask(taskId: string, active = false): TaskSummary {
  return {
    task_id: taskId,
    source_path: `/books/${taskId}.txt`,
    documents_count: 4,
    chapters_count: 2,
    read_completed: taskId === "task-alpha" ? 2 : 0,
    close_read_completed: taskId === "task-alpha" ? 1 : 0,
    total_documents: 4,
    close_read_done: false,
    active,
    progress: { ...progress(taskId === "task-alpha" ? "freeze_d_review" : "source selected"), task_id: taskId }
  };
}

export function resetMockState() {
  calls.createTask = [];
  calls.actions = [];
  calls.artifactViews = [];
  calls.messages = [];
  calls.commands = [];
  calls.deleteWriterRuns = [];
  messageListCounts = {};
  deferredMessagesByTask = {};
  deferredMessageJobIds = {};
  deferredMessagesReady = {};
  messageResponseDelayMs = 0;
  tasks = [makeTask("task-alpha", true), makeTask("task-beta")];
  messagesByTask = {
    "task-alpha": [
      {
        message_id: "assistant-decision",
        task_id: "task-alpha",
        role: "assistant",
        content: "请审阅本批剧情大纲。",
        payload: {},
        decision_cards: [
          {
            card_id: "writer-review-card",
            title: "本批剧情大纲",
            body: "选择下一步继续 Writer 流程。",
            actions: [
              { action: "confirm_current_step", label: "接受并继续", variant: "primary" },
              { action: "go_back", label: "返回上一层" },
              { action: "resume", label: "稍后继续" },
              { action: "accept_chapter", label: "接受本章" },
              { action: "rewrite_chapter", label: "基于反馈重写", requires_input: true },
              { action: "replan_chapter", label: "修改章节梗概后重写", requires_input: true },
              { action: "discard_chapter", label: "作废本次草稿", variant: "danger" },
              { action: "approve_writeback", label: "确认写回续写记忆" }
            ]
          }
        ],
        created_at: now
      }
    ],
    "task-beta": []
  };
}

export function setMessageResponseDelay(ms: number) {
  messageResponseDelayMs = Math.max(0, ms);
}

export function setWriterArtifactReviewAfterJobReplay(taskId = "task-alpha", jobId = "job-existing-start_writer") {
  const review: WriterArtifactReview = {
    schema_version: "1.0",
    run_id: "run-2",
    review_id: "artifact-review-run-2-freeze-a",
    artifact_kind: "book_continuation_plan",
    artifact_id: "writer-book-plan",
    title: "全书续写规划",
    summary: "续写规划已经生成，等待审阅。",
    next_prompt: "通过后继续生成本批剧情大纲。",
    detail_artifact_id: "writer-book-plan",
    actions: [
      {
        action: "run_reviewer",
        label: "Reviewer：大纲合理性",
        payload: {
          run_id: "run-2",
          review_id: "artifact-review-run-2-freeze-a",
          artifact_kind: "book_continuation_plan",
          artifact_id: "writer-book-plan",
          reviewer_id: "outline_plot_development",
          reviewer_ids: ["outline_plot_development"],
          target_type: "outline"
        },
        description: "",
        variant: "secondary",
        requires_input: false,
        input_role: ""
      },
      {
        action: "approve_writer_artifact",
        label: "通过并继续",
        payload: { run_id: "run-2", review_id: "artifact-review-run-2-freeze-a", artifact_kind: "book_continuation_plan" },
        description: "",
        variant: "primary",
        requires_input: false,
        input_role: "artifact_supplement"
      }
    ],
    technical_available: true,
    technical_details: {}
  };
  deferredMessagesByTask[taskId] = {
    message_id: "assistant-artifact-review-after-job",
    task_id: taskId,
    role: "assistant",
    content: "请审阅全书续写规划。",
    payload: { channel: "writer_artifact_review", run_id: review.run_id, review_id: review.review_id },
    writer_artifact_review: review,
    decision_cards: [],
    created_at: now
  };
  deferredMessageJobIds[jobId] = taskId;
}

export function setTaskActiveJob(taskId: string, jobId = "job-existing-start_close_read") {
  const job: JobSummary = {
    job_id: jobId,
    task_id: taskId,
    type: "close_read",
    status: "running",
    message: "后台任务正在运行",
    cancel_requested: false,
    created_at: now,
    updated_at: now,
    events_url: `/api/jobs/${jobId}/events`
  };
  tasks = tasks.map((task) => (task.task_id === taskId ? { ...task, active_job: job } : task));
}

export function setWriterQuestionMessage(taskId = "task-alpha") {
  const questionSet: WriterQuestionSet = {
    schema_version: "1.0",
    question_set_id: "outline-research-run-1-needs-answer",
    run_id: "run-1",
    stage: "outline_research_user_input",
    status: "pending",
    source_artifact_id: "writer:run-1:sufficiency-decision",
    artifact_path: "/tmp/outline_research_question_set.json",
    questions: [
      {
        question_id: "q1",
        prompt: "顾迟是否为新增人物？",
        required: true,
        hint: "这会影响人物补充和章节规划。",
        gap_id: "gap-001",
        risk_level: "high"
      }
    ],
    actions: { submit: "continue_after_outline_research_input", defer: "defer_outline_research_answers" },
    submit_action: "submit_outline_research_answers",
    defer_action: "defer_outline_research_answers",
    technical_available: true
  };
  messagesByTask[taskId] = [
    ...(messagesByTask[taskId] ?? []),
    {
      message_id: "assistant-question",
      task_id: taskId,
      role: "assistant",
      content: "大纲研究需要你补充几个关键问题。",
      payload: { channel: "writer_question_set", question_set_id: questionSet.question_set_id, run_id: questionSet.run_id },
      writer_question_set: questionSet,
      decision_cards: [],
      created_at: now
    }
  ];
}

export function setWriterArtifactReviewMessage(taskId = "task-alpha") {
  const review: WriterArtifactReview = {
    schema_version: "1.0",
    run_id: "run-1",
    review_id: "artifact-review-run-1-batch",
    artifact_kind: "batch_plan",
    artifact_id: "writer-batch-plan",
    title: "本批剧情大纲",
    summary: "本批会把旧案线索推到新地点。",
    next_prompt: "通过时可以补充风格、字数或禁止项；不通过时请说明调整方向。",
    detail_artifact_id: "writer-batch-plan",
    actions: [
      {
        action: "run_reviewer",
        label: "Reviewer：大纲合理性",
        payload: {
          run_id: "run-1",
          review_id: "artifact-review-run-1-batch",
          artifact_kind: "batch_plan",
          artifact_id: "writer-batch-plan",
          reviewer_id: "outline_plot_development",
          reviewer_ids: ["outline_plot_development"],
          target_type: "outline"
        },
        description: "",
        variant: "secondary",
        requires_input: false,
        input_role: ""
      },
      {
        action: "approve_writer_artifact",
        label: "通过并继续",
        payload: { run_id: "run-1", review_id: "artifact-review-run-1-batch", artifact_kind: "batch_plan" },
        description: "",
        variant: "primary",
        requires_input: false,
        input_role: "artifact_supplement"
      },
      {
        action: "request_writer_artifact_revision",
        label: "不通过并调整",
        payload: { run_id: "run-1", review_id: "artifact-review-run-1-batch", artifact_kind: "batch_plan" },
        description: "",
        variant: "secondary",
        requires_input: true,
        input_role: "artifact_revision_feedback"
      },
      {
        action: "defer_writer_artifact_review",
        label: "稍后继续",
        payload: { run_id: "run-1", review_id: "artifact-review-run-1-batch", artifact_kind: "batch_plan" },
        description: "",
        variant: "secondary",
        requires_input: false,
        input_role: ""
      }
    ],
    technical_available: true,
    technical_details: {}
  };
  messagesByTask[taskId] = [
    ...(messagesByTask[taskId] ?? []),
    {
      message_id: "assistant-artifact-review",
      task_id: taskId,
      role: "assistant",
      content: "请审阅本批剧情大纲。",
      payload: { channel: "writer_artifact_review", run_id: review.run_id, review_id: review.review_id },
      writer_artifact_review: review,
      decision_cards: [],
      created_at: now
    }
  ];
}

export function setWriterDraftReviewMessage(taskId = "task-alpha") {
  const review: WriterDraftReview = {
    schema_version: "1.0",
    run_id: "run-1",
    review_id: "draft-review-run-1-ch-1-draft-1",
    chapter_id: "ch-1",
    draft_id: "draft-1",
    title: "章节草稿决策",
    preview: "雨落下来，巷口的灯忽明忽暗。",
    word_count: 3200,
    target_word_count: 3000,
    continuity_summary: "人物动机保持一致。",
    detail_artifact_id: "writer-draft",
    actions: [
      {
        action: "run_reviewer",
        label: "Reviewer：局部连续性",
        payload: {
          run_id: "run-1",
          review_id: "draft-review-run-1-ch-1-draft-1",
          chapter_id: "ch-1",
          draft_id: "draft-1",
          artifact_id: "writer-draft",
          reviewer_id: "local_draft_continuity",
          reviewer_ids: ["local_draft_continuity"],
          target_type: "draft"
        },
        description: "",
        variant: "secondary",
        requires_input: false,
        input_role: ""
      },
      {
        action: "run_reviewer",
        label: "Reviewer：历史一致性",
        payload: {
          run_id: "run-1",
          review_id: "draft-review-run-1-ch-1-draft-1",
          chapter_id: "ch-1",
          draft_id: "draft-1",
          artifact_id: "writer-draft",
          reviewer_id: "memory_draft_consistency",
          reviewer_ids: ["memory_draft_consistency"],
          target_type: "draft"
        },
        description: "",
        variant: "secondary",
        requires_input: false,
        input_role: ""
      },
      {
        action: "run_reviewer",
        label: "Reviewer：文风氛围",
        payload: {
          run_id: "run-1",
          review_id: "draft-review-run-1-ch-1-draft-1",
          chapter_id: "ch-1",
          draft_id: "draft-1",
          artifact_id: "writer-draft",
          reviewer_id: "kb_draft_style_atmosphere",
          reviewer_ids: ["kb_draft_style_atmosphere"],
          target_type: "draft"
        },
        description: "",
        variant: "secondary",
        requires_input: false,
        input_role: ""
      }
    ],
    technical_available: true,
    technical_details: {}
  };
  messagesByTask[taskId] = [
    ...(messagesByTask[taskId] ?? []),
    {
      message_id: "assistant-draft-review",
      task_id: taskId,
      role: "assistant",
      content: "请决定当前章节草稿。",
      payload: { channel: "writer_draft_review", run_id: review.run_id, review_id: review.review_id },
      writer_draft_review: review,
      decision_cards: [],
      created_at: now
    }
  ];
}

const closeReadTree: ArtifactTreeNode[] = [
  node("overview", "总览", "overview", "close-read"),
  {
    ...node("people", "人物百科", "person", "close-read"),
    children: [
      {
        ...node("people-main", "主角", "person", "close-read"),
        children: [
          {
            ...node("person-shen-qing", "沈青", "person", "close-read"),
            children: [
              node("person-shen-qing-basic", "基本信息", "person_section", "close-read"),
              node("person-shen-qing-relationships", "关系网络", "person_section", "close-read")
            ]
          }
        ]
      }
    ]
  },
  node("world", "世界观", "world_item", "close-read"),
  node("outline", "故事大纲", "outline", "close-read")
];

const writerTree: ArtifactTreeNode[] = [
  {
    ...node("writer-run-history-1", "第一章 雨夜接应", "writer_run_group", "writer", "待决策"),
    children: [
      node("writer-run", "续写概览", "writer_run", "writer", "已生成"),
      node("writer-research", "大纲研究", "writer_stage", "writer", "已生成"),
      node("writer-questions", "问题集", "writer_artifact", "writer"),
      node("writer-notebook", "大纲研究笔记", "writer_artifact", "writer"),
      node("writer-trace", "检索轨迹", "writer_artifact", "writer"),
      node("writer-plan", "全书续写规划", "writer_artifact", "writer"),
      node("writer-batch-plan", "本批剧情大纲", "writer_artifact", "writer"),
      node("writer-chapter-package", "章节标题与梗概", "writer_artifact", "writer"),
      node("writer-guidance", "章节写作指导", "writer_artifact", "writer"),
      node("writer-draft", "正文草稿", "draft", "writer"),
      node("writer-generation-review", "草稿决策", "writer_artifact", "writer"),
      node("writer-writeback", "写回摘要", "writeback", "writer")
    ]
  },
  {
    ...node("writer-run-history-2", "第二章 旧码头回声", "writer_run_group", "writer", "已生成"),
    children: [node("writer-draft-2", "正文草稿", "draft", "writer")]
  }
];

function node(id: string, label: string, kind: string, surface: ArtifactSurface, badge = ""): ArtifactTreeNode {
  return {
    id,
    label,
    kind,
    surface,
    badge,
    children: [],
    has_lazy_children: false
  };
}

function artifactView(artifactId: string): ArtifactView {
  if (artifactId.startsWith("person-shen-qing")) {
    return {
      artifact_id: artifactId,
      title: "沈青",
      kind: "person_encyclopedia",
      sections: [
        { title: "基本信息", body: "身份：旧案相关的调查者。" },
        { title: "当前目标", body: "确认顾迟是否可信。" },
        { title: "关系网络", body: "顾迟：有限合作，信任未建立。" },
        { title: "性格与说话方式", body: "克制、短句、很少直接表露恐惧。" },
        { title: "已知秘密", body: "隐瞒了旧案线索来源。" },
        { title: "禁止误写点", body: "不要突然告白。" },
        { title: "最近变化", body: "第 12 章开始主动调查。" }
      ],
      actions: [],
      cards: [],
      tables: [],
      markdown: "",
      technical_available: true
    };
  }
  if (artifactId.startsWith("writer")) {
    return {
      artifact_id: artifactId,
      title: "正文草稿",
      kind: "writer_draft",
      sections: [
        { title: "字数", body: "3200" },
        { title: "连续性检查", body: "人物动机保持一致。" }
      ],
      actions: [
        {
          action: "run_reviewer",
          label: "Reviewer：局部连续性",
          payload: {
            artifact_id: artifactId,
            reviewer_id: "local_draft_continuity",
            reviewer_ids: ["local_draft_continuity"],
            target_type: "draft"
          }
        }
      ],
      cards: [],
      tables: [],
      markdown: "第一段正文。",
      technical_available: true
    };
  }
  return {
    artifact_id: artifactId,
    title: "阅读总览",
    kind: "close_read_overview",
    sections: [
      { title: "建模准备度", body: "人物=已完成；世界观=待补齐" },
      { title: "下一步", body: "查看人物百科或开始阅读。" }
    ],
    actions: [],
    cards: [],
    tables: [],
    markdown: "",
    technical_available: true
  };
}

function actionResult(taskId: string, body: WebActionRequest): WebActionResult {
  const job =
    body.action === "start_read" ||
    body.action === "start_close_read" ||
    body.action === "build_narrative_scene_index" ||
    body.action === "build_creative_kb" ||
    body.action === "start_writer" ||
    body.action === "run_reviewer"
      ? {
          job_id: `job-${body.action}`,
          task_id: taskId,
          type: body.action === "run_reviewer" ? "reviewer" : String(body.action),
          status: "queued" as const,
          message: "已加入后台队列",
          cancel_requested: false,
          created_at: now,
          updated_at: now,
          events_url: `/api/jobs/job-${body.action}/events`
        }
      : null;
  return {
    action: body.action,
    task_id: body.action === "select_task" ? String(body.payload?.task_id ?? taskId) : taskId,
    status: "ok",
    message: `${body.action} accepted`,
    payload: {},
    progress: progress(),
    job,
    decision_cards: [],
    technical_details: {}
  };
}

function jobEvents(jobId: string): JobEventView[] {
  const events: JobEventView[] = [
    {
      event_id: "000001",
      job_id: jobId,
      kind: "progress",
      message: "导入原文进度已更新",
      payload: jobId.includes("start_close_read") ? { stage: "close_reading", event: "batch_done" } : {},
      created_at: now
    }
  ];
  if (jobId.includes("start_writer")) {
    events.push({
      event_id: "000002",
      job_id: jobId,
      kind: "succeeded",
      message: "后台任务已完成",
      payload: {},
      created_at: now
    });
  }
  return events;
}

export const handlers = [
  http.get("/api/tasks", () => HttpResponse.json(tasks)),
  http.post("/api/tasks", async ({ request }) => {
    const body = (await request.json()) as { task_id: string; source_path?: string };
    calls.createTask.push(body);
    const task = {
      ...makeTask(body.task_id, true),
      source_path: body.source_path ?? ""
    };
    tasks = [task, ...tasks.map((item) => ({ ...item, active: false }))];
    messagesByTask[body.task_id] = [];
    return HttpResponse.json(task);
  }),
  http.delete("/api/tasks/:taskId", ({ params, request }) => {
    const confirm = new URL(request.url).searchParams.get("confirm") === "true";
    if (confirm) {
      tasks = tasks.filter((task) => task.task_id !== params.taskId);
    }
    return HttpResponse.json({
      task_id: params.taskId,
      would_delete: { db: true, writer_runs: false },
      deleted: confirm ? { db: true } : {}
    });
  }),
  http.delete("/api/tasks/:taskId/writer-runs/latest", ({ params, request }) => {
    const confirm = new URL(request.url).searchParams.get("confirm") === "true";
    calls.deleteWriterRuns.push({ taskId: String(params.taskId), confirm });
    return HttpResponse.json({
      task_id: params.taskId,
      confirmed: confirm,
      run_id: "run-1",
      candidate_paths: ["/tmp/runs/writer/run-1"],
      deleted_paths: confirm ? ["/tmp/runs/writer/run-1"] : [],
      errors: [],
      message: confirm ? "已删除最近一次 Writer 运行，可以重新提交续写意图。" : "将删除最近一次 Writer 运行产物，不影响阅读记忆和任务索引。"
    });
  }),
  http.post("/api/tasks/:taskId/reset-close-read", ({ params }) =>
    HttpResponse.json(actionResult(String(params.taskId), { action: "reset_close_read", payload: {} }))
  ),
  http.get("/api/tasks/:taskId/messages", ({ params }) => {
    const taskId = String(params.taskId);
    messageListCounts[taskId] = (messageListCounts[taskId] ?? 0) + 1;
    const messages = messagesByTask[taskId] ?? [];
    const deferredMessage = deferredMessagesReady[taskId] && messageListCounts[taskId] > 1 ? deferredMessagesByTask[taskId] : null;
    return HttpResponse.json(deferredMessage ? [...messages, deferredMessage] : messages);
  }),
  http.post("/api/tasks/:taskId/messages", async ({ params, request }) => {
    const body = await request.json();
    if (messageResponseDelayMs) {
      await delay(messageResponseDelayMs);
    }
    calls.messages.push({ taskId: String(params.taskId), body });
    const payload = (body as { payload?: Record<string, unknown> }).payload ?? {};
    const message: ConversationMessage = {
      message_id: `user-${calls.messages.length}`,
      task_id: String(params.taskId),
      role: "user",
      content: String((body as { content?: string }).content ?? ""),
      payload,
      decision_cards: [],
      created_at: now
    };
    messagesByTask[String(params.taskId)] = [...(messagesByTask[String(params.taskId)] ?? []), message];
    return HttpResponse.json(message);
  }),
  http.post("/api/tasks/:taskId/commands", async ({ params, request }) => {
    const body = await request.json();
    calls.commands.push({ taskId: String(params.taskId), body });
    return HttpResponse.json(actionResult(String(params.taskId), { action: "commands", payload: {} }));
  }),
  http.post("/api/tasks/:taskId/actions", async ({ params, request }) => {
    const body = (await request.json()) as WebActionRequest;
    calls.actions.push({ taskId: String(params.taskId), body });
    if (body.action === "select_task") {
      const nextTaskId = String(body.payload?.task_id ?? params.taskId);
      tasks = tasks.map((task) => ({ ...task, active: task.task_id === nextTaskId }));
    }
    return HttpResponse.json(actionResult(String(params.taskId), body));
  }),
  http.get("/api/jobs/:jobId/events/replay", ({ params }) => {
    const jobId = String(params.jobId);
    const taskId = deferredMessageJobIds[jobId];
    if (taskId) {
      deferredMessagesReady[taskId] = true;
    }
    return HttpResponse.json(jobEvents(jobId));
  }),
  http.get("/api/tasks/:taskId/artifact-tree", ({ request }) => {
    const surface = new URL(request.url).searchParams.get("surface");
    return HttpResponse.json(surface === "writer" ? writerTree : closeReadTree);
  }),
  http.get("/api/artifacts/:artifactId/view", ({ params }) => {
    calls.artifactViews.push(String(params.artifactId));
    return HttpResponse.json(artifactView(String(params.artifactId)));
  }),
  http.get("/api/artifacts/:artifactId/technical", ({ params }) =>
    HttpResponse.json({
      artifact_id: params.artifactId,
      raw_json: {
        raw_secret_stage: "freeze_d_review",
        descriptor: { internal: true }
      }
    })
  )
];

resetMockState();

export const server = setupServer(...handlers);
