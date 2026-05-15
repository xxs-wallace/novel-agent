from __future__ import annotations

import argparse
import importlib
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


ImportModule = Callable[[str], object]
Which = Callable[[str], str | None]


@dataclass(frozen=True, slots=True)
class LauncherConfig:
    repo_root: Path
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    web_host: str = "127.0.0.1"
    web_port: int = 5173
    install: bool = True
    open_browser: bool = True

    @property
    def web_dir(self) -> Path:
        return self.repo_root / "web"

    @property
    def frontend_url(self) -> str:
        return f"http://{self.web_host}:{self.web_port}"

    @property
    def api_url(self) -> str:
        return f"http://{self.api_host}:{self.api_port}"


@dataclass(frozen=True, slots=True)
class DependencyIssue:
    message: str
    recovery: str
    fatal: bool = True


class DependencyInspector:
    def __init__(
        self,
        config: LauncherConfig,
        *,
        which: Which = shutil.which,
        import_module: ImportModule = importlib.import_module,
    ) -> None:
        self.config = config
        self.which = which
        self.import_module = import_module

    def inspect(self) -> list[DependencyIssue]:
        issues: list[DependencyIssue] = []
        issues.extend(self._inspect_python_deps())
        issues.extend(self._inspect_node_deps())
        issues.extend(self._inspect_web_files())
        issues.extend(self._inspect_environment())
        return issues

    def _inspect_python_deps(self) -> list[DependencyIssue]:
        issues: list[DependencyIssue] = []
        for module_name, recovery in {
            "fastapi": f"{sys.executable} -m pip install -e .",
            "uvicorn": f"{sys.executable} -m pip install -e .",
        }.items():
            try:
                self.import_module(module_name)
            except Exception:
                issues.append(
                    DependencyIssue(
                        message=f"缺少 Python 依赖：{module_name}",
                        recovery=f"在仓库根目录运行：{recovery}",
                    )
                )
        return issues

    def _inspect_node_deps(self) -> list[DependencyIssue]:
        issues: list[DependencyIssue] = []
        if self.which("node") is None:
            issues.append(
                DependencyIssue(
                    message="未找到 node 可执行文件。",
                    recovery="请先安装 Node.js 20+，例如使用 nvm install 20。",
                )
            )
        if self.which("npm") is None:
            issues.append(
                DependencyIssue(
                    message="未找到 npm 可执行文件。",
                    recovery="请确认 Node.js/npm 已安装并在 PATH 中。",
                )
            )
        return issues

    def _inspect_web_files(self) -> list[DependencyIssue]:
        web_dir = self.config.web_dir
        if not web_dir.exists():
            return [
                DependencyIssue(
                    message=f"未找到 Web 前端目录：{web_dir}",
                    recovery="请确认当前 worktree 已包含 web/ 前端工程。",
                )
            ]
        if not (web_dir / "package.json").exists():
            return [
                DependencyIssue(
                    message=f"未找到前端 package.json：{web_dir / 'package.json'}",
                    recovery="请确认 web/package.json 已生成。",
                )
            ]
        return []

    def _inspect_environment(self) -> list[DependencyIssue]:
        if os.getenv("DEEPSEEK_API_KEY", "").strip():
            return []
        return [
            DependencyIssue(
                message="未检测到 DEEPSEEK_API_KEY；Web 可以启动，但真实模型动作会失败。",
                recovery="如果 key 定义在 ~/.bash_profile，请先 source ~/.bash_profile 再启动。",
                fatal=False,
            )
        ]


