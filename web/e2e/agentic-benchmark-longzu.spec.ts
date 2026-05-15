import { expect, test } from "@playwright/test";
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

type CommandResult = {
  code: number;
  stdout: string;
  stderr: string;
};

type AgenticBenchmarkPayload = {
  run_id: string;
  run_dir: string;
  book_id: string;
  source_path: string;
  prefix_source_path: string;
  db_path: string;
  writer_run_dir: string;
  draft_path: string;
  reference_truth_path: string;
  generated_synopsis_path: string;
  reference_synopsis_path: string;
  synopsis_reviewer_report_path: string;
  expansion_prompt_path: string;
  expansion_reviewer_report_path: string;
  reviewer_report_path: string;
  summary_path: string;
  generated_chars: number;
  reference_truth_chars: number;
  synopsis_decision: string;
  synopsis_score: number;
  expansion_decision: string;
  expansion_score: number;
  reviewer_decision: string;
  reviewer_score: number;
  summary_text: string;
};

const repoRoot = path.resolve("..");
const sourcePath = "/Users/luliao/agent/smolagents/novel_agent/tests/longzu_32kb.txt";
const runsDir = path.join(repoRoot, "runs", "e2e-agentic-benchmark-runs");
const cacheDir = path.join(repoRoot, "runs", "e2e-agentic-benchmark-cache");
const benchmarkTimeoutMs = 60 * 60 * 1000;

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, "'\\''")}'`;
}

