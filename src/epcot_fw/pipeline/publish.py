"""One step from a Studio changeset to a commit that is ready to go live.

`docs/WORKFLOW.md` used to be ten commands between pressing Export and
seeing a change on the published site - dry-run, apply, promote, three
rebuilds in a fixed order, add, commit, push, merge. Each was a place to
skip a step or run one from the wrong directory. This is that list as one
function, with the checks a careful person makes by eye written down as
guards that run every time.

Two paths, chosen by the changeset's own `festival`:

- **A festival that lives in files** (Arts, Flower & Garden, Holidays -
  see epcot_fw.festival_files). Nothing here needs the database, so it runs
  anywhere, including a GitHub Action. The changeset is first applied to a
  throwaway copy of the festival, the guards compare before with after, and
  only then is anything real written: the festival's files, the client feed
  (epcot_fw.client_feed) and the Studio's embedded copy of the festival.

- **The database festival** (Food & Wine). Resolving a correction means
  staging it and re-resolving in Postgres, so this runs only on the machine
  with the database. The guards run on the feed before and after.

Either way the result is a `PublishReport`: what changed, what was refused
and why, and which paths to commit. A refusal writes nothing on the file
path. Committing and pushing are separate (`commit`), so a caller can run
its own tests between the two - which is what the publish workflow does.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from epcot_fw import client_feed, festival_files
from epcot_fw.pipeline.studio import ApplyReport, apply_changeset, load_changeset

REPO_ROOT = Path(__file__).resolve().parents[3]

FESTIVAL_NAMES = {
    "festival-of-the-arts": "Arts",
    "flower-and-garden": "Flower & Garden",
    festival_files.DATABASE_FESTIVAL_KEY: "Food & Wine",
    "festival-of-the-holidays": "Holidays",
}

# How many rows the database festival may lose in one publish beyond what
# the changeset itself deletes. A file festival gets none: its files change
# only through changesets, so anything else vanishing is a bug. The database
# festival also carries whatever the daily crawl has retired since the last
# export, so it gets a small allowance - and a publish that would drop more
# than that is far more likely a broken resolve than a real menu change.
DATABASE_LOSS_FLOOR = 5
DATABASE_LOSS_SHARE = 0.10


@dataclass
class PublishReport:
    festival: str
    changeset: str
    dry_run: bool = False
    dishes: list[str] = field(default_factory=list)
    booths: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    photos: list[str] = field(default_factory=list)
    # Why this publish was refused. Empty means it may go live.
    refusals: list[str] = field(default_factory=list)
    # Repo-relative paths a commit of this publish should stage.
    paths: list[str] = field(default_factory=list)
    written: bool = False
    commit: str | None = None
    pushed: bool = False

    @property
    def ok(self) -> bool:
        return not self.refusals

    @property
    def total(self) -> int:
        return len(self.dishes) + len(self.booths)

    @property
    def festival_name(self) -> str:
        return FESTIVAL_NAMES.get(self.festival, self.festival)

    def headline(self) -> str:
        parts = []
        if self.dishes:
            parts.append(f"{len(self.dishes)} dish{'es' if len(self.dishes) != 1 else ''}")
        if self.booths:
            parts.append(f"{len(self.booths)} booth{'s' if len(self.booths) != 1 else ''}")
        if self.photos:
            parts.append(f"{len(self.photos)} photo{'s' if len(self.photos) != 1 else ''}")
        return f"{self.festival_name}: " + (", ".join(parts) or "nothing to change")

    def commit_message(self) -> str:
        lines = [f"Studio publish - {self.headline()}", ""]
        for label in (self.dishes + self.booths)[:20]:
            mark = "+" if label in self.added else "-" if label in self.deleted else "~"
            lines.append(f"{mark} {label}")
        if self.total > 20:
            lines.append(f"... and {self.total - 20} more")
        lines += ["", f"Changeset: {self.changeset}"]
        return "\n".join(lines) + "\n"

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "ok": self.ok, "headline": self.headline()}


# --------------------------------------------------------------------------
# guards
# --------------------------------------------------------------------------


@dataclass
class Inventory:
    """What a festival holds, reduced to what the guards compare."""

    booths: dict[str, str] = field(default_factory=dict)  # public_id -> name
    items: dict[str, tuple[str, str]] = field(default_factory=dict)  # public_id -> (booth, name)
    problems: list[str] = field(default_factory=list)

    def _add(self, bucket: dict, public_id: Any, value: Any, label: str) -> None:
        if not public_id:
            self.problems.append(f"{label} has no public_id")
        elif public_id in bucket:
            self.problems.append(f"{label} shares its public_id with another row")
        else:
            bucket[public_id] = value


def inventory_of_festival_snapshot(snapshot: dict[str, Any]) -> Inventory:
    """From the shape `festival_files.build_snapshot` and the export write."""
    inventory = Inventory()
    for booth in snapshot.get("booths") or []:
        inventory._add(inventory.booths, booth.get("public_id"), booth["name"], f"booth {booth['name']}")
        for item in booth.get("items") or []:
            inventory._add(
                inventory.items, item.get("public_id"), (booth["name"], item["name"]),
                f"dish {booth['name']} / {item['name']}",
            )
    return inventory


def inventory_of_client_snapshot(payload: dict[str, Any]) -> Inventory:
    """From the client contract (`docs/v1/snapshot.json`)."""
    inventory = Inventory()
    names: dict[Any, str] = {}
    for booth in payload.get("booths") or []:
        names[booth.get("id")] = booth["canonical_name"]
        inventory._add(
            inventory.booths, booth.get("public_id"), booth["canonical_name"],
            f"booth {booth['canonical_name']}",
        )
    for item in payload.get("menu_items") or []:
        booth_name = names.get(item.get("booth_id"))
        label = f"dish {booth_name or '?'} / {item['canonical_name']}"
        if booth_name is None:
            inventory.problems.append(f"{label} belongs to a booth that is not in the feed")
            continue
        inventory._add(inventory.items, item.get("public_id"), (booth_name, item["canonical_name"]), label)
    return inventory


def _deletions(payload: dict[str, Any]) -> tuple[set[str], set[tuple[str, str]]]:
    booths = {
        (b.get("name") or "").strip() for b in payload.get("booths") or [] if b.get("is_active") is False
    }
    items = {
        ((i.get("booth_name") or "").strip(), (i.get("name") or "").strip())
        for i in payload.get("menu_items") or []
        if i.get("is_active") is False
    }
    return booths, items


def _listed(labels: list[str], limit: int = 8) -> str:
    shown = ", ".join(labels[:limit])
    return shown + (f", and {len(labels) - limit} more" if len(labels) > limit else "")


def check_guards(
    before: Inventory,
    after: Inventory,
    payload: dict[str, Any],
    skipped: list[str],
    *,
    loss_floor: int = 0,
    loss_share: float = 0.0,
) -> list[str]:
    """Why this publish must not go live. Empty when it may.

    - Anything the changeset asked for that could not be applied. A skipped
      entry is an edit somebody made that would silently not happen.
    - A booth or dish that was there before and is gone after, unless the
      changeset deleted it (or deleted the booth it was in). `loss_floor`
      and `loss_share` allow the database festival the few rows a crawl may
      have retired in the meantime.
    - Rows that cannot be told apart: a missing or repeated `public_id`, or
      a dish whose booth is not in the feed.
    - A festival left with nothing in it.
    """
    refusals = [f"could not apply: {line}" for line in skipped]
    refusals += [f"after publishing, {problem}" for problem in after.problems]

    deleted_booths, deleted_items = _deletions(payload)

    lost_booths = sorted(
        name for public_id, name in before.booths.items()
        if public_id not in after.booths and name not in deleted_booths
    )
    allowed = max(loss_floor, int(len(before.booths) * loss_share))
    if len(lost_booths) > allowed:
        refusals.append(
            f"{len(lost_booths)} booth(s) would disappear that this changeset does not delete: "
            + _listed(lost_booths)
        )

    lost_items = sorted(
        f"{booth} / {name}" for public_id, (booth, name) in before.items.items()
        if public_id not in after.items
        and (booth, name) not in deleted_items
        and booth not in deleted_booths
    )
    allowed = max(loss_floor, int(len(before.items) * loss_share))
    if len(lost_items) > allowed:
        refusals.append(
            f"{len(lost_items)} dish(es) would disappear that this changeset does not delete: "
            + _listed(lost_items)
        )

    if before.booths and not after.booths:
        refusals.append("the festival would be left with no booths at all")
    return refusals


# --------------------------------------------------------------------------
# the two paths
# --------------------------------------------------------------------------


def _report(path: Path, festival: str, applied: ApplyReport, *, dry_run: bool) -> PublishReport:
    return PublishReport(
        festival=festival,
        changeset=path.name,
        dry_run=dry_run,
        dishes=list(applied.menu_items),
        booths=list(applied.booths),
        added=list(applied.added),
        deleted=list(applied.deleted),
        photos=list(applied.photos),
    )


def _build_studio():
    """tools/data_ledger/build_studio.py, which is a script directory rather
    than a package, imported the way its own tests import it."""
    tool_dir = str(REPO_ROOT / "tools" / "data_ledger")
    if tool_dir not in sys.path:
        sys.path.insert(0, tool_dir)
    import build_studio

    return build_studio


def _publish_file_festival(
    path: Path, payload: dict[str, Any], key: str, *, repo: Path, base_url: str, dry_run: bool
) -> PublishReport:
    root = repo / "data" / "festivals"
    docs = repo / "docs"
    before = inventory_of_festival_snapshot(festival_files.build_snapshot(key, root))

    # A rehearsal on a copy: the real files are not touched until the guards
    # have seen what applying this changeset would leave behind.
    with tempfile.TemporaryDirectory() as tmp:
        trial_root = Path(tmp) / "festivals"
        shutil.copytree(festival_files.festival_dir(key, root), trial_root / key)
        applied = apply_changeset(
            path, publish_dir=Path(tmp) / "dish-photos", base_url=base_url, festivals_root=trial_root
        )
        after = inventory_of_festival_snapshot(festival_files.build_snapshot(key, trial_root))
        feed = inventory_of_client_snapshot(client_feed.build_file_snapshot(key, trial_root))

    report = _report(path, key, applied, dry_run=dry_run)
    report.refusals = check_guards(before, after, payload, applied.skipped)
    report.refusals += [f"in the app's feed, {problem}" for problem in feed.problems]
    if dry_run or not report.ok or not report.total:
        return report

    apply_changeset(path, publish_dir=docs / "dish-photos", base_url=base_url, festivals_root=root)
    client_feed.write_feed(docs / "v1", root)

    studio = docs / "studio.html"
    festivals = {k: festival_files.build_snapshot(k, root) for k in festival_files.available(root)}
    studio.write_text(_build_studio().embed_festivals(studio.read_text(), festivals))

    report.written = True
    report.paths = [f"data/festivals/{key}", "docs/v1/festivals.json", "docs/v1/festivals", "docs/studio.html"]
    if report.photos:
        report.paths.append("docs/dish-photos")
    return report


def resolve_and_rebuild(repo: Path) -> None:
    """Steps 3-5 of the old workflow for the database festival: stage and
    resolve the curated files, let this season's photos win, and rebuild
    every page and the feed. Needs the database."""
    from epcot_fw.db.base import SessionLocal
    from epcot_fw.festival import require_current_festival
    from epcot_fw.pipeline.manual import stage_manual_overrides
    from epcot_fw.pipeline.photo_promotion import promote_current_season_photos
    from epcot_fw.pipeline.resolve_pipeline import run_resolve

    manual = repo / "data" / "manual"
    with SessionLocal() as session:
        stage_manual_overrides(
            session, path=manual / "booth_locations.json", items_path=manual / "menu_items.json"
        )
        run_resolve(session, festival_id=require_current_festival(session).id)
        promote_current_season_photos(session, path=manual / "menu_items.json")
        session.commit()

    # In this order, and none optional: export writes a snapshot with no
    # image data, fetch_images inlines the photos, build renders the pages.
    for script in ("export_snapshot.py", "fetch_images.py", "build_artifact.py"):
        subprocess.run([sys.executable, str(repo / "tools" / "data_ledger" / script)], cwd=repo, check=True)


def _publish_database_festival(
    path: Path,
    payload: dict[str, Any],
    *,
    repo: Path,
    base_url: str,
    dry_run: bool,
    rebuild: Callable[[Path], None],
) -> PublishReport:
    key = festival_files.DATABASE_FESTIVAL_KEY
    manual = repo / "data" / "manual"
    docs = repo / "docs"
    paths = {"items_path": manual / "menu_items.json", "booths_path": manual / "booth_locations.json"}

    rehearsal = apply_changeset(path, publish_dir=docs / "dish-photos", base_url=base_url, dry_run=True, **paths)
    report = _report(path, key, rehearsal, dry_run=dry_run)
    report.refusals = [f"could not apply: {line}" for line in rehearsal.skipped]
    if dry_run or not report.ok or not report.total:
        return report

    feed_path = docs / "v1" / "snapshot.json"
    before = inventory_of_client_snapshot(json.loads(feed_path.read_text()))
    apply_changeset(path, publish_dir=docs / "dish-photos", base_url=base_url, **paths)
    rebuild(repo)
    after = inventory_of_client_snapshot(json.loads(feed_path.read_text()))

    report.written = True
    report.refusals = check_guards(
        before, after, payload, [], loss_floor=DATABASE_LOSS_FLOOR, loss_share=DATABASE_LOSS_SHARE
    )
    report.paths = ["data/manual", "docs", "tools/data_ledger/ledger_history.json"]
    return report


def publish_changeset(
    path: Path,
    *,
    base_url: str,
    repo: Path = REPO_ROOT,
    dry_run: bool = False,
    rebuild: Callable[[Path], None] = resolve_and_rebuild,
) -> PublishReport:
    """Apply a changeset and rebuild everything it affects, behind the guards.

    Raises `ChangesetError` for a file that is not a changeset this build can
    apply at all. Everything short of that comes back as a report whose
    `refusals` say why it must not go live.
    """
    payload = load_changeset(path)
    festival = payload.get("festival") or festival_files.DATABASE_FESTIVAL_KEY
    if festival == festival_files.DATABASE_FESTIVAL_KEY:
        return _publish_database_festival(
            path, payload, repo=repo, base_url=base_url, dry_run=dry_run, rebuild=rebuild
        )
    # An unknown key is refused inside apply_changeset, with its own message.
    if festival not in festival_files.FILE_BACKED:
        apply_changeset(path, publish_dir=repo / "docs" / "dish-photos", base_url=base_url, dry_run=True)
    return _publish_file_festival(path, payload, festival, repo=repo, base_url=base_url, dry_run=dry_run)


# --------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return done.stdout.strip()


def commit(report: PublishReport, *, repo: Path = REPO_ROOT, push: bool = False) -> PublishReport:
    """Commit what a publish wrote, on the current branch, and optionally push it.

    Stages only the paths the publish names, never `git add -A`: the repo
    root can hold working folders that are nobody's to commit. A publish
    that changed nothing (the same changeset applied twice) leaves no commit.
    """
    if not report.written or not report.ok:
        return report
    existing = [p for p in report.paths if (repo / p).exists()]
    _git(repo, "add", "--", *existing)
    if not _git(repo, "diff", "--cached", "--name-only"):
        return report
    _git(repo, "commit", "-q", "-m", report.commit_message())
    report.commit = _git(repo, "rev-parse", "HEAD")
    if push:
        _git(repo, "push", "-q", "origin", "HEAD")
        report.pushed = True
    return report
