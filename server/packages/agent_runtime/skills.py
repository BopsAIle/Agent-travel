from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: str

    def as_system_prompt(self) -> str:
        header = f"You are {self.name}."
        if self.description:
            header += f" {self.description}"
        body = (self.body or "").strip()
        return f"{header}\n\n{body}" if body else header


def _parse_frontmatter(raw: str) -> tuple[dict, str]:
    text = raw.lstrip("\ufeff")
    if not text.startswith("---"):
        return {}, text
    rest = text[3:]
    end = rest.find("\n---")
    if end == -1:
        return {}, text
    block = rest[:end].strip()
    body = rest[end + 4 :].lstrip("\n")
    meta = {}
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        meta[key.strip()] = value.strip().strip("\"'")
    return meta, body


def load_skill_file(path: Path) -> Skill:
    meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
    name = meta.get("name") or path.stem
    description = meta.get("description") or ""
    return Skill(name=name, description=description, body=body, path=str(path))


def load_skills(skills_dir: str | Path) -> List[Skill]:
    directory = Path(skills_dir)
    if not directory.is_dir():
        return []
    skills = []
    for path in sorted(directory.glob("*.md")):
        if path.name.lower().startswith("readme"):
            continue
        skills.append(load_skill_file(path))
    return skills


def load_system_prompt(skills_dir: str | Path, fallback: Optional[str] = None) -> str:
    skills = load_skills(skills_dir)
    if not skills:
        return fallback or "You are a specialist agent. Use tools. Do not invent facts."
    return "\n\n---\n\n".join(skill.as_system_prompt() for skill in skills)


def skills_payload(skills_dir: str | Path) -> dict:
    skills = load_skills(skills_dir)
    return {
        "skills": [
            {
                "name": skill.name,
                "description": skill.description,
                "path": skill.path,
                "body": skill.body,
            }
            for skill in skills
        ]
    }
