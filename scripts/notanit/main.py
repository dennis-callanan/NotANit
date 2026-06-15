import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync repo best-practice docs from recent code-review patterns."
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to a JSON or YAML config file (see config.example.yaml).",
    )
    parser.add_argument(
        "--project",
        default=None,
        help='Project path, e.g. "mygroup/myrepo" (GitLab) or "owner/repo" (GitHub).',
    )
    parser.add_argument(
        "--scm",
        choices=["gitlab", "github"],
        default=None,
        help="Source-control provider (default: gitlab, or SCM_PROVIDER).",
    )
    parser.add_argument(
        "--scm-url",
        default=None,
        help="API base URL for the SCM host (defaults per provider).",
    )
    parser.add_argument(
        "--provider",
        choices=["anthropic", "bedrock"],
        default=None,
        help="LLM provider (default: anthropic, or LLM_PROVIDER).",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="LLM model id (defaults per provider, or LLM_MODEL_ID).",
    )
    parser.add_argument(
        "--weeks",
        type=int,
        default=None,
        help="How many weeks of MR/PR history to analyse (default: 8).",
    )
    parser.add_argument(
        "--target-files",
        nargs="+",
        default=None,
        help="Repo-relative paths of docs to update (default: AGENTS.md).",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory to write output files (default: proposals/).",
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Path to the repository root (default: current directory).",
    )
    parser.add_argument(
        "--min-mr-occurrences",
        type=int,
        default=None,
        help="Minimum MRs/PRs a theme must appear in to be considered (default: 3).",
    )
    parser.add_argument(
        "--max-proposals",
        type=int,
        default=None,
        help="Maximum number of proposed changes per run (default: 3).",
    )
    return parser


def main():
    args = build_parser().parse_args()

    # Late import so config errors surface cleanly
    from .config import load_config, load_config_file
    from .pipeline import run

    # Only forward flags the user actually set; None means "fall back".
    cli = {
        "project": args.project,
        "scm": args.scm,
        "scm_url": args.scm_url,
        "provider": args.provider,
        "model": args.model,
        "weeks": args.weeks,
        "target_files": args.target_files,
        "output_dir": args.output_dir,
        "min_mr_occurrences": args.min_mr_occurrences,
        "max_proposals": args.max_proposals,
    }

    try:
        file_cfg = load_config_file(args.config)
        cfg = load_config(cli=cli, file_cfg=file_cfg)
    except (EnvironmentError, ValueError, FileNotFoundError, RuntimeError) as e:
        print(f"[error] {e}", file=sys.stderr)
        sys.exit(1)

    repo_root = Path(args.repo_root).resolve()
    output_dir = repo_root / cfg.pipeline.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        result = run(cfg, repo_root)
    except Exception as e:
        print(f"\n[error] Pipeline failed: {e}", file=sys.stderr)
        sys.exit(1)

    if not result.proposals:
        print("\n✓ No proposals generated. Docs are likely up to date.")
        sys.exit(0)

    # Write outputs
    datestamp = datetime.now().strftime("%Y-%m-%d")

    evidence_path = output_dir / f"review-evidence-{datestamp}.md"
    patch_path = output_dir / f"best-practices-{datestamp}.patch"
    proposals_path = output_dir / f"proposals-{datestamp}.json"

    # Evidence report
    with evidence_path.open("w", encoding="utf-8") as f:
        f.write(f"# Review Evidence Report — {datestamp}\n\n")
        f.write(
            f"Generated from {cfg.pipeline.weeks} weeks of history "
            f"for `{cfg.scm.project_path}`.\n\n"
        )
        f.write("## Proposed Changes\n\n")
        for i, p in enumerate(result.proposals, 1):
            f.write(f"### {i}. `{p['target_file']}` → {p['target_section']}\n\n")
            f.write(f"**Rationale:** {p['rationale']}\n\n")
            f.write(f"**Evidence:** {p.get('evidence_summary', 'N/A')}\n\n")
            f.write(f"**Confidence:** {p.get('confidence', 'N/A')}\n\n")
            f.write(f"**Proposed text:**\n\n```markdown\n{p['proposed_text']}\n```\n\n")
        f.write("## Recurring Themes Analysed\n\n")
        for s in result.cluster_summaries:
            f.write(
                f"- **{s['theme']}**: {s['mr_count']} MRs, "
                f"{s['comment_count']} comments, "
                f"{s['reviewer_count']} reviewers\n"
            )

    # Patch file
    with patch_path.open("w", encoding="utf-8") as f:
        f.write(result.patch)

    # Raw proposals JSON
    with proposals_path.open("w", encoding="utf-8") as f:
        json.dump({"proposals": result.proposals}, f, indent=2)

    # Summary to stdout
    print(f"\n✓ Done. {len(result.proposals)} proposal(s) generated.\n")
    print(f"  Evidence report : {evidence_path}")
    print(f"  Patch file      : {patch_path}")
    print(f"  Proposals JSON  : {proposals_path}")
    print("\nReview the patch and evidence report before merging any changes.")


if __name__ == "__main__":
    main()
