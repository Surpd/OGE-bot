"""Compress the raw table reproducibly and verify every byte before optional cleanup."""

import argparse
import gzip
import hashlib
import shutil
from pathlib import Path

from simulate import HERE


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--dir", type=Path, default=HERE / "results")
    cli.add_argument("--remove-csv", action="store_true")
    args = cli.parse_args()
    raw = args.dir / "runs.csv"
    compressed = raw.with_suffix(".csv.gz")
    with raw.open("rb") as src, compressed.open("wb") as dest:
        with gzip.GzipFile(filename="", fileobj=dest, mode="wb", mtime=0) as archive:
            shutil.copyfileobj(src, archive)
    with gzip.open(compressed, "rb") as src:
        digest = hashlib.file_digest(src, "sha256").hexdigest()
    if digest != hashlib.sha256(raw.read_bytes()).hexdigest():
        raise RuntimeError("gzip round trip failed")
    print(f"raw SHA-256 {digest}")
    if args.remove_csv:
        raw.unlink()


if __name__ == "__main__":
    main()
