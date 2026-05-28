from __future__ import annotations

from .chapter_synopsis_plot_character import ChapterSynopsisPlotCharacterReviewer
from .kb_draft_style_atmosphere import KBDraftStyleAtmosphereReviewer
from .local_draft_continuity import LocalDraftContinuityReviewer
from .memory_draft_consistency import MemoryDraftConsistencyReviewer
from .model_only import ModelOnlyReviewer
from .outline_plot_development import OutlinePlotDevelopmentReviewer
from .source_chapter_literary_diagnostic import SourceChapterLiteraryDiagnosticReviewer


def default_reviewers() -> list[ModelOnlyReviewer]:
    return [
        OutlinePlotDevelopmentReviewer(),
        ChapterSynopsisPlotCharacterReviewer(),
        LocalDraftContinuityReviewer(),
        MemoryDraftConsistencyReviewer(),
        KBDraftStyleAtmosphereReviewer(),
        SourceChapterLiteraryDiagnosticReviewer(),
    ]


__all__ = [
    "ChapterSynopsisPlotCharacterReviewer",
    "KBDraftStyleAtmosphereReviewer",
    "LocalDraftContinuityReviewer",
    "MemoryDraftConsistencyReviewer",
    "ModelOnlyReviewer",
    "OutlinePlotDevelopmentReviewer",
    "SourceChapterLiteraryDiagnosticReviewer",
    "default_reviewers",
]
