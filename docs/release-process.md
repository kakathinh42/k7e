# Release process

k7e follows [Semantic Versioning](https://semver.org/). While at `0.x`,
minor bumps may include breaking changes (called out in the changelog).

## Cutting a release

1. Ensure `main` is green (CI passing) and the working tree is clean.
2. Update [`CHANGELOG.md`](../CHANGELOG.md):
   - Move `[Unreleased]` items under a new `## [x.y.z] - YYYY-MM-DD` heading.
   - Add a fresh `## [Unreleased]` section on top.
3. Commit: `docs(changelog): prepare x.y.z`.
4. Tag: `git tag -a vx.y.z -m "vx.y.z"`.
5. Push: `git push && git push --tags`.
6. The release workflow creates a GitHub Release from the tag. Paste the
   changelog section into the release notes.
7. Confirm the published artifacts and the `latest` badge update.

## Breaking changes

While at `0.x`, breaking changes are allowed in minor releases and MUST be:
- called out under a `### Changed` (breaking) entry in `CHANGELOG.md`,
- noted in the PR description with a migration note.

At `1.0+`, breaking changes require a major-version bump.

## Supported versions

See [`SECURITY.md`](../SECURITY.md): fixes target latest `main` and the most
recent release tag.
