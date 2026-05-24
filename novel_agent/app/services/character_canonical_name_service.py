from __future__ import annotations

import json
from typing import Any

from ..llm import JsonModelClient
from ..prompts.character_canonical_name_prompt import build_character_canonical_name_prompt
from ..repos.character_profiles_repo import CharacterProfilesRepo


class CharacterCanonicalNameService:
    def __init__(self, *, profiles_repo: CharacterProfilesRepo) -> None:
        self.profiles_repo = profiles_repo

    def resolve_updates(
        self,
        conn,
        *,
        book_id: str,
        model_client: JsonModelClient,
        updates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        resolved: list[dict[str, Any]] = []
        for update in updates:
            candidate_names, existing_profiles = self._candidate_context(conn, book_id=book_id, update=update)
            if len(candidate_names) <= 1:
                resolved.append(dict(update))
                continue
            decision = self._ask_model(
                model_client=model_client,
                prompt_input={
                    "book_id": book_id,
                    "current_canonical_name": str(update.get("canonical_name") or "").strip(),
                    "candidate_names": candidate_names,
                    "existing_profiles": existing_profiles,
                    "candidate_update": self._compact_update(update),
                },
                fallback_factory=lambda update=update: {
                    "preferred_canonical_name": str(update.get("canonical_name") or "").strip(),
                    "aliases_to_keep": update.get("aliases", []),
                    "reason": "fallback keeps current canonical name",
                    "confidence": 0.0,
                },
            )
            normalized = self._apply_decision(
                update=update,
                decision=decision,
                candidate_names=candidate_names,
                has_existing_profile=bool(existing_profiles),
            )
            resolved.append(normalized)
        return resolved

    def _ask_model(
        self,
        *,
        model_client: JsonModelClient,
        prompt_input: dict[str, Any],
        fallback_factory,
    ) -> dict[str, Any]:
        system_prompt, user_prompt = build_character_canonical_name_prompt(prompt_input)
        payload, _ = model_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_factory=fallback_factory,
            use_fallback_on_error=model_client.settings.dry_run,
        )
        if not isinstance(payload, dict):
            raise RuntimeError("Character canonical name model returned a non-object JSON payload")
        return dict(payload)

    def _apply_decision(
        self,
        *,
        update: dict[str, Any],
        decision: dict[str, Any],
        candidate_names: list[str],
        has_existing_profile: bool = False,
    ) -> dict[str, Any]:
        candidate_set = set(candidate_names)
        current = str(update.get("canonical_name") or "").strip()
        preferred = str(decision.get("preferred_canonical_name") or "").strip()
        if preferred not in candidate_set:
            preferred = current
        if has_existing_profile and preferred != current and not self._should_retitle_existing(decision):
            preferred = current
        aliases = []
        raw_aliases = decision.get("aliases_to_keep")
        if isinstance(raw_aliases, list):
            aliases.extend(str(item).strip() for item in raw_aliases if str(item).strip() in candidate_set)
        aliases.extend(name for name in candidate_names if name != preferred)
        normalized_aliases: list[str] = []
        seen: set[str] = set()
        for alias in aliases:
            if not alias or alias == preferred or alias in seen:
                continue
            seen.add(alias)
            normalized_aliases.append(alias)
        normalized = dict(update)
        normalized["canonical_name"] = preferred
        normalized["aliases"] = normalized_aliases
        normalized["preferred_canonical_name"] = preferred
        return normalized

    def _should_retitle_existing(self, decision: dict[str, Any]) -> bool:
        try:
            confidence = float(decision.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        reason = str(decision.get("reason") or "")
        correction_markers = ("误认", "误判", "错误", "错写", "伪装名", "假名", "身份修正")
        return confidence >= 0.95 and any(marker in reason for marker in correction_markers)

    def _candidate_context(self, conn, *, book_id: str, update: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
        names = self._name_list([update.get("canonical_name"), *self._as_list(update.get("aliases"))])
        if not names:
            return [], []
        rows = self.profiles_repo.list_by_book(conn, book_id=book_id)
        lookup = set(names)
        matched_profiles: list[dict[str, Any]] = []
        for row in rows:
            row_names = self._name_list([row["canonical_name"], *self._load_json_list(row, "aliases_json")])
            if lookup.intersection(row_names):
                names.extend(row_names)
                lookup.update(row_names)
                matched_profiles.append(self._profile_summary(row))
        return self._name_list(names), matched_profiles

    def _profile_summary(self, row: Any) -> dict[str, Any]:
        return {
            "canonical_name": str(row["canonical_name"] or "").strip(),
            "aliases": self._load_json_list(row, "aliases_json"),
            "personhood_evidence_summary": str(row["personhood_evidence_summary"] or ""),
            "profile_summary_md": str(row["profile_summary_md"] or "")[:1200],
            "first_seen_doc_id": row["first_seen_doc_id"],
            "last_seen_doc_id": row["last_seen_doc_id"],
        }

    def _compact_update(self, update: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "canonical_name",
            "aliases",
            "recent_activity",
            "relationships",
            "personhood_evidence_summary",
            "speaking_character_status",
        )
        return {key: update.get(key) for key in keys if key in update}

    def _load_json_list(self, row: Any, field_name: str) -> list[Any]:
        raw = row[field_name]
        if not raw:
            return []
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return loaded if isinstance(loaded, list) else []

    def _name_list(self, values: list[Any]) -> list[str]:
        result: list[str] = []
        for value in values:
            name = str(value or "").strip()
            if name and name not in result:
                result.append(name)
        return result

    def _as_list(self, value: object) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]
