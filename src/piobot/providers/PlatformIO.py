import enum
import packaging.version
import re
import requests
import typing

from .. import Models


class File(typing.TypedDict):
    download_url: str
    name: str
    system: str


class Owner(typing.TypedDict):
    username: str


class Version(typing.TypedDict):
    files: list[File]
    name: str


class Data(typing.TypedDict):
    name: str
    owner: Owner
    type: str
    version: Version
    versions: list[Version]


class Download(typing.TypedDict):
    file: str
    name: str
    owner: str
    package: str | None
    version: str


class Package(typing.TypedDict):
    name: str
    owner: str
    version: str


class Type(enum.StrEnum):
    LIBRARY = "library"
    PLATFORM = "platform"
    TOOL = "tool"


class Resolve:
    _api: re.Pattern[str]
    _download: re.Pattern[str]
    _package: re.Pattern[str]

    def __init__(self) -> None:
        self._api = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://api\.registry\.platformio\.org/v3/download/(?P<owner>[^/\s]+)/(?:library|platform|tool)/(?P<name>[^/\s]+)/(?P<version>[^/\s]+)/(?P<file>[^/\s]+)(?:\s*;.*)?$"
        )
        self._download = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://dl\.registry\.platformio\.org/download/(?P<owner>[^/\s]+)/(?:library|platform|tool)/(?P<name>[^/\s]+)/(?P<version>[^/\s]+)/(?P<file>[^/\s]+)(?:\s*;.*)?$"
        )
        self._package = re.compile(
            r"^(?P<owner>[^/\s]+)/(?P<name>[^/\s]+?)\s*@\s*(?P<version>[^\s]*)\S*(?:\s*;.*)?$"
        )

    def api(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(Download | None, self._api.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["version"])
        data = self._request_package_version(
            dependency.option, match["owner"], match["name"], match["version"]
        )
        _version = self._parse(data, version)
        if _version is None:
            return None
        system = self._system(data["version"]["files"], match["file"])
        for file in _version["files"]:
            if file["system"] != system:
                continue
            value = f"{'' if match['package'] is None else f'{match["package"]} @ '}{file['download_url']} ; {_version['name']}"
            if packaging.version.Version(_version["name"]) > version:
                type = self._type_html(data["type"])
                return Models.Result(
                    body="\n".join(
                        [
                            f"Bumps [{data['owner']['username']}/{data['name']}](https://registry.platformio.org/{type}/{data['owner']['username']}/{data['name']}) from {match['version']} to {_version['name']}.",
                            f"- [Versions](https://registry.platformio.org/{type}/{data['owner']['username']}/{data['name']}/versions?version={_version['name']})",
                        ]
                    ),
                    package=f"{data['owner']['username']}/{data['name']}",
                    value=value,
                    version_from=match["version"].removeprefix("v"),
                    version_to=_version["name"].removeprefix("v"),
                )
            return f"{dependency.option} = {value}"

    def download(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(Download | None, self._download.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["version"])
        data = self._request_package_version(
            dependency.option, match["owner"], match["name"], match["version"]
        )
        _version = self._parse(data, version)
        if _version is None:
            return None
        system = self._system(data["version"]["files"], match["file"])
        for file in _version["files"]:
            if file["system"] != system:
                continue
            value = f"{'' if match['package'] is None else f'{match["package"]} @ '}{file['download_url']} ; {_version['name']}"
            if packaging.version.Version(_version["name"]) > version:
                type = self._type_html(data["type"])
                return Models.Result(
                    body="\n".join(
                        [
                            f"Bumps [{data['owner']['username']}/{data['name']}](https://registry.platformio.org/{type}/{data['owner']['username']}/{data['name']}) from {match['version']} to {_version['name']}.",
                            f"- [Versions](https://registry.platformio.org/{type}/{data['owner']['username']}/{data['name']}/versions?version={_version['name']})",
                        ]
                    ),
                    package=f"{data['owner']['username']}/{data['name']}",
                    value=value,
                    version_from=match["version"].removeprefix("v"),
                    version_to=_version["name"].removeprefix("v"),
                )
            return f"{dependency.option} = {value}"

    def package(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(Package | None, self._package.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["version"])
        data = self._request_package(dependency.option, match["owner"], match["name"])
        _version = self._parse(data, version)
        if _version is None:
            return None
        value = f"{data['owner']['username']}/{data['name']} @ {_version['name']}"
        if packaging.version.Version(_version["name"]) > version:
            type = self._type_html(data["type"])
            return Models.Result(
                body="\n".join(
                    [
                        f"Bumps [{data['owner']['username']}/{data['name']}](https://registry.platformio.org/{type}/{data['owner']['username']}/{data['name']}) from {match['version']} to {_version['name']}.",
                        f"- [Versions](https://registry.platformio.org/{type}/{data['owner']['username']}/{data['name']}/versions?version={_version['name']})",
                    ]
                ),
                package=f"{data['owner']['username']}/{data['name']}",
                value=value,
                version_from=match["version"].removeprefix("v"),
                version_to=_version["name"].removeprefix("v"),
            )
        return f"{dependency.option} = {value}"

    def _parse(self, data: Data, version: packaging.version.Version) -> Version | None:
        latest = None
        for _candidate in typing.cast(list[Version], data["versions"]):
            try:
                _version = packaging.version.Version(_candidate["name"])
                if _version.is_prerelease and not version.is_prerelease:
                    continue
                elif _version > version:
                    return _candidate
                elif not latest:
                    latest = _candidate
            except packaging.version.InvalidVersion:
                print(
                    f"::debug::Invalid version: {data['owner']['username']}/{data['name']} {_candidate['name']}"
                )
                continue
        return latest

    def _request_package(self, option: str, owner: str, name: str) -> Data:
        return typing.cast(
            Data,
            self._request(
                f"https://api.registry.platformio.org/v3/packages/{owner}/{self._type_api(option)}/{name}"
            ).json(),
        )

    def _request_package_version(
        self, option: str, owner: str, name: str, version: str
    ) -> Data:
        return typing.cast(
            Data,
            self._request(
                f"https://api.registry.platformio.org/v3/packages/{owner}/{self._type_api(option)}/{name}?version={version}"
            ).json(),
        )

    def _request(self, url: str) -> requests.Response:
        response = requests.get(
            url=url,
            headers={
                "Accept": "application/json",
                "User-Agent": Models.Config.USER_AGENT,
            },
        )
        response.raise_for_status()
        return response

    def _system(self, files: list[File], file: str) -> str:
        for _file in files:
            if _file["name"] == file:
                return _file["system"]
        return "*"

    def _type_api(self, option: Models.Option | str) -> Type | str:
        if option == Models.Option.LIB_DEPS:
            return Type.LIBRARY
        elif option == Models.Option.PLATFORM:
            return Type.PLATFORM
        elif option == Models.Option.PLATFORM_PACKAGES:
            return Type.TOOL
        else:
            return option

    def _type_html(self, type: Type | str) -> str:
        if type == Type.LIBRARY:
            return "libraries"
        elif type == Type.PLATFORM:
            return "platforms"
        elif type == Type.TOOL:
            return "tools"
        else:
            return type
