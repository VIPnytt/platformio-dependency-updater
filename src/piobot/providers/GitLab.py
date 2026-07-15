import packaging.version
import re
import requests
import typing
import urllib.parse

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
        match = typing.cast(MatchTag | None, self._tag.fullmatch(dependency.value))
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
            value = f"{'' if match['package'] is None else f'{match["package"]} @ '}{source['url']} ; {release['tag_name']}"
            return (
                Models.Result(
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

    def release_tag_commit(
        self, dependency: Models.Dependency
    ) -> Models.Result | str | None:
        match = typing.cast(
            MatchCommit | None, self._commit.fullmatch(dependency.value)
        )
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
                Models.Result(
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

    def tag(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(MatchTag | None, self._tag.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["tag"])
        tag = self._request_tag(match["owner"], match["repo"], version)
        if tag is None:
            return None
        owner, repo = self._parse_link(tag["commit"]["web_url"])
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}https://gitlab.com/{owner}/{repo}/-/archive/{tag['name']}/{repo}-{tag['name']}.{match['variant']} ; {tag['name']}"
        return (
            Models.Result(
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

    def tag_commit(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(
            MatchCommit | None, self._commit.fullmatch(dependency.value)
        )
        if not match:
            return None
        version = packaging.version.Version(match["tag"])
        tag = self._request_tag(match["owner"], match["repo"], version)
        if tag is None:
            return None
        owner, repo = self._parse_link(tag["commit"]["web_url"])
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}https://gitlab.com/{owner}/{repo}/-/archive/{tag['commit']['id']}/{repo}-{tag['commit']['id']}.{match['variant']} ; {tag['name']}"
        return (
            Models.Result(
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
        fragments = url.split("/", 5)
        return fragments[3], fragments[4]

    def _request_release(
        self, owner: str, repo: str, version: packaging.version.Version
    ) -> Release | None:
        latest = None
        url = (
            f"https://gitlab.com/api/v4/projects/{owner}%2F{repo}/releases?per_page=100"
        )
        while url:
            response = self._request(url)
            for _release in typing.cast(list[Release], response.json()):
                try:
                    _version = packaging.version.Version(_release["tag_name"])
                    if _version.is_prerelease and not version.is_prerelease:
                        continue
                    elif _version > version:
                        return _release
                    elif not latest:
                        latest = _release
                except packaging.version.InvalidVersion:
                    _owner, _repo = self._parse_link(_release["commit"]["web_url"])
                    print(
                        f"::debug::Invalid version: {_owner}/{_repo} {_release['tag_name']}"
                    )
                    continue
            url = response.links.get("next", {}).get("url")
        return latest

    def _request_tag(
        self, owner: str, repo: str, version: packaging.version.Version
    ) -> Tag | None:
        latest = None
        url = f"https://gitlab.com/api/v4/projects/{owner}%2F{repo}/repository/tags?per_page=100"
        while url:
            response = self._request(url)
            for _tag in typing.cast(list[Tag], response.json()):
                try:
                    _version = packaging.version.Version(_tag["name"])
                    if _version.is_prerelease and not version.is_prerelease:
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
        response = requests.get(
            url=url,
            headers={
                "Accept": "application/json",
                "User-Agent": Models.Config.USER_AGENT,
            },
            timeout=Models.Config.TIMEOUT,
        )
        response.raise_for_status()
        return response
