import { expect, type APIRequestContext, type Page, test } from "@playwright/test";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

type TaskProgress = {
  read_progress?: { completed?: number; total?: number };
  close_read_progress?: { completed?: number; total?: number };
  modeling_ready?: Record<string, boolean>;
  counts?: Record<string, number>;
};

type WebActionResponse = {
  message?: string;
  job?: { job_id: string; status: string } | null;
};

type JobEvent = {
  kind: string;
  message: string;
  payload?: Record<string, unknown>;
};

type JobSummary = {
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  message?: string;
};

type ArtifactTreeNode = {
  id: string;
  label: string;
  kind: string;
  children: ArtifactTreeNode[];
};

type ArtifactView = {
  title: string;
  kind: string;
  sections: Array<{ title: string; body: string }>;
};

const repoRoot = path.resolve("..");
const smokeTimeoutMs = 30 * 60 * 1000;

test.setTimeout(smokeTimeoutMs);

test("real workspace flow clicks real read, close-read and Creative KB jobs", async ({ page, request }) => {
  test.skip(!hasDeepSeekApiKey(), "DEEPSEEK_API_KEY was not found after sourcing ~/.bash_profile.");
  expect(process.env.NOVEL_AGENT_WEB_JOB_MODE ?? "").not.toBe("fake");

  const taskId = `e2e-web-real-${Date.now()}`;
  const sourcePath = writeSmokeSource(taskId);

  try {
    await page.goto("/");
    await expect(page.getByTestId("workspace-shell")).toBeVisible();

    await page.getByRole("button", { name: "创建任务", exact: true }).click();
    const createDialog = page.getByRole("dialog", { name: "创建任务" });
    await expect(createDialog).toBeVisible();
    await createDialog.getByLabel("任务 ID").fill(taskId);
    await createDialog.getByLabel("原文路径").fill(sourcePath);
    await createDialog.getByRole("button", { name: "创建", exact: true }).click();

    await expect(page.getByRole("button", { name: taskId, exact: true })).toBeVisible();
    await page.getByRole("button", { name: taskId, exact: true }).click();

    const readAction = await triggerTaskAction(page, taskId, "开始粗读", "start_read");
    await expectRealModelEvent(request, readAction.job!.job_id, "粗读模型调用");
    await waitForProgress(request, taskId, (progress) => {
      const read = progress.read_progress ?? {};
      return Number(read.total ?? 0) > 0 && Number(read.completed ?? 0) >= Number(read.total ?? 0);
    });
    await waitForJobTerminal(request, readAction.job!.job_id);
    await expect(page.getByText(/后台任务已完成|粗读本轮已完成/).last()).toBeVisible();

    const closeReadAction = await triggerTaskAction(page, taskId, "运行精读", "start_close_read");
    await expectRealModelEvent(request, closeReadAction.job!.job_id, "精读模型调用");
    const closeReadStatus = await waitForProgress(request, taskId, (progress) => {
      const read = progress.read_progress ?? {};
      const close = progress.close_read_progress ?? {};
      return Number(read.total ?? 0) > 0 && Number(close.completed ?? 0) >= Number(read.total ?? 0);
    });
    await waitForJobTerminal(request, closeReadAction.job!.job_id);
    expect(closeReadStatus.counts?.chapters ?? 0).toBeGreaterThan(0);
    expect(closeReadStatus.counts?.character_profiles ?? 0).toBeGreaterThan(0);

    await page.reload();
    await expect(page.getByRole("button", { name: taskId, exact: true })).toBeVisible();
    await page.getByRole("button", { name: taskId, exact: true }).click();
    await page.getByRole("button", { name: "总览", exact: true }).click();
    await expect(page.getByText("Close-read 总览")).toBeVisible();
    await expect(page.getByText("建模准备度")).toBeVisible();
    await expect(page.getByText("raw_json")).toHaveCount(0);

    const personNode = await waitForFirstPersonNode(request, taskId);
    await page.getByRole("button", { name: personNode.label, exact: true }).first().click();
    await expect(page.getByText("人物百科").last()).toBeVisible();
    await expect(page.getByRole("heading", { name: personNode.label, exact: true })).toBeVisible();
    const personViewResponse = await request.get(`/api/artifacts/${encodeURIComponent(personNode.id)}/view`);
    expect(personViewResponse.ok()).toBe(true);
    const personView = (await personViewResponse.json()) as ArtifactView;
    expect(personView.kind).toBe("person_encyclopedia");
    expect(
      personView.sections.some((section) => section.body.trim() && section.body.trim() !== "暂无明确记录。"),
    ).toBe(true);

    const kbAction = await triggerTaskAction(page, taskId, "构建 Creative KB", "build_creative_kb");
    const kbStatus = await waitForProgress(request, taskId, (progress) => {
      return Boolean(progress.modeling_ready?.["桥段 KB"]) || Number(progress.counts?.fragment_cards ?? 0) > 0;
    });
    const kbEvents = await waitForJobEvents(
      request,
      kbAction.job!.job_id,
      (events) =>
        events.some((event) => event.payload?.phase === "fragment_card_document_done" && event.payload.used_fallback === false),
      "Creative KB 真实卡片构建",
    );
    await waitForJobTerminal(request, kbAction.job!.job_id);
    expect(kbStatus.modeling_ready?.["桥段 KB"] || Number(kbStatus.counts?.fragment_cards ?? 0) > 0).toBeTruthy();
    expect(kbEvents.length).toBeGreaterThan(0);
  } finally {
    await request.delete(`/api/tasks/${encodeURIComponent(taskId)}?confirm=true&include_runs=false`).catch(() => undefined);
  }
});

