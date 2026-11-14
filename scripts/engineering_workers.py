from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps" / "api"
TESTS = API / "tests"

WORKERS: dict[str, str] = {
    "pytest-actions": "Commerce action proposal and approval tests",
    "pytest-api": "API contract and endpoint tests",
    "pytest-auth-security": "Authentication and tenant security tests",
    "pytest-brave-search": "Web research connector tests",
    "pytest-concurrency": "Concurrency and lease coordination tests",
    "pytest-frankfurter": "Keyless FX reference-rate tests",
    "pytest-idempotency": "Idempotency contract tests",
    "pytest-job-api": "Background-job API tests",
    "pytest-job-queue": "Background worker and queue tests",
    "pytest-migrations": "Fresh and legacy database migration tests",
    "pytest-output-budgets": "Output-budget enforcement tests",
    "pytest-providers": "AI provider adapter contract tests",
    "pytest-rate-limits": "Rate-limit enforcement tests",
    "pytest-skill-evaluation": "Skill output evaluation tests",
    "pytest-skill-prompt-security": "Prompt-injection and untrusted-context tests",
    "pytest-skills": "Commerce skill runtime tests",
    "pytest-usage": "Usage and model-cost accounting tests",
    "ruff": "Ruff lint over API source and tests",
    "compile": "Python bytecode compilation over API source",
    "migration-upgrade": "Fresh SQLite database upgrade to the Alembic head",
    "openapi-contract": "OpenAPI generation and operation-ID uniqueness",
    "dependency-integrity": "Installed Python dependency consistency",
    "docs-links": "Repository-local Markdown link integrity",
    "package-wheel": "Build the API wheel without resolving new dependencies",
}


def write_summary(worker: str, description: str, success: bool, detail: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    status = "PASS" if success else "FAIL"
    with Path(summary_path).open("a", encoding="utf-8") as summary:
        summary.write(f"### {status}: {worker}\n\n")
        summary.write(f"{description}.\n\n")
        if detail:
            summary.write(f"{detail}\n\n")


def run_command(
    worker: str,
    description: str,
    command: list[str],
    *,
    cwd: Path = API,
    env: dict[str, str] | None = None,
) -> int:
    print(f"Worker: {worker} — {description}", flush=True)
    print("$ " + " ".join(command), flush=True)
    result = subprocess.run(command, cwd=cwd, env=env, check=False)
    success = result.returncode == 0
    detail = f"Exit code: {result.returncode}"
    write_summary(worker, description, success, detail)
    return result.returncode


def check_markdown_links() -> int:
    pattern = re.compile(r"!?'?\[[^\]]*\]\(([^)]+)\)")
    ignored = {".git", ".venv", "venv", "node_modules", "__pycache__"}
    markdown_files = [
        path for path in ROOT.rglob("*.md")
        if not any(part in ignored for part in path.relative_to(ROOT).parts)
    ]
    broken: list[str] = []
    checked = 0

    for markdown_file in markdown_files:
        content = markdown_file.read_text(encoding="utf-8")
        for match in pattern.finditer(content):
            destination = match.group(1).strip()
            if not destination:
                continue
            destination = destination.split(maxsplit=1)[0].strip("<>")
            parsed = urlsplit(destination)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            target_text = unquote(parsed.path)
            target = (
                ROOT / target_text.lstrip("/")
                if target_text.startswith("/")
                else markdown_file.parent / target_text
            )
            checked += 1
            if not target.exists():
                line = content.count("\n", 0, match.start()) + 1
                broken.append(
                    f"{markdown_file.relative_to(ROOT)}:{line} -> {destination}"
                )

    description = "Repository-local Markdown link integrity"
    if broken:
        for item in broken:
            print(f"BROKEN: {item}", file=sys.stderr)
        write_summary(
            "docs-links", description, False,
            f"Checked {checked} local links across {len(markdown_files)} files; "
            f"found {len(broken)} broken links.",
        )
        return 1

    detail = (
        f"Checked {checked} local links across {len(markdown_files)} Markdown files; "
        "no broken local targets found."
    )
    print(detail)
    write_summary("docs-links", description, True, detail)
    return 0


def run_worker(worker: str) -> int:
    description = WORKERS[worker]

    if worker.startswith("pytest-"):
        test_name = worker.removeprefix("pytest-")
        test_file = TESTS / f"test_{test_name.replace('-', '_')}.py"
        if not test_file.is_file():
            raise FileNotFoundError(f"Expected test module does not exist: {test_file}")
        return run_command(
            worker, description,
            [sys.executable, "-m", "pytest", "-q", str(test_file)],
        )

    if worker == "ruff":
        return run_command(worker, description, ["ruff", "check", "src", "tests"])

    if worker == "compile":
        return run_command(
            worker, description,
            [sys.executable, "-m", "compileall", "-q", "src"],
        )

    if worker == "migration-upgrade":
        with tempfile.TemporaryDirectory(prefix="emporia-migration-worker-") as temp_dir:
            database = Path(temp_dir) / "migration-check.sqlite3"
            env = os.environ.copy()
            env["EMPORIA_DATABASE_URL"] = f"sqlite:///{database}"
            return run_command(
                worker, description,
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                env=env,
            )

    if worker == "openapi-contract":
        code = (
            "from emporia_api.main import app\n"
            "schema = app.openapi()\n"
            "assert schema.get('openapi'), 'OpenAPI version is missing'\n"
            "paths = schema.get('paths', {})\n"
            "assert paths, 'OpenAPI schema has no paths'\n"
            "operations = [op for path in paths.values() for method, op in path.items() "
            "if method.lower() in {'get','post','put','patch','delete','options','head'}]\n"
            "ids = [op['operationId'] for op in operations if 'operationId' in op]\n"
            "assert len(ids) == len(set(ids)), 'Duplicate OpenAPI operationId values'\n"
            "print(f'OpenAPI {schema[\"openapi\"]}: {len(paths)} paths, "
            "{len(operations)} operations, unique operation IDs')\n"
        )
        env = os.environ.copy()
        env["PYTHONPATH"] = str(API / "src")
        return run_command(
            worker, description, [sys.executable, "-c", code], env=env,
        )

    if worker == "dependency-integrity":
        return run_command(
            worker, description, [sys.executable, "-m", "pip", "check"],
        )

    if worker == "docs-links":
        return check_markdown_links()

    if worker == "package-wheel":
        with tempfile.TemporaryDirectory(prefix="emporia-wheel-worker-") as temp_dir:
            return run_command(
                worker, description,
                [
                    sys.executable, "-m", "pip", "wheel",
                    "--no-deps", "--no-build-isolation",
                    "--wheel-dir", temp_dir, ".",
                ],
            )

    raise ValueError(f"No implementation registered for worker: {worker}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one bounded, deterministic Emporia engineering worker."
    )
    parser.add_argument("--worker", required=True, choices=sorted(WORKERS))
    args = parser.parse_args()

    if len(WORKERS) != 24:
        raise RuntimeError(f"Expected 24 registered workers, found {len(WORKERS)}")

    try:
        return run_worker(args.worker)
    except Exception as exc:
        write_summary(args.worker, WORKERS[args.worker], False, f"{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
