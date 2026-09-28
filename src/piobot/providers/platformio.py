import datetime
import re
import typing
import urllib.parse

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


class Item(typing.TypedDict):
    name: str
    owner: Owner
    type: str
    version: Version


class Name(typing.TypedDict):
    name: str
    version: str


class Package(typing.TypedDict):
    name: str
    owner: str
    version: str


class Search(typing.TypedDict):
    items: list[Item]
    limit: int
    page: int
    total: int


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
        self._name = re.compile(r"^(?P<name>[^/@]+?)\s*@\s*(?P<version>[^\s]+)\S*(?:\s*;.*)?$")
        self._package = re.compile(r"^(?P<owner>[^/\s]+)/(?P<name>[^/@]+?)\s*@\s*(?P<version>[^\s]+)\S*(?:\s*;.*)?$")

    def api(self, dependency: models.Dependency) -> models.Result | str | None:
        """
        Resolve a PlatformIO API download URL to an updated package reference or assignment.

        Parameters:
            dependency (models.Dependency): Dependency containing the API download URL.

        Returns:
            models.Result | str | None: An update result when a newer eligible version is found, an assignment string for an equal or older selected version, or None when the URL does not match, no eligible version exists, or no file matches the original system. Result version strings retain any `v` prefix.

        Raises:
            packaging.version.InvalidVersion: If the URL's decoded version is invalid.
            requests.exceptions.RequestException: If a registry request fails or its response is not valid JSON.
            ValueError: If a release timestamp cannot be parsed.
        """
        match = typing.cast(Download | None, self._api.fullmatch(dependency.value))
        if not match:
            return None
        version_ = urllib.parse.unquote(match["version"])
        version = packaging.version.Version(version_)
        data = self._request_package_version(
            dependency.option,
            urllib.parse.unquote(match["owner"]),
            urllib.parse.unquote(match["name"]),
            urllib.parse.unquote(match["version"]),
        )
        _version = self._parse(data, version)
        if _version is None:
            return None
        system = self._system(data["version"]["files"], urllib.parse.unquote(match["file"]))
        for file in _version["files"]:
            if file["system"] != system:
                continue
            value = f"{'' if match['package'] is None else f'{match["package"]} @ '}{file['download_url']} ; {_version['name']}"
            if packaging.version.Version(_version["name"]) > version:
                return models.Result(
                    body="\n".join(
                        self._body(
                            data["type"],
                            data["owner"]["username"],
                            data["name"],
                            version_,
                            _version["name"],
                        )
                    ),
                    package=f"{data['owner']['username']}/{data['name']}",
                    value=value,
                    version_from=version_,
                    version_to=_version["name"],
                )
            return f"{dependency.option} = {value}"
        return None

    def download(self, dependency: models.Dependency) -> models.Result | str | None:
        """
        Resolve a PlatformIO direct download URL to an eligible package version.

        Parameters:
            dependency (models.Dependency): Dependency containing the direct download URL and update option.

        Returns:
            models.Result | str | None: An update result for a newer version, an assignment string for an equal or older selected version, or `None` if the URL does not match, no eligible version exists, or no file matches the original system. Result version strings retain any `v` prefix.

        Raises:
            packaging.version.InvalidVersion: If the URL's decoded version is invalid.
            requests.exceptions.RequestException: If a registry request fails or its response is not valid JSON.
            ValueError: If a release timestamp cannot be parsed.
        """
        match = typing.cast(Download | None, self._download.fullmatch(dependency.value))
        if not match:
            return None
        version_ = urllib.parse.unquote(match["version"])
        version = packaging.version.Version(version_)
        data = self._request_package_version(
            dependency.option,
            urllib.parse.unquote(match["owner"]),
            urllib.parse.unquote(match["name"]),
            urllib.parse.unquote(match["version"]),
        )
        _version = self._parse(data, version)
        if _version is None:
            return None
        system = self._system(data["version"]["files"], urllib.parse.unquote(match["file"]))
        for file in _version["files"]:
            if file["system"] != system:
                continue
            value = f"{'' if match['package'] is None else f'{match["package"]} @ '}{file['download_url']} ; {_version['name']}"
            if packaging.version.Version(_version["name"]) > version:
                return models.Result(
                    body="\n".join(
                        self._body(
                            data["type"],
                            data["owner"]["username"],
                            data["name"],
                            version_,
                            _version["name"],
                        )
                    ),
                    package=f"{data['owner']['username']}/{data['name']}",
                    value=value,
                    version_from=version_,
                    version_to=_version["name"],
                )
            return f"{dependency.option} = {value}"
        return None

    def name(self, dependency: models.Dependency) -> models.Result | str | None:
        """
        Resolve an unscoped PlatformIO dependency name and version.

        Preserve a leading `^`, `~`, `>=`, or `<=` when updating the version; strip `==` as an exact-version marker. Updates may move the version beyond the original range. Bare and `==` versions require a package containing that version; other supported operators require a package containing a version at least as high.

        Parameters:
            dependency (models.Dependency): Dependency reference containing the package name, requested version, and package type option.

        Returns:
            models.Result | str | None: An update result for a newer eligible version, or an assignment string for an equal or older selected version. With a preserved operator, return the original assignment if no eligible candidate is at least the requested version. Return `None` if the reference or package cannot be resolved, or an exact reference has no eligible candidate.

        Raises:
            packaging.version.InvalidVersion: If the requested version is invalid after removing a supported operator.
            requests.exceptions.RequestException: If a registry search fails or returns invalid JSON; for operator searches, package request failures also propagate. Exact-version searches skip failed package requests.
            ValueError: If a release timestamp cannot be parsed.
        """
        match = typing.cast(Name | None, self._name.fullmatch(dependency.value))
        if not match:
            return None
        operator, version_ = self._operator(match["version"])
        version = packaging.version.Version(version_)
        data = (
            self._request_search_version(dependency.option, match["name"], version_)
            if len(operator) == 0
            else self._request_search(dependency.option, match["name"], version_)
        )
        if not data:
            return None
        candidate = self._parse(data, version)
        if len(operator) != 0 and (candidate is None or packaging.version.Version(candidate["name"]) < version):
            return f"{dependency.option} = {dependency.value}"
        if candidate is None:
            return None
        value = f"{data['owner']['username']}/{data['name']} @ {operator}{candidate['name']}"
        if packaging.version.Version(candidate["name"]) > version:
            return models.Result(
                body="\n".join(
                    self._body(
                        data["type"],
                        data["owner"]["username"],
                        data["name"],
                        version_,
                        candidate["name"],
                    )
                ),
                package=f"{data['owner']['username']}/{data['name']}",
                value=value,
                version_from=version_,
                version_to=candidate["name"],
            )
        return f"{dependency.option} = {value}"

    def package(self, dependency: models.Dependency) -> models.Result | str | None:
        """
        Resolve a package reference and produce an update result or assignment.

        Preserve a leading `^`, `~`, `>=`, or `<=` when updating the version; strip `==` as an exact-version marker. Updates may move the version beyond the original range.

        Parameters:
            dependency (models.Dependency): Dependency option and package reference to resolve.

        Returns:
            models.Result: Update information when a newer eligible version is available.
            str: Assignment using an equal or older selected version. With a preserved operator, return the original assignment if no eligible candidate is at least the requested version.
            None: If the dependency reference does not match, or an exact reference has no eligible version.

        Raises:
            packaging.version.InvalidVersion: If the requested version is invalid after removing a supported operator.
            requests.exceptions.RequestException: If a registry request fails or its response is not valid JSON.
            ValueError: If a release timestamp cannot be parsed.
        """
        match = typing.cast(Package | None, self._package.fullmatch(dependency.value))
        if not match:
            return None
        operator, version_ = self._operator(match["version"])
        version = packaging.version.Version(version_)
        data = self._request_package(dependency.option, match["owner"], match["name"])
        candidate = self._parse(data, version)
        if len(operator) != 0 and (candidate is None or packaging.version.Version(candidate["name"]) < version):
            return f"{dependency.option} = {dependency.value}"
        if candidate is None:
            return None
        value = f"{data['owner']['username']}/{data['name']} @ {operator}{candidate['name']}"
        if packaging.version.Version(candidate["name"]) > version:
            return models.Result(
                body="\n".join(
                    self._body(
                        data["type"],
                        data["owner"]["username"],
                        data["name"],
                        version_,
                        candidate["name"],
                    )
                ),
                package=f"{data['owner']['username']}/{data['name']}",
                value=value,
                version_from=version_,
                version_to=candidate["name"],
            )
        return f"{dependency.option} = {value}"

    def _body(self, option: str, owner: str, name: str, version_from: str, version_to: str) -> list[str]:
        type_ = {
            "library": "libraries",
            "platform": "platforms",
            "tool": "tools",
        }.get(option, urllib.parse.quote(option, ""))
        owner_ = urllib.parse.quote(owner, "")
        name_ = urllib.parse.quote(name, "")
        version_ = urllib.parse.quote(version_to, "")
        return [
            f"Bumps [{owner}/{name}](https://registry.platformio.org/{type_}/{owner_}/{name_}) from {version_from} to {version_to}.",
            f"- [Versions](https://registry.platformio.org/{type_}/{owner_}/{name_}/versions?version={version_})",
        ]

    def _operator(self, version: str) -> tuple[str, str]:
        """
        Split a leading `^`, `~`, `>=`, or `<=` from a version string.

        Return the operator and remaining text without validating or trimming it. A leading `==` is removed and returns an empty operator. Strings containing a comma or lacking a recognized prefix are returned unchanged with an empty operator.
        """
        if "," not in version:
            for operator in ("^", "~", ">=", "<="):
                if version.startswith(operator):
                    return operator, version.removeprefix(operator)
            if version.startswith("=="):
                return "", version.removeprefix("==")
        return "", version

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
                f"https://api.registry.platformio.org/v3/packages/{urllib.parse.quote(owner, '')}/{self._type(option)}/{urllib.parse.quote(name, '')}"
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
                f"https://api.registry.platformio.org/v3/packages/{urllib.parse.quote(owner, '')}/{self._type(option)}/{urllib.parse.quote(name, '')}?version={urllib.parse.quote(version, '')}"
            ).json(),
        )

    def _request_search(self, option: str, name: str, version: str) -> Data | None:
        """
        Search the registry for the first package with a version at least as high as requested.

        Parameters:
            option (str): Dependency option or registry category used to scope the search.
            name (str): Package name to search for.
            version (str): Inclusive minimum version, without a range operator.

        Returns:
            Data | None: Metadata for the first qualifying package in search order, or `None` after all search pages are exhausted. Invalid candidate versions are skipped; release cooldown and prerelease eligibility are not checked here.

        Raises:
            packaging.version.InvalidVersion: If the requested minimum version is invalid.
            requests.exceptions.RequestException: If a search or package request fails or returns invalid JSON.
        """
        _type = self._type(option)
        _version = packaging.version.Version(version)
        search = typing.cast(Search, {"items": [], "limit": 50, "page": 0, "total": 1})
        while search["page"] * search["limit"] < search["total"]:
            search = typing.cast(
                Search,
                self._request(
                    f"https://api.registry.platformio.org/v3/search?query=type:{_type}+name:%22{urllib.parse.quote(name, '')}%22&limit={search['limit']!s}{f'&page={(search["page"] + 1)!s}' if search['page'] else ''}"
                ).json(),
            )
            for item in search["items"]:
                data = self._request_package(item["type"], item["owner"]["username"], item["name"])
                for _candidate in data["versions"]:
                    try:
                        if packaging.version.Version(_candidate["name"]) >= _version:
                            return data
                    except packaging.version.InvalidVersion:
                        print(
                            f"::debug::Invalid version: {item['owner']['username']}/{item['name']} {_candidate['name']}"
                        )
        return None

    def _request_search_version(self, option: str, name: str, version: str) -> Data | None:
        """
        Find package metadata for a specific version by searching the registry.

        Return the first successful package lookup in search order. Failed package requests, including invalid JSON responses, are skipped; search request failures propagate.

        Parameters:
            option (str): Package type or API option used to scope the search.
            name (str): Package name to search for.
            version (str): Requested package version.

        Returns:
            Data | None: Metadata for the requested package version, or `None` if no matching package is found.

        Raises:
            requests.exceptions.RequestException: If a search request fails or returns invalid JSON.
        """
        _type = self._type(option)
        search = typing.cast(Search, {"items": [], "limit": 50, "page": 0, "total": 1})
        while search["page"] * search["limit"] < search["total"]:
            search = typing.cast(
                Search,
                self._request(
                    f"https://api.registry.platformio.org/v3/search?query=type:{_type}+name:%22{urllib.parse.quote(name, '')}%22&limit={search['limit']!s}{f'&page={(search["page"] + 1)!s}' if search['page'] else ''}"
                ).json(),
            )
            for item in search["items"]:
                try:
                    return self._request_package_version(item["type"], item["owner"]["username"], item["name"], version)
                except requests.exceptions.RequestException:
                    print(f"::debug::Invalid version: {item['owner']['username']}/{item['name']} {version}")
        return None

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

    def _type(self, option: models.Option | str) -> str:
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
