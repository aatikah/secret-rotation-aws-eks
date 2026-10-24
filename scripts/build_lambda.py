"""Build the rotation Lambda deployment package.

Assembles a directory that Terraform's archive provider zips:

    terraform/modules/rotation-lambda/build/package/
        handler.py                      # from lambda/database_rotation/
        secrets_rotation/...            # the library (src layout)
        psycopg/ ...                    # vendored for the Lambda platform

psycopg ships platform-specific binary wheels, so we fetch the manylinux wheel
matching the Lambda runtime (x86_64, cp312) rather than whatever is installed
on the build machine. boto3/botocore are provided by the Lambda runtime and are
NOT bundled.

Usage (from repo root):
    python scripts/build_lambda.py
    python scripts/build_lambda.py --python-version 312 --arch x86_64
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PKG = REPO / "terraform" / "modules" / "rotation-lambda" / "build" / "package"
HANDLER = REPO / "lambda" / "database_rotation" / "handler.py"
LIB = REPO / "src" / "secrets_rotation"
PSYCOPG_VERSION = "3.2.3"


def _clean() -> None:
    if PKG.exists():
        shutil.rmtree(PKG)
    PKG.mkdir(parents=True, exist_ok=True)
    # Preserve the git-tracked keepfile so the dir survives in version control
    # even after a build populates and later cleans it.
    (PKG / ".gitkeep").write_text(
        "# Populated by scripts/build_lambda.py; kept so terraform validate "
        "resolves the archive path.\n",
        encoding="utf-8",
    )


def _copy_sources() -> None:
    shutil.copy2(HANDLER, PKG / "handler.py")
    shutil.copytree(LIB, PKG / "secrets_rotation")
    # Drop caches.
    for pyc in PKG.rglob("__pycache__"):
        shutil.rmtree(pyc, ignore_errors=True)


def _vendor_psycopg(py_version: str, arch: str) -> None:
    platform = f"manylinux2014_{arch}"
    cmd = [
        sys.executable, "-m", "pip", "install",
        f"psycopg[binary]=={PSYCOPG_VERSION}",
        "--target", str(PKG),
        "--platform", platform,
        "--python-version", py_version,
        "--only-binary=:all:",
        "--implementation", "cp",
        "--upgrade",
    ]
    print("Vendoring psycopg for the Lambda platform:")
    print("  " + " ".join(cmd))
    # noqa justification: cmd is a fixed argument list (no shell), built from a
    # pinned version constant and CLI args constrained by argparse choices.
    subprocess.run(cmd, check=True)  # noqa: S603


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-version", default="312", help="Lambda cpython version, e.g. 312.")
    parser.add_argument("--arch", default="x86_64", choices=["x86_64", "aarch64"])
    parser.add_argument("--skip-psycopg", action="store_true",
                        help="Skip vendoring psycopg (for a quick packaging smoke test).")
    args = parser.parse_args()

    _clean()
    _copy_sources()
    if not args.skip_psycopg:
        _vendor_psycopg(args.python_version, args.arch)

    print(f"\nLambda package assembled at: {PKG}")
    print("Terraform will zip this directory via the archive provider.")


if __name__ == "__main__":
    main()
