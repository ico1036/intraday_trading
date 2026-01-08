# Sync Docs

Check and update all documentation files (README, docs/*.md) to reflect current codebase changes.

## Workflow

1. Run `git status` and `git diff --name-only` to identify changed files
2. Analyze the nature of changes:
   - New features or modules
   - API changes
   - New strategies or runners
   - Configuration changes
   - Dependency changes

3. Identify documentation files to check:
   - `README.md` - Main project documentation
   - `docs/*.md` - Additional documentation
   - `CLAUDE.md` - Development guidelines (only if dev workflow changes)

4. For each documentation file, verify:
   - Architecture diagrams match current structure
   - Code examples are valid and up-to-date
   - API references are correct
   - Installation/usage instructions work
   - Project structure section is accurate

5. Update documentation:
   - Add new features to appropriate sections
   - Update code examples if APIs changed
   - Update project structure if files added/moved
   - Keep existing style and formatting

6. Report changes:
   - List which docs were updated
   - Summarize what was changed
   - Note any manual review needed

## Guidelines

- Only update docs that need changes (don't touch unchanged sections)
- Preserve existing documentation style and language
- Keep README.md concise - detailed docs go in `docs/`
- Code examples must be runnable
- Architecture diagrams should use ASCII art format
- If uncertain about a change, flag it for manual review

## Skip Conditions

- No code changes detected (only test changes, formatting, etc.)
- Changes are internal refactoring with no API impact
- Documentation already reflects current state
