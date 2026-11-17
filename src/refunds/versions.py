"""Rule set versioning: every publish is an immutable file; rules.yaml is the live copy.
Rollback = publish an old version's rules again as a new version (history is never rewritten)."""

from datetime import UTC, datetime
from pathlib import Path

from refunds.config import ROOT
from refunds.rules import RuleSet, dump_ruleset, load_ruleset

LIVE = ROOT / "rules" / "rules.yaml"
VERSIONS = ROOT / "rules" / "versions"


def _path(versions_dir: Path, n: int) -> Path:
    return versions_dir / f"v{n:03d}.yaml"


def list_versions(versions_dir: Path = VERSIONS) -> list[RuleSet]:
    return sorted((load_ruleset(p) for p in versions_dir.glob("v*.yaml")), key=lambda r: r.version)


def ensure_seeded(live: Path = LIVE, versions_dir: Path = VERSIONS) -> None:
    versions_dir.mkdir(parents=True, exist_ok=True)
    rs = load_ruleset(live)
    if not _path(versions_dir, rs.version).exists():
        _path(versions_dir, rs.version).write_text(dump_ruleset(rs))


def publish(draft: RuleSet, author: str, change_note: str, live: Path = LIVE, versions_dir: Path = VERSIONS) -> RuleSet:
    ensure_seeded(live, versions_dir)
    latest = max(r.version for r in list_versions(versions_dir))
    new = draft.model_copy(update={"version": latest + 1, "author": author, "change_note": change_note,
                                   "created_at": datetime.now(UTC)})  # fmt: skip
    new = RuleSet.model_validate(new.model_dump(by_alias=True))  # re-validate the whole set
    _path(versions_dir, new.version).write_text(dump_ruleset(new))
    live.write_text(dump_ruleset(new))
    return new


def rollback(to_version: int, author: str, live: Path = LIVE, versions_dir: Path = VERSIONS) -> RuleSet:
    old = load_ruleset(_path(versions_dir, to_version))
    return publish(old, author, f"Rollback to v{to_version}", live, versions_dir)
