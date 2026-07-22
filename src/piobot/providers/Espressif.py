import datetime
import packaging.version
import re
import requests
import typing

from .. import Models


class Version(typing.TypedDict):
    created_at: str
    id: str
    url: str
    version: str
    yanked_at: str | None


class Data(typing.TypedDict):
    name: str
    namespace: str
    versions: list[Version]


class Disposition(typing.TypedDict):
    name: str
    namespace: str
    version: str


class Api(typing.TypedDict):
    id: str
    package: str | None


class Component(typing.TypedDict):
    file: str
    name: str
    namespace: str
    package: str | None
    version: str


class Resolve:
    _api: re.Pattern[str]
    _component: re.Pattern[str]

    def __init__(self) -> None:
        self._disposition = re.compile(r"^\S+;\s?filename=(?P<namespace>\S+)__(?P<name>\S+)-v(?P<version>\S+)\.\S+$")
        self._api = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://components\.espressif\.com/api/downloads/\?object_type=component&object_id=(?P<id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:\s*;.*)?$"
        )
        self._component = re.compile(
            r"^(?:(?P<package>(?:[^/\s]+/)?[^/\s]+)?\s*@\s*)?https://components-file\.espressif\.com/components/(?P<namespace>[^/\s]+)/(?P<name>[^/\s]+)/(?P<version>[^/\s]+)/(?P<file>[^/\s]+)(?:\s*;.*)?$"
        )

    def component(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(Component | None, self._component.fullmatch(dependency.value))
        if not match:
            return None
        version = packaging.version.Version(match["version"])
        data = self._request_component(match["namespace"], match["name"])
        _version = self._parse(data, version)
        if _version is None:
            return None
        value = (
            f"{'' if match['package'] is None else f'{match["package"]} @ '}{_version['url']} ; {_version['version']}"
        )
        if packaging.version.Version(_version["version"]) > version:
            return Models.Result(
                body="\n".join(
                    [
                        f"Bumps [{data['namespace']}/{data['name']}](https://components.espressif.com/components/{data['namespace']}/{data['name']}/versions/{_version['version']}) from {match['version']} to {_version['version']}.",
                        f"- [Versions](https://components.espressif.com/components/{data['namespace']}/{data['name']}/versions/{_version['version']}/versions)",
                    ]
                ),
                package=f"{data['namespace']}/{data['name']}",
                value=value,
                version_from=match["version"].removeprefix("v"),
                version_to=_version["version"].removeprefix("v"),
            )
        return f"{dependency.option} = {value}"

    def component_id(self, dependency: Models.Dependency) -> Models.Result | str | None:
        match = typing.cast(Api | None, self._api.fullmatch(dependency.value))
        if not match:
            return None
        disposition = self._request_component_id(match["id"])
        version = packaging.version.Version(disposition["version"])
        data = self._request_component(disposition["namespace"], disposition["name"])
        _version = self._parse(data, version)
        if _version is None:
            return None
        value = f"{'' if match['package'] is None else f'{match["package"]} @ '}https://components.espressif.com/api/downloads/?object_type=component&object_id={_version['id']} ; {data['namespace']}/{data['name']} {_version['version']}"
        if packaging.version.Version(_version["version"]) > version:
            return Models.Result(
                body="\n".join(
                    [
                        f"Bumps [{data['namespace']}/{data['name']}](https://components.espressif.com/components/{data['namespace']}/{data['name']}/versions/{_version['version']}) from {disposition['version']} to {_version['version']}.",
                        f"- [Versions](https://components.espressif.com/components/{data['namespace']}/{data['name']}/versions/{_version['version']}/versions)",
                    ]
                ),
                package=f"{data['namespace']}/{data['name']}",
                value=value,
                version_from=disposition["version"].removeprefix("v"),
                version_to=_version["version"].removeprefix("v"),
            )
        return f"{dependency.option} = {value}"

    def _parse(self, data: Data, version: packaging.version.Version) -> Version | None:
        latest = None
        for _candidate in typing.cast(list[Version], data["versions"]):
            try:
                _version = packaging.version.Version(_candidate["version"])
                if (
                    _candidate["yanked_at"] is not None
                    or (_version.is_prerelease and not version.is_prerelease)
                    or datetime.datetime.now(datetime.timezone.utc)
                    - datetime.datetime.fromisoformat(_candidate["created_at"])
                    < datetime.timedelta(days=Models.Config.COOLDOWN)
                ):
                    continue
                elif _version > version:
                    return _candidate
                elif not latest:
                    latest = _candidate
            except packaging.version.InvalidVersion:
                print(f"::debug::Invalid version: {data['namespace']}/{data['name']} {_candidate['version']}")
                continue
        return latest

    def _request_component(self, namespace: str, name: str) -> Data:
        response = requests.get(
            url=f"https://components.espressif.com/api/components/{namespace}/{name}",
            headers={
                "Accept": "application/json",
                "User-Agent": Models.Config.USER_AGENT,
            },
            timeout=Models.Config.TIMEOUT,
        )
        response.raise_for_status()
        return typing.cast(Data, response.json())

    def _request_component_id(self, id: str) -> Disposition:
        response = requests.head(
            url=f"https://components.espressif.com/api/downloads/?object_type=component&object_id={id}",
            headers={"User-Agent": Models.Config.USER_AGENT},
            timeout=Models.Config.TIMEOUT,
        )
        response.raise_for_status()
        return typing.cast(Disposition, response.headers["Content-Disposition"])
