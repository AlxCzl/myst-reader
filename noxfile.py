"""Task runner for the developer

Usage
-----

   nox -l

   nox -s <session>

   nox -k <keyword>

"""
from functools import partial
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

import nox

PACKAGE = "pelican-myst-reader"
CWD = Path.cwd()
if (CWD / "poetry.lock").exists():
    BUILD_SYSTEM = "poetry"
    PACKAGE_SPEC = "pyproject.toml"
else:
    BUILD_SYSTEM = "setuptools"
    PACKAGE_SPEC = "setup.cfg"

TEST_ENV_VARS = {}
if os.getenv("CI"):
    TEST_ENV_VARS["PYTEST_ADDOPTS"] = "--color=yes"


no_venv_session = partial(nox.session, venv_backend="none")
nox.options.sessions = ["tests"]


def run_ext(session, cmd):
    """Run an external command, i.e. outside a nox managed virtual envionment"""
    session.run(*shlex.split(cmd), external=True)


def rmdir(path_dir: str):
    if Path(path_dir).exists():
        shutil.rmtree(path_dir)


def poetry_install(session, *args):
    """Install with dependencies pinned in pyproject.toml"""
    run_ext(session, "poetry install " + " ".join(args))


def pip_install(session, filename):
    """Install with dependencies pinned in requirements/*.txt"""
    run_ext(session, f"python -m pip install -r requirements/{filename}.txt")


def pip_sync(session, filename):
    """Reset developer environment with dependencies pinned in requirements/dev.txt"""
    run_ext(session, f"python -m piptools sync requirements/{filename}.txt")


@no_venv_session
def install(session):
    """Install package."""
    if BUILD_SYSTEM == "poetry":
        poetry_install(session)
    else:
        pip_install(session, "main")


@no_venv_session
def develop(session):
    """Install developer environment."""
    if BUILD_SYSTEM == "poetry":
        poetry_install(session, "--with=dev")
    else:
        pip_install(session, "dev")


@no_venv_session
def sync(session):
    """Sync developer environment."""
    if BUILD_SYSTEM == "poetry":
        poetry_install(session, "--sync", "--with=dev")
    else:
        pip_sync(session, ["dev"])


@no_venv_session
def requires(session):
    """Pin dependencies"""
    if BUILD_SYSTEM == "poetry":
        run_ext(session, "poetry lock --no-update")
    else:
        session.notify("pip-compile")


@nox.session(name="pip-compile", reuse_venv=True)
@nox.parametrize("extra", [nox.param(extra, id=extra) for extra in ("main", "dev")])
def pip_compile(session, extra):
    """Pin dependencies to requirements/*.txt

    How to run all in parallel::

        pipx install nox
        make -j requirements

    """
    session.install("pip-tools")
    req = Path("requirements")

    if extra == "main":
        in_extra = ""
        in_file = ""
        out_file = req / "main.txt"
    else:
        in_extra = f"--extra {extra}"
        in_file = req / "vcs_packages.in"
        out_file = req / f"{extra}.txt"

    session.run(
        *shlex.split(
            "python -m piptools compile --resolver backtracking --quiet "
            f"{in_extra} {in_file} {PACKAGE_SPEC} "
            f"-o {out_file}"
        ),
        *session.posargs,
    )

    session.log(f"Removing absolute paths from {out_file}")
    packages = out_file.read_text()
    rel_path_packages = packages.replace("file://" + str(Path.cwd().resolve()), ".")
    if extra == "tests":
        tests_editable = out_file.parent / out_file.name.replace(
            "tests", "tests-editable"
        )
        session.log(f"Copying {out_file} with -e flag in {tests_editable}")
        tests_editable.write_text(rel_path_packages)
        session.log(f"Removing -e flag in {out_file}")
        rel_path_packages = re.sub(r"^-e\ \.", ".", rel_path_packages, flags=re.M)

    session.log(f"Writing {out_file}")
    out_file.write_text(rel_path_packages)


def install_with_tests(session):
    if BUILD_SYSTEM == "poetry":
        session.install("poetry")
        poetry_install(session, "--with=tests")
    else:
        session.install("-r", "requirements/tests.txt")


@nox.session
def tests(session):
    """Execute unit-tests using pytest"""
    install_with_tests(session)
    session.run(
        "pytest",
        *session.posargs,
        env=TEST_ENV_VARS,
    )


@nox.session(name="tests-cov")
def tests_cov(session):
    """Execute unit-tests using pytest+pytest-cov"""
    install_with_tests(session)
    session.run(
        "pytest",
        "--cov",
        "--cov-config=pyproject.toml",
        "--no-cov-on-fail",
        "--cov-report=term-missing",
        *session.posargs,
        env=TEST_ENV_VARS,
    )


