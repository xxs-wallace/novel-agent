from __future__ import annotations

from dataclasses import dataclass

from smolagents import Tool
from smolagents.default_tools import TOOL_MAPPING

from .task4_retrieval_tools import NOVEL_AGENT_TOOL_MAPPING as TASK4_NOVEL_AGENT_TOOL_MAPPING
from .task5_scene_tools import NOVEL_AGENT_TOOL_MAPPING as TASK5_NOVEL_AGENT_TOOL_MAPPING


NOVEL_AGENT_TOOL_MAPPING: dict[str, type[Tool]] = {
    **TASK4_NOVEL_AGENT_TOOL_MAPPING,
    **TASK5_NOVEL_AGENT_TOOL_MAPPING,
}


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str


class ToolFactory:
    def build(self, tool_specs: list[ToolSpec]) -> list[Tool]:
        tools: list[Tool] = []
        for spec in tool_specs:
            if spec.name in NOVEL_AGENT_TOOL_MAPPING:
                tools.append(NOVEL_AGENT_TOOL_MAPPING[spec.name]())
                continue
            if spec.name not in TOOL_MAPPING:
                raise ValueError(f"Unsupported tool: {spec.name}")
            tools.append(TOOL_MAPPING[spec.name]())
        return tools


def build_tools(tool_names: list[str]) -> list[Tool]:
    factory = ToolFactory()
    return factory.build([ToolSpec(name=name) for name in tool_names])
