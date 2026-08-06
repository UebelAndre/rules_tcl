"""A script for applying tclfmt fixes to Bazel targets."""

import argparse
import io
import os
import platform
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from python.runfiles import Runfiles
from tclint.cli.tclfmt import main as tclfmt_main

from tcl.tclint.private import target_query

# Aspect-side ignore tags for `tcl_tclint_fmt_aspect` -- kept in sync
# so `bazel run //tcl/tclint:format` and the aspect skip the same
# targets. Normalization (`-` -> `_`, casefold) happens in
# `target_query`, so callers only need to list one spelling.
_IGNORE_TAGS = (
    "no_tcl_format",
    "no_tclformat",
    "no_tclfmt",
    "noformat",
    "nofmt",
)


def _rlocation(runfiles: Runfiles, rlocationpath: str) -> Path:
    """Look up a runfile and ensure the file exists"""
    # TODO: https://github.com/periareon/rules_venv/issues/37
    source_repo = None
    if platform.system() == "Windows":
        source_repo = ""
    runfile = runfiles.Rlocation(rlocationpath, source_repo)
    if not runfile:
        raise FileNotFoundError(f"Failed to find runfile: {rlocationpath}")
    path = Path(runfile)
    if not path.exists():
        raise FileNotFoundError(f"Runfile does not exist: ({rlocationpath}) {path}")
    return path


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--bazel",
        type=Path,
        help="The path to a `bazel` binary. The `BAZEL_REAL` environment variable can also be used to set this value.",
    )
    parser.add_argument(
        "scope",
        nargs="*",
        default=["//...:all"],
        help="Bazel package or target scoping for formatting. E.g. `//...`, `//some:target`.",
    )

    parsed_args = parser.parse_args()

    if not parsed_args.bazel:
        parsed_args.bazel = target_query.find_bazel()

    return parsed_args


def run_tclfmt(
    sources: list[str],
    settings_path: Path,
    workspace_dir: Path,
) -> None:
    """Run tclfmt on a given set of sources"""
    if not sources:
        return

    tclfmt_args = ["tclfmt", "--config", str(settings_path), "--in-place"]
    tclfmt_args.extend(sources)

    exit_code = 0
    old_argv = list(sys.argv)
    sys.argv = tclfmt_args
    old_cwd = os.getcwd()
    os.chdir(workspace_dir)

    output_buffer = io.StringIO()
    try:
        with redirect_stdout(output_buffer), redirect_stderr(output_buffer):
            try:
                result = tclfmt_main()
                if result is not None:
                    exit_code = result
            except SystemExit as exc:
                exit_code = (
                    int(exc.code)
                    if isinstance(exc.code, int)
                    else (0 if exc.code is None else 1)
                )
    finally:
        os.chdir(old_cwd)
        sys.argv = old_argv

    if exit_code != 0:
        output = output_buffer.getvalue()
        if output:
            print(output, file=sys.stderr)
        sys.exit(exit_code)


def main() -> None:
    """The main entry point"""
    args = parse_args()

    if "BUILD_WORKSPACE_DIRECTORY" not in os.environ:
        raise EnvironmentError(
            "BUILD_WORKSPACE_DIRECTORY is not set. Is the process running under Bazel?"
        )

    workspace_dir = Path(os.environ["BUILD_WORKSPACE_DIRECTORY"])

    runfiles = Runfiles.Create()
    if not runfiles:
        raise EnvironmentError(
            "RUNFILES_MANIFEST_FILE and RUNFILES_DIR are not set. Is python running under Bazel?"
        )

    settings = _rlocation(runfiles, os.environ["TCLFMT_SETTINGS_PATH"])

    sources = target_query.resolve_source_paths(
        scope=args.scope,
        bazel=args.bazel,
        workspace_dir=workspace_dir,
        ignore_tags=_IGNORE_TAGS,
    )

    run_tclfmt(
        sources=sources,
        settings_path=settings,
        workspace_dir=workspace_dir,
    )


if __name__ == "__main__":
    main()