@nox.session(name="coverage-html")
def coverage_html(session, nox=False):
    """Generate coverage report in HTML. Requires `tests-cov` session."""
    report = Path.cwd() / ".coverage" / "html" / "index.html"
    session.install("coverage[toml]")
    session.run("coverage", "html")

    print("Code coverage analysis complete. View detailed report:")
    print(f"file://{report}")


@no_venv_session(name="format")
def format_(session):
    """Run pre-commit hooks on all files to set and lint code-format"""
    run_ext(session, "pre-commit install")
    run_ext(session, "pre-commit run --all-files")


@nox.session
def lint(session):
    """Run pre-commit hooks on files which differ in the current branch from origin/HEAD."""
    session.install("pre-commit")
    session.run("pre-commit", "install")
    session.run("pre-commit", "run", "--from-ref", "origin/HEAD", "--to-ref", "HEAD")


def _prepare_docs_session(session):
    session.install("-r", "requirements/docs.txt")
    session.chdir("./docs")

    build_dir = Path.cwd() / "_build"
    source_dir = "."
    output_dir = str(build_dir.resolve() / "html")
    return source_dir, output_dir


@nox.session
def docs(session):
    """Build documentation using Sphinx."""
    source, output = _prepare_docs_session(session)
    session.run(
        "python", "-m", "sphinx", "-b", "html", source, output
    )  # Same as sphinx-build
    print("Build finished.")
    print(f"file://{output}/index.html")


@nox.session(name="docs-autobuild")
def docs_autobuild(session):
    """Build documentation using sphinx-autobuild."""
    source, output = _prepare_docs_session(session)
    session.run(
        "python",
        "-m",
        "sphinx_autobuild",
        "--watch",
        "../src",
        "--re-ignore",
        r"(_build|generated)\/.*",
        source,
        output,
    )  # Same as sphinx-autobuild
    print("Build finished.")
    print(f"file://{output}/index.html")


@no_venv_session
def testpypi(session):
    """Release clean, build, upload to TestPyPI"""
    session.notify("release-clean")
    session.notify("release-build")
    session.notify("release-upload", ["--repository", "testpypi"])


@no_venv_session
def pypi(session):
    """Release clean, download from TestPyPI, test, upload to PyPI"""
    session.notify("release-clean")
    session.notify("download-testpypi")
    session.notify("release-tests")
    session.notify("release-upload", ["--repository", "pypi"])


@nox.session(name="download-testpypi")
def download_testpypi(session):
    """Download from TestPyPI and run tests"""
    (Path.cwd() / "dist").mkdir()
    session.chdir("./dist")

    git_tags = subprocess.check_output(
        ["git", "tag", "--list", "--sort=version:refname"], text=True
    )
    latest_version = git_tags.splitlines()[-1]
    spec = f"{PACKAGE}=={latest_version}"
    session.run(
        "python",
        "-m",
        "pip",
        "index",
        "versions",
        "--index",
        "https://test.pypi.org/simple",
        "--pre",
        PACKAGE,
    )
    session.run(
        "python",
        "-m",
        "pip",
        "download",
        "--index",
        "https://test.pypi.org/simple",
        "--pre",
        "--no-deps",
        spec,
    )


@nox.session(name="release-tests")
def release_tests(session):
    """Execute test suite with build / downloaded package in ./dist"""
    packages = [str(p) for p in Path("./dist").iterdir()]
    session.install(*packages)
    tests(session)


@no_venv_session(name="release-clean")
def release_clean(session):
    """Remove build and dist directories"""
    session.log("Removing build and dist")
    rmdir("./build/")
    rmdir("./dist/")


@nox.session(name="release-build")
def release_build(session):
    """Build package into dist."""
    session.install("build")
    session.run("python", "-m", "build")


@nox.session(name="release-upload")
def release_upload(session):
    """Upload dist/* to repository testpypi (default, must be configured in ~/.pypirc).
    Also accepts positional arguments to `twine upload` command.

    """
    session.install("twine")
    session.run("twine", "check", "dist/*")
    args = session.posargs

    # See
    # https://pypi.org/help/#apitoken and
    # https://twine.readthedocs.io/en/latest/#environment-variables
    env = {"TWINE_USERNAME": "__token__"}

    if "testpypi" in args and (api_token := os.getenv("TEST_PYPI_TOKEN")):
        env["TWINE_PASSWORD"] = api_token
    elif api_token := os.getenv("PYPI_TOKEN"):
        env["TWINE_PASSWORD"] = api_token

    session.run("twine", "upload", *args, "dist/*", env=env)