async function triggerTaskAction(
  page: Page,
  taskId: string,
  actionName: string,
  expectedAction: string,
): Promise<WebActionResponse> {
  const responsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().includes(`/api/tasks/${encodeURIComponent(taskId)}/actions`) &&
      requestBodyAction(response.request().postData()) === expectedAction,
  );
  await page.getByLabel(`打开 ${taskId} 操作菜单`).click();
  await page.getByRole("menuitem", { name: actionName }).click();
  const response = await responsePromise;
  expect(response.ok(), `${actionName} action response should be ok`).toBe(true);
  const result = (await response.json()) as WebActionResponse;
  expect(result.job?.job_id, `${actionName} should create a real background job`).toBeTruthy();
  return result;
}

function requestBodyAction(postData: string | null): string {
  if (!postData) {
    return "";
  }
  try {
    const payload = JSON.parse(postData) as { action?: unknown };
    return typeof payload.action === "string" ? payload.action : "";
  } catch {
    return "";
  }
}

async function waitForProgress(
  request: APIRequestContext,
  taskId: string,
  predicate: (progress: TaskProgress) => boolean,
): Promise<TaskProgress> {
  const deadline = Date.now() + smokeTimeoutMs - 30_000;
  let lastProgress: TaskProgress = {};
  while (Date.now() < deadline) {
    const response = await request.get(`/api/tasks/${encodeURIComponent(taskId)}/status`);
    if (response.ok()) {
      lastProgress = (await response.json()) as TaskProgress;
      if (predicate(lastProgress)) {
        return lastProgress;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 2_000));
  }
  throw new Error(`Timed out waiting for task progress: ${JSON.stringify(lastProgress)}`);
}

async function expectRealModelEvent(request: APIRequestContext, jobId: string, label: string): Promise<JobEvent[]> {
  return waitForJobEvents(
    request,
    jobId,
    (events) =>
      events.some(
        (event) =>
          event.payload?.event === "prompt_end" ||
          event.message.includes("模型调用完成") ||
          event.message.includes("正在调用模型"),
      ),
    label,
  );
}

