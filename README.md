# PlatformIO Dependency Updater

A GitHub Action that checks `platformio.ini` for dependency updates and creates pull requests when newer versions become available.

## Features

* Multiple dependency sources; *PlatformIO Registry*, *ESP Registry*, *GitHub*, *GitLab*, *Bitbucket*, and *Arduino* libraries
* Supports pre-release versions and custom package versions
* PRs include links to release notes and changelog when available
* Applies the `dependencies` and `platformio` labels if they exist
* Keeps PRs manageable with a maximum of 5 open dependency PRs
* Built-in 3-day cooldown for new releases to avoid faulty versions
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
        uses: actions/checkout

      - name: Check for dependency updates
        uses: VIPnytt/platformio-dependency-updater
```

## How updates work

The action performs the following steps:

1. Reads dependency definitions from `platformio.ini`
2. Resolves the dependency provider
3. Queries available versions
4. Compares the current version with available releases or tags
5. Creates a dedicated update branch
6. Updates the dependency reference
7. Opens a pull request

Existing dependency pull requests are automatically managed to avoid duplicates and keep updates current.

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
