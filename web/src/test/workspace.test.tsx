import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { createAppQueryClient } from "../App";
import { WorkspaceShell } from "../components/layout/WorkspaceShell";
import { calls, setTaskActiveJob } from "./server";

function renderWorkspace() {
  const queryClient = createAppQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <WorkspaceShell />
    </QueryClientProvider>
  );
}

async function waitForInitialTask() {
  return screen.findByRole("button", { name: "task-alpha" });
}

describe("Novel Agent Web workspace", () => {
  it("renders the three workspace regions without exposing internal stages", async () => {
    renderWorkspace();

    expect(await screen.findByRole("region", { name: "任务列表" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "会话" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "结果浏览器" })).toBeInTheDocument();
    expect(screen.queryByText("freeze_d_review")).not.toBeInTheDocument();
    expect(screen.queryByText("wait_chapter_acceptance")).not.toBeInTheDocument();
  });

  it("opens the create task dialog, submits to createTask, and starts importing", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await waitForInitialTask();

    await user.click(await screen.findByRole("button", { name: "创建任务" }));
    const dialog = screen.getByRole("dialog", { name: "创建任务" });
    await user.type(within(dialog).getByLabelText("任务 ID"), "new-task");
    await user.type(within(dialog).getByLabelText("原文路径"), "/tmp/source.txt");
    await user.click(within(dialog).getByRole("button", { name: "创建并导入" }));

    await waitFor(() => expect(calls.createTask).toHaveLength(1));
    expect(calls.createTask[0]).toEqual({ task_id: "new-task", source_path: "/tmp/source.txt" });
    await waitFor(() => expect(calls.actions.some((call) => call.taskId === "new-task" && call.body.action === "start_read")).toBe(true));
  });

  it("asks for confirmation before switching selected task", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await waitForInitialTask();

    await user.click(await screen.findByRole("button", { name: "task-beta" }));
    expect(await screen.findByText("确定切换到任务 task-beta 吗？")).toBeInTheDocument();
    expect(calls.actions.filter((call) => call.body.action === "select_task")).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "切换" }));

    await waitFor(() => expect(calls.actions.filter((call) => call.body.action === "select_task")).toHaveLength(1));
    expect(calls.actions.find((call) => call.body.action === "select_task")?.body.payload).toEqual({ task_id: "task-beta" });
  });

  it("does not reselect the current task when clicking it again", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await waitForInitialTask();

    await user.click(await screen.findByRole("button", { name: "task-alpha" }));
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(calls.actions.filter((call) => call.body.action === "select_task")).toHaveLength(0);
  });

  it("sends task menu actions as action ids, not slash commands", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await waitForInitialTask();

    await user.click(await screen.findByLabelText("打开 task-alpha 操作菜单"));
    await user.click(screen.getByRole("menuitem", { name: "导入原文" }));

    await waitFor(() => expect(calls.actions.some((call) => call.body.action === "start_read")).toBe(true));
    const actionCall = calls.actions.find((call) => call.body.action === "start_read");
    expect(actionCall?.body.action).toBe("start_read");
    expect(actionCall?.body.action.startsWith("/")).toBe(false);
    expect(calls.commands).toHaveLength(0);
  });

  it("refreshes the visible artifact detail when close-read progress arrives", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await waitForInitialTask();
    await screen.findByText("阅读总览");
    const initialArtifactViewCalls = calls.artifactViews.length;

    await user.click(await screen.findByLabelText("打开 task-alpha 操作菜单"));
    await user.click(screen.getByRole("menuitem", { name: "开始阅读" }));

    await waitFor(() => expect(calls.artifactViews.length).toBeGreaterThan(initialArtifactViewCalls));
  });

  it("reconnects to an already running task job after loading tasks", async () => {
    setTaskActiveJob("task-alpha");
    renderWorkspace();
    await waitForInitialTask();
    await screen.findByText("阅读总览");

    await screen.findByText("导入原文进度已更新");
  });

  it("sends natural language to messages endpoint, not commands", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await waitForInitialTask();

    const input = await screen.findByLabelText("输入给 Agent 的自然语言");
    await user.type(input, "请让主角先回到旧案现场。");
    await user.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => expect(calls.messages).toHaveLength(1));
    expect(calls.commands).toHaveLength(0);
    expect(calls.messages[0].body).toMatchObject({ content: "请让主角先回到旧案现场。" });
  });

  it("opens Writer wizard from the button and submits start_writer action", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await waitForInitialTask();

    await user.click(await screen.findByRole("button", { name: "开始续写" }));
    const dialog = screen.getByRole("dialog", { name: "Writer intent wizard" });
    await user.clear(within(dialog).getByLabelText("续写目标"));
    await user.type(within(dialog).getByLabelText("续写目标"), "进入新地点并揭露线索。");
    await user.click(within(dialog).getByRole("button", { name: "提交 Writer 意图" }));

    await waitFor(() => expect(calls.actions.some((call) => call.body.action === "start_writer")).toBe(true));
    const writerCall = calls.actions.find((call) => call.body.action === "start_writer");
    expect(writerCall?.body.payload).toMatchObject({ continuation_goal: "进入新地点并揭露线索。" });
    expect(calls.commands).toHaveLength(0);
  });

  it("submits decision card buttons as action ids", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await waitForInitialTask();

    await user.click(await screen.findByRole("button", { name: "接受并继续" }));

    await waitFor(() => expect(calls.actions.some((call) => call.body.action === "confirm_current_step")).toBe(true));
    expect(calls.actions.find((call) => call.body.action === "confirm_current_step")?.body.action.startsWith("/")).toBe(false);
  });

  it("submits scoped revision feedback to the Writer revision action", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await waitForInitialTask();

    await user.type(await screen.findByPlaceholderText("局部修改反馈"), "把这一段改得克制一点。");
    await user.click(screen.getByRole("button", { name: "按反馈修改" }));

    await waitFor(() => expect(calls.actions.some((call) => call.body.action === "request_scoped_artifact_revision")).toBe(true));
    const revisionCall = calls.actions.find((call) => call.body.action === "request_scoped_artifact_revision");
    expect(revisionCall?.body.payload).toMatchObject({ feedback: "把这一段改得克制一点。" });
    expect(calls.commands).toHaveLength(0);
  });

  it("shows person encyclopedia fields when clicking a person tree node", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await waitForInitialTask();

    await user.click(await screen.findByRole("button", { name: "沈青" }));

    expect((await screen.findAllByText("人物百科")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("基本信息").length).toBeGreaterThan(0);
    expect(screen.getAllByText("当前目标").length).toBeGreaterThan(0);
    expect(screen.getAllByText("关系网络").length).toBeGreaterThan(0);
    expect(screen.getAllByText("禁止误写点").length).toBeGreaterThan(0);
  });

  it("keeps raw JSON hidden until the technical details drawer is opened", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await waitForInitialTask();

    await screen.findByText("阅读总览");
    expect(screen.queryByText("raw_secret_stage")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "技术详情" }));

    expect(await screen.findByText(/raw_secret_stage/)).toBeInTheDocument();
  });
});
