#!/usr/bin/env python3
"""
Strategy Ontology Builder (Hybrid Approach)

2-Layer Generation:
- Layer 1: Rule-Based extraction (fast, structured)
- Layer 2: Semantic analysis with Opus 4.5 (deep, nuanced) [--semantic]

Usage:
    uv run python scripts/build_ontology.py              # Rule-based only
    uv run python scripts/build_ontology.py --semantic   # With semantic enrichment
"""

import argparse
import json
import re
from datetime import datetime
from pathlib import Path


# Known indicators for extraction
KNOWN_INDICATORS = [
    "vpin",
    "ofi",
    "rsi",
    "bollinger_bands",
    "keltner_channel",
    "macd",
    "volume_imbalance",
    "funding_rate",
    "cvd",
    "sma",
    "ema",
    "atr",
    "squeeze",
    "vwap",
    "td9",
    "stacked_imbalance",
    "iceberg",
    "footprint",
]

# Strategy categories
CATEGORY_KEYWORDS = {
    "volatility_breakout": ["breakout", "squeeze", "volatility", "expansion"],
    "mean_reversion": ["reversion", "contrarian", "fade", "mean"],
    "momentum": ["momentum", "trend", "crossover", "continuation"],
    "market_making": ["dual", "scalping", "spread"],
    "regime_based": ["regime", "filter", "divergence"],
}


def extract_indicators_from_code(code_path: Path) -> list[str]:
    """Extract indicators from strategy code."""
    if not code_path.exists():
        return []

    code = code_path.read_text().lower()
    found = []

    for indicator in KNOWN_INDICATORS:
        # Check various patterns
        patterns = [
            indicator,
            indicator.replace("_", ""),
            indicator.replace("_", " "),
        ]
        for pattern in patterns:
            if pattern in code:
                found.append(indicator)
                break

    return list(set(found))


def categorize_strategy(name: str, indicators: list[str], hypothesis: str) -> str:
    """Categorize strategy based on name, indicators, and hypothesis."""
    text = f"{name} {' '.join(indicators)} {hypothesis}".lower()

    scores = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scores[category] = score

    if scores:
        return max(scores, key=scores.get)
    return "uncategorized"


def parse_metrics_table(text: str, section_name: str) -> dict:
    """Parse a metrics table from markdown."""
    metrics = {}

    # Find the section
    pattern = rf"\*\*{section_name}\*\*:?\s*\n\|.*?\n\|[-\s|]+\n((?:\|.*?\n)*)"
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return metrics

    rows = match.group(1).strip().split("\n")
    for row in rows:
        cols = [c.strip() for c in row.split("|") if c.strip()]
        if len(cols) >= 2:
            metric_name = cols[0].lower().replace(" ", "_")
            value_str = cols[1]

            # Parse numeric value
            num_match = re.search(r"[+-]?[\d.]+", value_str.replace("%", ""))
            if num_match:
                try:
                    metrics[metric_name] = float(num_match.group())
                except ValueError:
                    pass

    return metrics


