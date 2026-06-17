from pathlib import Path


def load_docs(target_files: list[str], target_root: Path) -> dict[str, str]:
    """
    Returns a dict of {relative_path: content} for each target file.
    Skips files that don't exist (with a warning).
    """
    docs: dict[str, str] = {}

    for rel_path in target_files:
        full_path = target_root / rel_path
        if not full_path.exists():
            print(f"  [warn] target file not found, skipping: {rel_path}")
            continue
        docs[rel_path] = full_path.read_text(encoding="utf-8")
        print(f"  [docs] loaded {rel_path} ({len(docs[rel_path])} chars)")

    return docs
