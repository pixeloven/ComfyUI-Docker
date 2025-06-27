# Free Disk Space Action

A composite GitHub Action that maximizes available disk space on GitHub Actions runners by removing unnecessary packages, files, and Docker images.

## Features

- Uses `easimon/maximize-build-space` action for initial cleanup
- Removes large directories (dotnet, android, ghc, etc.)
- Purges unnecessary packages using aptitude
- Provides detailed disk usage reporting
- Configurable options for different cleanup levels

## Usage

### Basic Usage

```yaml
steps:
  - name: Free disk space
    uses: ./.github/actions/free-disk-space
```

### Advanced Usage with Custom Options

```yaml
steps:
  - name: Free disk space
    uses: ./.github/actions/free-disk-space
    with:
      swap-size-mb: '2048'
      remove-dotnet: 'true'
      remove-android: 'true'
      remove-haskell: 'true'
      remove-codeql: 'true'
      remove-docker-images: 'true'
      show-disk-usage: 'true'
```

## Inputs

| Input | Description | Required | Default |
|-------|-------------|----------|---------|
| `swap-size-mb` | Swap size in MB for maximize-build-space action | No | `1024` |
| `remove-dotnet` | Remove .NET from maximize-build-space action | No | `true` |
| `remove-android` | Remove Android from maximize-build-space action | No | `true` |
| `remove-haskell` | Remove Haskell from maximize-build-space action | No | `true` |
| `remove-codeql` | Remove CodeQL from maximize-build-space action | No | `true` |
| `remove-docker-images` | Remove Docker images from maximize-build-space action | No | `true` |
| `show-disk-usage` | Show detailed disk usage information after cleanup | No | `true` |

## What Gets Removed

### Directories
- `/usr/share/dotnet` - .NET runtime and SDK
- `/usr/local/lib/android` - Android SDK
- `/opt/ghc` - Glasgow Haskell Compiler
- `/usr/local/share/powershell` - PowerShell
- `/usr/share/swift` - Swift language
- `/usr/local/.ghcup` - Haskell toolchain installer
- `/usr/lib/jvm` - Java Virtual Machines

### Packages
- Development tools: `aria2`, `ansible`, `azure-cli`, `shellcheck`
- Browsers: `firefox`, `google-chrome-stable`, `microsoft-edge-stable`
- Language runtimes: `gfortran-8`, `gfortran-9`, `mono-complete`, `ruby-full`
- Database clients: `postgresql-client`, `mongodb-org`
- Image processing: `imagemagick`, `libmagick*`
- And many more...

## Disk Space Savings

Typically frees up 10-15GB of disk space on standard GitHub Actions runners, bringing available space from ~14GB to ~25-30GB.

## Notes

- This action should be run early in your workflow, before checking out code
- Some package removals may produce warnings - these are generally safe to ignore
- The action uses `aptitude` for better dependency resolution during package removal
- All operations are designed to be safe and not affect the core Ubuntu system functionality needed for CI/CD