function parseJsonPayload(stdout: string): AgenticBenchmarkPayload {
  const trimmed = stdout.trim();
  const candidates = [0];
  for (const match of trimmed.matchAll(/(?:^|\n)\s*\{/g)) {
    const start = match.index + match[0].lastIndexOf("{");
    if (!candidates.includes(start)) {
      candidates.push(start);
    }
  }
  let lastError: unknown;
  for (const start of candidates.reverse()) {
    try {
      return JSON.parse(trimmed.slice(start).trim()) as AgenticBenchmarkPayload;
    } catch (error) {
      lastError = error;
    }
  }
  throw new Error(
    `run_single_sample_smoke did not print a parseable final JSON payload: ${String(lastError)}\n` +
      trimmed.slice(-4000)
  );
}

class AgenticBenchmarkCli {
  constructor(private readonly cwd: string) {}

  async hasDeepSeekApiKey(): Promise<boolean> {
    const result = await this.runBash(
      [
        "set -a",
        "source ~/.bash_profile >/dev/null 2>&1 || true",
        "set +a",
        'test -n "${DEEPSEEK_API_KEY:-}"'
      ].join("\n"),
      10_000
    );
    return result.code === 0;
  }

  async hasOpenAIExtra(): Promise<boolean> {
    const result = await this.runBash(
      [
        "PYTHON_BIN=${PYTHON_BIN:-.venv/bin/python}",
        'if [ ! -x "$PYTHON_BIN" ]; then PYTHON_BIN=python3; fi',
        '"$PYTHON_BIN" - <<\'PY\'',
        "from smolagents.models import OpenAIModel",
        "OpenAIModel(model_id='deepseek-chat', api_base='https://api.deepseek.com', api_key='test-key')",
        "PY"
      ].join("\n"),
      20_000
    );
    return result.code === 0;
  }

  async runLongzu32kb(): Promise<AgenticBenchmarkPayload> {
    fs.mkdirSync(runsDir, { recursive: true });
    fs.mkdirSync(cacheDir, { recursive: true });

    const command = [
      "set -a",
      "source ~/.bash_profile >/dev/null 2>&1 || true",
      "set +a",
      "set -euo pipefail",
      'if [ -z "${DEEPSEEK_API_KEY:-}" ]; then',
      '  echo "DEEPSEEK_API_KEY is required; define it in ~/.bash_profile or export it before running e2e:agentic." >&2',
      "  exit 86",
      "fi",
      "PYTHON_BIN=${PYTHON_BIN:-.venv/bin/python}",
      'if [ ! -x "$PYTHON_BIN" ]; then PYTHON_BIN=python3; fi',
      'PYTHONUNBUFFERED=1 "$PYTHON_BIN" -m novel_agent.app.run_single_sample_smoke \\',
      `  --source ${shellQuote(sourcePath)} \\`,
      `  --repo-root ${shellQuote(this.cwd)} \\`,
      `  --runs-dir ${shellQuote(runsDir)} \\`,
      "  --use-real-model \\",
      "  --api-key-env DEEPSEEK_API_KEY \\",
      `  --benchmark-cache-dir ${shellQuote(cacheDir)} \\`,
      "  --reuse-modeling-cache \\",
      '  --prefix-min-chars "${AGENTIC_BENCHMARK_PREFIX_MIN_CHARS:-4000}" \\',
      '  --reference-min-chars "${AGENTIC_BENCHMARK_REFERENCE_MIN_CHARS:-2700}" \\',
      '  --max-read-kb "${AGENTIC_BENCHMARK_MAX_READ_KB:-64}" \\',
      '  --max-close-batches "${AGENTIC_BENCHMARK_MAX_CLOSE_BATCHES:-12}" \\',
      '  --segment-step-kb "${AGENTIC_BENCHMARK_SEGMENT_STEP_KB:-32}" \\',
      '  --close-step-batches "${AGENTIC_BENCHMARK_CLOSE_STEP_BATCHES:-1}"'
    ].join("\n");

    const result = await this.runBash(command, benchmarkTimeoutMs - 30_000);
    if (result.code !== 0) {
      throw new Error(
        [
          `run_single_sample_smoke exited with ${result.code}.`,
          "stdout:",
          result.stdout.slice(-4000),
          "stderr:",
          result.stderr.slice(-4000)
        ].join("\n")
      );
    }
    return parseJsonPayload(result.stdout);
  }

  private runBash(command: string, timeoutMs: number): Promise<CommandResult> {
    return new Promise((resolve, reject) => {
      const child = spawn("bash", ["-lc", command], {
        cwd: this.cwd,
        env: { ...process.env, PYTHONUNBUFFERED: "1" }
      });
      let stdout = "";
      let stderr = "";
      const timer = setTimeout(() => {
        child.kill("SIGTERM");
        reject(new Error(`Command timed out after ${timeoutMs}ms:\n${command}`));
      }, timeoutMs);

      child.stdout.on("data", (chunk: Buffer) => {
        stdout += chunk.toString();
      });
      child.stderr.on("data", (chunk: Buffer) => {
        stderr += chunk.toString();
      });
      child.on("error", (error) => {
        clearTimeout(timer);
        reject(error);
      });
      child.on("close", (code) => {
        clearTimeout(timer);
        resolve({ code: code ?? -1, stdout, stderr });
      });
    });
  }
}

test.skip(
  process.env.RUN_AGENTIC_BENCHMARK_E2E !== "1",
  "Set RUN_AGENTIC_BENCHMARK_E2E=1 or run npm run e2e:agentic to execute the live DeepSeek benchmark."
);

test.setTimeout(benchmarkTimeoutMs);

test("live agentic benchmark processes longzu_32kb and writes canonical artifacts", async () => {
  const cli = new AgenticBenchmarkCli(repoRoot);

  test.skip(!fs.existsSync(sourcePath), `Missing benchmark source fixture: ${sourcePath}`);
  test.skip(!(await cli.hasDeepSeekApiKey()), "DEEPSEEK_API_KEY was not found after sourcing ~/.bash_profile.");
  test.skip(
    !(await cli.hasOpenAIExtra()),
    "OpenAIModel dependency is missing. Install with: .venv/bin/python -m pip install -e '.[openai]'"
  );

  const payload = await cli.runLongzu32kb();

  expect(payload.source_path).toBe(sourcePath);
  expect(payload.run_id).toMatch(/^[0-9a-f]{32}$/);
  expect(payload.book_id).toContain("longzu");
  expect(payload.generated_chars).toBeGreaterThan(0);
  expect(payload.reference_truth_chars).toBeGreaterThan(1000);
  expect(payload.summary_text).toContain("梗概层 Reviewer");
  expect(payload.summary_text).toContain("扩写层 Reviewer");
  expect(payload.summary_text).toContain("综合 Reviewer");

  const requiredPaths = [
    payload.run_dir,
    payload.prefix_source_path,
    payload.db_path,
    payload.writer_run_dir,
    payload.draft_path,
    payload.reference_truth_path,
    payload.generated_synopsis_path,
    payload.reference_synopsis_path,
    payload.synopsis_reviewer_report_path,
    payload.expansion_prompt_path,
    payload.expansion_reviewer_report_path,
    payload.reviewer_report_path,
    payload.summary_path
  ];
  for (const artifactPath of requiredPaths) {
    expect(fs.existsSync(artifactPath), `${artifactPath} should exist`).toBe(true);
  }

  const runDir = path.resolve(payload.run_dir);
  for (const artifactPath of requiredPaths.filter((value) => value !== payload.db_path)) {
    expect(path.resolve(artifactPath).startsWith(runDir), `${artifactPath} should stay under run_dir`).toBe(true);
  }

  const draft = fs.readFileSync(payload.draft_path, "utf-8").trim();
  expect(draft.length).toBeGreaterThan(100);

  const summary = JSON.parse(fs.readFileSync(payload.summary_path, "utf-8")) as AgenticBenchmarkPayload;
  expect(summary.run_id).toBe(payload.run_id);
  expect(summary.generated_synopsis_path).toBe(payload.generated_synopsis_path);
  expect(summary.reference_synopsis_path).toBe(payload.reference_synopsis_path);
  expect(summary.reviewer_report_path).toBe(payload.reviewer_report_path);

  const reviewerReport = JSON.parse(fs.readFileSync(payload.reviewer_report_path, "utf-8")) as {
    layers?: Record<string, unknown>;
    generated_chars?: number;
    reference_truth_chars?: number;
  };
  expect(reviewerReport.layers).toHaveProperty("synopsis");
  expect(reviewerReport.layers).toHaveProperty("expansion");
  expect(reviewerReport.generated_chars).toBe(payload.generated_chars);
  expect(reviewerReport.reference_truth_chars).toBe(payload.reference_truth_chars);

  const generatedSynopsis = fs.readFileSync(payload.generated_synopsis_path, "utf-8").trim();
  const referenceSynopsis = fs.readFileSync(payload.reference_synopsis_path, "utf-8").trim();
  expect(generatedSynopsis).toContain("{");
  expect(referenceSynopsis).toContain("{");
});
