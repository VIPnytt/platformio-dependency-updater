import re
import typing

import packaging.version
import requests

from .. import models


class MatchCommit(typing.TypedDict):
    commit: str
    mount: str
    package: str | None
    project: str
    tag: str
    variant: str


class MatchRef(typing.TypedDict):
    commit: str
    peel: str | None
    tag: str


class MatchTag(typing.TypedDict):
    mount: str
    package: str | None
    project: str
    tag: str
    variant: str


class Tag(typing.TypedDict):
    commit: str
    tag: str


class Resolve:
    ref: re.Pattern[str]
    _ball_commit: re.Pattern[str]
    _ball_tag: re.Pattern[str]
    _git_commit: re.Pattern[str]
    _git_tag: re.Pattern[str]
    _tree_commit: re.Pattern[str]
    _tree_tag: re.Pattern[str]

    def __init__(self) -> None:
        """Initialize the SourceForge dependency resolver."""
        self.ref = re.compile(r"^[0-9a-f]{4}(?P<commit>[0-9a-f]{40})\srefs/tags/(?P<tag>[^\s^]+)(?P<peel>\^\{\})?$")
        self._ball_commit = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://sourceforge\.net/p/(?P<project>[^/\s]+)/(?P<mount>[^/\s]+)/ci/(?P<commit>[0-9a-f]{40})/(?P<variant>tar)ball\s*;\s*(?P<tag>\S+)$"
        )
        self._ball_tag = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://sourceforge\.net/p/(?P<project>[^/\s]+)/(?P<mount>[^/\s]+)/ci/(?P<tag>[^/\s]+)/(?P<variant>tar)ball(?:\s*;.*)?$"
        )
        self._git_commit = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?(?P<variant>git|git\+https|git\+ssh|https)://git\.code\.sf\.net/p/(?P<project>[^/\s]+)/(?P<mount>[^/\s]+)#(?P<commit>[0-9a-f]{40})\s*;\s*(?P<tag>\S+)$"
        )
        self._git_tag = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?(?P<variant>git|git\+https|git\+ssh|https)://git\.code\.sf\.net/p/(?P<project>[^/\s]+)/(?P<mount>[^/\s]+)#(?P<tag>[^/\s]+)(?:\s*;.*)?$"
        )
        self._tree_commit = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://sourceforge\.net/p/(?P<project>[^/\s]+)/(?P<mount>[^/\s]+)/ci/(?P<commit>[0-9a-f]{40})/tree/\?format=(?P<variant>tar|tgz|zip)\s*;\s*(?P<tag>\S+)$"
        )
        self._tree_tag = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://sourceforge\.net/p/(?P<project>[^/\s]+)/(?P<mount>[^/\s]+)/ci/(?P<tag>[^/\s]+)/tree/\?format=(?P<variant>tar|tgz|zip)(?:\s*;.*)?$"
        )

    def tag_commit_ball(self, dependency: models.Dependency) -> models.Result | str | None:
        """
        Resolve a SourceForge tarball URL pinned to a commit using its required version comment.

        The URL must contain a full lowercase 40-character commit hash followed by a ``; tag`` comment.
        Fetch the highest eligible version tag, preserving the optional package prefix and URL variant.
        Return update details for a newer version, a formatted dependency assignment otherwise, or None
        if the URL does not match or no eligible tag exists.

        InvalidVersion for the current tag, Requests exceptions, and response UnicodeDecodeError propagate.
        """
        match = typing.cast(MatchCommit | None, self._ball_commit.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["tag"])
        ref = self._request_tag(match["project"], match["mount"], version)
        if ref is None:
            return None
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}https://sourceforge.net/p/{match['project']}/{match['mount']}/ci/{ref['commit']}/{match['variant']}ball ; {ref['tag']}"
        return (
            models.Result(
                body="\n".join(
                    [
                        f"Bumps [{match['project']}/{match['mount']}](https://sourceforge.net/p/{match['project']}/{match['mount']}/) from {match['tag']} to {ref['tag']}.",
                        f"- [Tag](https://sourceforge.net/p/{match['project']}/{match['mount']}/ci/{ref['tag']})",
                    ]
                ),
                package=f"{match['project']}/{match['mount']}",
                value=value,
                version_from=match["tag"].removeprefix("v"),
                version_to=ref["tag"].removeprefix("v"),
            )
            if packaging.version.Version(ref["tag"]) > version
            else f"{dependency.option} = {value}"
        )

    def tag_commit_git(self, dependency: models.Dependency) -> models.Result | str | None:
        """
        Resolve a SourceForge Git URL pinned to a commit using its required version comment.

        The fragment must be a full lowercase 40-character commit hash followed by a ``; tag`` comment.
        Fetch the highest eligible version tag, preserving the optional package prefix and URL variant.
        Return update details for a newer version, a formatted dependency assignment otherwise, or None
        if the URL does not match or no eligible tag exists.

        InvalidVersion for the current tag, Requests exceptions, and response UnicodeDecodeError propagate.
        """
        match = typing.cast(MatchCommit | None, self._git_commit.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["tag"])
        ref = self._request_tag(match["project"], match["mount"], version)
        if ref is None:
            return None
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}{match['variant']}://git.code.sf.net/p/{match['project']}/{match['mount']}#{ref['commit']} ; {ref['tag']}"
        return (
            models.Result(
                body="\n".join(
                    [
                        f"Bumps [{match['project']}/{match['mount']}](https://sourceforge.net/p/{match['project']}/{match['mount']}/) from {match['tag']} to {ref['tag']}.",
                        f"- [Tag](https://sourceforge.net/p/{match['project']}/{match['mount']}/ci/{ref['tag']})",
                    ]
                ),
                package=f"{match['project']}/{match['mount']}",
                value=value,
                version_from=match["tag"].removeprefix("v"),
                version_to=ref["tag"].removeprefix("v"),
            )
            if packaging.version.Version(ref["tag"]) > version
            else f"{dependency.option} = {value}"
        )

    def tag_commit_tree(self, dependency: models.Dependency) -> models.Result | str | None:
        """
        Resolve a SourceForge tree archive pinned to a commit using its required version comment.

        Accept tar, tgz, or zip with a full lowercase 40-character commit hash and a ``; tag`` comment.
        Fetch the highest eligible version tag, preserving the optional package prefix and URL variant.
        Return update details for a newer version, a formatted dependency assignment otherwise, or None
        if the URL does not match or no eligible tag exists.

        InvalidVersion for the current tag, Requests exceptions, and response UnicodeDecodeError propagate.
        """
        match = typing.cast(MatchCommit | None, self._tree_commit.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["tag"])
        ref = self._request_tag(match["project"], match["mount"], version)
        if ref is None:
            return None
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}https://sourceforge.net/p/{match['project']}/{match['mount']}/ci/{ref['commit']}/tree/?format={match['variant']} ; {ref['tag']}"
        return (
            models.Result(
                body="\n".join(
                    [
                        f"Bumps [{match['project']}/{match['mount']}](https://sourceforge.net/p/{match['project']}/{match['mount']}/) from {match['tag']} to {ref['tag']}.",
                        f"- [Tag](https://sourceforge.net/p/{match['project']}/{match['mount']}/ci/{ref['tag']})",
                    ]
                ),
                package=f"{match['project']}/{match['mount']}",
                value=value,
                version_from=match["tag"].removeprefix("v"),
                version_to=ref["tag"].removeprefix("v"),
            )
            if packaging.version.Version(ref["tag"]) > version
            else f"{dependency.option} = {value}"
        )

    def tag_ball(self, dependency: models.Dependency) -> models.Result | str | None:
        """
        Resolve a SourceForge tarball URL using the version tag in its path.

        Any trailing comment is ignored when determining the current version.
        Fetch the highest eligible version tag, preserving the optional package prefix and URL variant.
        Return update details for a newer version, a formatted dependency assignment otherwise, or None
        if the URL does not match or no eligible tag exists.

        InvalidVersion for the current tag, Requests exceptions, and response UnicodeDecodeError propagate.
        """
        match = typing.cast(MatchTag | None, self._ball_tag.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["tag"])
        ref = self._request_tag(match["project"], match["mount"], version)
        if ref is None:
            return None
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}https://sourceforge.net/p/{match['project']}/{match['mount']}/ci/{ref['tag']}/{match['variant']}ball ; {ref['tag']}"
        return (
            models.Result(
                body="\n".join(
                    [
                        f"Bumps [{match['project']}/{match['mount']}](https://sourceforge.net/p/{match['project']}/{match['mount']}/) from {match['tag']} to {ref['tag']}.",
                        f"- [Tag](https://sourceforge.net/p/{match['project']}/{match['mount']}/ci/{ref['tag']})",
                    ]
                ),
                package=f"{match['project']}/{match['mount']}",
                value=value,
                version_from=match["tag"].removeprefix("v"),
                version_to=ref["tag"].removeprefix("v"),
            )
            if packaging.version.Version(ref["tag"]) > version
            else f"{dependency.option} = {value}"
        )

    def tag_git(self, dependency: models.Dependency) -> models.Result | str | None:
        """
        Resolve a SourceForge Git URL using the version tag in its fragment.

        Fetch the highest eligible version tag, preserving the optional package prefix and URL variant.
        Return update details for a newer version, a formatted dependency assignment otherwise, or None
        if the URL does not match or no eligible tag exists.

        InvalidVersion for the current tag, Requests exceptions, and response UnicodeDecodeError propagate.
        """
        match = typing.cast(MatchTag | None, self._git_tag.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["tag"])
        ref = self._request_tag(match["project"], match["mount"], version)
        if ref is None:
            return None
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}{match['variant']}://git.code.sf.net/p/{match['project']}/{match['mount']}#{ref['tag']} ; {ref['tag']}"
        return (
            models.Result(
                body="\n".join(
                    [
                        f"Bumps [{match['project']}/{match['mount']}](https://sourceforge.net/p/{match['project']}/{match['mount']}/) from {match['tag']} to {ref['tag']}.",
                        f"- [Tag](https://sourceforge.net/p/{match['project']}/{match['mount']}/ci/{ref['tag']})",
                    ]
                ),
                package=f"{match['project']}/{match['mount']}",
                value=value,
                version_from=match["tag"].removeprefix("v"),
                version_to=ref["tag"].removeprefix("v"),
            )
            if packaging.version.Version(ref["tag"]) > version
            else f"{dependency.option} = {value}"
        )

    def tag_tree(self, dependency: models.Dependency) -> models.Result | str | None:
        """
        Resolve a SourceForge tree archive URL using the version tag in its path.

        Accept tar, tgz, or zip; ignore any trailing comment when determining the current version.
        Fetch the highest eligible version tag, preserving the optional package prefix and URL variant.
        Return update details for a newer version, a formatted dependency assignment otherwise, or None
        if the URL does not match or no eligible tag exists.

        InvalidVersion for the current tag, Requests exceptions, and response UnicodeDecodeError propagate.
        """
        match = typing.cast(MatchTag | None, self._tree_tag.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["tag"])
        ref = self._request_tag(match["project"], match["mount"], version)
        if ref is None:
            return None
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}https://sourceforge.net/p/{match['project']}/{match['mount']}/ci/{ref['tag']}/tree/?format={match['variant']} ; {ref['tag']}"
        return (
            models.Result(
                body="\n".join(
                    [
                        f"Bumps [{match['project']}/{match['mount']}](https://sourceforge.net/p/{match['project']}/{match['mount']}/) from {match['tag']} to {ref['tag']}.",
                        f"- [Tag](https://sourceforge.net/p/{match['project']}/{match['mount']}/ci/{ref['tag']})",
                    ]
                ),
                package=f"{match['project']}/{match['mount']}",
                value=value,
                version_from=match["tag"].removeprefix("v"),
                version_to=ref["tag"].removeprefix("v"),
            )
            if packaging.version.Version(ref["tag"]) > version
            else f"{dependency.option} = {value}"
        )

    def _request_tag(self, project: str, mount: str, version: packaging.version.Version) -> Tag | None:
        """
        Fetch the highest parseable version tag and its advertised commit, or None if none qualifies.

        The mount is the repository path component within the SourceForge project. Invalid version tags are
        skipped; prereleases are eligible only if version is a prerelease. The selected tag may be older than
        version, and no cooldown is applied. Annotated tags use the peeled commit when advertised.

        Requests exceptions and UnicodeDecodeError from decoding the response propagate to the caller.
        """
        url = f"https://git.code.sf.net/p/{project}/{mount}/info/refs?service=git-upload-pack"
        tags: dict[str, str] = {}
        for line in self._request(url).iter_lines():
            match = typing.cast(MatchRef | None, self.ref.fullmatch(line.decode()))
            if not match:
                continue
            elif match["peel"] is None:
                tags.setdefault(match["tag"], match["commit"])
            else:
                tags[match["tag"]] = match["commit"]
        version_: packaging.version.Version | None = None
        latest: Tag | None = None
        for _tag, _commit in tags.items():
            try:
                _version = packaging.version.Version(_tag)
                if _version.is_prerelease and not version.is_prerelease:
                    continue
                elif version_ is None or _version > version_:
                    version_ = _version
                    latest = {
                        "commit": _commit,
                        "tag": _tag,
                    }
            except packaging.version.InvalidVersion:
                print(f"::debug::Invalid version: {project}/{mount} {_tag}")
                continue
        return latest

    def _request(self, url: str) -> requests.Response:
        """
        Fetch a Git reference advertisement using the configured request timeout in seconds.

        Return the response after checking its HTTP status. Requests connection, timeout, and HTTP errors
        propagate to the caller.
        """
        response = requests.get(
            url=url,
            headers={
                "Accept": "application/x-git-upload-pack-advertisement",
                "User-Agent": models.Config.USER_AGENT,
            },
            timeout=models.Config.TIMEOUT,
        )
        response.raise_for_status()
        return response
