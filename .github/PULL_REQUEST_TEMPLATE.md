<!-- Thanks for the PR! Keep the sections that apply, delete the rest. -->

## Summary

<!-- What does this PR change, and why? Link the issue: "Closes #123". -->

## Change type

- [ ] Bug fix (non-breaking)
- [ ] New feature (non-breaking)
- [ ] Refactor / chore
- [ ] Docs
- [ ] Breaking change (called out in CHANGELOG.md)

## Checklist

- [ ] Linked the issue (if any).
- [ ] Added/updated tests for behavior changes.
- [ ] `uv run ruff check apps tests && uv run ruff format --check apps tests` passes.
- [ ] `uv run pytest -k "not pg and not temporal and not bench"` passes.
- [ ] `cd apps/web && npm run build && npm test` passes (if web touched).
- [ ] Updated `CHANGELOG.md` under `[Unreleased]` for user-facing changes.
- [ ] No secrets / internal-only data added.

## Notes for reviewers

<!-- Anything non-obvious, trade-offs, or follow-ups. -->
