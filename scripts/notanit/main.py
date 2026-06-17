import sys
from pathlib import Path

# Fixed locations, relative to the working directory. All settings live in the
# YAML config; secret values come from the environment / .env via ${VAR} refs.
CONFIG_PATH = "config.yaml"
ENV_PATH = ".env"


def main():
    # Load .env first so its values are visible to ${VAR} resolution in the config.
    # Exported shell vars already in the environment take precedence.
    from .dotenv import load_dotenv

    load_dotenv(ENV_PATH)

    # Late import so config errors surface cleanly
    from .config import load_config, load_config_file
    from .pipeline import run

    try:
        file_cfg = load_config_file(CONFIG_PATH)
        cfg = load_config(file_cfg=file_cfg)
    except (EnvironmentError, ValueError, FileNotFoundError, RuntimeError) as e:
        print(f"[error] {e}", file=sys.stderr)
        sys.exit(1)

    target_root = Path(cfg.pipeline.target_root).resolve()

    try:
        result = run(cfg, target_root)
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