class WebWorkbenchLauncher:
    def __init__(self, config: LauncherConfig) -> None:
        self.config = config
        self.processes: list[subprocess.Popen[bytes]] = []

    def ensure_frontend_dependencies(self) -> None:
        node_modules = self.config.web_dir / "node_modules"
        package_lock = self.config.web_dir / "package-lock.json"
        if node_modules.exists():
            return
        if not self.config.install:
            raise RuntimeError(
                "前端依赖尚未安装。请运行 cd web && npm install，或重新执行 novel-agent-web 且不要传 --no-install。"
            )
        install_command = ["npm", "install"]
        if package_lock.exists():
            install_command = ["npm", "install"]
        print("前端依赖未安装，正在执行：cd web && npm install")
        subprocess.run(install_command, cwd=self.config.web_dir, check=True)

    def backend_command(self) -> list[str]:
        return [
            sys.executable,
            "-m",
            "uvicorn",
            "novel_agent.app.web.main:app",
            "--host",
            self.config.api_host,
            "--port",
            str(self.config.api_port),
        ]

    def frontend_command(self) -> list[str]:
        return [
            "npm",
            "run",
            "dev",
            "--",
            "--host",
            self.config.web_host,
            "--port",
            str(self.config.web_port),
        ]

    def backend_environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env["NOVEL_AGENT_REPO_ROOT"] = str(self.config.repo_root)
        return env

    def frontend_environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env["VITE_API_PROXY_TARGET"] = self.config.api_url
        return env

    def start(self) -> int:
        self.ensure_frontend_dependencies()
        self._warn_if_port_accepts_connections(self.config.api_host, self.config.api_port, "后端")
        self._warn_if_port_accepts_connections(self.config.web_host, self.config.web_port, "前端")

        print(f"启动 Novel Agent Web 后端：{self.config.api_url}")
        backend = subprocess.Popen(self.backend_command(), cwd=self.config.repo_root, env=self.backend_environment())
        self.processes.append(backend)

        print(f"启动 Novel Agent Web 前端：{self.config.frontend_url}")
        frontend = subprocess.Popen(
            self.frontend_command(),
            cwd=self.config.web_dir,
            env=self.frontend_environment(),
        )
        self.processes.append(frontend)

        print(f"打开工作台：{self.config.frontend_url}")
        if self.config.open_browser:
            time.sleep(1.0)
            webbrowser.open(self.config.frontend_url)

        return self.wait()

    def wait(self) -> int:
        try:
            while True:
                for process in self.processes:
                    return_code = process.poll()
                    if return_code is not None:
                        self.terminate()
                        return return_code
                time.sleep(0.25)
        except KeyboardInterrupt:
            print("\n收到退出信号，正在关闭前后端服务。")
            self.terminate()
            return 130

    def terminate(self) -> None:
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
        deadline = time.monotonic() + 5
        for process in self.processes:
            if process.poll() is not None:
                continue
            remaining = max(0.1, deadline - time.monotonic())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                process.kill()

    def _warn_if_port_accepts_connections(self, host: str, port: int, label: str) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            if sock.connect_ex((host, port)) == 0:
                print(f"警告：{label}端口 {host}:{port} 已可连接；如果启动失败，请换一个端口。")


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start Novel Agent Web frontend and backend together.")
    parser.add_argument("--repo-root", type=Path, default=_default_repo_root(), help="Repository root.")
    parser.add_argument("--api-host", default="127.0.0.1", help="FastAPI bind host.")
    parser.add_argument("--api-port", type=int, default=8000, help="FastAPI bind port.")
    parser.add_argument("--web-host", default="127.0.0.1", help="Vite bind host.")
    parser.add_argument("--web-port", type=int, default=5173, help="Vite bind port.")
    parser.add_argument("--no-install", action="store_true", help="Do not run npm install when node_modules is missing.")
    parser.add_argument("--no-open", action="store_true", help="Do not open the browser automatically.")
    parser.add_argument("--check-only", action="store_true", help="Check dependencies and exit without starting services.")
    return parser


def _print_issues(issues: Sequence[DependencyIssue]) -> None:
    for issue in issues:
        level = "错误" if issue.fatal else "提醒"
        print(f"{level}：{issue.message}")
        print(f"  处理方式：{issue.recovery}")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    config = LauncherConfig(
        repo_root=args.repo_root.expanduser().resolve(),
        api_host=args.api_host,
        api_port=args.api_port,
        web_host=args.web_host,
        web_port=args.web_port,
        install=not args.no_install,
        open_browser=not args.no_open,
    )
    issues = DependencyInspector(config).inspect()
    fatal_issues = [issue for issue in issues if issue.fatal]
    _print_issues(issues)
    if fatal_issues:
        return 2
    if args.check_only:
        print("依赖检查完成，可以启动 Novel Agent Web。")
        return 0
    return WebWorkbenchLauncher(config).start()


if __name__ == "__main__":
    raise SystemExit(main())
