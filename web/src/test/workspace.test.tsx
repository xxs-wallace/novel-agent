import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { createAppQueryClient } from "../App";
import { WorkspaceShell } from "../components/layout/WorkspaceShell";
import {
  calls,
  setMessageResponseDelay,
  setTaskActiveJob,
  setWriterArtifactReviewAfterJobReplay,
  setWriterArtifactReviewMessage,
  setWriterDraftReviewMessage,
  setWriterQuestionMessage
} from "./server";

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
    expect(screen.queryByText("我的反馈")).not.toBeInTheDocument();
  });

  it("shows Creative KB build progress in the task rail", async () => {
    renderWorkspace();
    await waitForInitialTask();

    expect(screen.getAllByText("Creative KB").length).toBeGreaterThan(0);
    expect(screen.getAllByLabelText("Creative KB进度 75%").length).toBeGreaterThan(0);
    expect(screen.getAllByText("3/4 · 2 簇").length).toBeGreaterThan(0);
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

  it("can preview and delete the latest Writer run without deleting the task", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await waitForInitialTask();

    await user.click(await screen.findByLabelText("打开 task-alpha 操作菜单"));
    await user.click(screen.getByRole("menuitem", { name: "删除最近续写" }));

    expect(await screen.findByText("删除最近续写预览")).toBeInTheDocument();
    expect(calls.deleteWriterRuns).toEqual([{ taskId: "task-alpha", confirm: false }]);

    await user.click(screen.getByRole("button", { name: "确认删除最近续写" }));

    await waitFor(() => expect(calls.deleteWriterRuns).toHaveLength(2));
    expect(calls.deleteWriterRuns[1]).toEqual({ taskId: "task-alpha", confirm: true });
    expect(await screen.findByRole("button", { name: "task-alpha" })).toBeInTheDocument();
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

  it("refreshes conversation messages when a Writer job reaches review", async () => {
    setTaskActiveJob("task-alpha", "job-existing-start_writer");
    setWriterArtifactReviewAfterJobReplay("task-alpha", "job-existing-start_writer");
    renderWorkspace();
    await waitForInitialTask();

    await screen.findByText("全书续写规划");
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

  it("switches the shared chat input into read-only analyzer mode", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await waitForInitialTask();

    await user.click(await screen.findByRole("button", { name: "小说专家意见" }));
    const input = await screen.findByLabelText("输入给 Agent 的自然语言");
    expect(input).toHaveAttribute("placeholder", "向小说专家提问，例如：当前未解之谜哪条最适合下一阶段回收？");

    await user.type(input, "当前旧案线索应该如何推进？");
    await user.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => expect(calls.messages).toHaveLength(1));
    expect(calls.messages[0].body).toMatchObject({
      content: "当前旧案线索应该如何推进？",
      payload: {
        channel: "outline_analyzer",
        question: "当前旧案线索应该如何推进？"
      }
    });
    expect(calls.commands).toHaveLength(0);
  });

  it("shows a local analyzer pending message while the model call is running", async () => {
    const user = userEvent.setup();
    setMessageResponseDelay(200);
    renderWorkspace();
    await waitForInitialTask();

    await user.click(await screen.findByRole("button", { name: "小说专家意见" }));
    const input = await screen.findByLabelText("输入给 Agent 的自然语言");
    await user.type(input, "强哥下一阶段是否应该回归？");
    await user.click(screen.getByRole("button", { name: "发送" }));

    expect(await screen.findByText("强哥下一阶段是否应该回归？")).toBeInTheDocument();
    expect(await screen.findByText("Analyzer 正在阅读当前小说记忆并分析剧情，请稍等。")).toBeInTheDocument();
    await waitFor(() => expect(calls.messages).toHaveLength(1));
  });

  it("keeps analyzer mode separate from Writer gate actions", async () => {
    const user = userEvent.setup();
    setWriterQuestionMessage("task-alpha");
    renderWorkspace();
    await waitForInitialTask();

    expect(await screen.findByText("顾迟是否为新增人物？")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "小说专家意见" }));
    expect(await screen.findByRole("button", { name: "退出专家意见" })).toBeInTheDocument();

    const input = await screen.findByLabelText("输入给 Agent 的自然语言");
    await user.type(input, "/analyze 当前未解之谜哪条更适合回收？");
    await user.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => expect(calls.messages).toHaveLength(1));
    expect(calls.messages[0].body).toMatchObject({
      content: "/analyze 当前未解之谜哪条更适合回收？",
      payload: {
        channel: "outline_analyzer",
        question: "/analyze 当前未解之谜哪条更适合回收？"
      }
    });
    expect(calls.actions.some((call) => call.body.action === "submit_outline_research_answers")).toBe(false);
    expect(calls.commands).toHaveLength(0);
  });

  it("binds Writer question answers to the chat input and only continues through the card action", async () => {
    const user = userEvent.setup();
    setWriterQuestionMessage("task-alpha");
    renderWorkspace();
    await waitForInitialTask();

    expect(await screen.findByText("顾迟是否为新增人物？")).toBeInTheDocument();
    const input = await screen.findByLabelText("输入给 Agent 的自然语言");
    await user.type(input, "不是新增人物，本轮不加入。");
    await user.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => expect(calls.messages).toHaveLength(1));
    expect(calls.messages[0].body).toMatchObject({
      content: "不是新增人物，本轮不加入。",
      payload: {
        channel: "writer_question_answer",
        run_id: "run-1",
        question_set_id: "outline-research-run-1-needs-answer",
        answer_text: "不是新增人物，本轮不加入。"
      }
    });
    expect(calls.actions.some((call) => call.body.action === "submit_outline_research_answers")).toBe(false);

    await user.click(screen.getByRole("button", { name: "提交回答并继续研究" }));

    await waitFor(() => expect(calls.actions.some((call) => call.body.action === "submit_outline_research_answers")).toBe(true));
    const submitCall = calls.actions.find((call) => call.body.action === "submit_outline_research_answers");
    expect(submitCall?.body.payload).toMatchObject({
      run_id: "run-1",
      question_set_id: "outline-research-run-1-needs-answer",
      source_message_id: "user-1",
      answer_text: "不是新增人物，本轮不加入。"
    });
    expect(calls.commands).toHaveLength(0);
  });

  it("uses the shared chat input for Writer artifact approval supplements", async () => {
    const user = userEvent.setup();
    setWriterArtifactReviewMessage("task-alpha");
    renderWorkspace();
    await waitForInitialTask();

    expect(await screen.findByText("本批会把旧案线索推到新地点。")).toBeInTheDocument();
    expect(within(screen.getByRole("log")).queryByRole("button", { name: "用输入框补充" })).not.toBeInTheDocument();
    const input = await screen.findByLabelText("输入给 Agent 的自然语言");
    await user.type(input, "动作段更紧，结尾不要解释幕后人。");
    const approveButtons = await screen.findAllByRole("button", { name: "通过并继续" });
    await user.click(approveButtons[approveButtons.length - 1]);

    await waitFor(() => expect(calls.messages.some((call) => call.body && JSON.stringify(call.body).includes("writer_artifact_supplement"))).toBe(true));

    await waitFor(() => expect(calls.actions.some((call) => call.body.action === "approve_writer_artifact")).toBe(true));
    const actionCall = calls.actions.find((call) => call.body.action === "approve_writer_artifact");
    expect(actionCall?.body.payload).toMatchObject({
      review_id: "artifact-review-run-1-batch",
      supplement_text: "动作段更紧，结尾不要解释幕后人。",
      source_message_id: "user-1"
    });
    await waitFor(() =>
      expect(within(document.querySelector("form.composer") as HTMLElement).queryByRole("button", { name: "通过并继续" })).not.toBeInTheDocument()
    );
  });

  it("uses the shared chat input for Writer artifact revision feedback", async () => {
    const user = userEvent.setup();
    setWriterArtifactReviewMessage("task-alpha");
    renderWorkspace();
    await waitForInitialTask();

    expect(within(screen.getByRole("log")).queryByRole("button", { name: "输入调整反馈" })).not.toBeInTheDocument();
    const input = await screen.findByLabelText("输入给 Agent 的自然语言");
    await user.type(input, "第二个场景因果太跳，先补人物动机。");
    const revisionButtons = await screen.findAllByRole("button", { name: "不通过并调整" });
    await user.click(revisionButtons[revisionButtons.length - 1]);

    await waitFor(() => expect(calls.actions.some((call) => call.body.action === "request_writer_artifact_revision")).toBe(true));
    const actionCall = calls.actions.find((call) => call.body.action === "request_writer_artifact_revision");
    expect(actionCall?.body.payload).toMatchObject({
      revision_feedback: "第二个场景因果太跳，先补人物动机。",
      source_message_id: "user-1"
    });
    await waitFor(() =>
      expect(within(document.querySelector("form.composer") as HTMLElement).queryByRole("button", { name: "不通过并调整" })).not.toBeInTheDocument()
    );
  });

  it("shows the draft review card without the old length-rewrite branch", async () => {
    const user = userEvent.setup();
    setWriterDraftReviewMessage("task-alpha");
    renderWorkspace();
    await waitForInitialTask();

    expect(await screen.findByText("雨落下来，巷口的灯忽明忽暗。")).toBeInTheDocument();
    expect(screen.queryByText("调整字数后重写")).not.toBeInTheDocument();
    expect(within(screen.getByRole("log")).queryByRole("button", { name: "输入重写反馈" })).not.toBeInTheDocument();
    const input = await screen.findByLabelText("输入给 Agent 的自然语言");
    await user.type(input, "节奏太慢，冲突提前。");
    const rewriteButtons = await screen.findAllByRole("button", { name: "基于反馈重写" });
    await user.click(rewriteButtons[rewriteButtons.length - 1]);

    await waitFor(() => expect(calls.actions.some((call) => call.body.action === "rewrite_chapter")).toBe(true));
    const rewriteCall = calls.actions.find((call) => call.body.action === "rewrite_chapter");
    expect(rewriteCall?.body.payload).toMatchObject({
      feedback_text: "节奏太慢，冲突提前。",
      source_message_id: "user-1"
    });
    await waitFor(() =>
      expect(within(document.querySelector("form.composer") as HTMLElement).queryByRole("button", { name: "基于反馈重写" })).not.toBeInTheDocument()
    );
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
    expect(writerCall?.body.payload).toMatchObject({
      continuation_goal: "进入新地点并揭露线索。",
      desired_actions: ["进入新地点并揭露线索。"],
      target_chapter_count: 3,
      default_chapter_target_chars: 3000,
      story_scale: { target_chapter_count: 3, default_chapter_target_chars: 3000, pacing_profile: "延续原作节奏" }
    });
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

  it("shows the Agent Loop Writer artifact tree", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    await waitForInitialTask();

    await user.click(screen.getByRole("tab", { name: /Writer/ }));

    expect(await screen.findByText("第一章 雨夜接应")).toBeInTheDocument();
    expect(screen.getByText("第二章 旧码头回声")).toBeInTheDocument();
    expect(await screen.findByText("大纲研究")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "问题集" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "大纲研究笔记" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "检索轨迹" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "章节写作指导" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "验收决策" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "章节长度计划" })).not.toBeInTheDocument();
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
