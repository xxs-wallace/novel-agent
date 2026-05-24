import { expect, test, type Page, type Route } from "@playwright/test";

import type {
  ArtifactTreeNode,
  ArtifactView,
  ConversationMessage,
  TaskProgress,
  TaskSummary,
  WebActionRequest,
  WebActionResult,
  WriterArtifactReview,
  WriterQuestionSet
} from "../src/api/types";

const now = "2026-05-16T00:00:00.000Z";
const taskId = "writer-loop-e2e";

test("Writer loop uses chat input plus structured actions for review gates", async ({ page }) => {
  const api = new WriterLoopApiMock();
  const pageErrors: string[] = [];
  const consoleMessages: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("console", (message) => consoleMessages.push(`${message.type()}: ${message.text()}`));
  await api.install(page);

  await page.goto("/");
  await expect(page.getByTestId("workspace-shell"), [...pageErrors, ...consoleMessages].join("\n")).toBeVisible();

  const chatInput = page.getByLabel("输入给 Agent 的自然语言");
  await chatInput.fill("进入新地点并揭露旧案线索。");
  await page.getByRole("button", { name: "开始续写", exact: true }).first().click();
  const wizard = page.getByRole("dialog", { name: "创建续写任务" });
  await expect(wizard).toBeVisible();
  await wizard.getByRole("button", { name: "创建续写任务" }).click();

  await expect(page.getByText("顾迟是否为新增人物？")).toBeVisible();
  await chatInput.fill("不是新增人物，本轮只沿用已有关系。");
  await page.getByRole("button", { name: "发送" }).click();

  expect(api.actions.some((action) => action.action === "submit_outline_research_answers")).toBe(false);
  await page.getByRole("button", { name: "提交回答并继续研究" }).click();
  await expect(page.getByRole("heading", { name: "全书续写规划" })).toBeVisible();

  await chatInput.fill("通过，但第三章结尾不要解释幕后人。");
  await page.getByRole("button", { name: "通过并继续" }).last().click();
  await expect.poll(() => api.messagePosts.at(-1)?.payload?.channel).toBe("writer_artifact_supplement");
  await expect(page.getByText("通过补充：通过，但第三章结尾不要解释幕后人。")).toBeVisible();

  await expect(page.getByRole("heading", { name: "章节标题与梗概" })).toBeVisible();

  const submit = api.actions.find((action) => action.action === "submit_outline_research_answers");
  expect(submit?.payload).toMatchObject({
    question_set_id: "outline-question-set",
    answer_text: "不是新增人物，本轮只沿用已有关系。"
  });

  const approval = api.actions.find((action) => action.action === "approve_writer_artifact");
  expect(approval?.payload).toMatchObject({
    review_id: "book-plan-review",
    artifact_kind: "book_plan",
    supplement_text: "通过，但第三章结尾不要解释幕后人。"
  });
});

class WriterLoopApiMock {
  readonly actions: WebActionRequest[] = [];
  readonly messagePosts: Array<{ content: string; payload: Record<string, unknown> }> = [];
  private messages: ConversationMessage[] = [
    assistantMessage("assistant-start", "Writer 可以开始续写。", {})
  ];
  private tasks: TaskSummary[] = [
    {
      task_id: taskId,
      source_path: "/tmp/writer-loop-e2e.txt",
      documents_count: 3,
      chapters_count: 2,
      read_completed: 3,
      close_read_completed: 3,
      total_documents: 3,
      close_read_done: true,
      active: true,
      progress: progress("可开始续写")
    }
  ];

  async install(page: Page) {
    await page.route(/\/api\/(?:tasks|artifacts|jobs)(?:\/|\?|$)/, async (route) => this.handle(route));
  }

  private async handle(route: Route) {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    const path = url.pathname;

    if (method === "GET" && path === "/api/tasks") {
      return this.json(route, this.tasks);
    }
    if (method === "GET" && path === `/api/tasks/${taskId}/messages`) {
      return this.json(route, this.messages);
    }
    if (method === "POST" && path === `/api/tasks/${taskId}/messages`) {
      const body = JSON.parse(request.postData() || "{}") as { content?: string; payload?: Record<string, unknown> };
      this.messagePosts.push({ content: String(body.content ?? ""), payload: body.payload ?? {} });
      const message = assistantMessage(`user-${this.messages.length}`, String(body.content ?? ""), body.payload ?? {}, "user");
      this.messages.push(message);
      return this.json(route, message);
    }
    if (method === "POST" && path === `/api/tasks/${taskId}/actions`) {
      const body = JSON.parse(request.postData() || "{}") as WebActionRequest;
      this.actions.push(body);
      this.applyAction(body);
      return this.json(route, actionResult(body));
    }
    if (method === "GET" && path === `/api/tasks/${taskId}/artifact-tree`) {
      return this.json(route, writerTree());
    }
    if (method === "GET" && path.startsWith("/api/artifacts/")) {
      return this.json(route, artifactView(path.split("/").pop() ?? ""));
    }
    if (method === "GET" && path.startsWith("/api/jobs/")) {
      return this.json(route, []);
    }
    return this.json(route, {});
  }

