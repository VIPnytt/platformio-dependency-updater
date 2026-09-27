import datetime
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
    cooldown: datetime.timedelta
    ref: re.Pattern[str]
    _ball_commit: re.Pattern[str]
    _ball_tag: re.Pattern[str]
    _git_commit: re.Pattern[str]
    _git_tag: re.Pattern[str]
    _tree_commit: re.Pattern[str]
    _tree_tag: re.Pattern[str]

    def __init__(self, cooldown: datetime.timedelta) -> None:
        self.cooldown = cooldown
        self.ref = re.compile(r"^[0-9a-f]{4}(?P<commit>[0-9a-f]{40})\srefs/tags/(?P<tag>[^\s^]+)(?P<peel>\^\{\})?$")
        self._ball_commit = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://sourceforge\.net/p/(?P<project>[^/\s]+)/(?P<mount>[^/\s]+)/ci/(?P<commit>[0-9a-f]{40})/(?P<variant>tar)ball(?:\s*;\s*(?P<tag>\S+)$"
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
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://sourceforge\.net/p/(?P<project>[^/\s]+)/(?P<mount>[^/\s]+)/ci/(?P<commit>[0-9a-f]{40})/tree/\?format=(?P<variant>tar|tgz|zip)(?:\s*;\s*(?P<tag>\S+)$"
        )
        self._tree_tag = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://sourceforge\.net/p/(?P<project>[^/\s]+)/(?P<mount>[^/\s]+)/ci/(?P<tag>[^/\s]+)/tree/\?format=(?P<variant>tar|tgz|zip)(?:\s*;.*)?$"
        )

    def tag_commit_ball(self, dependency: models.Dependency) -> models.Result | str | None:
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
