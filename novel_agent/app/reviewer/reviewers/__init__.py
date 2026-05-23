from __future__ import annotations

from .chapter_synopsis_plot_character import ChapterSynopsisPlotCharacterReviewer
from .kb_draft_style_atmosphere import KBDraftStyleAtmosphereReviewer
from .local_draft_continuity import LocalDraftContinuityReviewer
from .memory_draft_consistency import MemoryDraftConsistencyReviewer
from .model_only import ModelOnlyReviewer
from .outline_plot_development import OutlinePlotDevelopmentReviewer


def default_reviewers() -> list[ModelOnlyReviewer]:
    return [
        OutlinePlotDevelopmentReviewer(),
        ChapterSynopsisPlotCharacterReviewer(),
        LocalDraftContinuityReviewer(),
        MemoryDraftConsistencyReviewer(),
        KBDraftStyleAtmosphereReviewer(),
    ]


__all__ = [
    "ChapterSynopsisPlotCharacterReviewer",
    "KBDraftStyleAtmosphereReviewer",
    "LocalDraftContinuityReviewer",
    "MemoryDraftConsistencyReviewer",
    "ModelOnlyReviewer",
    "OutlinePlotDevelopmentReviewer",
    "default_reviewers",
]