  private applyAction(body: WebActionRequest) {
    if (body.action === "start_writer") {
      this.messages.push(writerQuestionMessage());
    }
    if (body.action === "submit_outline_research_answers") {
      this.messages.push(writerArtifactReviewMessage("book-plan-review", "book_plan", "全书续写规划"));
    }
    if (body.action === "approve_writer_artifact" && body.payload?.review_id === "book-plan-review") {
      this.messages.push(writerArtifactReviewMessage("chapter-review", "chapter_package", "章节标题与梗概"));
    }
  }

  private json(route: Route, body: unknown) {
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body)
    });
  }
}

function progress(step: string): TaskProgress {
  return {
    task_id: taskId,
    flow: "Writer",
    step,
    next_action: "",
    message: step,
    read_progress: { completed: 3, total: 3 },
    close_read_progress: { completed: 3, total: 3 },
    modeling_ready: { characters: true, outline: true },
    counts: { chapters: 2 },
    technical_available: true
  };
}

function actionResult(request: WebActionRequest): WebActionResult {
  return {
    action: request.action,
    task_id: taskId,
    status: "ok",
    message: `${request.action} accepted`,
    payload: {},
    progress: progress("进行中"),
    job: null,
    decision_cards: [],
    technical_details: {}
  };
}

function assistantMessage(
  messageId: string,
  content: string,
  payload: Record<string, unknown>,
  role: "assistant" | "user" = "assistant"
): ConversationMessage {
  return {
    message_id: messageId,
    task_id: taskId,
    role,
    content,
    payload,
    decision_cards: [],
    created_at: now
  };
}

function writerQuestionMessage(): ConversationMessage {
  const questionSet: WriterQuestionSet = {
    schema_version: "1.0",
    question_set_id: "outline-question-set",
    run_id: "run-writer-loop",
    stage: "outline_research_user_input",
    status: "pending",
    questions: [
      {
        question_id: "q1",
        prompt: "顾迟是否为新增人物？",
        required: true,
        hint: "这会影响人物关系和章节梗概。",
        gap_id: "gap-1",
        risk_level: "high"
      }
    ],
    source_artifact_id: "writer-outline-research",
    artifact_path: "/tmp/outline_research_question_set.json",
    actions: {},
    submit_action: "submit_outline_research_answers",
    defer_action: "defer_outline_research_answers",
    technical_available: true
  };
  return {
    ...assistantMessage("assistant-question", "大纲研究需要补充信息。", {
      channel: "writer_question_set",
      run_id: questionSet.run_id,
      question_set_id: questionSet.question_set_id
    }),
    writer_question_set: questionSet
  };
}

function writerArtifactReviewMessage(reviewId: string, artifactKind: string, title: string): ConversationMessage {
  const review: WriterArtifactReview = {
    schema_version: "1.0",
    run_id: "run-writer-loop",
    review_id: reviewId,
    artifact_kind: artifactKind,
    artifact_id: `artifact-${reviewId}`,
    title,
    summary: `${title}已经生成，请审阅后决定下一步。`,
    next_prompt: "通过时可补充要求；不通过时请说明调整方向。",
    detail_artifact_id: `artifact-${reviewId}`,
    actions: [
      reviewAction("approve_writer_artifact", "通过并继续", reviewId, artifactKind, "primary"),
      reviewAction("request_writer_artifact_revision", "不通过并调整", reviewId, artifactKind, "secondary", true),
      reviewAction("defer_writer_artifact_review", "稍后继续", reviewId, artifactKind)
    ],
    technical_available: true,
    technical_details: {}
  };
  return {
    ...assistantMessage(`assistant-${reviewId}`, `请审阅${title}。`, {
      channel: "writer_artifact_review",
      run_id: review.run_id,
      review_id: review.review_id
    }),
    writer_artifact_review: review
  };
}

function reviewAction(
  action: string,
  label: string,
  reviewId: string,
  artifactKind: string,
  variant: "primary" | "secondary" | "danger" = "secondary",
  requiresInput = false
) {
  return {
    action,
    label,
    payload: {
      run_id: "run-writer-loop",
      review_id: reviewId,
      artifact_kind: artifactKind
    },
    description: "",
    variant,
    requires_input: requiresInput,
    input_role: requiresInput ? "artifact_revision_feedback" : ""
  };
}

function writerTree(): ArtifactTreeNode[] {
  return [
    node("writer-intent", "用户原始输入", "writer_artifact"),
    node("writer-book-plan", "生成出来的大纲", "writer_artifact"),
    node("writer-chapter", "接下来要写的梗概", "writer_artifact"),
    node("writer-draft", "草稿正文", "draft")
  ];
}

function node(id: string, label: string, kind: string): ArtifactTreeNode {
  return {
    id,
    label,
    kind,
    surface: "writer",
    badge: "",
    children: [],
    has_lazy_children: false
  };
}

function artifactView(artifactId: string): ArtifactView {
  return {
    artifact_id: artifactId,
    title: "Writer Artifact",
    kind: "writer_artifact",
    sections: [{ title: "摘要", body: "已生成。" }],
    cards: [],
    tables: [],
    markdown: "",
    technical_available: true
  };
}
