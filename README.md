# PlatformIO Dependency Updater

A GitHub Action that checks `platformio.ini` for dependency updates and creates pull requests when newer versions become available.

## Highlights

* Multiple dependency sources; *PlatformIO*, *Espressif*, *GitHub*, *GitLab*, *Bitbucket*, and *Arduino*
* Release notes included in the PR description, when available
* Channel-aware pre-release handling
* Support for custom platform-package versions
* Pauses updates for inactive repositories after 3 months

## Limitations

* Dependencies must be pinned to a specific version
* Version ranges are not supported

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
        uses: VIPnytt/platformio-dependency-updater@v1.0.0-b2
```

## Options

### `cooldown`

Defines a cooldown period for dependency updates, allowing updates to be delayed for a configurable number of days.

Defaults `3` days.

### `labels`

Specify your own labels for all pull requests raised. Multiple labels can be specified as a comma-separated list.

Defaults to `dependencies,platformio`.

### `open-pull-requests-limit`

Change the limit on the maximum number of pull requests for version updates open at any time.

Defaults to `5` PRs.

### `project-dir`

Specify the path to project directory.

Defaults to `.` (the root of the repository).

## Full example

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
        uses: VIPnytt/platformio-dependency-updater@v1.0.0-b2
        with:
          cooldown: 3                     # days
          labels: dependencies,platformio # comma-separated list
          open-pull-requests-limit: 5     # PRs
          project-dir: .                  # directory containing platformio.ini
```

## Troubleshooting

### Dependency cannot be resolved

Available updates are determined by comparing the current version with versions reported by the provider. Some dependency URLs do not contain enough information to determine the current version.

For example, a commit SHA identifies a specific revision, but it does not indicate which release or tag it belongs to. In these cases, add the current version as an inline comment:

```ini
lib_deps =
    https://github.com/example/library/archive/<commit>.tar.gz ; v1.0.0
```

The same applies to other dependency formats where the version cannot be directly extracted from the URL.

If a dependency cannot be resolved, it will be reported as an unresolved dependency in the workflow summary. This usually indicates that a version comment is required or that the dependency format is not currently supported.

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
