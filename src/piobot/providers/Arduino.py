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
                timeout=Models.Config.TIMEOUT,
            )
            response.raise_for_status()
            self._data = typing.cast(Data, response.json())
        except Exception:
            self._data["libraries"] = []

    def library(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(Match | None, self._libraries.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["version"])
        library = self._parse(match["name"], version)
        if library is None:
            return None
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}{library['url']} ; {library['version']}"
        return (
            Models.Result(
                body=f"Bumps [{library['name']}]({library['website']}) from {match['version']} to {library['version']}.",
                package=library["name"],
                value=value,
                version_from=match["version"].removeprefix("v"),
                version_to=library["version"].removeprefix("v"),
            )
            if packaging.version.Version(library["version"]) > version
            else f"{dependency.option} = {value}"
        )

    def _parse(self, name: str, version: packaging.version.Version) -> Library | None:
        """
        Select a library record matching the requested name and version criteria.
        
        Parameters:
            name (str): Library name to match.
            version (packaging.version.Version): Version used to select a candidate.
        
        Returns:
            Library | None: The first matching library with a greater eligible version, or the first eligible matching library when no greater version exists; `None` if no matching library is found.
        """
        latest = None
        for _library in self._data["libraries"]:
            if _library["name"] != name:
                continue
            try:
                _version = packaging.version.Version(_library["version"])
                if _version.is_prerelease and not version.is_prerelease:
                    continue
                elif _version > version:
                    return _library
                elif not latest:
                    latest = _library
            except packaging.version.InvalidVersion:
                print(f"::debug::Invalid version: {_library['name']} {_library['version']}")
                continue
        return latest
