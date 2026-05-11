"""Unified CLI/TUI interaction layer for Novel Agent."""

from .app import TuiApp, TuiSessionConfig
from .artifacts import ArtifactPresenter, ArtifactSaveResult, ArtifactSummary
from .decisions import DecisionAction, DecisionOption, DecisionPanel
from .events import MessageStream, RunEvent, RunEventStream
from .facade import TuiTaskSnapshot, WorkflowFacade
from .forms import ChapterAcceptanceForm, WriterIntentForm
from .input import ChineseInputBuffer
from .router import CommandContext, CommandInvocation, CommandRouter
from .status import StatusPresenter, StatusView, WriterStageAction, WriterStatusPresenter
from .textual_app import TextualNovelAgentApp
from .textual_screens import HomeScreen, WorkbenchScreen
from .textual_widgets import (
    ArtifactEditorPane,
    ArtifactReferenceCandidate,
    ArtifactReviewPane,
    ChapterAcceptanceFormWidget,
    CommandPalette,
    DecisionPanelWidget,
    MessageFlow,
    PromptInput,
    ScopedRevisionFeedbackWidget,
    StatusOverlay,
    StatusSidebar,
    TechnicalDetailsOverlay,
    ToastLayer,
    WriterIntentWizardWidget,
)


__all__ = [
    "ArtifactPresenter",
    "ArtifactSaveResult",
    "ArtifactSummary",
    "ChapterAcceptanceForm",
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
    "WriterIntentForm",
    "ArtifactEditorPane",
    "ArtifactReferenceCandidate",
    "ArtifactReviewPane",
    "ChapterAcceptanceFormWidget",
    "CommandPalette",
    "DecisionPanelWidget",
    "HomeScreen",
    "MessageFlow",
    "PromptInput",
    "ScopedRevisionFeedbackWidget",
    "StatusOverlay",
    "StatusSidebar",
    "TechnicalDetailsOverlay",
    "TextualNovelAgentApp",
    "ToastLayer",
    "WorkbenchScreen",
    "WriterIntentWizardWidget",
]
