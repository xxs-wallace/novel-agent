import { http, HttpResponse } from "msw";
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
  WebActionResult
} from "../api/types";

const now = "2026-05-12T00:00:00.000Z";

export const calls: {
  createTask: unknown[];
  actions: Array<{ taskId: string; body: WebActionRequest }>;
  artifactViews: string[];
  messages: Array<{ taskId: string; body: unknown }>;
  commands: Array<{ taskId: string; body: unknown }>;
} = {
  createTask: [],
  actions: [],
  artifactViews: [],
  messages: [],
  commands: []
};

let tasks: TaskSummary[] = [];
let messagesByTask: Record<string, ConversationMessage[]> = {};

function progress(step = "freeze_d_review") {
  return {
    task_id: "task-alpha",
    flow: "Writer",
    step,
    next_action: "wait_chapter_acceptance",
    message: "freeze_d_review",
    read_progress: { completed: 2, total: 4 },
    close_read_progress: { completed: 1, total: 4 },
    modeling_ready: { characters: true, world: false, outline: true },
    counts: { chapters: 2 },
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
              { action: "rewrite_with_length", label: "调整字数后重写", requires_input: true },
              { action: "rewrite_with_outline", label: "修改章节梗概后重写", requires_input: true },
              { action: "discard_draft", label: "作废本次草稿", variant: "danger" },
              { action: "confirm_writeback", label: "确认写回续写记忆" }
            ]
          }
        ],
        created_at: now
      }
    ],
    "task-beta": []
  };
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
  node("writer-run", "Run 总览", "writer_run", "writer", "已生成"),
  node("writer-plan", "全书续写规划", "writer_artifact", "writer"),
  node("writer-draft", "正文草稿", "draft", "writer")
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
      cards: [],
      tables: [],
      markdown: "第一段正文。",
      technical_available: true
    };
  }
  return {
    artifact_id: artifactId,
    title: "Close-read 总览",
    kind: "close_read_overview",
    sections: [
      { title: "建模准备度", body: "人物=已完成；世界观=待补齐" },
      { title: "下一步", body: "查看人物百科或运行精读。" }
    ],
    cards: [],
    tables: [],
    markdown: "",
    technical_available: true
  };
}

function actionResult(taskId: string, body: WebActionRequest): WebActionResult {
  const job =
    body.action === "start_read" || body.action === "start_close_read" || body.action === "build_creative_kb" || body.action === "start_writer"
      ? {
          job_id: `job-${body.action}`,
          task_id: taskId,
          type: String(body.action),
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
    decision_cards:
      body.action === "start_writer"
        ? [
            {
              card_id: "start-writer-review",
              title: "Writer 审阅",
              body: "Writer 已启动。",
              actions: [{ action: "confirm_current_step", label: "接受并继续", variant: "primary" }]
            }
          ]
        : [],
    technical_details: {}
  };
}

function jobEvents(jobId: string): JobEventView[] {
  return [
    {
      event_id: "000001",
      job_id: jobId,
      kind: "progress",
      message: "粗读进度已更新",
      payload: jobId.includes("start_close_read") ? { stage: "close_reading", event: "batch_done" } : {},
      created_at: now
    }
  ];
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
  http.post("/api/tasks/:taskId/reset-close-read", ({ params }) =>
    HttpResponse.json(actionResult(String(params.taskId), { action: "reset_close_read", payload: {} }))
  ),
  http.get("/api/tasks/:taskId/messages", ({ params }) => HttpResponse.json(messagesByTask[String(params.taskId)] ?? [])),
  http.post("/api/tasks/:taskId/messages", async ({ params, request }) => {
    const body = await request.json();
    calls.messages.push({ taskId: String(params.taskId), body });
    const message: ConversationMessage = {
      message_id: `user-${calls.messages.length}`,
      task_id: String(params.taskId),
      role: "user",
      content: String((body as { content?: string }).content ?? ""),
      payload: {},
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
  http.get("/api/jobs/:jobId/events/replay", ({ params }) => HttpResponse.json(jobEvents(String(params.jobId)))),
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