async function waitForJobEvents(
  request: APIRequestContext,
  jobId: string,
  predicate: (events: JobEvent[]) => boolean,
  label: string,
): Promise<JobEvent[]> {
  const deadline = Date.now() + smokeTimeoutMs - 30_000;
  let lastEvents: JobEvent[] = [];
  while (Date.now() < deadline) {
    const response = await request.get(`/api/jobs/${encodeURIComponent(jobId)}/events/replay`);
    if (response.ok()) {
      lastEvents = (await response.json()) as JobEvent[];
      const errorEvent = lastEvents.find((event) => event.kind === "error");
      if (errorEvent) {
        throw new Error(`${label} failed before the expected event: ${JSON.stringify(errorEvent)}`);
      }
      if (predicate(lastEvents)) {
        return lastEvents;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 2_000));
  }
  throw new Error(`Timed out waiting for ${label}: ${JSON.stringify(lastEvents.slice(-8))}`);
}

async function waitForJobTerminal(request: APIRequestContext, jobId: string): Promise<JobSummary> {
  const deadline = Date.now() + smokeTimeoutMs - 30_000;
  let lastSummary: JobSummary = { status: "queued" };
  while (Date.now() < deadline) {
    const response = await request.get(`/api/jobs/${encodeURIComponent(jobId)}`);
    if (response.ok()) {
      lastSummary = (await response.json()) as JobSummary;
      if (lastSummary.status === "succeeded") {
        return lastSummary;
      }
      if (["failed", "cancelled"].includes(lastSummary.status)) {
        const events = await request.get(`/api/jobs/${encodeURIComponent(jobId)}/events/replay`);
        const eventPayload = events.ok() ? await events.text() : "";
        throw new Error(`Job ${jobId} ended as ${lastSummary.status}: ${lastSummary.message ?? ""}\n${eventPayload}`);
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 2_000));
  }
  throw new Error(`Timed out waiting for job ${jobId} terminal status: ${JSON.stringify(lastSummary)}`);
}

async function waitForFirstPersonNode(request: APIRequestContext, taskId: string): Promise<ArtifactTreeNode> {
  const deadline = Date.now() + smokeTimeoutMs - 30_000;
  let lastTree: ArtifactTreeNode[] = [];
  while (Date.now() < deadline) {
    const response = await request.get(`/api/tasks/${encodeURIComponent(taskId)}/artifact-tree?surface=close-read`);
    if (response.ok()) {
      lastTree = (await response.json()) as ArtifactTreeNode[];
      const personNode = flattenArtifactTree(lastTree).find(
        (node) => node.kind === "person" && node.children.some((child) => child.kind === "person_section"),
      );
      if (personNode) {
        return personNode;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 2_000));
  }
  throw new Error(`Timed out waiting for a real person encyclopedia node: ${JSON.stringify(lastTree)}`);
}

function flattenArtifactTree(nodes: ArtifactTreeNode[]): ArtifactTreeNode[] {
  return nodes.flatMap((node) => [node, ...flattenArtifactTree(node.children ?? [])]);
}

function hasDeepSeekApiKey(): boolean {
  const result = spawnSync(
    "bash",
    ["-lc", "set -a; source ~/.bash_profile >/dev/null 2>&1 || true; set +a; test -n \"${DEEPSEEK_API_KEY:-}\""],
    { cwd: repoRoot },
  );
  return result.status === 0;
}

function writeSmokeSource(taskId: string): string {
  const sourceDir = path.join(repoRoot, "runs", "e2e-web-smoke-sources");
  fs.mkdirSync(sourceDir, { recursive: true });
  const sourcePath = path.join(sourceDir, `${taskId}.txt`);
  fs.writeFileSync(
    sourcePath,
    [
      "第一章 雨夜旧案",
      "沈青在雨夜回到旧图书馆。她发现借阅卡背面有一行被水洇开的地址，顾迟提醒她不要立刻报警，因为这条线索可能会惊动藏在档案室里的内应。",
      "两人检查旧书架时，灯忽然熄灭。沈青听见楼上传来脚步声，她没有追上去，只把一枚带泥的铜扣收进证物袋。",
      "",
      "第二章 暗巷证词",
      "第二天清晨，沈青和顾迟来到铜扣指向的暗巷。卖花老人承认十年前见过同样的扣子，但要求他们先找到失踪的录音带。",
      "顾迟提出分头调查，沈青拒绝。她意识到顾迟知道得太多，却又暂时只能依靠他的情报网。",
    ].join("\n"),
    "utf-8",
  );
  return sourcePath;
}
