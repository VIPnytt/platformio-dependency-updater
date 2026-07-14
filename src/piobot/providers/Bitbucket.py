import os
import packaging.version
import re
import requests
import typing
import urllib.parse

from .. import Models


class User(typing.TypedDict):
    uuid: str


class Author(typing.TypedDict):
    user: User


class Commit(typing.TypedDict):
    commit: str
    package: str | None
    repo: str
    tag: str
    variant: str


class Html(typing.TypedDict):
    href: str


class Links(typing.TypedDict):
    html: Html


class Repository(typing.TypedDict):
    full_name: str
    links: Links
    uuid: str


class Tag(typing.TypedDict):
    package: str | None
    repo: str
    tag: str
    variant: str


class Target(typing.TypedDict):
    author: Author
    hash: str
    repository: Repository


class Value(typing.TypedDict):
    name: str
    target: Target


class Response(typing.TypedDict):
    next: str
    values: Value


class Resolve:
    _name_commit: re.Pattern[str]
    _name_tag: re.Pattern[str]
    _uuid_commit: re.Pattern[str]
    _uuid_tag: re.Pattern[str]

    def __init__(self) -> None:
        self._name_commit = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://bitbucket\.org/(?P<repo>[^/\s]+/[^/\s]+)/get/(?P<commit>[0-9a-f]{40})\.(?P<variant>tar\.gz|zip)\s*;\s*(?P<tag>\S+)$"
        )
        self._name_tag = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://bitbucket\.org/(?P<repo>[^/\s]+/[^/\s]+)/get/(?P<tag>[^/\s]+)\.(?P<variant>tar\.gz|zip)(?:\s*;.*)?$"
        )
        self._uuid_commit = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://bitbucket\.org/(?P<repo>%7B[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}%7D/%7B[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}%7D)/get/(?P<commit>[0-9a-f]{40})\.(?P<variant>tar\.gz|zip)(?:\s*;.*)?$"
        )
        self._uuid_tag = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://bitbucket\.org/(?P<repo>%7B[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}%7D/%7B[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}%7D)/get/(?P<tag>[^/\s]+)\.(?P<variant>tar\.gz|zip)(?:\s*;.*)?$"
        )

    def name_commit(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(
            Commit | None, self._name_commit.fullmatch(dependency.value)
        )
        if not match:
            return
        version = packaging.version.Version(match["tag"])
        tag = self._request_tag(match["repo"], version.is_prerelease)
        if tag is None:
            return
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}{tag['target']['repository']['links']['html']['href']}/get/{tag['target']['hash']}.{match['variant']} ; {tag['name']}"
        if packaging.version.Version(tag["name"]) > packaging.version.Version(
            match["tag"]
        ):
            return Models.Result(
                body="\n".join(
                    [
                        f"Bumps [{tag['target']['repository']['full_name']}]({tag['target']['repository']['links']['html']['href']}) from {match['tag']} to {tag['name']}.",
                        f"- [Tag]({tag['target']['repository']['links']['html']['href']}/src/{tag['name']}/)",
                        f"- [Compare changes]({tag['target']['repository']['links']['html']['href']}/branches/compare/{match['commit']}%0D{tag['target']['hash']})",
                    ]
                ),
                package=tag["target"]["repository"]["full_name"],
                value=value,
                version_from=match["tag"].removeprefix("v"),
                version_to=tag["name"].removeprefix("v"),
            )
        return f"{dependency.option} = {value}"

    def name_tag(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(Tag | None, self._name_tag.fullmatch(dependency.value))
        if not match:
            return
        version = packaging.version.Version(match["tag"])
        tag = self._request_tag(match["repo"], version.is_prerelease)
        if tag is None:
            return
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}{tag['target']['repository']['links']['html']['href']}/get/{tag['name']}.{match['variant']} ; {tag['name']}"
        if packaging.version.Version(tag["name"]) > version:
            return Models.Result(
                body="\n".join(
                    [
                        f"Bumps [{tag['target']['repository']['full_name']}]({tag['target']['repository']['links']['html']['href']}) from {match['tag']} to {tag['name']}.",
                        f"- [Tag]({tag['target']['repository']['links']['html']['href']}/src/{tag['name']}/)",
                        f"- [Compare changes]({tag['target']['repository']['links']['html']['href']}/branches/compare/{match['tag']}%0D{tag['name']})",
                    ]
                ),
                package=tag["target"]["repository"]["full_name"],
                value=value,
                version_from=match["tag"].removeprefix("v"),
                version_to=tag["name"].removeprefix("v"),
            )
        return f"{dependency.option} = {value}"

    def uuid_commit(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(
            Commit | None, self._uuid_commit.fullmatch(dependency.value)
        )
        if not match:
            return
        version = packaging.version.Version(match["tag"])
        tag = self._request_tag(match["repo"], version.is_prerelease)
        if tag is None:
            return
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}https://bitbucket.org/{urllib.parse.quote(tag['target']['author']['user']['uuid'])}/{urllib.parse.quote(tag['target']['repository']['uuid'])}/get/{tag['target']['hash']}.{match['variant']} ; {tag['target']['repository']['full_name']} {tag['name']}"
        if packaging.version.Version(tag["name"]) > version:
            return Models.Result(
                body="\n".join(
                    [
                        f"Bumps [{tag['target']['repository']['full_name']}]({tag['target']['repository']['links']['html']['href']}) from {match['tag']} to {tag['name']}.",
                        f"- [Tag]({tag['target']['repository']['links']['html']['href']}/src/{tag['name']}/)",
                        f"- [Compare changes]({tag['target']['repository']['links']['html']['href']}/branches/compare/{match['commit']}%0D{tag['target']['hash']})",
                    ]
                ),
                package=tag["target"]["repository"]["full_name"],
                value=value,
                version_from=match["tag"].removeprefix("v"),
                version_to=tag["name"].removeprefix("v"),
            )
        return f"{dependency.option} = {value}"

    def uuid_tag(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(Tag | None, self._uuid_tag.fullmatch(dependency.value))
        if not match:
            return
        version = packaging.version.Version(match["tag"])
        tag = self._request_tag(match["repo"], version.is_prerelease)
        if tag is None:
            return
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}https://bitbucket.org/{urllib.parse.quote(tag['target']['author']['user']['uuid'])}/{urllib.parse.quote(tag['target']['repository']['uuid'])}/get/{tag['name']}.{match['variant']} ; {tag['target']['repository']['full_name']} {tag['name']}"
        if packaging.version.Version(tag["name"]) > version:
            return Models.Result(
                body="\n".join(
                    [
                        f"Bumps [{tag['target']['repository']['full_name']}]({tag['target']['repository']['links']['html']['href']}) from {match['tag']} to {tag['name']}.",
                        f"- [Tag]({tag['target']['repository']['links']['html']['href']}/src/{tag['name']}/)",
                        f"- [Compare changes]({tag['target']['repository']['links']['html']['href']}/branches/compare/{match['tag']}%0D{tag['name']})",
                    ]
                ),
                package=tag["target"]["repository"]["full_name"],
                value=value,
                version_from=match["tag"].removeprefix("v"),
                version_to=tag["name"].removeprefix("v"),
            )
        return f"{dependency.option} = {value}"

    def _request_tag(self, repo: str, prerelease: bool) -> Value | None:
        response = typing.cast(
            Response,
            self._request(
                f"https://api.bitbucket.org/2.0/repositories/{repo}/refs/tags?sort=-target.date"
            ).json(),
        )
        value = None
        version = None
        for _value in typing.cast(list[Value], response["values"]):
            try:
                _version = packaging.version.Version(_value["name"])
                if _version.is_prerelease and not prerelease:
                    continue
            except packaging.version.InvalidVersion:
                print(
                    f"::debug::Invalid version: {_value['target']['repository']['full_name']} {_value['name']}"
                )
                continue
            if value is None or version is None or _version > version:
                value = _value
                version = _version
        return value

    def _request(self, url: str) -> requests.Response:
        token = os.getenv("$BITBUCKET_STEP_OIDC_TOKEN")
        response = requests.get(
            url=url,
            headers={
                "Accept": "application/json",
                "User-Agent": Models.Config.USER_AGENT,
            }
            if token is None
            else {
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "User-Agent": Models.Config.USER_AGENT,
            },
        )
        response.raise_for_status()
        return response
