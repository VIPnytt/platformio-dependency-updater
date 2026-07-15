import datetime
import fileinput
import git
import github
import os
import sys
import typing

from . import Models
from .providers import Arduino
from .providers import Bitbucket
from .providers import GitHub
from .providers import GitLab
from .providers import PlatformIO


class Piobot:
    dependencies: list[Models.Dependency]
    ref: str
    repository: str
    _git: git.Repo
    _github: github.Github
    _token: str

    def __init__(self) -> None:
        self.dependencies = list()
        self.ref = os.getenv("GITHUB_REF_NAME") or ""
        self.repository = os.getenv("GITHUB_REPOSITORY") or ""
        self._token = os.getenv("GITHUB_TOKEN") or ""
        self._git = git.Repo()
        if datetime.datetime.now(
            self._git.head.commit.committed_datetime.tzinfo
        ) - self._git.head.commit.committed_datetime > datetime.timedelta(days=90):
            return None
        self._git.config_writer().set_value(
            "user", "name", "github-actions[bot]"
        ).release()
        self._git.config_writer().set_value(
            "user", "email", "41898282+github-actions[bot]@users.noreply.github.com"
        ).release()
        self._git.remote().set_url(
            f"https://x-access-token:{self._token}@github.com/{self.repository}.git"
        )
        self._github = github.Github(auth=github.Auth.Token(self._token))
        i = 0
        option: Models.Option | None = None
        with open(Models.Config.FILE, encoding="utf-8") as file:
            for line in file:
                i += 1
                if (
                    line.startswith(";")
                    or line.startswith("#")
                    or len(line.strip()) == 0
                ):
                    continue
                elif line.startswith("\t") or line.startswith("  "):
                    _line = line.strip()
                    if (
                        option is not None
                        and len(_line) > 0
                        and not _line.startswith(";")
                        and not _line.startswith("#")
                    ):
                        self.dependencies.append(
                            Models.Dependency(line=i, option=option, value=_line)
                        )
                    continue
                key, _, value = line.partition("=")
                _key = key.rstrip()
                if _key in Models.Option:
                    _value = value.strip()
                    if len(_value) > 0:
                        self.dependencies.append(
                            Models.Dependency(
                                line=i,
                                option=typing.cast(Models.Option, _key),
                                value=_value,
                            )
                        )
                    if _key != Models.Option.PLATFORM:
                        option = typing.cast(Models.Option, _key)
                        continue
                option = None

    def check(self) -> int:
        for provider in [
            self.platformio,
            self.github,
            self.gitlab,
            self.bitbucket,
            self.arduino,
        ]:
            provider()
            if len(self.dependencies) == 0:
                break
        return 0

    def arduino(self) -> None:
        resolve = Arduino.Resolve()
        for dependency in self.dependencies.copy():
            try:
                self._handle(dependency, resolve.library(dependency))
            except Exception as e:
                print(f"::warning Arduino::{e}")

    def bitbucket(self) -> None:
        resolve = Bitbucket.Resolve()
        for description, handler in {
            "uuid commit": resolve.uuid_commit,
            "uuid tag": resolve.uuid_tag,
            "name commit": resolve.name_commit,
            "name tag": resolve.name_tag,
        }.items():
            for dependency in self.dependencies.copy():
                try:
                    self._handle(dependency, handler(dependency))
                except Exception as e:
                    print(f"::warning Bitbucket {description}::{e}")
            if len(self.dependencies) == 0:
                break

    def github(self) -> None:
        resolve = GitHub.Resolve()
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
                except Exception as e:
                    print(f"::warning GitHub {description}::{e}")
            if len(self.dependencies) == 0:
                break

    def gitlab(self) -> None:
        resolve = GitLab.Resolve()
        for description, handler in {
            "release tag commit": resolve.release_tag_commit,
            "tag commit": resolve.tag_commit,
            "release tag": resolve.release_tag,
            "tag": resolve.tag,
        }.items():
            for dependency in self.dependencies.copy():
                try:
                    self._handle(dependency, handler(dependency))
                except Exception as e:
                    print(f"::warning GitLab {description}::{e}")
            if len(self.dependencies) == 0:
                break

    def platformio(self) -> None:
        resolve = PlatformIO.Resolve()
        for description, handler in {
            "package": resolve.package,
            "download": resolve.download,
            "api": resolve.api,
        }.items():
            for dependency in self.dependencies.copy():
                try:
                    self._handle(dependency, handler(dependency))
                except Exception as e:
                    print(f"::warning PlatformIO Registry {description}::{e}")
            if len(self.dependencies) == 0:
                break

    def _handle(
        self, dependency: Models.Dependency, result: Models.Result | str | None
    ) -> None:
        if isinstance(result, str):
            print(f"::debug::{result}")
        elif isinstance(result, Models.Result):
            print(
                f"::notice file={Models.Config.FILE},line={dependency.line},title=Update available::{result.value}"
            )
            self._bump(dependency, result)
        else:
            return None
        self.dependencies.remove(dependency)

    def _bump(self, dependency: Models.Dependency, result: Models.Result) -> None:
        head = f"dependabot/platformio/{result.package}-{result.version_to}"
        if head in self._git.heads:
            return None
        repo = self._github.get_repo(self.repository)
        if (
            repo.get_pulls(
                base=self.ref, head=f"{repo.owner.login}:{head}", state="all"
            ).totalCount
            > 0
        ):
            return None
        open = repo.get_pulls(base=self.ref, state="open")
        _pr = next(
            (
                pr
                for pr in open
                if pr.head.ref.startswith(f"dependabot/platformio/{result.package}-")
            ),
            None,
        )
        if (
            _pr is None
            and sum(
                1 for pr in open if pr.head.ref.startswith("dependabot/platformio/")
            )
            >= 5
        ):
            return None
        self._git.head.set_reference(self._git.create_head(head, self.ref))
        self._git.head.reset(index=True, working_tree=True)
        i = 0
        with fileinput.FileInput(Models.Config.FILE, True) as file:
            for line in file:
                i += 1
                sys.stdout.write(
                    line.replace(dependency.value, result.value)
                    if i == dependency.line
                    else line
                )
        self._git.index.add(Models.Config.FILE)
        self._git.index.commit(
            f"Bump {result.package} from {result.version_from} to {result.version_to}"
        )
        self._git.remote().push(head).raise_if_error()
        pr = repo.create_pull(
            base=self.ref,
            body=result.body,
            head=head,
            title=f"Bump {result.package} from {result.version_from} to {result.version_to}",
        )
        for label in repo.get_labels():
            if label.name.lower() in {"dependencies", "platformio"}:
                pr.add_to_labels(label)
        pr.add_to_labels()
        if _pr is not None:
            _pr.create_issue_comment(f"Superseded by #{pr.number}.")
            _pr.edit(state="closed")
            _pr.delete_branch()

    def __del__(self) -> None:
        for dependency in self.dependencies:
            print(
                f"::error file={Models.Config.FILE},line={dependency.line},title=Unresolved::{dependency.option} = {dependency.value.split(';', 1)[0].rstrip()}"
            )
