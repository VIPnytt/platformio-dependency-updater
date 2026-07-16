import datetime
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
    name: str
    package: str | None
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
    name: str
    package: str | None
    tag: str
    variant: str


class Target(typing.TypedDict):
    author: Author
    date: str
    hash: str
    repository: Repository


class Value(typing.TypedDict):
    name: str
    target: Target


class Data(typing.TypedDict):
    next: str | None
    values: Value


class Resolve:
    _name_commit: re.Pattern[str]
    _name_tag: re.Pattern[str]
    _uuid_commit: re.Pattern[str]
    _uuid_tag: re.Pattern[str]

    def __init__(self) -> None:
        self._name_commit = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://bitbucket\.org/(?P<name>[^/\s]+/[^/\s]+)/get/(?P<commit>[0-9a-f]{40})\.(?P<variant>tar\.gz|zip)\s*;\s*(?P<tag>\S+)$"
        )
        self._name_tag = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://bitbucket\.org/(?P<name>[^/\s]+/[^/\s]+)/get/(?P<tag>[^/\s]+)\.(?P<variant>tar\.gz|zip)(?:\s*;.*)?$"
        )
        self._uuid_commit = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://bitbucket\.org/(?P<name>%7B[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}%7D/%7B[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}%7D)/get/(?P<commit>[0-9a-f]{40})\.(?P<variant>tar\.gz|zip)(?:\s*;.*)?$"
        )
        self._uuid_tag = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://bitbucket\.org/(?P<name>%7B[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}%7D/%7B[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}%7D)/get/(?P<tag>[^/\s]+)\.(?P<variant>tar\.gz|zip)(?:\s*;.*)?$"
        )

    def name_commit(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(Commit | None, self._name_commit.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["tag"])
        tag = self._request_tag(match["name"], version)
        if tag is None:
            return None
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}{tag['target']['repository']['links']['html']['href']}/get/{tag['target']['hash']}.{match['variant']} ; {tag['name']}"
        return (
            Models.Result(
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
            if packaging.version.Version(tag["name"]) > version
            else f"{dependency.option} = {value}"
        )

    def name_tag(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(Tag | None, self._name_tag.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["tag"])
        tag = self._request_tag(match["name"], version)
        if tag is None:
            return None
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}{tag['target']['repository']['links']['html']['href']}/get/{tag['name']}.{match['variant']} ; {tag['name']}"
        return (
            Models.Result(
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
            if packaging.version.Version(tag["name"]) > version
            else f"{dependency.option} = {value}"
        )

    def uuid_commit(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(Commit | None, self._uuid_commit.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["tag"])
        tag = self._request_tag(match["name"], version)
        if tag is None:
            return None
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}https://bitbucket.org/{urllib.parse.quote(tag['target']['author']['user']['uuid'])}/{urllib.parse.quote(tag['target']['repository']['uuid'])}/get/{tag['target']['hash']}.{match['variant']} ; {tag['target']['repository']['full_name']} {tag['name']}"
        return (
            Models.Result(
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
            if packaging.version.Version(tag["name"]) > version
            else f"{dependency.option} = {value}"
        )

    def uuid_tag(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(Tag | None, self._uuid_tag.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["tag"])
        tag = self._request_tag(match["name"], version)
        if tag is None:
            return None
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}https://bitbucket.org/{urllib.parse.quote(tag['target']['author']['user']['uuid'])}/{urllib.parse.quote(tag['target']['repository']['uuid'])}/get/{tag['name']}.{match['variant']} ; {tag['target']['repository']['full_name']} {tag['name']}"
        return (
            Models.Result(
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
            if packaging.version.Version(tag["name"]) > version
            else f"{dependency.option} = {value}"
        )

    def _request_tag(self, name: str, version: packaging.version.Version) -> Value | None:
        latest = None
        url = f"https://api.bitbucket.org/2.0/repositories/{name}/refs/tags?sort=-target.date&pagelen=100"
        while url:
            response = typing.cast(Data, self._request(url).json())
            for _value in typing.cast(list[Value], response["values"]):
                try:
                    _version = packaging.version.Version(_value["name"])
                    _timestamp = datetime.datetime.fromisoformat(_value["target"]["date"])
                    if (_version.is_prerelease and not version.is_prerelease) or datetime.datetime.now(
                        _timestamp.tzinfo
                    ) - _timestamp < datetime.timedelta(days=Models.Config.COOLDOWN):
                        continue
                    elif _version > version:
                        return _value
                    elif not latest:
                        latest = _value
                except packaging.version.InvalidVersion:
                    print(f"::debug::Invalid version: {_value['target']['repository']['full_name']} {_value['name']}")
                    continue
            url = response["next"] if "next" in response else None
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
