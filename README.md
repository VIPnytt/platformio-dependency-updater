# 🤖 PlatformIO Dependency Updater

A GitHub Action that checks `platformio.ini` for dependency updates and creates pull requests when newer versions become available.

**Supported providers:** PlatformIO Registry · GitHub · GitLab · Bitbucket · Espressif · Arduino · SourceForge

## Highlights

* Release notes link in the PR description, when available
* Channel-aware pre-release handling
* Configurable cooldown period for delaying fresh updates
* Pauses updates for inactive repositories after 3 months

## Usage

Create a workflow file such as:

`.github/workflows/platformio.yml`

```yaml
name: PlatformIO Dependency Updater

on:
  schedule:
    - cron: "0 9 * * 1" # Mondays at 09:00 UTC

jobs:
  platformio:
    name: Update PlatformIO dependencies
    runs-on: ubuntu-slim
    permissions:
      contents: write      # Required for creating branches and pushing commits
      pull-requests: write # Required for creating and modifying pull requests

    steps:
      - name: Checkout the repository
        uses: actions/checkout@v7

      - name: Check for dependency updates
        uses: VIPnytt/platformio-dependency-updater@v1.1.0
```

## Options

### `cooldown`

Number of days to delay an update after a release is published.

Defaults to `3` days. Ignored for Arduino and SourceForge dependencies, as neither provider exposes release dates.

### `labels`

Comma-separated list of labels to apply to created pull requests.

Defaults to `dependencies,platformio`.

### `open-pull-requests-limit`

Maximum number of open pull requests permitted at any time.

Defaults to `5`.

### `project-dir`

Path to the directory containing `platformio.ini`.

Defaults to repository root (`.`).

## Full example

```yaml
name: PlatformIO Dependency Updater

on:
  schedule:
    - cron: "0 9 * * 1-5" # Weekdays at 09:00 UTC

jobs:
  platformio:
    name: Update PlatformIO dependencies
    runs-on: ubuntu-slim
    permissions:
      contents: write      # Required for creating branches and pushing commits
      pull-requests: write # Required for creating and modifying pull requests

    steps:
      - name: Checkout the repository
        uses: actions/checkout@v7

      - name: Check for dependency updates
        uses: VIPnytt/platformio-dependency-updater@v1.1.0
        with:
          cooldown: 3                     # days
          labels: dependencies,platformio # comma-separated list
          open-pull-requests-limit: 5     # PRs
          project-dir: .                  # directory containing platformio.ini
```

## Troubleshooting

### Unexpected or outdated version proposed

Upstream projects occasionally change versioning schemes, or actively maintain multiple release lines at once.

Prioritizing version progression over release dates ensures projects on stable branches continue receiving backports and security fixes without losing their upgrade path. A natural trade-off is that older historical releases with high numerical values, like CalVer tags, can initially appear as candidate upgrades.

Close pull requests for unwanted releases. The action records the closure and will not propose that release again, but will continue checking on schedule and propose an update once a newer release appears upstream.

### Indeterminate dependencies

The updater requires a baseline version to calculate available updates. If a baseline cannot be determined from the dependency definition, it will be reported as *Indeterminate* in the workflow summary.

It most commonly occurs when a dependency is intentionally unpinned (e.g., a bare PlatformIO Registry package) or uses an opaque format (e.g., a Git commit SHA or floating branch).

To track these dependencies, explicitly supply a baseline version. Pin the package directly, or for opaque URLs, append the version as an inline comment as shown below. The updater will parse the comment and use it as the baseline for comparison.

```ini
platform = https://api.github.com/repos/pioarduino/platform-espressif32/tarball/cbc3349061987c28bc1b48d43d473e70c5ae04ed ; 55.03.39
platform_packages =
    framework-arduinoespressif32 @ https://api.github.com/repos/espressif/arduino-esp32/tarball/5b5114c832dfe309f3e73879d2ac8922c8276559 ; 3.3.9
lib_deps =
    bblanchon/ArduinoJson @ 7.4.3
```

### Pull requests does not appear

Ensure the workflow has write permissions and that it has permission to create pull requests.

```yaml
permissions:
  contents: write
  pull-requests: write
```

Repository > Settings > Actions > General:

> :ballot_box_with_check: Allow GitHub Actions to create and approve pull requests

If GitHub Actions was previously unable to create pull requests due to insufficient permissions, `dependabot/platformio/`-prefixed branches may have been left behind. Delete any existing branches before rerunning the workflow.
