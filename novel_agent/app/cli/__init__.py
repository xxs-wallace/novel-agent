"""Unified CLI/TUI interaction layer for Novel Agent."""

from .app import TuiApp, TuiSessionConfig
from .artifacts import ArtifactPresenter, ArtifactSaveResult, ArtifactSummary
from .decisions import DecisionAction, DecisionOption, DecisionPanel
from .events import MessageStream, RunEvent, RunEventStream
from .facade import TuiTaskSnapshot, WorkflowFacade
from .input import ChineseInputBuffer
from .router import CommandContext, CommandInvocation, CommandRouter
from .status import StatusPresenter, StatusView, WriterStageAction, WriterStatusPresenter
from .textual_app import TextualNovelAgentApp
from .textual_screens import HomeScreen, WorkbenchScreen
from .textual_widgets import (
    ArtifactEditorPane,
    ArtifactReferenceCandidate,
    ArtifactReviewPane,
    CommandPalette,
    DecisionPanelWidget,
    MessageFlow,
    PromptInput,
    StatusOverlay,
    StatusSidebar,
    TechnicalDetailsOverlay,
    ToastLayer,
)


__all__ = [
    "ArtifactPresenter",
    "ArtifactSaveResult",
    "ArtifactSummary",
    "ChineseInputBuffer",
    "CommandContext",
    "CommandInvocation",
    "CommandRouter",
    "DecisionAction",
    "DecisionOption",
    "DecisionPanel",
    "MessageStream",
    "RunEvent",
    "RunEventStream",
    "StatusPresenter",
    "StatusView",
    "WriterStageAction",
    "WriterStatusPresenter",
    "TuiApp",
    "TuiSessionConfig",
    "TuiTaskSnapshot",
    "WorkflowFacade",
    "ArtifactEditorPane",
    "ArtifactReferenceCandidate",
    "ArtifactReviewPane",
    "CommandPalette",
    "DecisionPanelWidget",
    "HomeScreen",
    "MessageFlow",
    "PromptInput",
    "StatusOverlay",
    "StatusSidebar",
    "TechnicalDetailsOverlay",
    "TextualNovelAgentApp",
    "ToastLayer",
    "WorkbenchScreen",
]
