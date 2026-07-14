import packaging.version
import re
import requests
import typing

from .. import Models


class Library(typing.TypedDict):
    name: str
    url: str
    version: str
    website: str


class Data(typing.TypedDict):
    libraries: list[Library]


class Match(typing.TypedDict):
    name: str
    package: str | None
    version: str


class Resolve:
    _data: Data
    _libraries: re.Pattern[str]

    def __init__(self) -> None:
        self._libraries = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://downloads\.arduino\.cc/libraries/(?:[^\s]+)/(?P<name>[^/\s]+)-(?P<version>[^/\s]+)\.zip(?:\s*;.*)?$"
        )
        try:
            response = requests.get(
                "https://downloads.arduino.cc/libraries/library_index.json",
                headers={
                    "Accept": "application/json",
                    "User-Agent": Models.Config.USER_AGENT,
                },
            )
            response.raise_for_status()
            self._data = typing.cast(Data, response.json())
        except Exception:
            self._data["libraries"] = []

    def libraries(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(Match | None, self._libraries.fullmatch(dependency.value))
        if not match:
            return
        version = packaging.version.Version(match["version"])
        library = self._parse(match["name"], version.is_prerelease)
        if library is None:
            return
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}{library['url']} ; {library['version']}"
        if packaging.version.Version(library["version"]) > version:
            return Models.Result(
                body=f"Bumps [{library['name']}]({library['website']}) from {match['version']} to {library['version']}.",
                package=library["name"],
                value=value,
                version_from=match["version"].removeprefix("v"),
                version_to=library["version"].removeprefix("v"),
            )
        return f"{dependency.option} = {value}"

    def _parse(self, name: str, prerelease: bool) -> Library | None:
        library = None
        version = None
        for _library in self._data["libraries"]:
            if _library["name"] != name:
                continue
            try:
                _version = packaging.version.Version(_library["version"])
                if _version.is_prerelease and not prerelease:
                    continue
            except packaging.version.InvalidVersion:
                print(
                    f"::debug::Invalid version: {_library['name']} {_library['version']}"
                )
                continue
            if library is None or version is None or _version > version:
                library = _library
                version = _version
        return library
