---
description: Query strategy knowledge base for lessons, similar strategies, and best practices
argument-hint: <subcommand> [args]
allowed-tools: Read, Grep
---

# Strategy Knowledge Base Query

You are querying the strategy ontology knowledge base to help with trading strategy development.

## Available Subcommands

| Subcommand | Usage | Description |
|------------|-------|-------------|
| `lessons` | `/strategy-kb lessons <indicator\|tag>` | Get lessons for indicator/tag |
| `similar` | `/strategy-kb similar <strategy>` | Find similar strategies |
| `indicator` | `/strategy-kb indicator <name>` | Get best practices for indicator |
| `mistakes` | `/strategy-kb mistakes <pattern>` | Lookup common mistake patterns |
| `search` | `/strategy-kb search <query>` | Semantic search across KB |
| `stats` | `/strategy-kb stats` | Show KB statistics |

## Arguments

$ARGUMENTS

## Data Source

Read the knowledge base from: `strategies_ontology.json`

## Instructions

1. Parse the subcommand from the first argument
2. Read `strategies_ontology.json`
3. Filter relevant entries based on subcommand:
   - `lessons`: Filter `lessons_learned` by `affected_indicators` or `tags`
   - `similar`: Filter `relationships` where `type=similar_to` or `shares_indicator`
   - `indicator`: Return `indicator_taxonomy[name]` with strategies using it
   - `mistakes`: Return `common_mistakes[pattern]`
   - `search`: Semantic match against `hypothesis`, `tags`, `title` fields
   - `stats`: Show strategy count, approved count, indicator count
4. Format response concisely (max 5 results unless stats)
5. Include actionable `fix` and `prevention` for lessons

## Response Format

For `lessons`:
```
## /strategy-kb lessons {args}

Found N lessons related to "{args}":

### L001: [Title] (severity: critical)
- **Source**: {strategy}, iteration {n}
- **Issue**: {brief description}
- **Fix**: {actionable fix}
- **Prevention**: {how to avoid}

---
Related strategies: {list}
```

For `similar`:
```
## /strategy-kb similar {strategy}

### Similar Strategies

| Strategy | Relationship | Shared |
|----------|--------------|--------|
| {name} | {type} | {indicators/concepts} |

### Recommendations
- {strategy1}의 {feature} 참조 가능
```

For `indicator`:
```
## /strategy-kb indicator {name}

### {name} Usage

**Strategies using {name}**: {count}
- {list}

### Best Practices
- {practice1}
- {practice2}
```

For `mistakes`:
```
## /strategy-kb mistakes {pattern}

### Pattern: {pattern}

| Field | Value |
|-------|-------|
| Symptoms | {list} |
| Cause | {cause} |
| Prevention | {prevention} |

### Affected Strategies
- {list}
```

For `stats`:
```
## /strategy-kb stats

### Knowledge Base Statistics

| Category | Count |
|----------|-------|
| Total Strategies | N |
| Approved | N |
| In Progress | N |
| Rejected | N |
| Relationships | N |
| Indicators | N |
| Lessons | N |

### Top Indicators
- {indicator1}: N strategies
- {indicator2}: N strategies
```
