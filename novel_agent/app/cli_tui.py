from __future__ import annotations

from .bootstrap import resolve_repo_root


def main() -> int:
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
