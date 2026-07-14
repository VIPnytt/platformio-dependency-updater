import os
import packaging.version
import re
import requests
import typing

from .. import Models


class Commit(typing.TypedDict):
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
    tag_name: str
    _links: Links


class Tag(typing.TypedDict):
    commit: Commit
    name: str


class Resolve:
    _tag: re.Pattern[str]
    _commit: re.Pattern[str]

    def __init__(self, token: str | None = None) -> None:
        self._commit = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://gitlab\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)/-/archive/(?P<commit>[0-9a-f]{40})/[^/\s]+\.(?P<variant>tar|tar\.gz|zip)\s*;\s*(?P<tag>\S+)$"
        )
        self._tag = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://gitlab\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)/-/archive/(?P<tag>[^/\s]+)/[^/\s]+\.(?P<variant>tar|tar\.gz|zip)(?:\s*;.*)?$"
        )

    def release_tag(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(
            MatchTag | None,
            self._tag.fullmatch(dependency.value),
        )
        if not match:
            return
        version = packaging.version.Version(match["tag"])
        release = self._request_release(
            match["owner"], match["repo"], version.is_prerelease
        )
        if release is None:
            return
        owner, repo = self._parse_link(release["_links"]["self"])
        for source in release["assets"]["sources"]:
            if source["format"] != match["variant"]:
                continue
            value = f"{'' if match['package'] is None else f'{match["package"]} @ '}{source['url']} ; {release['tag_name']}"
            if packaging.version.Version(release["tag_name"]) > version:
                return Models.Result(
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
            return f"{dependency.option} = {value}"

    def release_tag_commit(
        self, dependency: Models.Dependency
    ) -> Models.Result | str | None:
        match = typing.cast(
            MatchCommit | None,
            self._tag.fullmatch(dependency.value),
        )
        if not match:
            return
        version = packaging.version.Version(match["tag"])
        release = self._request_release(
            match["owner"], match["repo"], version.is_prerelease
        )
        if release is None:
            return
        owner, repo = self._parse_link(release["_links"]["self"])
        for source in release["assets"]["sources"]:
            if source["format"] != match["variant"]:
                continue
            value = f"{'' if match['package'] is None else f'{match["package"]} @ '}https://gitlab.com/{owner}/{repo}/-/archive/{release['commit']['id']}/{repo}-{release['commit']['id']}.{match['variant']} ; {release['tag_name']}"
            if packaging.version.Version(release["tag_name"]) > version:
                return Models.Result(
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
            return f"{dependency.option} = {value}"

    def tag(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(
            MatchTag | None,
            self._tag.fullmatch(dependency.value),
        )
        if not match:
            return
        version = packaging.version.Version(match["tag"])
        tag = self._request_tag(match["owner"], match["repo"], version.is_prerelease)
        if tag is None:
            return
        owner, repo = self._parse_link(tag["commit"]["web_url"])
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}https://gitlab.com/{owner}/{repo}/-/archive/{tag['name']}/{repo}-{tag['name']}.{match['variant']} ; {tag['name']}"
        if packaging.version.Version(tag["name"]) > version:
            return Models.Result(
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
        return f"{dependency.option} = {value}"

    def tag_commit(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(
            MatchCommit | None,
            self._tag.fullmatch(dependency.value),
        )
        if not match:
            return
        version = packaging.version.Version(match["tag"])
        tag = self._request_tag(match["owner"], match["repo"], version.is_prerelease)
        if tag is None:
            return
        owner, repo = self._parse_link(tag["commit"]["web_url"])
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}https://gitlab.com/{owner}/{repo}/-/archive/{tag['commit']['id']}/{repo}-{tag['commit']['id']}.{match['variant']} ; {tag['name']}"
        if packaging.version.Version(tag["name"]) > version:
            return Models.Result(
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
        return f"{dependency.option} = {value}"

    def _parse_link(self, url: str) -> tuple[str, str]:
        fragments = url.split("/", 5)
        return fragments[3], fragments[4]

    def _request_release(
        self, repo: str, name: str, prerelease: bool
    ) -> Release | None:
        response = self._request(
            f"https://gitlab.com/api/v4/projects/{repo}%2F{name}/releases"
        )
        release = None
        version = None
        for _release in typing.cast(list[Release], response.json()):
            try:
                _version = packaging.version.Version(_release["tag_name"])
                if _version.is_prerelease and not prerelease:
                    continue
            except packaging.version.InvalidVersion:
                owner, repo = self._parse_link(_release["commit"]["web_url"])
                print(f"::debug::Invalid version: {owner}{repo} {_release['tag_name']}")
                continue
            if release is None or version is None or _version > version:
                release = _release
                version = _version
        return release

    def _request_tag(self, repo: str, name: str, prerelease: bool) -> Tag | None:
        response = self._request(
            f"https://gitlab.com/api/v4/projects/{repo}%2F{name}/repository/tags"
        )
        tag = None
        version = None
        for _tag in typing.cast(list[Tag], response.json()):
            try:
                _version = packaging.version.Version(_tag["name"])
                if _version.is_prerelease and not prerelease:
                    continue
            except packaging.version.InvalidVersion:
                owner, repo = self._parse_link(_tag["commit"]["web_url"])
                print(f"::debug::Invalid version: {owner}{repo} {_tag['name']}")
                continue
            if tag is None or version is None or _version > version:
                tag = _tag
                version = _version
        return tag

    def _request(self, url: str) -> requests.Response:
        token = os.getenv("CI_JOB_TOKEN")
        response = requests.get(
            url=url,
            headers={
                "Accept": "application/json",
                "User-Agent": Models.Config.USER_AGENT,
            }
            if token is None
            else {
                "Accept": "application/json",
                "JOB-TOKEN": token,
                "User-Agent": Models.Config.USER_AGENT,
            },
        )
        response.raise_for_status()
        return response
