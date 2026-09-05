"""Zero-quota regression checks for the generic branch-recon workflow.

The workflow intentionally executes code from arbitrary repository refs. That
code must therefore be treated as untrusted and must never inherit long-lived
provider secrets or retained repository credentials.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "branch_recon.yml"


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"PASS {message}")


def main():
    text = WORKFLOW.read_text(encoding="utf-8")

    check("workflow_dispatch:" in text, "branch recon remains manual-dispatch only")
    for forbidden_trigger in ("pull_request_target:", "schedule:", "push:", "pull_request:"):
        check(forbidden_trigger not in text, f"generic recon has no {forbidden_trigger[:-1]} trigger")

    check("${{ secrets." not in text, "generic recon references no GitHub Actions secrets")
    check("GROQ_API_KEY" not in text, "generic recon cannot expose GROQ_API_KEY")
    check("GEMINI_API_KEY" not in text, "generic recon cannot expose GEMINI_API_KEY")
    check("OPENROUTER_API_KEY" not in text, "generic recon cannot expose OPENROUTER_API_KEY")
    check("FAL_KEY" not in text, "generic recon cannot expose FAL_KEY")
    check("ELEVENLABS" not in text.upper(), "generic recon cannot expose ElevenLabs credentials")

    check("permissions:\n  contents: read\n" in text,
          "workflow declares repository contents read-only")
    check(not re.search(r"^\s*[A-Za-z_-]+:\s*write\s*$", text, re.MULTILINE),
          "workflow grants no write-scoped GitHub permission")
    check("persist-credentials: false" in text,
          "checkout credentials are removed before arbitrary branch code executes")

    timeout = re.search(r"timeout-minutes:\s*(\d+)", text)
    check(bool(timeout) and int(timeout.group(1)) <= 5,
          "arbitrary branch execution has a short bounded timeout")

    check("ref: ${{ inputs.ref }}" in text,
          "requested ref is passed through checkout's ref input")
    check("RECON_SCRIPT: ${{ inputs.script }}" in text,
          "requested script is transferred through an environment variable")
    check('${{ inputs.script }}' not in "\n".join(
        line for line in text.splitlines() if line.lstrip().startswith("run:")
    ), "script input is not directly interpolated into a run command")

    check("Validate diagnostic path without executing branch Python" in text,
          "path validation explicitly precedes untrusted Python execution")
    guard_start = text.index("- name: Validate diagnostic path without executing branch Python")
    run_start = text.index("- name: Run zero-secret recon script")
    guard = text[guard_start:run_start]
    check("python " not in guard.lower(),
          "pre-execution path guard invokes no Python from the untrusted checkout")
    check('"$RECON_SCRIPT" != *.py' in guard,
          "diagnostic path must have a .py suffix")
    check('realpath -e -- "$GITHUB_WORKSPACE"' in guard,
          "path guard anchors to the resolved GITHUB_WORKSPACE")
    check('realpath -e -- "$RECON_SCRIPT"' in guard,
          "path guard resolves symlinks and traversal before execution")
    check('[[ ! -f "$candidate" ]]' in guard,
          "path guard requires an existing regular file")
    check('"$workspace"/*' in guard,
          "path guard rejects resolved paths outside GITHUB_WORKSPACE")

    run_block = text[run_start:]
    check('exec python "$script_path"' in run_block,
          "only the validated resolved diagnostic is handed to Python")
    check('BRANCH_RECON_ZERO_SECRET: "1"' in text,
          "diagnostic receives an explicit zero-secret mode marker")
    check("purpose-built workflows" in text,
          "security contract directs secret-backed diagnostics to trusted purpose-built workflows")

    print("branch_recon security regression: PASS")


if __name__ == "__main__":
    main()
