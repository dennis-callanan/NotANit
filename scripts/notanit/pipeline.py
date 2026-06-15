import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime

from .config import Config
from .scm import ReviewComment, build_scm_client
from .doc_loader import load_docs
from .llm_client import call_llm


# ---------------------------------------------------------------------------
# Simple lexical clustering — groups comments by shared keywords
# ---------------------------------------------------------------------------

def _cluster_comments(
    comments: list[ReviewComment],
    theme_keywords: dict[str, list[str]],
) -> dict[str, list[ReviewComment]]:
    clusters: dict[str, list[ReviewComment]] = defaultdict(list)

    for comment in comments:
        lowered = comment.body.lower()
        matched = False
        for theme, keywords in theme_keywords.items():
            if any(kw in lowered for kw in keywords):
                clusters[theme].append(comment)
                matched = True
                break
        if not matched:
            clusters["other"].append(comment)

    return dict(clusters)


def _summarise_clusters(
    clusters: dict[str, list[ReviewComment]],
    min_mr_occurrences: int,
) -> list[dict]:
    """
    For each cluster, count unique MRs and pick up to 5 representative comments.
    Drop clusters that don't meet the minimum occurrence threshold.
    """
    summaries = []

    for theme, comments in clusters.items():
        mr_ids = {c.mr_iid for c in comments}
        if len(mr_ids) < min_mr_occurrences:
            continue

        authors = {c.author for c in comments}
        # Pick the most representative: longest unique comments, up to 5
        deduped = list({c.body: c for c in comments}.values())
        deduped.sort(key=lambda c: len(c.body), reverse=True)
        representatives = deduped[:5]

        summaries.append(
            {
                "theme": theme,
                "mr_count": len(mr_ids),
                "comment_count": len(comments),
                "reviewer_count": len(authors),
                "representative_comments": [
                    {"mr_iid": c.mr_iid, "author": c.author, "body": c.body}
                    for c in representatives
                ],
            }
        )

    # Most evidence first
    summaries.sort(key=lambda s: s["mr_count"], reverse=True)
    return summaries


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def _build_prompt(
    docs: dict[str, str],
    cluster_summaries: list[dict],
    max_proposals: int,
    extra_guidance: str = "",
) -> str:
    docs_section = "\n\n".join(
        f"### FILE: {path}\n\n{content}" for path, content in docs.items()
    )

    clusters_json = json.dumps(cluster_summaries, indent=2)

    target_files = list(docs.keys())

    extra_section = (
        f"\n\n## Additional team-specific guidance\n\n{extra_guidance.strip()}"
        if extra_guidance and extra_guidance.strip()
        else ""
    )

    return f"""You are maintaining repository coding guidance for a software engineering team.

## Your inputs

### 1. Current guidance files

{docs_section}

### 2. Recurring review comment themes

These themes were extracted from recent merged merge requests.
Each theme met a minimum threshold of appearances across multiple MRs and reviewers.

{clusters_json}

## Your task

1. For each recurring theme, decide:
   - Is it already clearly covered in the current guidance? → skip it
   - Is it missing entirely? → propose an addition
   - Is it only vaguely covered? → propose a small clarification

2. Propose at most {max_proposals} changes total.

3. Each proposed change must:
   - Be a small addition or clarification only (a bullet point or a short sentence)
   - Not rewrite or remove existing content
   - Preserve the existing tone, style, and structure of the file
   - Be justified by repeated evidence across multiple MRs

4. Target files you may suggest changes for: {target_files}
{extra_section}

## Output format

Return ONLY valid JSON matching this exact schema. No prose before or after.

{{
  "proposals": [
    {{
      "target_file": "<relative path to file>",
      "target_section": "<exact section heading, e.g. ## Testing>",
      "proposed_text": "<the exact markdown text to add>",
      "rationale": "<one sentence explaining why this is needed>",
      "evidence_themes": ["<theme name>"],
      "evidence_summary": "<e.g. appeared in 9 MRs across 4 reviewers>",
      "confidence": <float 0.0–1.0>
    }}
  ]
}}"""


