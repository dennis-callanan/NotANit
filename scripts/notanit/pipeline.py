import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

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
    max_changes: int,
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
   - Is it missing entirely? → add it
   - Is it only vaguely covered? → add a small clarification

2. Make at most {max_changes} changes total.

3. Each change must:
   - Be a small addition or clarification only (a bullet point or a short sentence)
   - Not rewrite or remove existing content
   - Preserve the existing tone, style, and structure of the file
   - Be justified by repeated evidence across multiple MRs

4. Target files you may change: {target_files}
{extra_section}

## Output format

Return ONLY valid JSON matching this exact schema. No prose before or after.

{{
  "changes": [
    {{
      "target_file": "<relative path to file>",
      "target_section": "<exact section heading, e.g. ## Testing>",
      "text": "<the exact markdown text to add>",
      "summary": "<one short sentence describing the change>"
    }}
  ]
}}"""


# ---------------------------------------------------------------------------
# Applying changes directly to the target files
# ---------------------------------------------------------------------------

def _insert_under_section(content: str, target_section: str, text: str) -> str:
    """Return ``content`` with ``text`` inserted under ``target_section``.

    Insertion goes right after the section heading (skipping any blank lines that
    follow it). If the heading isn't found, the text is appended to the end of the
    file. Blank lines are kept around the inserted block so the markdown stays well
    formed.
    """
    lines = content.splitlines(keepends=True)

    section_idx = None
    for i, line in enumerate(lines):
        if line.strip() == target_section.strip():
            section_idx = i
            break

    if section_idx is None:
        insert_idx = len(lines)
    else:
        insert_idx = section_idx + 1
        while insert_idx < len(lines) and lines[insert_idx].strip() == "":
            insert_idx += 1

    block = text.strip() + "\n"
    # Keep a blank line before the block if the preceding line isn't already blank.
    if insert_idx > 0 and lines[insert_idx - 1].strip() != "":
        block = "\n" + block
    # Keep a blank line after the block if there's following content.
    if insert_idx < len(lines) and lines[insert_idx].strip() != "":
        block = block + "\n"

    new_lines = lines[:insert_idx] + [block] + lines[insert_idx:]
    return "".join(new_lines)


def _resolve_target(target_file: str, doc_keys: list[str]) -> str | None:
    """Map the LLM's ``target_file`` to one of the loaded doc keys.

    The doc keys are whatever was listed in ``target_files`` (often absolute
    paths), but the LLM tends to answer with just the basename. Match leniently:
    exact key, then unique basename, then unique suffix.
    """
    if target_file in doc_keys:
        return target_file
    name = Path(target_file).name
    by_name = [k for k in doc_keys if Path(k).name == name]
    if len(by_name) == 1:
        return by_name[0]
    by_suffix = [k for k in doc_keys if k.endswith(target_file) or target_file.endswith(k)]
    if len(by_suffix) == 1:
        return by_suffix[0]
    return None


def _apply_changes(
    changes: list[dict],
    docs: dict[str, str],
    repo_root: Path,
) -> list[dict]:
    """Write each change directly into its target file. Returns the changes that
    were actually applied (unresolvable target files are skipped)."""
    updated = dict(docs)
    applied: list[dict] = []

    for change in changes:
        key = _resolve_target(change["target_file"], list(updated.keys()))
        if key is None:
            print(f"  [skip] LLM named an unknown target file: {change['target_file']}")
            continue
        updated[key] = _insert_under_section(
            updated[key], change["target_section"], change["text"]
        )
        # Normalise so the write-back loop and summary use the resolved key.
        change["target_file"] = key
        applied.append(change)

    # Write each touched file once, after all its edits are merged in.
    for target_file in {c["target_file"] for c in applied}:
        full_path = repo_root / target_file
        full_path.write_text(updated[target_file], encoding="utf-8")
        print(f"  [write] {full_path}")

    return applied


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    applied_changes: list[dict]
    cluster_summaries: list[dict]


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
        print("  No recurring themes found. Nothing to change.")
        return PipelineResult(applied_changes=[], cluster_summaries=[])

    print("\n[4/5] Calling LLM...")
    prompt = _build_prompt(
        docs,
        summaries,
        cfg.pipeline.max_changes,
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
        changes = parsed.get("changes", [])
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"LLM did not return valid JSON.\nError: {e}\n\nRaw:\n{raw_response}"
        )

    print(f"  LLM returned {len(changes)} change(s)")

    print("\n[5/5] Applying changes to files...")
    applied = _apply_changes(changes, docs, repo_root)

    return PipelineResult(
        applied_changes=applied,
        cluster_summaries=summaries,
    )
