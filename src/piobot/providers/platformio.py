import datetime
import re
import typing

import packaging.version
import requests

from .. import models


class File(typing.TypedDict):
    download_url: str
    name: str
    system: str


class Owner(typing.TypedDict):
    username: str


class Version(typing.TypedDict):
    files: list[File]
    name: str
    released_at: str


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
    owner: str | None
    version: str


class Resolve:
    cooldown: datetime.timedelta
    _api: re.Pattern[str]
    _download: re.Pattern[str]
    _package: re.Pattern[str]

    def __init__(self, cooldown: datetime.timedelta) -> None:
        """
        Initialize dependency resolution with the release cooldown and matching patterns.

        Parameters:
                cooldown (datetime.timedelta): Minimum age required for a release to be eligible.
        """
        self.cooldown = cooldown
        self._api = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://api\.registry\.platformio\.org/v3/download/(?P<owner>[^/\s]+)/(?:library|platform|tool)/(?P<name>[^/\s]+)/(?P<version>[^/\s]+)/(?P<file>[^/\s]+)(?:\s*;.*)?$"
        )
        self._download = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://dl\.registry\.platformio\.org/download/(?P<owner>[^/\s]+)/(?:library|platform|tool)/(?P<name>[^/\s]+)/(?P<version>[^/\s]+)/(?P<file>[^/\s]+)(?:\s*;.*)?$"
        )
        self._package = re.compile(
            r"^(?:(?P<owner>[^/\s]+)/)?(?P<name>[^/\s]+?)\s*@\s*(?P<version>[^\s]+)\S*(?:\s*;.*)?$"
        )

    def api(self, dependency: models.Dependency) -> models.Result | str | None:
        """
        Resolve a PlatformIO API download URL to an updated package reference or assignment.

        Parameters:
            dependency (models.Dependency): Dependency containing the API download URL.

        Returns:
            models.Result | str | None: An update result when a newer eligible version is found, an assignment string when the current version is selected, or None when the URL or package cannot be resolved.
        """
        match = typing.cast(Download | None, self._api.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["version"])
        data = self._request_package_version(dependency.option, match["owner"], match["name"], match["version"])
        _version = self._parse(data, version)
        if _version is None:
            return None
        system = self._system(data["version"]["files"], match["file"])
        for file in _version["files"]:
            if file["system"] != system:
                continue
            value = f"{'' if match['package'] is None else f'{match["package"]} @ '}{file['download_url']} ; {_version['name']}"
            if packaging.version.Version(_version["name"]) > version:
                type_ = self._type_html(data["type"])
                return models.Result(
                    body="\n".join(
                        [
                            f"Bumps [{data['owner']['username']}/{data['name']}](https://registry.platformio.org/{type_}/{data['owner']['username']}/{data['name']}) from {match['version']} to {_version['name']}.",
                            f"- [Versions](https://registry.platformio.org/{type_}/{data['owner']['username']}/{data['name']}/versions?version={_version['name']})",
                        ]
                    ),
                    package=f"{data['owner']['username']}/{data['name']}",
                    value=value,
                    version_from=match["version"].removeprefix("v"),
                    version_to=_version["name"].removeprefix("v"),
                )
            return f"{dependency.option} = {value}"
        return None

    def download(self, dependency: models.Dependency) -> models.Result | str | None:
        """
        Resolve a PlatformIO direct download URL to an eligible package version.

        Parameters:
            dependency (models.Dependency): Dependency containing the direct download URL and update option.

        Returns:
            models.Result | str | None: An update result for a newer version, an assignment string for the selected version, or `None` if the URL or matching file cannot be resolved.
        """
        match = typing.cast(Download | None, self._download.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["version"])
        data = self._request_package_version(dependency.option, match["owner"], match["name"], match["version"])
        _version = self._parse(data, version)
        if _version is None:
            return None
        system = self._system(data["version"]["files"], match["file"])
        for file in _version["files"]:
            if file["system"] != system:
                continue
            value = f"{'' if match['package'] is None else f'{match["package"]} @ '}{file['download_url']} ; {_version['name']}"
            if packaging.version.Version(_version["name"]) > version:
                type_ = self._type_html(data["type"])
                return models.Result(
                    body="\n".join(
                        [
                            f"Bumps [{data['owner']['username']}/{data['name']}](https://registry.platformio.org/{type_}/{data['owner']['username']}/{data['name']}) from {match['version']} to {_version['name']}.",
                            f"- [Versions](https://registry.platformio.org/{type_}/{data['owner']['username']}/{data['name']}/versions?version={_version['name']})",
                        ]
                    ),
                    package=f"{data['owner']['username']}/{data['name']}",
                    value=value,
                    version_from=match["version"].removeprefix("v"),
                    version_to=_version["name"].removeprefix("v"),
                )
            return f"{dependency.option} = {value}"
        return None

    def package(self, dependency: models.Dependency) -> models.Result | str | None:
        """
        Resolve a package reference and produce an update result or assignment.

        Parameters:
            dependency (models.Dependency): Dependency option and package reference to resolve.

        Returns:
            models.Result: Update information when a newer eligible version is available.
            str: Assignment using the resolved package version when no update is needed.
            None: If the dependency reference does not match or no eligible version is found.
        """
        match = typing.cast(Package | None, self._package.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["version"])
        data = self._request_package(
            dependency.option, "platformio" if match["owner"] is None else match["owner"], match["name"]
        )
        _version = self._parse(data, version)
        if _version is None:
            return None
        value = f"{data['owner']['username']}/{data['name']} @ {_version['name']}"
        if packaging.version.Version(_version["name"]) > version:
            type_ = self._type_html(data["type"])
            return models.Result(
                body="\n".join(
                    [
                        f"Bumps [{data['owner']['username']}/{data['name']}](https://registry.platformio.org/{type_}/{data['owner']['username']}/{data['name']}) from {match['version']} to {_version['name']}.",
                        f"- [Versions](https://registry.platformio.org/{type_}/{data['owner']['username']}/{data['name']}/versions?version={_version['name']})",
                    ]
                ),
                package=f"{data['owner']['username']}/{data['name']}",
                value=value,
                version_from=match["version"].removeprefix("v"),
                version_to=_version["name"].removeprefix("v"),
            )
        return f"{dependency.option} = {value}"

    def _parse(self, data: Data, version: packaging.version.Version) -> Version | None:
        """
        Select a suitable package version from the available release data.

        Parameters:
            data (Data): Package metadata containing available versions and release timestamps.
            version (packaging.version.Version): Currently requested version.

        Returns:
            Version | None: The first eligible version greater than the requested version, or the first eligible version when no greater version is available; `None` if no valid version qualifies.
        """
        latest = None
        for _candidate in typing.cast(list[Version], data["versions"]):
            try:
                _timestamp = datetime.datetime.fromisoformat(_candidate["released_at"])
                _version = packaging.version.Version(_candidate["name"])
                if (_version.is_prerelease and not version.is_prerelease) or datetime.datetime.now(
                    _timestamp.tzinfo
                ) - _timestamp < self.cooldown:
                    continue
                elif _version > version:
                    return _candidate
                elif not latest:
                    latest = _candidate
            except packaging.version.InvalidVersion:
                print(f"::debug::Invalid version: {data['owner']['username']}/{data['name']} {_candidate['name']}")
                continue
        return latest

    def _request_package(self, option: str, owner: str, name: str) -> Data:
        """
        Fetch package metadata from the PlatformIO registry.

        Parameters:
            option (str): Dependency option used to determine the registry category.
            owner (str): Package owner name.
            name (str): Package name.

        Returns:
            Data: Package metadata.
        """
        return typing.cast(
            Data,
            self._request(
                f"https://api.registry.platformio.org/v3/packages/{owner}/{self._type_api(option)}/{name}"
            ).json(),
        )

    def _request_package_version(self, option: str, owner: str, name: str, version: str) -> Data:
        """
        Fetches package data for a specific version from the PlatformIO registry.

        Parameters:
            option (str): Dependency option used to determine the registry category.
            owner (str): Package owner.
            name (str): Package name.
            version (str): Requested package version.

        Returns:
            Data: Package metadata for the requested version.
        """
        return typing.cast(
            Data,
            self._request(
                f"https://api.registry.platformio.org/v3/packages/{owner}/{self._type_api(option)}/{name}?version={version}"
            ).json(),
        )

    def _request(self, url: str) -> requests.Response:
        """
        Fetch a PlatformIO registry resource.

        Parameters:
            url (str): The resource URL to request.

        Returns:
            requests.Response: The successful HTTP response.

        Raises:
            requests.HTTPError: If the response indicates an HTTP error.
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

    def _system(self, files: list[File], file: str) -> str:
        """
        Find the system associated with a file name.

        Parameters:
            files (list[File]): Available package files.
            file (str): File name to look up.

        Returns:
            str: The matching system, or "*" when no matching file is found.
        """
        for _file in files:
            if _file["name"] == file:
                return _file["system"]
        return "*"

    def _type_api(self, option: models.Option | str) -> str:
        """
        Map a dependency option to its PlatformIO registry category.

        Returns:
            str: The mapped category, or the option value when no mapping exists.
        """
        return {
            models.Option.LIB_DEPS.value: "library",
            models.Option.PLATFORM.value: "platform",
            models.Option.PLATFORM_PACKAGES.value: "tool",
        }.get(str(option), str(option))

    def _type_html(self, type_: str) -> str:
        """Map a PlatformIO registry type to its plural URL path segment.

        Parameters:
            type_ (str): Registry type to convert.

        Returns:
            str: The plural URL path segment, or `type_` when no mapping exists.
        """
        return {
            "library": "libraries",
            "platform": "platforms",
            "tool": "tools",
        }.get(type_, type_)