def parse_memory_file(memory_path: Path) -> dict:
    """Parse memory.md file to extract strategy metadata."""
    if not memory_path.exists():
        return {}

    text = memory_path.read_text()
    data = {
        "iterations": 0,
        "status": "unknown",
        "best_metrics": {},
        "hypothesis": "",
        "lessons": [],
    }

    # Extract goal/hypothesis from CORE GOAL table
    goal_match = re.search(r"\| Goal \| (.+?) \|", text)
    if goal_match:
        data["hypothesis"] = goal_match.group(1).strip()

    hypothesis_match = re.search(r"\| Hypothesis \| (.+?) \|", text)
    if hypothesis_match:
        data["hypothesis"] = hypothesis_match.group(1).strip()

    # Count iterations
    iteration_matches = re.findall(r"### Iteration (\d+)", text)
    if iteration_matches:
        data["iterations"] = max(int(i) for i in iteration_matches)

    # Find status (APPROVED, NEED_IMPROVEMENT, etc.)
    if "**Decision**: **APPROVED**" in text or "**Decision**: APPROVED" in text:
        data["status"] = "approved"
    elif "NOT APPROVED" in text:
        data["status"] = "rejected"
    else:
        data["status"] = "in_progress"

    # Extract best IS metrics from the most recent iteration
    is_results_matches = list(re.finditer(r"\*\*IS Results\*\*", text))
    if is_results_matches:
        last_is_pos = is_results_matches[-1].start()
        is_section = text[last_is_pos : last_is_pos + 1500]
        data["best_metrics"] = parse_metrics_table(is_section, "IS Results")

    # Extract lessons from Key Insight and Root Cause Analysis sections
    insight_matches = re.findall(r"\*\*Key Insight\*\*:?\s*\n(.+?)(?=\n\*\*|\n---|\n###|\Z)", text, re.DOTALL)
    for insight in insight_matches:
        cleaned = insight.strip()
        if cleaned and len(cleaned) > 20:
            data["lessons"].append(cleaned[:500])

    root_cause_matches = re.findall(r"\*\*Root Cause.*?\*\*:?\s*\n(.+?)(?=\n\*\*Key|\n---|\n###|\Z)", text, re.DOTALL)
    for rc in root_cause_matches:
        cleaned = rc.strip()
        if cleaned and len(cleaned) > 20:
            data["lessons"].append(cleaned[:500])

    return data


def find_strategy_code(strategy_name: str) -> Path | None:
    """Find strategy code file."""
    base_path = Path("src/intraday/strategies/tick")

    # Try exact match
    exact_path = base_path / f"{strategy_name}.py"
    if exact_path.exists():
        return exact_path

    # Try without _dir suffix
    name = strategy_name.replace("_dir", "")
    exact_path = base_path / f"{name}.py"
    if exact_path.exists():
        return exact_path

    # Try fuzzy match
    for py_file in base_path.glob("*.py"):
        if name in py_file.stem or py_file.stem in name:
            return py_file

    return None


def extract_class_name(code_path: Path) -> str | None:
    """Extract strategy class name from code."""
    if not code_path or not code_path.exists():
        return None

    code = code_path.read_text()
    match = re.search(r"class (\w+Strategy)\(", code)
    if match:
        return match.group(1)
    return None


def infer_relationships(strategies: dict) -> list[dict]:
    """Infer relationships between strategies."""
    relationships = []

    strategy_names = list(strategies.keys())

    for i, name1 in enumerate(strategy_names):
        s1 = strategies[name1]
        ind1 = set(s1.get("indicators", []))

        for name2 in strategy_names[i + 1 :]:
            s2 = strategies[name2]
            ind2 = set(s2.get("indicators", []))

            # shares_indicator relationship
            shared = ind1 & ind2
            if shared:
                relationships.append(
                    {
                        "source": name1,
                        "target": name2,
                        "type": "shares_indicator",
                        "shared_indicators": list(shared),
                    }
                )

            # similar_to relationship (same category + shared indicators)
            if s1.get("category") == s2.get("category") and len(shared) >= 2:
                relationships.append(
                    {
                        "source": name1,
                        "target": name2,
                        "type": "similar_to",
                        "similarity_score": len(shared) / max(len(ind1), len(ind2), 1),
                        "shared_concepts": list(shared) + [s1.get("category", "")],
                    }
                )

    return relationships


def build_indicator_taxonomy(strategies: dict) -> dict:
    """Build indicator taxonomy from strategies."""
    taxonomy = {}

    for name, strategy in strategies.items():
        for indicator in strategy.get("indicators", []):
            if indicator not in taxonomy:
                taxonomy[indicator] = {
                    "description": "",
                    "strategies": [],
                    "best_practices": [],
                }
            if name not in taxonomy[indicator]["strategies"]:
                taxonomy[indicator]["strategies"].append(name)

    return taxonomy


