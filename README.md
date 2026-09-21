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
        uses: VIPnytt/platformio-dependency-updater@v1.0.2
```

## Options

### `cooldown`

Defines a cooldown period for dependency updates, allowing updates to be delayed for a configurable number of days.

Default is `3` days.

### `labels`

Specify your own labels for all pull requests raised. Multiple labels can be specified as a comma-separated list.

Defaults to `dependencies,platformio`.

### `open-pull-requests-limit`

Change the limit on the maximum number of pull requests for version updates open at any time.

Default is `5` concurrent PRs.

### `project-dir`

Specify the path to project directory.

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
        uses: VIPnytt/platformio-dependency-updater@v1.0.2
        with:
          token: ${{ secrets.GITHUB_TOKEN }} # see "Choosing a token"
          cooldown: 3                     # days
          labels: dependencies,platformio # comma-separated list
          open-pull-requests-limit: 5     # PRs
          project-dir: .                  # directory containing platformio.ini
```

## Choosing a token

`token` defaults to the workflow token, which is enough for a repository whose
dependencies are all public and where the pull requests are reviewed by hand.

Supply a personal access token or a GitHub App token instead when either of the
following applies:

- **Dependencies live in private repositories.** The workflow token is scoped to
  the repository running the workflow, so tags and releases in any other private
  repository are invisible and those dependencies silently never update.
- **You want CI to run on the pull requests.** GitHub does not start workflow
  runs for events raised by the workflow token, so pull requests opened with it
  arrive with no checks. A dependency bump that has not been built is not worth
  much, and firmware projects in particular want the build and any size report
  attached before the bump is merged.

```yaml
        with:
          token: ${{ secrets.DEPENDENCY_UPDATER_TOKEN }}
```

The token needs `contents: write` and `pull-requests: write` on this repository,
plus read access to any private repository a dependency points at.

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