# ---------------------------------------------------------------------------
# Patch generation
# ---------------------------------------------------------------------------

def _generate_patch(
    proposals: list[dict],
    docs: dict[str, str],
    repo_root: Path,
) -> str:
    """
    Produces a unified-diff-style patch string.
    Appends proposed text under the target section heading.
    """
    lines = []

    for proposal in proposals:
        target_file = proposal["target_file"]
        target_section = proposal["target_section"]
        proposed_text = proposal["proposed_text"].strip()

        if target_file not in docs:
            continue

        original = docs[target_file]
        original_lines = original.splitlines(keepends=True)

        # Find the target section
        section_line_idx = None
        for i, line in enumerate(original_lines):
            if line.strip() == target_section.strip():
                section_line_idx = i
                break

        if section_line_idx is None:
            # Section not found — append to end of file
            insert_idx = len(original_lines)
        else:
            # Insert after the section heading (and any blank line following it)
            insert_idx = section_line_idx + 1
            while insert_idx < len(original_lines) and original_lines[
                insert_idx
            ].strip() == "":
                insert_idx += 1

        new_lines = (
            original_lines[:insert_idx]
            + [proposed_text + "\n"]
            + original_lines[insert_idx:]
        )

        lines.append(f"--- a/{target_file}")
        lines.append(f"+++ b/{target_file}")

        # Show context around insertion
        context_start = max(0, insert_idx - 3)
        context_end = min(len(original_lines), insert_idx + 3)

        lines.append(
            f"@@ -{context_start + 1},{context_end - context_start} "
            f"+{context_start + 1},{context_end - context_start + 1} @@"
        )

        for i in range(context_start, context_end):
            if i == insert_idx:
                lines.append(f"+{proposed_text}")
            lines.append(f" {original_lines[i].rstrip()}")

        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    proposals: list[dict]
    patch: str
    cluster_summaries: list[dict]
    raw_llm_response: str


def run(cfg: Config, repo_root: Path) -> PipelineResult:
    print("\n[1/5] Loading docs...")
    docs = load_docs(cfg.pipeline.target_files, repo_root)
    if not docs:
        raise RuntimeError("No target files were loaded. Aborting.")

    print(f"\n[2/5] Fetching review comments from {cfg.scm.provider}...")
    client = build_scm_client(
        cfg.scm,
        noise_patterns=cfg.pipeline.noise_patterns,
        min_comment_length=cfg.pipeline.min_comment_length,
    )
    comments = client.fetch_review_comments(weeks=cfg.pipeline.weeks)
    print(f"  fetched {len(comments)} substantive comments")

    print("\n[3/5] Clustering comments...")
    clusters = _cluster_comments(comments, cfg.pipeline.theme_keywords)
    summaries = _summarise_clusters(clusters, cfg.pipeline.min_mr_occurrences)
    print(f"  {len(summaries)} themes met the threshold")

    if not summaries:
        print("  No recurring themes found. Nothing to propose.")
        return PipelineResult(
            proposals=[], patch="", cluster_summaries=[], raw_llm_response=""
        )

    print("\n[4/5] Calling LLM...")
    prompt = _build_prompt(
        docs,
        summaries,
        cfg.pipeline.max_proposals,
        cfg.pipeline.extra_guidance,
    )
    raw_response = call_llm(cfg.llm, prompt)

    # Parse JSON — be tolerant of markdown code fences
    json_text = raw_response.strip()
    if json_text.startswith("```"):
        json_text = re.sub(r"^```[a-z]*\n?", "", json_text)
        json_text = re.sub(r"\n?```$", "", json_text)

    try:
        parsed = json.loads(json_text)
        proposals = parsed.get("proposals", [])
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"LLM did not return valid JSON.\nError: {e}\n\nRaw:\n{raw_response}"
        )

    print(f"  LLM proposed {len(proposals)} change(s)")

    print("\n[5/5] Generating patch...")
    patch = _generate_patch(proposals, docs, repo_root)

    return PipelineResult(
        proposals=proposals,
        patch=patch,
        cluster_summaries=summaries,
        raw_llm_response=raw_response,
    )
