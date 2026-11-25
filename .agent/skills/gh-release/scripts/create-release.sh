#!/bin/bash
set -e

VERSION=""
NOTES_FILE=""

usage() {
  echo "Usage: $0 <version> [--notes-file <path>]"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --notes-file)
      if [[ -z "${2:-}" ]]; then
        echo "Error: --notes-file requires a file path."
        usage
      fi
      NOTES_FILE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      ;;
    -*)
      echo "Error: Unknown option: $1"
      usage
      ;;
    *)
      if [[ -z "$VERSION" ]]; then
        VERSION="$1"
        shift
      else
        echo "Error: Unexpected argument: $1"
        usage
      fi
      ;;
  esac
done

if [[ -z "$VERSION" ]]; then
  usage
fi

if [[ -n "$NOTES_FILE" && ! -f "$NOTES_FILE" ]]; then
  echo "Error: Release notes file not found: $NOTES_FILE"
  exit 1
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [[ "$BRANCH" != "main" ]]; then
  echo "Error: You must be on the main branch to create a release."
  exit 1
fi

if [[ -n $(git status -s) ]]; then
  echo "Error: Working directory is not clean. Please commit or stash your changes."
  exit 1
fi

if ! command -v gh &> /dev/null; then
  echo "gh command could not be found, please install it first"
  exit 1
fi

FILE_PATH="pyproject.toml"

if [ ! -f "$FILE_PATH" ]; then
  echo "Error: $FILE_PATH not found."
  exit 1
fi

# Update version in pyproject.toml using sed
# This assumes the format: version = "X.Y.Z"
if [[ "$OSTYPE" == "darwin"* ]]; then
  # macOS requires an empty string argument for -i
  sed -i '' "s/^version = \".*\"/version = \"$VERSION\"/" "$FILE_PATH"
else
  sed -i "s/^version = \".*\"/version = \"$VERSION\"/" "$FILE_PATH"
fi

git add "$FILE_PATH"
if [ -f "uv.lock" ]; then
  # Ensure uv.lock version update is also staged if present
  uv lock || true
  git add uv.lock
fi
git commit -m "chore(release): $VERSION"
git push

if [[ -n "$NOTES_FILE" ]]; then
  gh release create "$VERSION" --title "$VERSION" --notes-file "$NOTES_FILE"
else
  gh release create "$VERSION" --title "$VERSION" --generate-notes
fi
