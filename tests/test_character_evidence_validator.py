from __future__ import annotations

from novel_agent.app.services.character_evidence_validator import CharacterEvidenceValidator


def test_validator_rejects_high_risk_verb_like_name_without_strong_cues() -> None:
    validator = CharacterEvidenceValidator()
    text = "诺诺也不生气，张开双臂，歪头看着他。"
    names = ["张开"]
    evidence = {"张开": ["张开双臂"]}
    assert validator.filter_names(doc_text=text, names=names, evidence_map=evidence) == []


def test_validator_accepts_name_with_intro_pattern_even_if_high_risk() -> None:
    validator = CharacterEvidenceValidator()
    text = "他名叫张开，是个奇怪的人。张开走进来。"
    names = ["张开"]
    evidence = {"张开": ["名叫张开"]}
    assert validator.filter_names(doc_text=text, names=names, evidence_map=evidence) == ["张开"]


def test_validator_drops_known_prefix_when_full_name_present() -> None:
    validator = CharacterEvidenceValidator()
    text = "路明非抬头看着他。路明非说：没事。"
    names = ["路明", "路明非"]
    evidence = {"路明": ["路明非抬头"], "路明非": ["路明非抬头"]}
    assert validator.filter_names(doc_text=text, names=names, evidence_map=evidence) == ["路明非"]


def test_validator_rejects_unknown_name_without_person_cue_even_with_snippet_match() -> None:
    validator = CharacterEvidenceValidator()
    text = "卡塞尔学院对于新学生张开了怀抱。"
    names = ["张开"]
    evidence = {"张开": ["新学生张开了怀抱"]}
    assert validator.filter_names(doc_text=text, names=names, evidence_map=evidence) == []
