import datetime
import os
import packaging.version
import re
import requests
import typing

from .. import Models


class Asset(typing.TypedDict):
    browser_download_url: str
    name: str


class Commit(typing.TypedDict):
    sha: str
    url: str


class Committer(typing.TypedDict):
    date: str


class CommitID(typing.TypedDict):
    committer: Committer


class CommitResponse(typing.TypedDict):
    commit: CommitID


class MatchCommit(typing.TypedDict):
    commit: str
    name: str
    package: str | None
    tag: str
    variant: str


class MatchDownload(typing.TypedDict):
    asset: str
    name: str
    package: str | None
    tag: str


class MatchTag(typing.TypedDict):
    name: str
    package: str | None
    tag: str
    variant: str


class Object(typing.TypedDict):
    sha: str


class Release(typing.TypedDict):
    assets: list[Asset]
    html_url: str
    prerelease: bool
    published_at: str | None
    tag_name: str
    tarball_url: str
    url: str
    zipball_url: str


class Tag(typing.TypedDict):
    commit: Commit
    name: str
    tarball_url: str
    zipball_url: str


class TagID(typing.TypedDict):
    object: Object


class Resolve:
    _archive_commit: re.Pattern[str]
    _archive_tag: re.Pattern[str]
    _ball_commit: re.Pattern[str]
    _ball_tag: re.Pattern[str]
    _download: re.Pattern[str]
    _git_commit: re.Pattern[str]
    _git_tag: re.Pattern[str]

    def __init__(self) -> None:
        self._archive_commit = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://github\.com/(?P<name>[^/\s]+/[^/\s]+)/archive/(?P<commit>[0-9a-f]{40})\.(?P<variant>tar\.gz|zip)\s*;\s*(?P<tag>\S+)$"
        )
        self._archive_tag = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://github\.com/(?P<name>[^/\s]+/[^/\s]+)/archive/refs/tags/(?P<tag>[^/\s]+)\.(?P<variant>tar\.gz|zip)(?:\s*;.*)?$"
        )
        self._ball_commit = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://api\.github\.com/repos/(?P<name>[^/\s]+/[^/\s]+)/(?P<variant>tar|zip)ball/(?P<commit>[0-9a-f]{40})\s*;\s*(?P<tag>\S+)$"
        )
        self._ball_tag = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://api\.github\.com/repos/(?P<name>[^/\s]+/[^/\s]+)/(?P<variant>tar|zip)ball/(?:refs/tags/)?(?P<tag>[^/\s]+)(?:\s*;.*)?$"
        )
        self._download = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://github\.com/(?P<name>[^/\s]+/[^/\s]+)/releases/download/(?P<tag>[^/\s]+)/(?P<asset>[^/\s]+\.(?:tar|tar\.gz|tgz|zip))(?:\s*;.*)?$"
        )
        self._git_commit = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?(?P<variant>git|git\+https|git\+ssh|https)://github\.com/(?P<name>[^/\s]+/[^/\s]+)\.git#(?P<commit>[0-9a-f]{40})\s*;\s*(?P<tag>\S+)$"
        )
        self._git_tag = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?(?P<variant>git|git\+https|git\+ssh|https)://github\.com/(?P<name>[^/\s]+/[^/\s]+)\.git#(?P<tag>[^/\s]+)(?:\s*;.*)?$"
        )

    def release_commit_git(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(MatchCommit | None, self._git_commit.fullmatch(dependency.value))
        if not match:
            return None
        release = self._request_release(match["name"], match["tag"])
        if not release:
            return None
        owner, repo = self._parse_link(release["url"])
        commit = self._request_tag_id(owner, repo, release["tag_name"])["object"]["sha"]
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}{match['variant']}://github.com/{owner}/{repo}.git#{commit} ; {release['tag_name']}"
        return (
            Models.Result(
                body="\n".join(
                    [
                        f"Bumps [{owner}/{repo}](https://github.com/{owner}/{repo}) from {match['tag']} to {release['tag_name']}.",
                        f"- [Release notes]({release['html_url']})",
                        f"- [Compare changes](https://github.com/{owner}/{repo}/compare/{match['commit']}...{commit})",
                    ]
                ),
                package=f"{owner}/{repo}",
                value=value,
                version_from=match["tag"].removeprefix("v"),
                version_to=release["tag_name"].removeprefix("v"),
            )
            if packaging.version.Version(release["tag_name"]) > packaging.version.Version(match["tag"])
            else f"{dependency.option} = {value}"
        )

    def release_tag_archive(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(MatchTag | None, self._archive_tag.fullmatch(dependency.value))
        if not match:
            return None
        release = self._request_release(match["name"], match["tag"])
        if not release:
            return None
        owner, repo = self._parse_link(release["url"])
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}https://github.com/{owner}/{repo}/archive/refs/tags/{release['tag_name']}.{match['variant']} ; {release['tag_name']}"
        return (
            Models.Result(
                body="\n".join(
                    [
                        f"Bumps [{owner}/{repo}](https://github.com/{owner}/{repo}) from {match['tag']} to {release['tag_name']}.",
                        f"- [Release notes]({release['html_url']})",
                        f"- [Compare changes](https://github.com/{owner}/{repo}/compare/{match['tag']}...{release['tag_name']})",
                    ]
                ),
                package=f"{owner}/{repo}",
                value=value,
                version_from=match["tag"].removeprefix("v"),
                version_to=release["tag_name"].removeprefix("v"),
            )
            if packaging.version.Version(release["tag_name"]) > packaging.version.Version(match["tag"])
            else f"{dependency.option} = {value}"
        )

    def release_tag_asset(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(MatchDownload | None, self._download.fullmatch(dependency.value))
        if not match:
            return None
        release = self._request_release(match["name"], match["tag"])
        if not release:
            return None
        names = {
            match["asset"],
            match["asset"].replace(match["tag"], release["tag_name"]),
        }
        for asset in release["assets"]:
            if asset["name"] not in names:
                continue
            owner, repo = self._parse_link(release["url"])
            value = f"{'' if match['package'] is None else f'{match["package"]} @ '}{asset['browser_download_url']} ; {release['tag_name']}"
            return (
                Models.Result(
                    body="\n".join(
                        [
                            f"Bumps [{owner}/{repo}](https://github.com/{owner}/{repo}) from {match['tag']} to {release['tag_name']}.",
                            f"- [Release notes]({release['html_url']})",
                            f"- [Compare changes](https://github.com/{owner}/{repo}/compare/{match['tag']}...{release['tag_name']})",
                        ]
                    ),
                    package=f"{owner}/{repo}",
                    value=value,
                    version_from=match["tag"].removeprefix("v"),
                    version_to=release["tag_name"].removeprefix("v"),
                )
                if packaging.version.Version(release["tag_name"]) > packaging.version.Version(match["tag"])
                else f"{dependency.option} = {value}"
            )
        return None

    def release_tag_ball(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(MatchTag | None, self._ball_tag.fullmatch(dependency.value))
        if not match:
            return None
        release = self._request_release(match["name"], match["tag"])
        if not release:
            return None
        ball = release[f"{match['variant']}ball_url"]
        owner, repo = self._parse_link(ball)
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}{ball} ; {release['tag_name']}"
        return (
            Models.Result(
                body="\n".join(
                    [
                        f"Bumps [{owner}/{repo}](https://github.com/{owner}/{repo}) from {match['tag']} to {release['tag_name']}.",
                        f"- [Release notes]({release['html_url']})",
                        f"- [Compare changes](https://github.com/{owner}/{repo}/compare/{match['tag']}...{release['tag_name']})",
                    ]
                ),
                package=f"{owner}/{repo}",
                value=value,
                version_from=match["tag"].removeprefix("v"),
                version_to=release["tag_name"].removeprefix("v"),
            )
            if packaging.version.Version(release["tag_name"]) > packaging.version.Version(match["tag"])
            else f"{dependency.option} = {value}"
        )

    def release_tag_commit_archive(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(MatchCommit | None, self._archive_commit.fullmatch(dependency.value))
        if not match:
            return None
        release = self._request_release(match["name"], match["tag"])
        if not release:
            return None
        owner, repo = self._parse_link(release["url"])
        commit = self._request_tag_id(owner, repo, release["tag_name"])["object"]["sha"]
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}https://github.com/{owner}/{repo}/archive/{commit}.{match['variant']} ; {release['tag_name']}"
        return (
            Models.Result(
                body="\n".join(
                    [
                        f"Bumps [{owner}/{repo}](https://github.com/{owner}/{repo}) from {match['tag']} to {release['tag_name']}.",
                        f"- [Release notes]({release['html_url']})",
                        f"- [Compare changes](https://github.com/{owner}/{repo}/compare/{match['commit']}...{commit})",
                    ]
                ),
                package=f"{owner}/{repo}",
                value=value,
                version_from=match["tag"].removeprefix("v"),
                version_to=release["tag_name"].removeprefix("v"),
            )
            if packaging.version.Version(release["tag_name"]) > packaging.version.Version(match["tag"])
            else f"{dependency.option} = {value}"
        )

    def release_tag_commit_ball(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(MatchCommit | None, self._ball_commit.fullmatch(dependency.value))
        if not match:
            return None
        release = self._request_release(match["name"], match["tag"])
        if not release:
            return None
        owner, repo = self._parse_link(release["url"])
        commit = self._request_tag_id(owner, repo, release["tag_name"])["object"]["sha"]
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}https://api.github.com/repos/{owner}/{repo}/{match['variant']}ball/{commit} ; {release['tag_name']}"
        return (
            Models.Result(
                body="\n".join(
                    [
                        f"Bumps [{owner}/{repo}](https://github.com/{owner}/{repo}) from {match['tag']} to {release['tag_name']}.",
                        f"- [Release notes]({release['html_url']})",
                        f"- [Compare changes](https://github.com/{owner}/{repo}/compare/{match['commit']}...{commit})",
                    ]
                ),
                package=f"{owner}/{repo}",
                value=value,
                version_from=match["tag"].removeprefix("v"),
                version_to=release["tag_name"].removeprefix("v"),
            )
            if packaging.version.Version(release["tag_name"]) > packaging.version.Version(match["tag"])
            else f"{dependency.option} = {value}"
        )

    def release_tag_git(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(MatchTag | None, self._git_tag.fullmatch(dependency.value))
        if not match:
            return None
        release = self._request_release(match["name"], match["tag"])
        if not release:
            return None
        owner, repo = self._parse_link(release["url"])
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}{match['variant']}://github.com/{owner}/{repo}.git#{release['tag_name']} ; {release['tag_name']}"
        return (
            Models.Result(
                body="\n".join(
                    [
                        f"Bumps [{owner}/{repo}](https://github.com/{owner}/{repo}) from {match['tag']} to {release['tag_name']}.",
                        f"- [Release notes]({release['html_url']})",
                        f"- [Compare changes](https://github.com/{owner}/{repo}/compare/{match['tag']}...{release['tag_name']})",
                    ]
                ),
                package=f"{owner}/{repo}",
                value=value,
                version_from=match["tag"].removeprefix("v"),
                version_to=release["tag_name"].removeprefix("v"),
            )
            if packaging.version.Version(release["tag_name"]) > packaging.version.Version(match["tag"])
            else f"{dependency.option} = {value}"
        )

    def tag_archive(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(MatchTag | None, self._archive_tag.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["tag"])
        tag = self._request_tag(match["name"], version)
        if not tag:
            return None
        owner, repo = self._parse_link(tag["commit"]["url"])
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}https://github.com/{owner}/{repo}/archive/refs/tags/{tag['name']}.{match['variant']} ; {tag['name']}"
        return (
            Models.Result(
                body="\n".join(
                    [
                        f"Bumps [{owner}/{repo}](https://github.com/{owner}/{repo}) from {match['tag']} to {tag['name']}.",
                        f"- [Tag](https://github.com/{owner}/{repo}/releases/tag/{tag['name']})",
                        f"- [Compare changes](https://github.com/{owner}/{repo}/compare/{match['tag']}...{tag['name']})",
                    ]
                ),
                package=f"{owner}/{repo}",
                value=value,
                version_from=match["tag"].removeprefix("v"),
                version_to=tag["name"].removeprefix("v"),
            )
            if packaging.version.Version(tag["name"]) > version
            else f"{dependency.option} = {value}"
        )

    def tag_ball(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(MatchTag | None, self._ball_tag.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["tag"])
        tag = self._request_tag(match["name"], version)
        if not tag:
            return None
        ball = tag[f"{match['variant']}ball_url"]
        owner, repo = self._parse_link(ball)
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}{ball} ; {tag['name']}"
        return (
            Models.Result(
                body="\n".join(
                    [
                        f"Bumps [{owner}/{repo}](https://github.com/{owner}/{repo}) from {match['tag']} to {tag['name']}.",
                        f"- [Tag](https://github.com/{owner}/{repo}/releases/tag/{tag['name']})",
                        f"- [Compare changes](https://github.com/{owner}/{repo}/compare/{match['tag']}...{tag['name']})",
                    ]
                ),
                package=f"{owner}/{repo}",
                value=value,
                version_from=match["tag"].removeprefix("v"),
                version_to=tag["name"].removeprefix("v"),
            )
            if packaging.version.Version(tag["name"]) > version
            else f"{dependency.option} = {value}"
        )

    def tag_commit_archive(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(MatchCommit | None, self._archive_commit.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["tag"])
        tag = self._request_tag(match["name"], version)
        if not tag:
            return None
        owner, repo = self._parse_link(tag["commit"]["url"])
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}https://github.com/{owner}/{repo}/archive/{tag['commit']['sha']}.{match['variant']} ; {tag['name']}"
        return (
            Models.Result(
                body="\n".join(
                    [
                        f"Bumps [{owner}/{repo}](https://github.com/{owner}/{repo}) from {match['tag']} to {tag['name']}.",
                        f"- [Tag](https://github.com/{owner}/{repo}/releases/tag/{tag['name']})",
                        f"- [Compare changes](https://github.com/{owner}/{repo}/compare/{match['commit']}...{tag['commit']['sha']})",
                    ]
                ),
                package=f"{owner}/{repo}",
                value=value,
                version_from=match["tag"].removeprefix("v"),
                version_to=tag["name"].removeprefix("v"),
            )
            if packaging.version.Version(tag["name"]) > version
            else f"{dependency.option} = {value}"
        )

    def tag_commit_ball(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(MatchCommit | None, self._ball_commit.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["tag"])
        tag = self._request_tag(match["name"], version)
        if not tag:
            return None
        owner, repo = self._parse_link(tag["commit"]["url"])
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}https://api.github.com/repos/{owner}/{repo}/{match['variant']}ball/{tag['commit']['sha']} ; {tag['name']}"
        return (
            Models.Result(
                body="\n".join(
                    [
                        f"Bumps [{owner}/{repo}](https://github.com/{owner}/{repo}) from {match['tag']} to {tag['name']}.",
                        f"- [Tag](https://github.com/{owner}/{repo}/releases/tag/{tag['name']})",
                        f"- [Compare changes](https://github.com/{owner}/{repo}/compare/{match['commit']}...{tag['commit']['sha']})",
                    ]
                ),
                package=f"{owner}/{repo}",
                value=value,
                version_from=match["tag"].removeprefix("v"),
                version_to=tag["name"].removeprefix("v"),
            )
            if packaging.version.Version(tag["name"]) > version
            else f"{dependency.option} = {value}"
        )

    def tag_commit_git(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(MatchCommit | None, self._git_commit.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["tag"])
        tag = self._request_tag(match["name"], version)
        if not tag:
            return None
        owner, repo = self._parse_link(tag["commit"]["url"])
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}{match['variant']}://github.com/{owner}/{repo}.git#{tag['commit']['sha']} ; {tag['name']}"
        return (
            Models.Result(
                body="\n".join(
                    [
                        f"Bumps [{owner}/{repo}](https://github.com/{owner}/{repo}) from {match['tag']} to {tag['name']}.",
                        f"- [Tag](https://github.com/{owner}/{repo}/releases/tag/{tag['name']})",
                        f"- [Compare changes](https://github.com/{owner}/{repo}/compare/{match['commit']}...{tag['commit']['sha']})",
                    ]
                ),
                package=f"{owner}/{repo}",
                value=value,
                version_from=match["tag"].removeprefix("v"),
                version_to=tag["name"].removeprefix("v"),
            )
            if packaging.version.Version(tag["name"]) > version
            else f"{dependency.option} = {value}"
        )

    def tag_git(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(MatchTag | None, self._git_tag.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["tag"])
        tag = self._request_tag(match["name"], version)
        if not tag:
            return None
        owner, repo = self._parse_link(tag["commit"]["url"])
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}{match['variant']}://github.com/{owner}/{repo}.git#{tag['name']} ; {tag['name']}"
        return (
            Models.Result(
                body="\n".join(
                    [
                        f"Bumps [{owner}/{repo}](https://github.com/{owner}/{repo}) from {match['tag']} to {tag['name']}.",
                        f"- [Tag](https://github.com/{owner}/{repo}/releases/tag/{tag['name']})",
                        f"- [Compare changes](https://github.com/{owner}/{repo}/compare/{match['tag']}...{tag['name']})",
                    ]
                ),
                package=f"{owner}/{repo}",
                value=value,
                version_from=match["tag"].removeprefix("v"),
                version_to=tag["name"].removeprefix("v"),
            )
            if packaging.version.Version(tag["name"]) > version
            else f"{dependency.option} = {value}"
        )

    def _parse_link(self, url: str) -> tuple[str, str]:
        fragments = url.split("/", 6)
        return fragments[4], fragments[5]

    def _request_commit_id(self, name: str, commit: str) -> CommitResponse:
        return typing.cast(
            CommitResponse,
            self._request(f"https://api.github.com/repos/{name}/commits/{commit}").json(),
        )

    def _request_release(self, name: str, tag: str) -> Release | None:
        version = packaging.version.Version(tag)
        prerelease = version.is_prerelease
        if not prerelease:
            try:
                prerelease = self._request_release_id(name, tag)["prerelease"]
            except Exception:
                print(f"::debug::Invalid release: {name} {tag}")
        latest = None
        url = f"https://api.github.com/repos/{name}/releases?per_page=100"
        while url:
            response = self._request(url)
            for _release in typing.cast(list[Release], response.json()):
                try:
                    _version = packaging.version.Version(_release["tag_name"])
                    _published_at = _release.get("published_at")
                    if (
                        (_version.is_prerelease and not prerelease)
                        or _published_at is None
                        or datetime.datetime.now(datetime.timezone.utc)
                        - datetime.datetime.fromisoformat(_published_at.replace("Z", "+00:00"))
                        < datetime.timedelta(days=Models.Config.COOLDOWN)
                    ):
                        continue
                    elif _version > version:
                        return _release
                    elif not latest:
                        latest = _release
                except packaging.version.InvalidVersion:
                    _owner, _repo = self._parse_link(_release["url"])
                    print(f"::debug::Invalid version: {_owner}/{_repo} {_release['tag_name']}")
                    continue
            url = response.links.get("next", {}).get("url")
        return latest

    def _request_release_id(self, name: str, tag: str) -> Release:
        return typing.cast(
            Release,
            self._request(f"https://api.github.com/repos/{name}/releases/tags/{tag}").json(),
        )

    def _request_tag(self, name: str, version: packaging.version.Version) -> Tag | None:
        latest = None
        url = f"https://api.github.com/repos/{name}/tags?per_page=100"
        while url:
            response = self._request(url)
            for _tag in typing.cast(list[Tag], response.json()):
                try:
                    _version = packaging.version.Version(_tag["name"])
                    if _version.is_prerelease and not version.is_prerelease:
                        continue
                    elif _version > version:
                        _commit = self._request_commit_id(name, _tag["commit"]["sha"])
                        if datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(
                            _commit["commit"]["committer"]["date"].replace("Z", "+00:00")
                        ) < datetime.timedelta(days=Models.Config.COOLDOWN):
                            continue
                        return _tag
                    elif not latest:
                        latest = _tag
                except packaging.version.InvalidVersion:
                    _owner, _repo = self._parse_link(_tag["commit"]["url"])
                    print(f"::debug::Invalid version: {_owner}/{_repo} {_tag['name']}")
                    continue
            url = response.links.get("next", {}).get("url")
        return latest

    def _request_tag_id(self, owner: str, repo: str, tag: str) -> TagID:
        return typing.cast(
            TagID,
            self._request(f"https://api.github.com/repos/{owner}/{repo}/git/refs/tags/{tag}").json(),
        )

    def _request(self, url: str) -> requests.Response:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": Models.Config.USER_AGENT,
            "X-GitHub-Api-Version": "2026-03-10",
        }
        token = os.getenv("GITHUB_TOKEN")
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        response = requests.get(
            url=url,
            headers=headers,
            timeout=Models.Config.TIMEOUT,
        )
        response.raise_for_status()
        return response
