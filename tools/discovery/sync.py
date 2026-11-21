"""Synchronisation incrémentale dans un clone temporaire et publication d'une ref locale."""

import tempfile
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path

from tools.cli import UsageError
from tools.core.catalog import write_text
from tools.core.exit_codes import ExitCode
from tools.discovery import scan
from tools.discovery.repos import Git, GitError
from tools.index.search import index


def tip(git, ref):
    return git.run("rev-parse", "--verify", "--quiet", "--end-of-options", ref + "^{commit}",
                   ok=(0, 1)).decode().strip()


def checked_out(git, ref):
    return f"branch {ref}".encode() in git.run("worktree", "list", "--porcelain", "-z").split(b"\0")


def report(work, result):
    lines = ["# Synchronisation du registre", "",
             f"- Copies analysées · {result['scannedCopies']}",
             f"- Nouveaux assets · {result['newAssets']}",
             f"- Nouveaux IDs · {result['newIds']}"]
    if result["divergentSources"]:
        lines.extend(("", "## Copies divergentes", ""))
        lines.extend(f"- {item['name']} · {item['message']}" for item in result["divergentSources"])
    lines.extend(("", "Usages retirés · `generated/reports/removed-in-use.json`.", ""))
    path = work / "generated" / "reports" / "sync-pr.md"
    write_text(path, "\n".join(lines))


def sync(root, args):
    root = root.resolve()
    git = Git(root)
    branch = args.branch or f"sync/{datetime.now(timezone.utc).date().isoformat()}"
    if not branch.startswith("sync/"):
        raise UsageError("--branch doit commencer par sync/.")
    ref = f"refs/heads/{branch}"
    try:
        git.run("check-ref-format", ref)
    except GitError as exc:
        raise UsageError("Nom de branche invalide.") from exc
    if checked_out(git, ref):
        return ExitCode.VERSION_CONFLICT, {"ok": False, "error": "sync-branch-checked-out"}

    base = tip(git, "refs/heads/main") or tip(git, "HEAD")
    old = tip(git, ref)
    if old and git.run("merge-base", base, old, ok=(0, 1)).decode().strip() != base:
        return ExitCode.VERSION_CONFLICT, {"ok": False, "error": "sync-branch-diverged"}
    selected_base = old or base
    settings = Namespace(cache=scan.cache_path(args).resolve(), fetch=args.fetch, sources=None, only=args.only,
                         provider=None, job=None, verify=False, dry_run=args.dry_run, incremental=True)
    copies = scan.preflight(root, settings)

    with tempfile.TemporaryDirectory(prefix="assetctl-sync-") as tmp:
        work = Path(tmp) / "registry"
        git.run("clone", "--no-local", "--no-checkout", "--no-tags", "--template=", "--", root.as_uri(), str(work))
        local = Git(work)
        local.run("checkout", "--detach", selected_base)
        code, result = scan.run(work, settings, copies)
        result["branch"] = branch
        if code != ExitCode.OK or args.dry_run:
            return code, result
        if result["scannedCopies"] or not (work / "generated" / "reports" / "sync-pr.md").exists():
            index(work, Namespace(dry_run=False))
            report(work, result)
        changes = local.run("ls-files", "-m", "-o", "--exclude-standard", "-z",
                            "--", "catalog", "generated", "thumbnails").split(b"\0")
        paths = sorted({path.decode() for path in changes if path})
        for offset in range(0, len(paths), 128):
            local.run("add", "--", *paths[offset:offset + 128])
        tree = local.run("write-tree").decode().strip()
        parent_tree = local.run("rev-parse", "HEAD^{tree}").decode().strip()
        commit = selected_base
        if tree != parent_tree:
            commit = local.run("-c", "user.name=OpenCade Asset Registry",
                               "-c", "user.email=asset-registry@noreply.opencade.invalid",
                               "commit-tree", tree, "-p", selected_base,
                               "-m", "Synchronise le catalogue des assets").decode().strip()
            local.run("update-ref", "refs/heads/assetctl-result", commit)
            git.run("fetch", "--no-write-fetch-head", "--no-tags", "--no-recurse-submodules",
                    "--", work.as_uri(), "refs/heads/assetctl-result")
        if checked_out(git, ref):
            return ExitCode.VERSION_CONFLICT, {"ok": False, "error": "sync-branch-checked-out"}
        try:
            git.run("update-ref", ref, commit, old or "0" * len(commit))
        except GitError:
            return ExitCode.VERSION_CONFLICT, {"ok": False, "error": "sync-ref-changed"}
        body = (work / "generated" / "reports" / "sync-pr.md").read_text(encoding="utf-8")
    result = {**result, "commit": commit, "report": "generated/reports/sync-pr.md"}
    if getattr(args, "open_pr", False):
        if commit == base:
            result["pullRequest"] = None
        else:
            return open_pr(git, args, branch, ref, body, result)
    return ExitCode.OK, result


def open_pr(git, args, branch, ref, body, result):
    """Pousse la branche sync/… (jamais main, jamais en force) puis ouvre la PR vers main."""
    from tools.publish.forge import FORGE_URL, ForgeError, open_pull_request

    if not args.forge_repo:
        raise UsageError("--open-pr exige --forge-repo propriétaire/dépôt.")
    import os

    if not os.environ.get("ASSETCTL_FORGEJO_TOKEN"):
        return ExitCode.IO, {**result, "ok": False, "error": "sync-pr-failed",
                             "message": "ASSETCTL_FORGEJO_TOKEN absent : branche ni poussée ni proposée."}
    remote = args.pr_remote or f"{(args.forge_url or FORGE_URL).rstrip('/')}/{args.forge_repo}.git"
    try:
        git.run("push", "--no-verify", "--", remote, f"{ref}:{ref}")
    except GitError:
        return ExitCode.IO, {**result, "ok": False, "error": "sync-push-failed"}
    try:
        result["pullRequest"] = open_pull_request(args.forge_repo, branch, "main", "Synchronisation du catalogue des assets",
                                                  body, forge_url=args.forge_url)
    except ForgeError as exc:
        return ExitCode.IO, {**result, "ok": False, "error": "sync-pr-failed", "message": str(exc)}
    except ValueError as exc:
        raise UsageError(str(exc)) from exc
    return ExitCode.OK, result
