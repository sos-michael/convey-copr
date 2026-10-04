# Convey RPM builds

Repository: https://copr.fedorainfracloud.org/coprs/grantson/convey/

Build targets: Fedora 44 and Fedora Rawhide, x86_64. Upstream branch:
https://gitlab.gnome.org/donnybeelo/convey/-/tree/main

After a successful build:

```sh
sudo dnf copr enable grantson/convey && sudo dnf install convey
```

## How updates work

[GitHub Actions](https://github.com/sos-michael/convey-copr/actions/workflows/upstream.yml)
invokes `weekly.py` every Monday at 14:17 UTC (10:17 a.m. Eastern during
daylight saving time, 9:17 a.m. during standard time). The computer does not
need to be running. COPR handles compilation and RPM repository hosting.
Packaging changes also trigger a check. The Actions page supports manual
runs and a force-rebuild option.

New snapshots build for all enabled COPR targets, including Rawhide.

The script resolves upstream `main` to a full commit hash, renders the spec
into a self-contained COPR custom source script, and submits it through
the `COPR_CONFIG` GitHub repository secret. Credentials are placed in a
temporary runner file and deleted when the step exits; they are never
committed or embedded in submitted scripts or RPMs. COPR's 4 kB script limit requires compressing
the spec inside the submitted script; the editable source is `convey.spec.in`.

The source builder fetches the exact commit and generates an archive plus
spec. The binary builder uses Fedora dependencies with Meson downloads
disabled. Versions include the upstream version, UTC commit time and hash;
for example `50.2.1^20260919123456git0123456789ab`.

The checker reads build history and the exact previous recipe from COPR;
it needs no local state or GitHub cache. Running builds are not duplicated.
An unchanged successful recipe is skipped when it covered all currently
enabled targets. Failed builds are retried on the next run. Changing the
spec also triggers a build. The workflow waits for COPR, and a failed build
makes the Actions run fail. Inspect failures in the Actions logs and COPR UI.

GitHub disables scheduled workflows in public repositories after 60 days
without repository activity. A separate job records the first scheduled
check each month in `.github/last-scheduled-check` to keep the schedule
active. That file does not trigger builds. Only this job has repository
write permission; the build job has read permission.

## Maintenance

The local checkout can be moved or removed without affecting updates.
For local checks, create a Python environment, install `requirements.txt`,
and configure COPR credentials in `~/.config/copr` (or set `COPR_CONFIG_FILE`
to a configuration file). Existing credentials are not needed for unit tests.

```sh
# Test scheduling without network requests.
.venv/bin/python -m unittest -v

# Check upstream and COPR without submitting.
.venv/bin/python weekly.py --dry-run

# Check now and submit if needed.
.venv/bin/python weekly.py --wait
```

If COPR credentials expire, renew them at
https://copr.fedorainfracloud.org/api/ and replace the repository's
`COPR_CONFIG` Actions secret. No systemd timer is used by this setup.

This is unofficial development snapshot packaging. The spec runs the
upstream Meson tests under D-Bus and Xvfb. Generic global action icons are
removed from the install tree because they already exist in Convey's
embedded resources and can conflict with Geary.

The build-only test environment disables WebKit's nested sandbox because
COPR's outer container denies its `/proc` mount. The installed application
keeps WebKit's normal sandbox. Private Convey shared-library dependencies
are filtered from RPM metadata; the libraries ship in the same RPM.

COPR custom-source reference:
https://docs.copr.fedorainfracloud.org/custom_source_method.html
