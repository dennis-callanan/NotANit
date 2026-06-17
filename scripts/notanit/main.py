import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync repo best-practice docs from recent code-review patterns. "
        "All settings live in the YAML config (see config.example.yaml); secret "
        "values come from the environment / .env via ${VAR} references.",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to the YAML config file (default: config.yaml).",
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to the .env file holding secret values (default: .env). "
        "Variables already in the environment take precedence over it.",
    )
    return parser


def main():
    args = build_parser().parse_args()

    # Load .env first so its values are visible to ${VAR} resolution in the config.
    # Exported shell vars already in the environment take precedence.
    from .dotenv import load_dotenv

    load_dotenv(args.env_file)

    # Late import so config errors surface cleanly
    from .config import load_config, load_config_file
    from .pipeline import run

    try:
        file_cfg = load_config_file(args.config)
        cfg = load_config(file_cfg=file_cfg)
    except (EnvironmentError, ValueError, FileNotFoundError, RuntimeError) as e:
        print(f"[error] {e}", file=sys.stderr)
        sys.exit(1)

    repo_root = Path(cfg.pipeline.repo_root).resolve()

    try:
        result = run(cfg, repo_root)
    except Exception as e:
        print(f"\n[error] Pipeline failed: {e}", file=sys.stderr)
        sys.exit(1)

    if not result.applied_changes:
        print("\n✓ No changes needed. Docs are likely up to date.")
        sys.exit(0)

    print(f"\n✓ Done. Applied {len(result.applied_changes)} change(s):\n")
    for c in result.applied_changes:
        print(f"  • {c['target_file']} → {c['target_section']}")
        summary = c.get("summary")
        if summary:
            print(f"    {summary}")
    print("\nReview the edits with `git diff` before committing.")


if __name__ == "__main__":
    main()
