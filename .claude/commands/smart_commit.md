# Smart Commit

Analyze git changes and create separate commits by category.

## Workflow

1. Run `git status` and `git diff --name-only` to list changed files
2. Analyze each file's changes with `git diff <file>`
3. Categorize changes into:
   - `feat`: New feature
   - `fix`: Bug fix
   - `refactor`: Code refactoring (no functional change)
   - `test`: Add/modify tests
   - `docs`: Documentation changes
   - `chore`: Build, config, dependencies, etc.
   - `style`: Code style changes (formatting)

4. Group related files by category
5. Create individual commits for each group:
   - `git add <related files>`
   - Commit message format:
     ```
     <category>: <concise description>

     <detailed description (optional)>

     🤖 Generated with [Claude Code](https://claude.com/claude-code)

     Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
     ```

6. Verify with `git log --oneline`

## Guidelines

- Include untracked files in analysis
- Check `git status` before committing
- Group dependent changes into single commit
- Keep commit messages consistent (English preferred)
