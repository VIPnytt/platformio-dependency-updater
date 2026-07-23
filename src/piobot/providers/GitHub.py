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
    cooldown: datetime.timedelta
    _archive_commit: re.Pattern[str]
    _archive_tag: re.Pattern[str]
    _ball_commit: re.Pattern[str]
    _ball_tag: re.Pattern[str]
    _download: re.Pattern[str]
    _git_commit: re.Pattern[str]
    _git_tag: re.Pattern[str]

    def __init__(self, cooldown: datetime.timedelta) -> None:
        """
        Initialize dependency URL matching patterns and store the release eligibility cooldown.

        Parameters:
                cooldown (datetime.timedelta): Minimum age required for a release or tag to be eligible.
        """
        self.cooldown = cooldown
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
        """
        Resolve a GitHub commit-based Git dependency to the commit associated with a newer release tag.

        Parameters:
            dependency (Models.Dependency): Dependency value containing the GitHub repository, commit, and release tag.

        Returns:
            Models.Result | str | None: A release update result, a formatted dependency string when no newer release exists, or `None` when the dependency does not match or no release is found.
        """
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
        """
        Resolve a GitHub archive dependency from its current tag to a newer release tag.

        Args:
            dependency (Models.Dependency): Dependency containing the GitHub archive URL.

        Returns:
            Models.Result | str | None: A release update result, a formatted dependency
            value when no newer release is available, or `None` when the dependency
            does not match or no release can be resolved.
        """
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
        """Resolve a GitHub release asset dependency to a newer release when available.

        Parameters:
            dependency (Models.Dependency): Dependency value containing a GitHub release asset URL.

        Returns:
            Models.Result: Release update details when a newer release asset is found.
            str: Formatted dependency assignment when the resolved release is not newer.
            None: If the dependency does not match or no corresponding release asset is found.
        """
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
        """Resolve a GitHub tarball or zipball dependency to a newer release tag.

        Parameters:
                dependency (Models.Dependency): Dependency value containing a GitHub ball URL and tag.

        Returns:
                Models.Result | str | None: A release update result or formatted dependency value, or `None` when the value does not match or no suitable release is found.
        """
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
        """
        Resolve a commit-based GitHub archive dependency to a newer release when available.

        Parameters:
                dependency (Models.Dependency): Dependency containing the archive URL and version information.

        Returns:
                Models.Result: Updated dependency details when a newer release is found.
                str: Formatted dependency assignment when no newer release is available.
                None: If the dependency does not match the supported archive format or no release is found.
        """
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
        """
        Resolve a commit-based API tarball or zipball dependency to a newer GitHub release.

        Parameters:
                dependency (Models.Dependency): Dependency value containing the repository, commit, tag, and archive variant.

        Returns:
                Models.Result | str | None: A release update result or formatted dependency assignment, or `None` when the value does not match or no suitable release is found.
        """
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
        """
        Update a GitHub Git dependency to a newer release tag.

        Parameters:
                dependency (Models.Dependency): Dependency value containing the repository and current release tag.

        Returns:
                Models.Result: Release update details when a newer release is available.
                str: Formatted dependency assignment when the resolved release is not newer.
                None: If the dependency does not match the supported Git tag format or no release is found.
        """
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
        """
        Resolve a GitHub archive dependency to a newer compatible tag.

        Parameters:
                dependency (Models.Dependency): Dependency containing the archive URL and its current tag.

        Returns:
                Models.Result: Update details when a newer tag is available.
                str: A formatted dependency assignment when no newer tag is available.
                None: If the dependency does not match the expected archive format or no suitable tag is found.
        """
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
        """
        Resolve a GitHub tarball or zipball dependency to a newer compatible tag.

        Parameters:
            dependency (Models.Dependency): Dependency containing the GitHub ball URL and update option.

        Returns:
            Models.Result: Update details when a newer tag is found.
            str: Formatted dependency assignment when the resolved tag is not newer.
            None: If the dependency format is unsupported or no suitable tag is found.
        """
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
        """
        Resolve a GitHub archive dependency that identifies a commit and tag.

        Parameters:
            dependency (Models.Dependency): Dependency specification containing the archive URL.

        Returns:
            Models.Result | str | None: Updated dependency metadata or formatted dependency string, or `None` when the value is not a matching archive URL or no suitable tag is found.
        """
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
        """
        Resolve a commit-based GitHub tarball or zipball dependency to a newer tag.

        Parameters:
                dependency (Models.Dependency): Dependency containing the GitHub ball URL and version tag.

        Returns:
                Models.Result: Update details when a newer tag is available.
                str: Formatted dependency replacement when no newer tag is available.
                None: If the dependency does not match the supported format or no tag is found.
        """
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
        """
        Resolve a Git dependency pinned to a commit by updating it to a newer compatible tag.

        Parameters:
            dependency (Models.Dependency): Dependency value containing the repository, commit, and tag information.

        Returns:
            Models.Result | str | None: A version update result, a formatted dependency assignment when no newer tag is available, or `None` when the dependency does not match or no tag can be resolved.
        """
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
        """
        Fetch commit metadata from GitHub for a repository and commit reference.

        Parameters:
                name (str): Repository name in `owner/repository` format.
                commit (str): Commit SHA or reference.

        Returns:
                CommitResponse: Commit metadata returned by the GitHub API.
        """
        return typing.cast(
            CommitResponse,
            self._request(f"https://api.github.com/repos/{name}/commits/{commit}").json(),
        )

    def _request_release(self, name: str, tag: str) -> Release | None:
        """
        Find a suitable GitHub release for a repository and version tag.

        Parameters:
            name (str): GitHub repository name in `owner/repository` format.
            tag (str): Current release tag used as the version baseline.

        Returns:
            Release | None: A newer eligible release, the latest eligible release, or `None` if no suitable release exists.
        """
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
                        < self.cooldown
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
        """Fetch release details for a repository tag.

        Parameters:
                name (str): The repository name.
                tag (str): The release tag.

        Returns:
                Release: The release metadata for the specified tag.
        """
        return typing.cast(
            Release,
            self._request(f"https://api.github.com/repos/{name}/releases/tags/{tag}").json(),
        )

    def _request_tag(self, name: str, version: packaging.version.Version) -> Tag | None:
        """
        Find an eligible GitHub tag for a requested version.

        Parameters:
            name (str): GitHub repository name in `owner/repository` format.
            version (packaging.version.Version): Current dependency version used for comparison.

        Returns:
            Tag | None: The first eligible newer tag, the latest acceptable fallback tag, or `None` when no tags are available.
        """
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
                        if (
                            datetime.datetime.now(datetime.timezone.utc)
                            - datetime.datetime.fromisoformat(
                                _commit["commit"]["committer"]["date"].replace("Z", "+00:00")
                            )
                            < self.cooldown
                        ):
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
        """Retrieve metadata for a GitHub repository tag reference.

        Parameters:
                owner (str): GitHub repository owner.
                repo (str): GitHub repository name.
                tag (str): Tag name.

        Returns:
                TagID: Metadata for the specified tag reference.
        """
        return typing.cast(
            TagID,
            self._request(f"https://api.github.com/repos/{owner}/{repo}/git/refs/tags/{tag}").json(),
        )

    def _request(self, url: str) -> requests.Response:
        """
        Send an authenticated request to the GitHub API.

        Parameters:
                url (str): The API URL to request.

        Returns:
                requests.Response: The successful HTTP response.
        """
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
