import dataclasses
import enum
import github.Consts


@dataclasses.dataclass(frozen=True)
class Config:
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
class Defaults:
    COOLDOWN: str = "3"
    LABELS: str = "dependencies,platformio"
    OPEN_PULL_REQUESTS_LIMIT: str = "5"
    PROJECT_DIR: str = "."


@dataclasses.dataclass(frozen=True)
class Inputs:
    COOLDOWN: str = "COOLDOWN"
    LABELS: str = "LABELS"
    OPEN_PULL_REQUESTS_LIMIT: str = "OPEN_PULL_REQUESTS_LIMIT"
    PROJECT_DIR: str = "PROJECT_DIR"


@dataclasses.dataclass(frozen=True)
class Result:
    body: str
    package: str
    value: str
    version_from: str
    version_to: str
