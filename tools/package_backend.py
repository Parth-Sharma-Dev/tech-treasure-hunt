"""Build a backend-only Azure ZIP from tracked application source and explicit runtime files."""

import argparse
import subprocess
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"


def build_package(output):
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
    for source in files.values():
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"Expected a regular source file: {source}")
    output = Path(output).resolve()
    if output in [source.resolve() for source in files.values()]:
        raise ValueError("Package output cannot overwrite application source.")
    if output.exists():
        raise FileExistsError(
            f"Package already exists; choose a new release filename: {output}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, source in sorted(files.items()):
            # Normalize line endings for Linux, especially shell scripts from Windows checkouts.
            archive.writestr(name, source.read_bytes().replace(b"\r\n", b"\n"))
    return len(files)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    count = build_package(args.output)
    print(f"Packaged {count} backend runtime files into {args.output}")
