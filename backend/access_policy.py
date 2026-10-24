from pathlib import Path


ALLOWED_ASSET_SUFFIXES = {".html", ".js", ".css", ".svg", ".png", ".ico", ".woff2"}


class AccessDenied(Exception):
    pass


class AccessPolicy:
    """Restrict application-managed reads to built frontend assets."""

    def __init__(self, root: str | Path, allowed_suffixes: set[str] | None = None):
        self.root = Path(root).resolve()
        self.allowed_suffixes = {
            suffix.lower() for suffix in (allowed_suffixes or ALLOWED_ASSET_SUFFIXES)
        }

    def asset(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root) or path.suffix.lower() not in self.allowed_suffixes or not path.is_file():
            raise AccessDenied from None
        return path
