#!/usr/bin/env python3
"""Check upstream and use COPR history to submit changed snapshots."""
import argparse
import base64
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import zlib

ROOT = Path(__file__).resolve().parent
OWNER, PROJECT = "grantson", "convey"
UPSTREAM = "https://gitlab.gnome.org/donnybeelo/convey.git"
FINISHED = {"succeeded", "failed", "canceled", "skipped"}

def render(commit):
    template = (ROOT / "source.py.in").read_text()
    spec = base64.b64encode(zlib.compress((ROOT / "convey.spec.in").read_bytes(), 9)).decode()
    script = template.replace("@PIN@", repr(commit)).replace("@SPEC@", repr(spec))
    if len(script.encode()) > 4000:
        raise ValueError("COPR custom source script exceeds its 4 kB limit")
    return script

def fingerprint(script):
    # Different runner versions can compress the same spec differently.
    # Compare the actual spec, without executing any retrieved source script.
    def normalize(match):
        spec = zlib.decompress(base64.b64decode(match.group(1)))
        return "base64.b64decode(" + hashlib.sha256(spec).hexdigest() + ")"
    normalized = re.sub(r"base64\.b64decode\(['\"]([A-Za-z0-9+/=]+)['\"]\)", normalize, script)
    return hashlib.sha256(normalized.strip().encode()).hexdigest()

def check(client, script, force=False):
    # This project contains only Convey. Query the project, not the package:
    # new builds may not have a package name until sources exist.
    recent = list(client.build_proxy.get_list(OWNER, PROJECT, pagination={"limit": 1}))
    latest = recent[0] if recent else None
    if latest and latest["state"] not in FINISHED:
        return False, latest["id"], f"Build {latest['id']} is still {latest['state']}."
    if force:
        return True, None, "Forced rebuild requested."
    if latest and latest["state"] == "succeeded":
        config = client.build_proxy.get_source_build_config(latest["id"])
        previous = config.get("source_dict", {}).get("script", "")
        targets = set(client.project_proxy.get(OWNER, PROJECT)["chroot_repos"])
        if (previous and fingerprint(previous) == fingerprint(script)
                and targets.issubset(latest["chroots"])):
            return False, None, f"Up to date: successful build {latest['id']} has this recipe and all targets."
    return True, None, "Source, recipe, or targets changed, or the previous build needs retrying."

def watch(build_id):
    command = [str(Path(sys.executable).with_name("copr-cli"))]
    if os.environ.get("COPR_CONFIG_FILE"):
        command.extend(["--config", os.environ["COPR_CONFIG_FILE"]])
    subprocess.run([*command, "watch-build", str(build_id)], check=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Check upstream and COPR without submitting")
    parser.add_argument("--force", action="store_true", help="Rebuild an unchanged recipe")
    parser.add_argument("--wait", action="store_true", help="Wait for COPR and fail if the build fails")
    parser.add_argument("--commit", help="Build a specific full commit instead of main")
    args = parser.parse_args()
    if args.commit:
        commit = args.commit
    else:
        output = subprocess.check_output(["git", "ls-remote", "--exit-code", UPSTREAM, "refs/heads/main"], text=True, timeout=120)
        commit = output.split()[0]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Expected a full Git commit hash")
    script = render(commit)
    from copr.v3 import Client
    client = Client.create_from_config_file(os.environ.get("COPR_CONFIG_FILE"))
    needed, pending, message = check(client, script, args.force)
    print(f"Upstream: {commit}\n{message}", flush=True)
    if args.dry_run:
        print(f"Would submit a build: {needed}")
        return
    if pending and args.wait:
        watch(pending)
        needed, pending, message = check(client, script, args.force)
        print(message, flush=True)
    if not needed:
        return
    # COPR retains the pinned recipe as durable state. No runner cache or
    # local state file is needed to prevent duplicates.
    build = client.build_proxy.create_from_custom(
        OWNER, PROJECT, script,
        script_chroot="fedora-44-x86_64",
        script_builddeps=["git-core", "python3"],
        script_resultdir="results",
    )
    print(f"Submitted https://copr.fedorainfracloud.org/coprs/{OWNER}/{PROJECT}/build/{build.id}/", flush=True)
    if args.wait:
        watch(build.id)

if __name__ == "__main__":
    main()
