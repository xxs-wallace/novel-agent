from __future__ import annotations

import json
from typing import Any, Mapping

from ..llm import JsonModelClient
from ..prompts.character_identity_resolution_prompt import build_character_identity_resolution_prompt
from ..repos.character_profiles_repo import CharacterProfilesRepo
from .character_roster_service import CharacterRosterService


class CharacterIdentityResolutionService:
    def __init__(self, *, profiles_repo: CharacterProfilesRepo) -> None:
        self.profiles_repo = profiles_repo
        self.roster_service = CharacterRosterService(profiles_repo=profiles_repo)

    def resolve_updates(
        self,
        conn,
        *,
        book_id: str,
        model_client: JsonModelClient,
        updates: list[dict[str, Any]],
        source_verified_names: list[str],
        source_verified_speakers: list[str],
    ) -> list[dict[str, Any]]:
        if not updates:
            return []
        resolved: list[dict[str, Any]] = []
        existing_character_roster = self.roster_service.load_recent_roster(conn, book_id=book_id)
        compact_profiles = self._profiles_for_verified_names(
            conn,
            book_id=book_id,
            source_verified_names=source_verified_names,
        )
        for update in updates:
            candidate_name = self._clean_name(update.get("canonical_name"))
            if not candidate_name:
                continue
            first_decision = self._ask_model(
                model_client=model_client,
                prompt_input={
                    "book_id": book_id,
                    "candidate_update": self._compact_update(update),
                    "source_verified_names": source_verified_names,
                    "source_verified_speakers": source_verified_speakers,
                    "existing_character_roster": existing_character_roster,
                    "character_profiles": compact_profiles,
                    "all_character_profiles": [],
                    "resolution_round": "initial",
                },
                fallback_factory=lambda update=update: self._fallback_decision(
                    update=update,
                    source_verified_names=source_verified_names,
                ),
            )
            decision = first_decision
            if self._decision_action(first_decision) == "request_all_profiles":
                all_profiles = self._all_profile_summaries(conn, book_id=book_id)
                decision = self._ask_model(
                    model_client=model_client,
                    prompt_input={
                        "book_id": book_id,
                        "candidate_update": self._compact_update(update),
                        "source_verified_names": source_verified_names,
                        "source_verified_speakers": source_verified_speakers,
                        "existing_character_roster": existing_character_roster,
                        "character_profiles": compact_profiles,
                        "all_character_profiles": all_profiles,
                        "resolution_round": "with_all_profiles",
                    },
                    fallback_factory=lambda update=update: self._fallback_decision(
                        update=update,
                        source_verified_names=source_verified_names,
                    ),
                )
            normalized = self._apply_decision(
                update=update,
                decision=decision,
                source_verified_names=source_verified_names,
                known_profile_names=self._known_profile_names(conn, book_id=book_id),
            )
            if normalized is not None:
                resolved.append(normalized)
        return resolved

    def _ask_model(
        self,
        *,
        model_client: JsonModelClient,
        prompt_input: dict[str, Any],
        fallback_factory,
    ) -> dict[str, Any]:
        system_prompt, user_prompt = build_character_identity_resolution_prompt(prompt_input)
        payload, _ = model_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_factory=fallback_factory,
            use_fallback_on_error=model_client.settings.dry_run,
        )
        decision = dict(payload) if isinstance(payload, dict) else {}
        if self._decision_action(decision) not in {"create_new", "merge_existing", "drop", "request_all_profiles"}:
            fallback = fallback_factory()
            return dict(fallback) if isinstance(fallback, dict) else {}
        return decision

    def _apply_decision(
        self,
        *,
        update: dict[str, Any],
        decision: Mapping[str, Any],
        source_verified_names: list[str],
        known_profile_names: set[str],
    ) -> dict[str, Any] | None:
        action = self._decision_action(decision)
        if action in {"drop", "request_all_profiles"}:
            return None
        candidate_name = self._clean_name(update.get("canonical_name"))
        source_names = set(source_verified_names)
        if action == "create_new":
            canonical_name = self._clean_name(decision.get("canonical_name")) or candidate_name
            if canonical_name not in source_names:
                return None
        elif action == "merge_existing":
            canonical_name = self._clean_name(decision.get("existing_canonical_name"))
            if not canonical_name or canonical_name not in known_profile_names:
                return None
        else:
            return None
        aliases_to_add = self._source_supported_aliases(
            decision.get("aliases_to_add"),
            source_verified_names=source_verified_names,
        )
        normalized = dict(update)
        normalized["canonical_name"] = canonical_name
        normalized["aliases"] = self._merge_aliases(update.get("aliases"), aliases_to_add)
        return normalized

    def _fallback_decision(self, *, update: dict[str, Any], source_verified_names: list[str]) -> dict[str, Any]:
        candidate_name = self._clean_name(update.get("canonical_name"))
        if candidate_name and candidate_name in set(source_verified_names):
            return {
                "action": "create_new",
                "canonical_name": candidate_name,
                "existing_canonical_name": "",
                "aliases_to_add": [],
                "reason": "candidate_name is source verified",
                "confidence": 0.7,
            }
        return {
            "action": "drop",
            "canonical_name": "",
            "existing_canonical_name": "",
            "aliases_to_add": [],
            "reason": "candidate_name is not source verified and no model decision is available",
            "confidence": 0.5,
        }

    def _profiles_for_verified_names(
        self,
        conn,
        *,
        book_id: str,
        source_verified_names: list[str],
    ) -> list[dict[str, Any]]:
        if not source_verified_names:
            return []
        rows = self.profiles_repo.list_by_book(conn, book_id=book_id)
        names = set(source_verified_names)
        selected = []
        for row in rows:
            canonical_name = str(row["canonical_name"] or "").strip()
            aliases = self._load_json_list(row, "aliases_json")
            if canonical_name in names or any(str(alias).strip() in names for alias in aliases):
                selected.append(row)
        return [self._profile_summary(row) for row in selected]

    def _all_profile_summaries(self, conn, *, book_id: str) -> list[dict[str, Any]]:
        return [self._profile_summary(row) for row in self.profiles_repo.list_by_book(conn, book_id=book_id)]

    def _known_profile_names(self, conn, *, book_id: str) -> set[str]:
        return {str(row["canonical_name"] or "").strip() for row in self.profiles_repo.list_by_book(conn, book_id=book_id)}

    def _profile_summary(self, row) -> dict[str, Any]:
        return {
            "canonical_name": str(row["canonical_name"] or "").strip(),
            "aliases": self._load_json_list(row, "aliases_json"),
            "profile_summary_md": str(row["profile_summary_md"] or "")[:1200],
            "personhood_evidence_summary": str(row["personhood_evidence_summary"] or ""),
            "speaking_character_status": str(row["speaking_character_status"] or "unknown"),
            "first_seen_doc_id": row["first_seen_doc_id"],
            "last_seen_doc_id": row["last_seen_doc_id"],
        }

    def _compact_update(self, update: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "canonical_name",
            "aliases",
            "recent_activity",
            "relationships",
            "speaking_character_status",
            "speaking_evidence",
            "personhood_evidence_summary",
            "activity_or_state_evidence",
            "relationship_evidence",
            "evidence_level",
        )
        return {key: update.get(key) for key in keys if key in update}

    def _source_supported_aliases(self, aliases: object, *, source_verified_names: list[str]) -> list[str]:
        source_names = set(source_verified_names)
        return [alias for alias in self._as_name_list(aliases) if alias in source_names]

    def _merge_aliases(self, raw_aliases: object, aliases_to_add: list[str]) -> list[str]:
        aliases: list[str] = []
        for alias in [*self._as_name_list(raw_aliases), *aliases_to_add]:
            if alias and alias not in aliases:
                aliases.append(alias)
        return aliases

    def _load_json_list(self, row: Any, field_name: str) -> list[Any]:
        raw = row[field_name]
        if not raw:
            return []
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return loaded if isinstance(loaded, list) else []

    def _as_name_list(self, values: object) -> list[str]:
        if not isinstance(values, list):
            return []
        result: list[str] = []
        for value in values:
            name = self._clean_name(value)
            if name and name not in result:
                result.append(name)
        return result

    @staticmethod
    def _decision_action(decision: Mapping[str, Any]) -> str:
        action = str(decision.get("action") or "").strip().lower()
        if action == "need_all_profiles":
            return "request_all_profiles"
        return action

    @staticmethod
    def _clean_name(value: object) -> str:
        return str(value or "").strip()
