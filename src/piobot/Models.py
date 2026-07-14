import dataclasses
import enum


@dataclasses.dataclass(frozen=True)
class Config:
    FILE: str = "platformio.ini"
    USER_AGENT: str = "platformio-dependency-updater (+https://github.com/VIPnytt/platformio-dependency-updater)"


class Option(enum.StrEnum):
    LIB_DEPS = "lib_deps"
    PLATFORM = "platform"
    PLATFORM_PACKAGES = "platform_packages"


@dataclasses.dataclass(frozen=True)
class Dependency:
    line: int
    option: Option
    value: str


@dataclasses.dataclass(frozen=True)
class Result:
    body: str
    package: str
    value: str
    version_from: str
    version_to: str
