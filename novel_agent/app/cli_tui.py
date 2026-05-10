from __future__ import annotations

import sys

from .bootstrap import resolve_repo_root


CREATIVE_KB_BENCHMARK_COMMANDS = {"creative-kb-benchmark", "creative-kb-bench", "kb-benchmark"}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in CREATIVE_KB_BENCHMARK_COMMANDS:
        from .run_creative_kb_benchmark import main as run_creative_kb_benchmark

        return run_creative_kb_benchmark(argv[1:])

    try:
        from .cli.textual_app import TextualNovelAgentApp
    except ModuleNotFoundError as exc:
        missing_name = str(getattr(exc, "name", "") or "")
        if missing_name.split(".")[0] != "textual":
            raise
        print("未安装 Textual。请先运行：python -m pip install -e .")
        print("开发调试入口等价命令：python -m novel_agent.app.cli_tui")
        return 2

    TextualNovelAgentApp(repo_root=resolve_repo_root()).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
