"""Build an Azure application ZIP, optionally including the compiled React frontend."""

import argparse
import hashlib
import json
import re
import subprocess
import zipfile
from html.parser import HTMLParser
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"


class AssetReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("src"):
            self.urls.append(attrs["src"])
        if tag == "link" and attrs.get("rel") in {"stylesheet", "modulepreload"}:
            self.urls.append(attrs.get("href", ""))


def frontend_files(dist):
    dist = Path(dist).resolve()
    manifest = json.loads((dist / ".vite/manifest.json").read_text(encoding="utf-8"))
    entry = manifest.get("index.html", {})
    if not entry.get("isEntry") or not entry.get("file"):
        raise ValueError("Build the React frontend with npm run build before packaging.")
    files = {}
    asset_pattern = (
        r"assets/[^/]+-[A-Za-z0-9_-]{8,}\.(?:js|css|svg|png|jpe?g|webp|gif|ico|avif|woff2?|ttf|otf)"
    )
    for source in dist.rglob("*"):
        name = source.relative_to(dist).as_posix()
        if source.is_symlink():
            raise ValueError(f"Frontend build cannot contain symlinks: {name}")
        if source.is_dir() or name == ".vite/manifest.json":
            continue
        if name != "index.html" and not re.fullmatch(asset_pattern, name):
            raise ValueError(f"Unexpected frontend build file (not a public asset): {name}")
        files[f"frontend_dist/{name}"] = source
    parser = AssetReferences()
    parser.feed((dist / "index.html").read_text(encoding="utf-8"))
    if f"/static/frontend/{entry['file']}" not in parser.urls:
        raise ValueError("The frontend HTML does not reference the Vite entry bundle.")
    for url in parser.urls:
        if (
            not url.startswith("/static/frontend/assets/")
            or f"frontend_dist/{url.removeprefix('/static/frontend/')}" not in files
        ):
            raise ValueError(f"Missing or incorrectly configured frontend asset: {url}")
    for chunk in manifest.values():
        for name in [chunk["file"], *chunk.get("css", []), *chunk.get("assets", [])]:
            if f"frontend_dist/{name}" not in files:
                raise ValueError(f"Frontend manifest references a missing asset: {name}")
    return files


def build_package(output, frontend_dist=None):
    source_list = (
        subprocess.run(
            ["git", "ls-files", "-z", "--", "backend/config", "backend/competition"],
            cwd=REPO,
            check=True,
            capture_output=True,
        )
        .stdout.decode()
        .split("\0")
    )
    files = {
        Path(name).relative_to("backend").as_posix(): REPO / name
        for name in source_list
        if name and Path(name).suffix == ".py"
    }
    files.update(
        {
            "manage.py": BACKEND / "manage.py",
            "gunicorn.conf.py": BACKEND / "gunicorn.conf.py",
            "startup.sh": BACKEND / "startup.sh",
            "requirements.txt": BACKEND / "requirements-production.txt",
        }
    )
    if frontend_dist is not None:
        files.update(frontend_files(frontend_dist))
    for source in files.values():
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"Expected a regular source file: {source}")
    output = Path(output).resolve()
    if output in [source.resolve() for source in files.values()]:
        raise ValueError("Package output cannot overwrite application source.")
    if output.exists():
        raise FileExistsError(f"Package already exists; choose a new release filename: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, source in sorted(files.items()):
            # Normalize line endings for Linux, especially shell scripts from Windows checkouts.
            content = source.read_bytes()
            if not name.startswith("frontend_dist/"):
                content = content.replace(b"\r\n", b"\n")
            archive.writestr(name, content)
    return len(files)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--frontend-dist", type=Path, help="Include a validated Vite dist directory"
    )
    args = parser.parse_args()
    count = build_package(args.output, args.frontend_dist)
    print(f"Packaged {count} runtime files into {args.output}")
    with args.output.open("rb") as stream:
        print(f"SHA256: {hashlib.file_digest(stream, 'sha256').hexdigest()}")
