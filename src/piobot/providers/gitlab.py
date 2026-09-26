import datetime
import re
import typing

import packaging.version
import requests

from .. import models


class Commit(typing.TypedDict):
    created_at: str
    id: str
    web_url: str


class Links(typing.TypedDict):
    self: str


class MatchCommit(typing.TypedDict):
    commit: str
    owner: str
    package: str | None
    repo: str
    tag: str
    variant: str


class MatchTag(typing.TypedDict):
    owner: str
    package: str | None
    repo: str
    tag: str
    variant: str


class Source(typing.TypedDict):
    format: str
    url: str


class Assets(typing.TypedDict):
    sources: list[Source]


class Release(typing.TypedDict):
    assets: Assets
    commit: Commit
    created_at: str
    released_at: str | None
    tag_name: str
    _links: Links


class Tag(typing.TypedDict):
    commit: Commit
    name: str


class Resolve:
    cooldown: datetime.timedelta
    _archive_commit: re.Pattern[str]
    _archive_tag: re.Pattern[str]
    _git_commit: re.Pattern[str]
    _git_tag: re.Pattern[str]

    def __init__(self, cooldown: datetime.timedelta) -> None:
        """
        Initialize a resolver with the minimum age required for releases and tags.

        Parameters:
            cooldown (datetime.timedelta): Minimum age, inclusive, measured from the later of release creation
                and publication, or from the commit creation time for tags.
        """
        self.cooldown = cooldown
        self._archive_commit = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://gitlab\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)/-/archive/(?P<commit>[0-9a-f]{40})/[^/\s]+\.(?P<variant>tar|tar\.gz|zip)\s*;\s*(?P<tag>\S+)$"
        )
        self._archive_tag = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://gitlab\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)/-/archive/(?P<tag>[^/\s]+)/[^/\s]+\.(?P<variant>tar|tar\.gz|zip)(?:\s*;.*)?$"
        )
        self._git_commit = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?(?P<variant>git|git\+https|git\+ssh|https)://gitlab\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)\.git#(?P<commit>[0-9a-f]{40})\s*;\s*(?P<tag>\S+)$"
        )
        self._git_tag = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?(?P<variant>git|git\+https|git\+ssh|https)://gitlab\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)\.git#(?P<tag>[^/\s]+)(?:\s*;.*)?$"
        )

    def release_tag_archive(self, dependency: models.Dependency) -> models.Result | str | None:
        """
        Resolve a tag-based GitLab dependency to an eligible release asset.

        Selects the first eligible newer version in API order, or the first eligible version otherwise.
        Candidates must meet the cooldown; prereleases are eligible only if the current version is a prerelease.

        HTTP, connection, timeout, and malformed API response errors propagate. Invalid candidate versions are skipped.

        Parameters:
                dependency (models.Dependency): Dependency expression containing a GitLab tag archive URL.

        Returns:
                models.Result: Update details when the selected release has a newer version and matching archive format.
                str: Assignment string when the selected release is not newer and has a matching archive format.
                None: If the URL is unsupported, no eligible release exists, or that release lacks the archive format.

        Raises:
            packaging.version.InvalidVersion: If the dependency's current tag is not a valid version.
        """
        match = typing.cast(MatchTag | None, self._archive_tag.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["tag"])
        release = self._request_release(match["owner"], match["repo"], version)
        if release is None:
            return None
        owner, repo = self._parse_link(release["_links"]["self"])
        for source in release["assets"]["sources"]:
            if source["format"] != match["variant"]:
                continue
            value = (
                f"{'' if match['package'] is None else f'{match["package"]} @ '}{source['url']} ; {release['tag_name']}"
            )
            return (
                models.Result(
                    body="\n".join(
                        [
                            f"Bumps [{owner}/{repo}](https://gitlab.com/{owner}/{repo}) from {match['tag']} to {release['tag_name']}.",
                            f"- [Release notes]({release['_links']['self']})",
                            f"- [Compare changes](https://gitlab.com/{owner}/{repo}/-/compare/{match['tag']}..{release['tag_name']})",
                        ]
                    ),
                    package=f"{owner}/{repo}",
                    value=value,
                    version_from=match["tag"].removeprefix("v"),
                    version_to=release["tag_name"].removeprefix("v"),
                )
                if packaging.version.Version(release["tag_name"]) > version
                else f"{dependency.option} = {value}"
            )
        return None

    def release_tag_git(self, dependency: models.Dependency) -> models.Result | str | None:
        """
        Resolve a GitLab Git dependency to an eligible release tag.

        Selects the first eligible newer version in API order, or the first eligible version otherwise.
        Candidates must meet the cooldown; prereleases are eligible only if the current version is a prerelease.
        Preserves the package alias and URL scheme (`git`, `git+https`, `git+ssh`, or `https`).

        HTTP, connection, timeout, and malformed API response errors propagate. Invalid candidate versions are skipped.

        Parameters:
            dependency (models.Dependency): GitLab.com `.git#<tag>` URL whose fragment supplies the current version.

        Returns:
            models.Result: Update details when the selected release has a newer version.
            str: Assignment string when the selected release is not newer.
            None: If the URL is unsupported or no eligible release is found.

        Raises:
            packaging.version.InvalidVersion: If the dependency's current tag is not a valid version.
        """
        match = typing.cast(MatchTag | None, self._git_tag.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["tag"])
        release = self._request_release(match["owner"], match["repo"], version)
        if release is None:
            return None
        owner, repo = self._parse_link(release["_links"]["self"])
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}{match['variant']}://gitlab.com/{owner}/{repo}.git#{release['tag_name']} ; {release['tag_name']}"
        return (
            models.Result(
                body="\n".join(
                    [
                        f"Bumps [{owner}/{repo}](https://gitlab.com/{owner}/{repo}) from {match['tag']} to {release['tag_name']}.",
                        f"- [Release notes]({release['_links']['self']})",
                        f"- [Compare changes](https://gitlab.com/{owner}/{repo}/-/compare/{match['tag']}..{release['tag_name']})",
                    ]
                ),
                package=f"{owner}/{repo}",
                value=value,
                version_from=match["tag"].removeprefix("v"),
                version_to=release["tag_name"].removeprefix("v"),
            )
            if packaging.version.Version(release["tag_name"]) > version
            else f"{dependency.option} = {value}"
        )

    def release_tag_commit_archive(self, dependency: models.Dependency) -> models.Result | str | None:
        """
        Resolve a commit-archive dependency to an eligible GitLab release commit.

        Selects the first eligible newer version in API order, or the first eligible version otherwise.
        Candidates must meet the cooldown; prereleases are eligible only if the current version is a prerelease.

        HTTP, connection, timeout, and malformed API response errors propagate. Invalid candidate versions are skipped.

        Parameters:
                dependency (models.Dependency): Dependency with a 40-character lowercase commit hash in its archive URL
                    and a required `; tag` suffix supplying the current version.

        Returns:
                models.Result: Update details when the selected release has a newer version and matching archive format.
                str: Assignment string when the selected release is not newer and has a matching archive format.
                None: If the URL is unsupported, no eligible release exists, or that release lacks the archive format.

        Raises:
            packaging.version.InvalidVersion: If the dependency's current tag is not a valid version.
        """
        match = typing.cast(MatchCommit | None, self._archive_commit.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["tag"])
        release = self._request_release(match["owner"], match["repo"], version)
        if release is None:
            return None
        owner, repo = self._parse_link(release["_links"]["self"])
        for source in release["assets"]["sources"]:
            if source["format"] != match["variant"]:
                continue
            value = f"{'' if match['package'] is None else f'{match["package"]} @ '}https://gitlab.com/{owner}/{repo}/-/archive/{release['commit']['id']}/{repo}-{release['commit']['id']}.{match['variant']} ; {release['tag_name']}"
            return (
                models.Result(
                    body="\n".join(
                        [
                            f"Bumps [{owner}/{repo}](https://gitlab.com/{owner}/{repo}) from {match['tag']} to {release['tag_name']}.",
                            f"- [Release notes]({release['_links']['self']})",
                            f"- [Compare changes](https://gitlab.com/{owner}/{repo}/-/compare/{match['commit']}..{release['commit']['id']})",
                        ]
                    ),
                    package=f"{owner}/{repo}",
                    value=value,
                    version_from=match["tag"].removeprefix("v"),
                    version_to=release["tag_name"].removeprefix("v"),
                )
                if packaging.version.Version(release["tag_name"]) > version
                else f"{dependency.option} = {value}"
            )
        return None

    def release_tag_commit_git(self, dependency: models.Dependency) -> models.Result | str | None:
        """
        Resolve a GitLab Git dependency to an eligible release commit.

        Selects the first eligible newer version in API order, or the first eligible version otherwise.
        Candidates must meet the cooldown; prereleases are eligible only if the current version is a prerelease.
        Preserves the package alias and URL scheme (`git`, `git+https`, `git+ssh`, or `https`).

        HTTP, connection, timeout, and malformed API response errors propagate. Invalid candidate versions are skipped.

        Parameters:
            dependency (models.Dependency): GitLab.com `.git#<commit>` URL with a 40-character lowercase commit hash
                and a required `; tag` suffix supplying the current version.

        Returns:
            models.Result: Update details when the selected release has a newer version.
            str: Assignment string when the selected release is not newer.
            None: If the URL is unsupported or no eligible release is found.

        Raises:
            packaging.version.InvalidVersion: If the dependency's current tag is not a valid version.
        """
        match = typing.cast(MatchCommit | None, self._git_commit.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["tag"])
        release = self._request_release(match["owner"], match["repo"], version)
        if release is None:
            return None
        owner, repo = self._parse_link(release["_links"]["self"])
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}{match['variant']}://gitlab.com/{owner}/{repo}.git#{release['commit']['id']} ; {release['tag_name']}"
        return (
            models.Result(
                body="\n".join(
                    [
                        f"Bumps [{owner}/{repo}](https://gitlab.com/{owner}/{repo}) from {match['tag']} to {release['tag_name']}.",
                        f"- [Release notes]({release['_links']['self']})",
                        f"- [Compare changes](https://gitlab.com/{owner}/{repo}/-/compare/{match['commit']}..{release['commit']['id']})",
                    ]
                ),
                package=f"{owner}/{repo}",
                value=value,
                version_from=match["tag"].removeprefix("v"),
                version_to=release["tag_name"].removeprefix("v"),
            )
            if packaging.version.Version(release["tag_name"]) > version
            else f"{dependency.option} = {value}"
        )

    def tag_archive(self, dependency: models.Dependency) -> models.Result | str | None:
        """
        Resolve a tag-based GitLab dependency to an eligible tag archive.

        Selects the first eligible newer version in API order, or the first eligible version otherwise.
        Candidates must meet the cooldown; prereleases are eligible only if the current version is a prerelease.

        HTTP, connection, timeout, and malformed API response errors propagate. Invalid candidate versions are skipped.

        Parameters:
            dependency (models.Dependency): Dependency expression containing a GitLab tag archive reference.

        Returns:
            models.Result: Update metadata when a newer eligible tag is available.
            str: Dependency assignment when the resolved tag is not newer.
            None: If the dependency format is unsupported or no eligible tag is found.

        Raises:
            packaging.version.InvalidVersion: If the dependency's current tag is not a valid version.
        """
        match = typing.cast(MatchTag | None, self._archive_tag.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["tag"])
        tag = self._request_tag(match["owner"], match["repo"], version)
        if tag is None:
            return None
        owner, repo = self._parse_link(tag["commit"]["web_url"])
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}https://gitlab.com/{owner}/{repo}/-/archive/{tag['name']}/{repo}-{tag['name']}.{match['variant']} ; {tag['name']}"
        return (
            models.Result(
                body="\n".join(
                    [
                        f"Bumps [{owner}/{repo}](https://gitlab.com/{owner}/{repo}) from {match['tag']} to {tag['name']}.",
                        f"- [Tag](https://gitlab.com/{owner}/{repo}/-/tags/{tag['name']})",
                        f"- [Compare changes](https://gitlab.com/{owner}/{repo}/-/compare/{match['tag']}..{tag['name']})",
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

    def tag_git(self, dependency: models.Dependency) -> models.Result | str | None:
        """
        Resolve a GitLab Git dependency to an eligible tag.

        Selects the first eligible newer version in API order, or the first eligible version otherwise.
        Candidates must meet the cooldown; prereleases are eligible only if the current version is a prerelease.
        Preserves the package alias and URL scheme (`git`, `git+https`, `git+ssh`, or `https`).

        HTTP, connection, timeout, and malformed API response errors propagate. Invalid candidate versions are skipped.

        Parameters:
            dependency (models.Dependency): GitLab.com `.git#<tag>` URL whose fragment supplies the current version.

        Returns:
            models.Result: Update details when the selected tag has a newer version.
            str: Assignment string when the selected tag is not newer.
            None: If the URL is unsupported or no eligible tag is found.

        Raises:
            packaging.version.InvalidVersion: If the dependency's current tag is not a valid version.
        """
        match = typing.cast(MatchTag | None, self._git_tag.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["tag"])
        tag = self._request_tag(match["owner"], match["repo"], version)
        if tag is None:
            return None
        owner, repo = self._parse_link(tag["commit"]["web_url"])
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}{match['variant']}://gitlab.com/{owner}/{repo}.git#{tag['name']} ; {tag['name']}"
        return (
            models.Result(
                body="\n".join(
                    [
                        f"Bumps [{owner}/{repo}](https://gitlab.com/{owner}/{repo}) from {match['tag']} to {tag['name']}.",
                        f"- [Tag](https://gitlab.com/{owner}/{repo}/-/tags/{tag['name']})",
                        f"- [Compare changes](https://gitlab.com/{owner}/{repo}/-/compare/{match['tag']}..{tag['name']})",
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

    def tag_commit_archive(self, dependency: models.Dependency) -> models.Result | str | None:
        """
        Resolve a commit archive dependency to an eligible GitLab tag commit.

        Selects the first eligible newer version in API order, or the first eligible version otherwise.
        Candidates must meet the cooldown; prereleases are eligible only if the current version is a prerelease.

        HTTP, connection, timeout, and malformed API response errors propagate. Invalid candidate versions are skipped.

        Parameters:
            dependency (models.Dependency): Dependency with a 40-character lowercase commit hash in its archive URL
                and a required `; tag` suffix supplying the current version.

        Returns:
            models.Result: Updated dependency details when a newer tag is available.
            str: Assignment string when the resolved tag is not newer.
            None: If the dependency does not match or no eligible tag is found.

        Raises:
            packaging.version.InvalidVersion: If the dependency's current tag is not a valid version.
        """
        match = typing.cast(MatchCommit | None, self._archive_commit.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["tag"])
        tag = self._request_tag(match["owner"], match["repo"], version)
        if tag is None:
            return None
        owner, repo = self._parse_link(tag["commit"]["web_url"])
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}https://gitlab.com/{owner}/{repo}/-/archive/{tag['commit']['id']}/{repo}-{tag['commit']['id']}.{match['variant']} ; {tag['name']}"
        return (
            models.Result(
                body="\n".join(
                    [
                        f"Bumps [{owner}/{repo}](https://gitlab.com/{owner}/{repo}) from {match['tag']} to {tag['name']}.",
                        f"- [Tag](https://gitlab.com/{owner}/{repo}/-/tags/{tag['name']})",
                        f"- [Compare changes](https://gitlab.com/{owner}/{repo}/-/compare/{match['commit']}..{tag['commit']['id']})",
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

    def tag_commit_git(self, dependency: models.Dependency) -> models.Result | str | None:
        """
        Resolve a GitLab Git dependency to an eligible tag commit.

        Selects the first eligible newer version in API order, or the first eligible version otherwise.
        Candidates must meet the cooldown; prereleases are eligible only if the current version is a prerelease.
        Preserves the package alias and URL scheme (`git`, `git+https`, `git+ssh`, or `https`).

        HTTP, connection, timeout, and malformed API response errors propagate. Invalid candidate versions are skipped.

        Parameters:
            dependency (models.Dependency): GitLab.com `.git#<commit>` URL with a 40-character lowercase commit hash
                and a required `; tag` suffix supplying the current version.

        Returns:
            models.Result: Update details when the selected tag has a newer version.
            str: Assignment string when the selected tag is not newer.
            None: If the URL is unsupported or no eligible tag is found.

        Raises:
            packaging.version.InvalidVersion: If the dependency's current tag is not a valid version.
        """
        match = typing.cast(MatchCommit | None, self._git_commit.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["tag"])
        tag = self._request_tag(match["owner"], match["repo"], version)
        if tag is None:
            return None
        owner, repo = self._parse_link(tag["commit"]["web_url"])
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}{match['variant']}://gitlab.com/{owner}/{repo}.git#{tag['commit']['id']} ; {tag['name']}"
        return (
            models.Result(
                body="\n".join(
                    [
                        f"Bumps [{owner}/{repo}](https://gitlab.com/{owner}/{repo}) from {match['tag']} to {tag['name']}.",
                        f"- [Tag](https://gitlab.com/{owner}/{repo}/-/tags/{tag['name']})",
                        f"- [Compare changes](https://gitlab.com/{owner}/{repo}/-/compare/{match['commit']}..{tag['commit']['id']})",
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
        """
        Extract the owner and repository names from a GitLab URL.

        Parameters:
                url (str): A GitLab URL containing the owner and repository path.

        Returns:
                tuple[str, str]: The owner and repository names.
        """
        fragments = url.split("/", 5)
        return fragments[3], fragments[4]

    def _request_release(self, owner: str, repo: str, version: packaging.version.Version) -> Release | None:
        """
        Finds an eligible GitLab release newer than the specified version.

        Parameters:
            owner (str): GitLab project owner or namespace.
            repo (str): GitLab repository name.
            version (packaging.version.Version): Current dependency version.

        Returns:
            Release | None: The first eligible release newer than the current version, the first eligible release otherwise, or None if no eligible release is found.
        """
        latest = None
        url = f"https://gitlab.com/api/v4/projects/{owner}%2F{repo}/releases?per_page=100"
        while url:
            response = self._request(url)
            for _release in typing.cast(list[Release], response.json()):
                try:
                    _version = packaging.version.Version(_release["tag_name"])
                    _timestamp = max(
                        datetime.datetime.fromisoformat(_release["created_at"]),
                        datetime.datetime.fromisoformat(_release.get("released_at") or _release["created_at"]),
                    )
                    if (_version.is_prerelease and not version.is_prerelease) or datetime.datetime.now(
                        _timestamp.tzinfo
                    ) - _timestamp < self.cooldown:
                        continue
                    elif _version > version:
                        return _release
                    elif not latest:
                        latest = _release
                except packaging.version.InvalidVersion:
                    _owner, _repo = self._parse_link(_release["commit"]["web_url"])
                    print(f"::debug::Invalid version: {_owner}/{_repo} {_release['tag_name']}")
                    continue
            url = response.links.get("next", {}).get("url")
        return latest

    def _request_tag(self, owner: str, repo: str, version: packaging.version.Version) -> Tag | None:
        """
        Selects an eligible GitLab tag relative to the specified version.

        Parameters:
            owner (str): GitLab project owner or namespace.
            repo (str): GitLab repository name.
            version (packaging.version.Version): Version used to evaluate candidate tags.

        Returns:
            Tag | None: The first eligible tag newer than the specified version, the first eligible tag when no newer tag exists, or `None` when no eligible tag is found.
        """
        latest = None
        url = f"https://gitlab.com/api/v4/projects/{owner}%2F{repo}/repository/tags?per_page=100"
        while url:
            response = self._request(url)
            for _tag in typing.cast(list[Tag], response.json()):
                try:
                    _version = packaging.version.Version(_tag["name"])
                    _timestamp = datetime.datetime.fromisoformat(_tag["commit"]["created_at"])
                    if (_version.is_prerelease and not version.is_prerelease) or datetime.datetime.now(
                        _timestamp.tzinfo
                    ) - _timestamp < self.cooldown:
                        continue
                    elif _version > version:
                        return _tag
                    elif not latest:
                        latest = _tag
                except packaging.version.InvalidVersion:
                    _owner, _repo = self._parse_link(_tag["commit"]["web_url"])
                    print(f"::debug::Invalid version: {_owner}/{_repo} {_tag['name']}")
                    continue
            url = response.links.get("next", {}).get("url")
        return latest

    def _request(self, url: str) -> requests.Response:
        """
        Fetch a JSON response from the specified URL.

        Parameters:
            url (str): The URL to request.

        Returns:
            requests.Response: The successful HTTP response.

        Raises:
            requests.HTTPError: If the response has an unsuccessful status code.
        """
        response = requests.get(
            url=url,
            headers={
                "Accept": "application/json",
                "User-Agent": models.Config.USER_AGENT,
            },
            timeout=models.Config.TIMEOUT,
        )
        response.raise_for_status()
        return response
