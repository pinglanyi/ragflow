"""Export/import trusted administrator-managed Chunk multimodal archives."""

import argparse
import hashlib
import json
import os
import re
import uuid
import zipfile
from collections import defaultdict
from pathlib import Path

from filelock import FileLock


ENTRY = r"[0-9a-f]{64}/entries/[0-9a-f]{64}/"
ALLOWED = re.compile(r"^(?:" + ENTRY + r"(?:screenshot\.png|config\.json|success\.json|attempts/[0-9a-f]{20}/(?:request\.json|response\.json|status\.json|result\.md))|[0-9a-f]{64}/runs/[0-9a-f]{32}\.json)$")


def export_archive(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if not root.is_dir():
        raise ValueError("Archive directory does not exist")
    checksums = {}
    # 'x' refuses to overwrite a previous export.
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for tenant in sorted(root.iterdir()):
            if not tenant.is_dir() or not re.fullmatch(r"[0-9a-f]{64}", tenant.name):
                continue
            for entry in sorted((tenant / "entries").glob("*")):
                if not entry.is_dir():
                    continue
                with FileLock(str(entry / ".lock"), timeout=720):
                    for path in sorted(entry.rglob("*")):
                        name = path.relative_to(root).as_posix()
                        if not path.is_file() or not ALLOWED.fullmatch(name):
                            continue
                        data = path.read_bytes()
                        checksums[name] = hashlib.sha256(data).hexdigest()
                        bundle.writestr(name, data)
            for path in sorted((tenant / "runs").glob("*.json")):
                name = path.relative_to(root).as_posix()
                if ALLOWED.fullmatch(name):
                    data = path.read_bytes()
                    checksums[name] = hashlib.sha256(data).hexdigest()
                    bundle.writestr(name, data)
        bundle.writestr("bundle.json", json.dumps({"schema_version": 1, "sha256": checksums}, indent=2))
    return len(checksums)


def import_archive(root, source):
    root = Path(root).resolve()
    groups = defaultdict(list)
    with zipfile.ZipFile(source) as bundle:
        manifest = json.loads(bundle.read("bundle.json"))
        if manifest.get("schema_version") != 1:
            raise ValueError("Unsupported archive schema")
        checksums = manifest["sha256"]
        if len(bundle.namelist()) != len(set(bundle.namelist())) or set(bundle.namelist()) != set(checksums) | {"bundle.json"}:
            raise ValueError("Duplicate or unlisted archive members")
        # Check every name and checksum before writing anything.
        for name, checksum in checksums.items():
            if not ALLOWED.fullmatch(name):
                raise ValueError("Invalid archive member: " + name)
            target = (root / name).resolve()
            if not target.is_relative_to(root):
                raise ValueError("Archive path escapes destination")
            if hashlib.sha256(bundle.read(name)).hexdigest() != checksum:
                raise ValueError("Archive checksum mismatch: " + name)
            parts = name.split("/")
            group = "/".join(parts[:3]) if parts[1] == "entries" else "/".join(parts[:2])
            groups[group].append(name)
        written = 0
        for group, names in groups.items():
            folder = root / group
            folder.mkdir(parents=True, exist_ok=True)
            with FileLock(str(folder / ".lock"), timeout=720):
                # Publish cache pointers only after their attempt files are present.
                for name in sorted(names, key=lambda n: n.endswith("/success.json")):
                    target = root / name
                    data = bundle.read(name)
                    if target.exists():
                        if target.read_bytes() == data or name.endswith("/success.json") or "/runs/" in name:
                            continue
                        raise ValueError("Existing immutable archive differs: " + name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temp = target.with_name(uuid.uuid4().hex[:12] + ".tmp")
                    try:
                        with temp.open("xb") as stream:
                            stream.write(data)
                            stream.flush()
                            os.fsync(stream.fileno())
                        os.replace(temp, target)
                        written += 1
                    finally:
                        temp.unlink(missing_ok=True)
    return written


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["export", "import"])
    parser.add_argument("bundle", help="ZIP output (export) or input (import)")
    parser.add_argument("--root", default=os.getenv("RAGFLOW_MULTIMODAL_ARCHIVE_DIR", "data/multimodal_archive"))
    args = parser.parse_args()
    count = export_archive(args.root, args.bundle) if args.action == "export" else import_archive(args.root, args.bundle)
    print(f"{args.action}: {count} files")
