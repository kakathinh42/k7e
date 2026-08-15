"""The OKF bundle — a git repo of typed Markdown pages (the v2 canonical store).

Thin, testable layer over :mod:`k7e_api.okf`: read/write/list typed pages,
maintain ``index.md`` (catalog) and ``log.md`` (operation log), and commit to
git. All knowledge lives here as portable, version-controlled Markdown; Postgres
becomes a search mirror of it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from filelock import FileLock

from k7e_api import okf
from k7e_api.okf import PAGE_DIRS, OkfPage


def _cell(text: str) -> str:
    """Make a string safe for a Markdown table cell (no pipes/newlines)."""
    return text.replace("|", "\\|").replace("\n", " ").strip()


class OkfBundle:
    """A git-backed directory of typed OKF pages."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    # -- lifecycle ---------------------------------------------------------
    def init(self) -> None:
        """Create the bundle layout and initialise git if needed."""
        for sub in PAGE_DIRS.values():
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        if not (self.root / ".git").exists():
            self._git("init", "-q")
        for name in ("index.md", "log.md"):
            f = self.root / name
            if not f.exists():
                f.write_text("" if name == "log.md" else "# Index\n", encoding="utf-8")
        gitignore = self.root / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(".okf.lock\n", encoding="utf-8")

    def lock(self, timeout: float = 60.0) -> FileLock:
        """Cross-process advisory lock for the write→index→log→commit section."""
        return FileLock(str(self.root / ".okf.lock"), timeout=timeout)

    # -- page I/O ----------------------------------------------------------
    def page_file(self, page_type: str, slug: str) -> Path:
        return self.root / okf.page_path(page_type, slug)

    def exists(self, page_type: str, slug: str) -> bool:
        return self.page_file(page_type, slug).exists()

    def read_page(self, page_type: str, slug: str) -> OkfPage | None:
        f = self.page_file(page_type, slug)
        if not f.exists():
            return None
        return okf.parse(f.read_text(encoding="utf-8"), slug=slug)

    def write_page(self, page: OkfPage) -> None:
        f = self.page_file(page.frontmatter.type, page.slug)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(okf.serialize(page), encoding="utf-8")

    def list_pages(self, page_type: str) -> list[str]:
        d = self.root / PAGE_DIRS[page_type]
        return sorted(p.stem for p in d.glob("*.md")) if d.exists() else []

    def all_slugs(self) -> dict[str, set[str]]:
        """Return ``{page_type: {slug, ...}}`` for resolve-time matching."""
        return {t: set(self.list_pages(t)) for t in PAGE_DIRS}

    # -- catalog + log -----------------------------------------------------
    def update_index(self) -> None:
        """Rebuild ``index.md`` as per-type catalog tables (slug · summary · date)."""
        lines = ["# Index", ""]
        for page_type, sub in PAGE_DIRS.items():
            slugs = self.list_pages(page_type)
            if not slugs:
                continue
            lines.append(f"## {sub.capitalize()}")
            lines.append("")
            if page_type == "source":
                lines.append("| Page | Summary | Date |")
                lines.append("|------|---------|------|")
            else:
                lines.append("| Page | Summary |")
                lines.append("|------|---------|")
            for slug in slugs:
                page = self.read_page(page_type, slug)
                summary = _cell(page.frontmatter.description if page else "")
                if page_type == "source":
                    date = _cell(
                        (page.frontmatter.updated or page.frontmatter.timestamp or "")
                        if page
                        else ""
                    )
                    lines.append(f"| [[{slug}]] | {summary} | {date} |")
                else:
                    lines.append(f"| [[{slug}]] | {summary} |")
            lines.append("")
        (self.root / "index.md").write_text("\n".join(lines), encoding="utf-8")

    def append_log(self, entry: str, *, timestamp: str) -> None:
        with (self.root / "log.md").open("a", encoding="utf-8") as fh:
            fh.write(f"- {timestamp} {entry}\n")

    def append_log_entry(
        self,
        *,
        op: str,
        subject: str,
        created: list[str],
        updated: list[str],
        timestamp: str,
    ) -> None:
        """Append a structured changelog entry to ``log.md``."""
        lines = [f"\n## [{timestamp}] {op} | {subject}\n"]
        if created:
            lines.append("- **Pages created:**")
            lines += [f"  - [[{slug}]]" for slug in created]
        if updated:
            lines.append("- **Pages updated:**")
            lines += [f"  - [[{slug}]]" for slug in updated]
        lines.append("")
        with (self.root / "log.md").open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

    # -- git ---------------------------------------------------------------
    def commit(self, message: str) -> str | None:
        """Stage everything and commit. Returns the short hash, or None if no change."""
        self._git("add", "-A")
        status = self._git("status", "--porcelain")
        if not status.strip():
            return None
        # Pin author via -c so the bundle commits without global git config.
        self._git(
            "-c",
            "user.email=okf@k7e",
            "-c",
            "user.name=k7e",
            "commit",
            "-q",
            "-m",
            message,
        )
        return self._git("rev-parse", "--short", "HEAD").strip() or None

    def _git(self, *args: str) -> str:
        """Run a git command; return stdout, or "" if git is absent/fails."""
        try:
            result = subprocess.run(
                ["git", "-C", str(self.root), *args],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout
        except (FileNotFoundError, subprocess.CalledProcessError):
            return ""
