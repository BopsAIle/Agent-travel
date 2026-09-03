from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy.orm import Session

from conversation import ChatSession
from memory.episodic import retrieve_episodes, upsert_episode
from memory.semantic import (
    add_facts,
    apply_profile_updates,
    get_or_create_profile,
    profile_as_dict,
    profile_as_text,
    retrieve_facts,
)
from memory.working import save_session
from schemas import MemoryExtraction


@dataclass
class MemoryBundle:
    profile: dict = field(default_factory=dict)
    profile_text: str = ""
    facts: List[str] = field(default_factory=list)
    episodes: List[dict] = field(default_factory=list)

    def as_prompt(self) -> str:
        blocks = []
        if self.profile_text:
            blocks.append(f"Long-term traveler profile:\n{self.profile_text}")
        if self.facts:
            joined = "\n".join(f"- {item}" for item in self.facts)
            blocks.append(f"Known durable facts about this traveler:\n{joined}")
        if self.episodes:
            lines = []
            for item in self.episodes:
                dest = item.get("destination") or "a destination"
                dates = " ".join(
                    part for part in [item.get("start_date") or "", item.get("end_date") or ""] if part
                )
                lines.append(f"- {dest} {dates}: {item.get('summary')}")
            blocks.append("Relevant past trips (episodic memory):\n" + "\n".join(lines))
        return "\n\n".join(blocks)

    def as_planner_context(self) -> str:
        parts = []
        if self.profile_text:
            parts.append(self.profile_text.replace("\n", " "))
        if self.facts:
            parts.append("Facts: " + "; ".join(self.facts))
        if self.episodes:
            dests = [item.get("destination") for item in self.episodes if item.get("destination")]
            if dests:
                parts.append("Previously visited: " + ", ".join(dests))
        return " ".join(parts)


def retrieve_memory(db: Session, user_id, user_message: str) -> MemoryBundle:
    profile = get_or_create_profile(db, user_id)
    facts = retrieve_facts(db, user_id, user_message, limit=5)
    episodes = retrieve_episodes(db, user_id, user_message, limit=3)
    return MemoryBundle(
        profile=profile_as_dict(profile),
        profile_text=profile_as_text(profile),
        facts=facts,
        episodes=episodes,
    )


def persist_working(db: Session, session: ChatSession) -> None:
    save_session(db, session)


def write_semantic_from_turn(
    db: Session,
    session: ChatSession,
    extraction: Optional[MemoryExtraction],
) -> None:
    if not extraction:
        return
    updates = extraction.profile.model_dump(exclude_none=True) if extraction.profile else {}
    if updates:
        apply_profile_updates(db, session.user_id, updates)
    if extraction.facts:
        add_facts(db, session.user_id, extraction.facts, source_session_id=session.session_id)


def write_episode_from_plan(db: Session, session: ChatSession) -> None:
    upsert_episode(db, session)
