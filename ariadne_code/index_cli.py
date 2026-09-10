"""`ariadne index` - build or refresh a project's semantic index."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="ariadne index",
        description="Index a project for semantic code search. Runs locally; no API key needed.",
    )
    parser.add_argument("path", nargs="?", default=".", help="Project folder (default: current)")
    parser.add_argument("--rebuild", action="store_true", help="Discard the existing index first")
    parser.add_argument("-q", "--quiet", action="store_true", help="Only print the summary")
    args = parser.parse_args()

    from .rag import Embedder, EmbedderUnavailable, build_index, index_path, open_store

    root = Path(args.path).expanduser().resolve()
    if not root.is_dir():
        print(f"不是目录：{root}", file=sys.stderr)
        return 1

    if args.rebuild:
        db = index_path(root)
        if db.exists():
            db.unlink()
            print(f"已删除旧索引 {db}")

    try:
        embedder = Embedder()
        # load the model up front so a download failure reports before the walk
        _ = embedder.model
    except EmbedderUnavailable as e:
        print(f"无法加载嵌入模型：\n{e}", file=sys.stderr)
        return 2

    print(f"索引 {root}")
    print(f"模型 {embedder.model_name}（本地推理，不消耗 API 额度）")

    store = open_store(root, embedder)
    started = time.time()

    def progress(rel, stats):
        if not args.quiet:
            print(f"  [{stats.files_indexed:>4}] {rel}")

    try:
        stats = build_index(root, embedder, store, on_progress=progress)
    finally:
        store.close()

    print(f"\n{stats.summary()}")
    print(f"耗时 {time.time() - started:.1f}s，索引位于 {index_path(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
