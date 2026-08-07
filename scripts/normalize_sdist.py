#!/usr/bin/env python3
"""Normalize source-distribution metadata for reproducible release candidates."""

from __future__ import annotations

import argparse
import copy
import gzip
import io
import os
import tarfile
import tempfile
from pathlib import Path, PurePosixPath


def normalize(path: Path, epoch: int) -> None:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"sdist must be a regular file: {path}")
    entries: list[tuple[tarfile.TarInfo, bytes | None]] = []
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            pure = PurePosixPath(member.name)
            if pure.is_absolute() or ".." in pure.parts:
                raise ValueError(f"unsafe sdist entry: {member.name}")
            stream = archive.extractfile(member) if member.isfile() else None
            entries.append((member, stream.read() if stream else None))

    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temp_path = Path(temp_name)
    try:
        with temp_path.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch) as compressed:
                with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                    for original, data in sorted(entries, key=lambda item: item[0].name):
                        member = copy.copy(original)
                        member.uid = 0
                        member.gid = 0
                        member.uname = ""
                        member.gname = ""
                        member.mtime = epoch
                        member.pax_headers = {
                            key: value for key, value in member.pax_headers.items()
                            if key not in {"atime", "ctime", "mtime"}
                        }
                        if data is None:
                            archive.addfile(member)
                        else:
                            archive.addfile(member, io.BytesIO(data))
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sdist", type=Path)
    parser.add_argument("--epoch", type=int, default=None)
    args = parser.parse_args()
    epoch = args.epoch if args.epoch is not None else int(os.environ.get("SOURCE_DATE_EPOCH", "0"))
    normalize(args.sdist, epoch)
    print(f"sdist=normalized file={args.sdist} epoch={epoch}")


if __name__ == "__main__":
    main()