def extract_lessons_learned(strategies: dict) -> list[dict]:
    """Extract and deduplicate lessons learned."""
    lessons = []
    seen_titles = set()
    lesson_id = 1

    for name, strategy in strategies.items():
        for lesson_text in strategy.get("_raw_lessons", []):
            # Create a simple title from first line
            first_line = lesson_text.split("\n")[0][:100]
            if first_line in seen_titles:
                continue
            seen_titles.add(first_line)

            # Determine severity
            severity = "info"
            lower_text = lesson_text.lower()
            if "critical" in lower_text or "catastrophic" in lower_text or "fatal" in lower_text:
                severity = "critical"
            elif "fail" in lower_text or "problem" in lower_text or "issue" in lower_text:
                severity = "high"
            elif "warning" in lower_text or "concern" in lower_text:
                severity = "medium"

            lessons.append(
                {
                    "id": f"L{lesson_id:03d}",
                    "source_strategy": name,
                    "title": first_line,
                    "content": lesson_text[:500],
                    "severity": severity,
                    "affected_indicators": strategy.get("indicators", []),
                    "tags": [],
                }
            )
            lesson_id += 1

    return lessons


def build_ontology(semantic: bool = False) -> dict:
    """
    Build strategy ontology using 2-layer approach.

    Args:
        semantic: If True, run Opus 4.5 semantic analysis (Layer 2)
    """
    ontology = {
        "version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "strategies": {},
        "relationships": [],
        "indicator_taxonomy": {},
        "lessons_learned": [],
        "common_mistakes": {},
        "category_taxonomy": {},
    }

    # ========================================
    # Layer 1: Rule-Based Extraction
    # ========================================

    print("Layer 1: Rule-Based Extraction...")

    # Scan strategy directories
    strategy_dirs = sorted(Path(".").glob("*_dir"))
    print(f"  Found {len(strategy_dirs)} strategy directories")

    for strategy_dir in strategy_dirs:
        name = strategy_dir.name.replace("_dir", "")
        memory_path = strategy_dir / "memory.md"
        algorithm_path = strategy_dir / "algorithm_prompt.txt"

        print(f"  Processing: {name}")

        # Parse memory file
        memory_data = parse_memory_file(memory_path)

        # Find and analyze code
        code_path = find_strategy_code(name)
        indicators = extract_indicators_from_code(code_path) if code_path else []
        class_name = extract_class_name(code_path)

        # Categorize
        category = categorize_strategy(name, indicators, memory_data.get("hypothesis", ""))

        strategy_data = {
            "name": class_name or f"{name.title().replace('_', '')}Strategy",
            "display_name": name.replace("_", " ").title(),
            "category": category,
            "indicators": indicators,
            "hypothesis": memory_data.get("hypothesis", ""),
            "best_metrics": memory_data.get("best_metrics", {}),
            "status": memory_data.get("status", "unknown"),
            "iterations": memory_data.get("iterations", 0),
            "memory_path": str(memory_path) if memory_path.exists() else None,
            "code_path": str(code_path) if code_path else None,
            "tags": [category] + indicators,
            "_raw_lessons": memory_data.get("lessons", []),
        }

        ontology["strategies"][name] = strategy_data

    # Build relationships
    print("  Inferring relationships...")
    ontology["relationships"] = infer_relationships(ontology["strategies"])

    # Build indicator taxonomy
    print("  Building indicator taxonomy...")
    ontology["indicator_taxonomy"] = build_indicator_taxonomy(ontology["strategies"])

    # Extract lessons learned
    print("  Extracting lessons learned...")
    ontology["lessons_learned"] = extract_lessons_learned(ontology["strategies"])

    # Build category taxonomy
    for name, strategy in ontology["strategies"].items():
        category = strategy.get("category", "uncategorized")
        if category not in ontology["category_taxonomy"]:
            ontology["category_taxonomy"][category] = []
        ontology["category_taxonomy"][category].append(name)

    # Clean up raw lessons from strategy data
    for strategy in ontology["strategies"].values():
        strategy.pop("_raw_lessons", None)

    # Add common mistakes (initial set)
    ontology["common_mistakes"] = {
        "fee_dominated_loss": {
            "pattern": "Win Rate > 50% but Total Return < 0",
            "cause": "수수료가 평균 수익보다 높음",
            "symptoms": ["Win Rate > 50%", "Total Return < 0%", "Avg Win < fee"],
            "prevention": "fee_ratio >= 1.5 검증",
            "affected_count": 0,
        },
        "rr_inversion": {
            "pattern": "설계한 R:R와 실제 R:R 불일치",
            "cause": "TP/SL 외 다른 exit 조건이 먼저 트리거",
            "symptoms": ["Avg Win / Avg Loss != TP / SL"],
            "prevention": "exit 우선순위 명확화, 백테스트 후 실제 R:R 검증",
            "affected_count": 0,
        },
        "overfitting_to_period": {
            "pattern": "IS 우수, OS 급락",
            "cause": "특정 기간 패턴에 과적합",
            "symptoms": ["IS Return >> OS Return", "IS Sharpe 방향 != OS Sharpe 방향"],
            "prevention": "파라미터 수 최소화, 단순한 로직 선호",
            "affected_count": 0,
        },
    }

    # ========================================
    # Layer 2: Semantic Enrichment (Optional)
    # ========================================

    if semantic:
        print("\nLayer 2: Semantic Analysis with Opus 4.5...")
        print("  (This requires ANTHROPIC_API_KEY and will make API calls)")

        try:
            from anthropic import Anthropic

            client = Anthropic()

            for name, strategy in ontology["strategies"].items():
                code_path = strategy.get("code_path")
                memory_path = strategy.get("memory_path")

                if not code_path or not memory_path:
                    print(f"  Skipping {name}: missing files")
                    continue

                print(f"  Analyzing {name}...")

                code = Path(code_path).read_text()[:5000] if Path(code_path).exists() else ""
                memory = Path(memory_path).read_text()[:3000] if Path(memory_path).exists() else ""

                prompt = f"""다음 전략 코드와 메모리를 분석하라:

## Code
{code}

## Memory
{memory}

## 분석 요청
JSON으로만 응답 (다른 텍스트 없이):
{{
    "core_logic": "이 전략이 실제로 하는 것 (1문장, 한국어)",
    "implicit_assumptions": ["코드에 암묵적으로 가정된 시장 조건 리스트 (한국어)"],
    "failure_nuance": "memory에서 읽히는 실패의 진짜 원인 (있다면, 한국어)",
    "similar_patterns": ["이 로직과 유사한 알려진 트레이딩 패턴 이름"],
    "hidden_risks": ["코드에서 발견되는 잠재적 위험 (한국어)"]
}}"""

                try:
                    response = client.messages.create(
                        model="claude-sonnet-4-20250514",
                        max_tokens=1024,
                        messages=[{"role": "user", "content": prompt}],
                    )

                    response_text = response.content[0].text.strip()
                    # Extract JSON from response
                    json_match = re.search(r"\{[\s\S]*\}", response_text)
                    if json_match:
                        semantic_data = json.loads(json_match.group())
                        strategy["_semantic"] = semantic_data
                        print(f"    ✓ {name}: {semantic_data.get('core_logic', '')[:50]}...")
                except Exception as e:
                    print(f"    ✗ {name}: {e}")

        except ImportError:
            print("  ERROR: anthropic package not installed. Run: uv pip install anthropic")
        except Exception as e:
            print(f"  ERROR: {e}")

    return ontology


def main():
    parser = argparse.ArgumentParser(description="Build strategy ontology")
    parser.add_argument(
        "--semantic",
        action="store_true",
        help="Run Opus 4.5 semantic analysis (slower but deeper)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="strategies_ontology.json",
        help="Output file path (default: strategies_ontology.json)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Strategy Ontology Builder")
    print("=" * 60)

    ontology = build_ontology(semantic=args.semantic)

    # Save
    output_path = Path(args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(ontology, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 60)
    print(f"Generated {output_path}")
    print(f"  - Strategies: {len(ontology['strategies'])}")
    print(f"  - Relationships: {len(ontology['relationships'])}")
    print(f"  - Indicators: {len(ontology['indicator_taxonomy'])}")
    print(f"  - Lessons: {len(ontology['lessons_learned'])}")
    print("=" * 60)


if __name__ == "__main__":
    main()
