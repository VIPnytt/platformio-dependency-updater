import dataclasses
import enum
import github.Consts


@dataclasses.dataclass(frozen=True)
class Config:
    COOLDOWN: int = 3
    FILE: str = "platformio.ini"
    TIMEOUT: int = github.Consts.DEFAULT_TIMEOUT
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
