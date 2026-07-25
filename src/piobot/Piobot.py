import datetime
import fileinput
import os
import pathlib
import re
import sys
import typing

import git as gitpython
import github as pygithub

from . import models
from .providers import arduino, bitbucket, espressif, github, gitlab, platformio


class Piobot:
    cooldown: datetime.timedelta
    dependencies: list[models.Dependency]
    ini: pathlib.Path
    labels: set[str]
    ref: str
    repository: str
    _git: gitpython.Repo
    _github: pygithub.Github
    _token: str

    def __init__(self) -> None:
        """
        Initialize repository access and parse supported dependency entries from the configured PlatformIO file.

        Initialization stops after loading configuration if the latest commit is more than 90 days old. Otherwise, Git and GitHub access are configured and dependencies are loaded from the file.
        """
        self.cooldown = datetime.timedelta(days=int(os.getenv(models.Inputs.COOLDOWN, models.Defaults.COOLDOWN)))
        self.dependencies = []
        self.ini = (
            (pathlib.Path(os.getenv(models.Inputs.PROJECT_DIR, models.Defaults.PROJECT_DIR)) / "platformio.ini")
            .resolve(True)
            .relative_to(pathlib.Path.cwd())
        )
        self.labels = {label.strip() for label in os.getenv(models.Inputs.LABELS, models.Defaults.LABELS).split(",")}
        self.ref = os.getenv("GITHUB_REF_NAME", "")
        self.repository = os.getenv("GITHUB_REPOSITORY", "")
        self._token = os.getenv("GITHUB_TOKEN", "")
        self._git = gitpython.Repo()
        if datetime.datetime.now(
            self._git.head.commit.committed_datetime.tzinfo
        ) - self._git.head.commit.committed_datetime > datetime.timedelta(days=90):
            return
        self._git.config_writer().set_value("user", "name", "github-actions[bot]").release()
        self._git.config_writer().set_value(
            "user", "email", "41898282+github-actions[bot]@users.noreply.github.com"
        ).release()
        self._git.remote().set_url(f"https://x-access-token:{self._token}@github.com/{self.repository}.git")
        self._github = pygithub.Github(auth=pygithub.Auth.Token(self._token))
        _variable = re.compile(r"^\${\S+\.(?:lib_deps|platform|platform_packages)}(?:\s*;.*)?$")
        i = 0
        option: models.Option | None = None
        with self.ini.open(encoding="utf-8") as file:
            for line in file:
                i += 1
                if line.startswith((";", "#")) or len(line.strip()) == 0:
                    continue
                elif line.startswith(("\t", "  ")):
                    _line = line.strip()
                    if (
                        option is not None
                        and len(_line) > 0
                        and not _line.startswith(";")
                        and not _line.startswith("#")
                        and _variable.fullmatch(_line) is None
                    ):
                        self.dependencies.append(models.Dependency(line=i, option=option, value=_line))
                    continue
                key, _, value = line.partition("=")
                _key = key.rstrip()
                if _key in models.Option:
                    _value = value.strip()
                    if len(_value) > 0 and _variable.fullmatch(_value) is None:
                        self.dependencies.append(
                            models.Dependency(
                                line=i,
                                option=typing.cast(models.Option, _key),
                                value=_value,
                            )
                        )
                    if _key != models.Option.PLATFORM:
                        option = typing.cast(models.Option, _key)
                        continue
                option = None

    def check(self) -> None:
        """Resolve dependencies using the configured provider integrations."""
        for provider in [
            self.platformio,
            self.espressif,
            self.github,
            self.gitlab,
            self.bitbucket,
            self.arduino,
        ]:
            provider()
            if len(self.dependencies) == 0:
                break

    def arduino(self) -> None:
        resolve = arduino.Resolve()
        for dependency in self.dependencies.copy():
            try:
                self._handle(dependency, resolve.library(dependency))
            except Exception as e:  # ruff:ignore[BLE001]
                print(f"::warning Arduino::{e}")

    def bitbucket(self) -> None:
        """
        Resolves unresolved dependencies using Bitbucket repository references.

        """
        resolve = bitbucket.Resolve(self.cooldown)
        for description, handler in {
            "uuid commit": resolve.uuid_commit,
            "uuid tag": resolve.uuid_tag,
            "name commit": resolve.name_commit,
            "name tag": resolve.name_tag,
        }.items():
            for dependency in self.dependencies.copy():
                try:
                    self._handle(dependency, handler(dependency))
                except Exception as e:  # ruff:ignore[BLE001]
                    print(f"::warning Bitbucket {description}::{e}")
            if len(self.dependencies) == 0:
                break

    def espressif(self) -> None:
        """Resolve dependencies using the Espressif component registry."""
        resolve = espressif.Resolve(self.cooldown)
        for description, handler in {
            "file": resolve.component,
            "download": resolve.component_id,
        }.items():
            for dependency in self.dependencies.copy():
                try:
                    self._handle(dependency, handler(dependency))
                except Exception as e:  # ruff:ignore[BLE001]
                    print(f"::warning Espressif Registry {description}::{e}")
            if len(self.dependencies) == 0:
                break

    def github(self) -> None:
        """
        Resolve GitHub dependencies and process any available updates.

        Unresolved dependencies remain available for subsequent resolution methods. Exceptions from individual resolution attempts are reported as warnings.
        """
        resolve = github.Resolve(self.cooldown)
        for description, handler in {
            "release tag commit archive": resolve.release_tag_commit_archive,
            "release tag commit ball": resolve.release_tag_commit_ball,
            "release tag commit git": resolve.release_commit_git,
            "tag commit archive": resolve.tag_commit_archive,
            "tag commit ball": resolve.tag_commit_ball,
            "tag commit git": resolve.tag_commit_git,
            "release tag asset": resolve.release_tag_asset,
            "release tag archive": resolve.release_tag_archive,
            "release tag ball": resolve.release_tag_ball,
            "release tag git": resolve.release_tag_git,
            "tag archive": resolve.tag_archive,
            "tag ball": resolve.tag_ball,
            "tag git": resolve.tag_git,
        }.items():
            for dependency in self.dependencies.copy():
                try:
                    self._handle(dependency, handler(dependency))
                except Exception as e:  # ruff:ignore[BLE001]
                    print(f"::warning GitHub {description}::{e}")
            if len(self.dependencies) == 0:
                break

    def gitlab(self) -> None:
        """Resolve dependencies using GitLab release and tag information."""
        resolve = gitlab.Resolve(self.cooldown)
        for description, handler in {
            "release tag commit": resolve.release_tag_commit,
            "tag commit": resolve.tag_commit,
            "release tag": resolve.release_tag,
            "tag": resolve.tag,
        }.items():
            for dependency in self.dependencies.copy():
                try:
                    self._handle(dependency, handler(dependency))
                except Exception as e:  # ruff:ignore[BLE001]
                    print(f"::warning GitLab {description}::{e}")
            if len(self.dependencies) == 0:
                break

    def platformio(self) -> None:
        """
        Resolve dependencies using PlatformIO Registry providers.

        Unresolved dependencies remain available for subsequent resolver methods, while resolution errors are reported as warnings.
        """
        resolve = platformio.Resolve(self.cooldown)
        for description, handler in {
            "package": resolve.package,
            "download": resolve.download,
            "api": resolve.api,
        }.items():
            for dependency in self.dependencies.copy():
                try:
                    self._handle(dependency, handler(dependency))
                except Exception as e:  # ruff:ignore[BLE001]
                    print(f"::warning PlatformIO Registry {description}::{e}")
            if len(self.dependencies) == 0:
                break

    def _handle(self, dependency: models.Dependency, result: models.Result | str | None) -> None:
        """
        Process a dependency resolution result and remove it once handled.

        Parameters:
                dependency (models.Dependency): The dependency associated with the result.
                result (models.Result | str | None): The resolved update, diagnostic message, or no result.
        """
        if isinstance(result, str):
            print(f"::debug::{result}")
        elif isinstance(result, models.Result):
            print(f"::notice file={self.ini},line={dependency.line},title=Update available::{result.value}")
            self._bump(dependency, result)
        else:
            return
        self.dependencies.remove(dependency)

    def _bump(self, dependency: models.Dependency, result: models.Result) -> None:
        """
        Create and publish a dependency update branch and pull request.

        Parameters:
            dependency (models.Dependency): Dependency entry to update.
            result (models.Result): Update details, including package, versions, replacement value, and pull request body.

        The update is skipped when an equivalent branch or pull request already exists, or when the open pull request limit is reached. An older matching pull request is closed and its branch deleted when superseded.
        """
        head = f"dependabot/platformio/{'' if self.ini.parent == '.' else f'{re.sub(r"[^a-z0-9/]", "", str(self.ini.parent).lower())}/'}{result.package}-{result.version_to}"
        if head in self._git.heads:
            return
        repo = self._github.get_repo(self.repository)
        if repo.get_pulls(base=self.ref, head=f"{repo.owner.login}:{head}", state="all").totalCount > 0:
            return
        open = repo.get_pulls(base=self.ref, state="open")
        _pr = next((pr for pr in open if pr.head.ref.startswith(head.removesuffix(result.version_to))), None)
        if _pr is None and sum(1 for pr in open if pr.head.ref.startswith("dependabot/platformio/")) >= int(
            os.getenv(models.Inputs.OPEN_PULL_REQUESTS_LIMIT, models.Defaults.OPEN_PULL_REQUESTS_LIMIT)
        ):
            return
        self._git.head.set_reference(self._git.create_head(head, self.ref))
        self._git.head.reset(index=True, working_tree=True)
        with fileinput.FileInput(self.ini, True, encoding="utf-8") as file:
            for line in file:
                sys.stdout.write(line.replace(dependency.value, result.value))
        self._git.index.add(self.ini)
        self._git.index.commit(
            f"Bump {result.package} from {result.version_from} to {result.version_to} in /{'' if self.ini.parent == '.' else self.ini.parent}"
        )
        self._git.remote().push(head).raise_if_error()
        pr = repo.create_pull(
            base=self.ref,
            body=result.body,
            head=head,
            title=f"Bump {result.package} from {result.version_from} to {result.version_to}{'' if self.ini.parent == '.' else f' in /{self.ini.parent}'}",
        )
        for label in repo.get_labels():
            if label.name in self.labels:
                pr.add_to_labels(label)
        if _pr is not None:
            _pr.create_issue_comment(f"Superseded by #{pr.number}.")
            _pr.edit(state="closed")
            _pr.delete_branch()

    def __del__(self) -> None:
        """Report unresolved dependencies using GitHub Actions error annotations."""
        for dependency in self.dependencies:
            print(
                f"::error file={self.ini},line={dependency.line},title=Unresolved::{dependency.option} = {dependency.value.split(';', 1)[0].rstrip()}"
            )
