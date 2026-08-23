from app.engines.scoring.base import ComponentResult, ScoreInputs, ScoreResult
from app.engines.scoring.components import COMPONENT_FUNCS


def compute_score(inputs: ScoreInputs, weights: dict[str, float]) -> ScoreResult:
    """Renormalizes over whatever components actually have data (§L
    missing-data-graceful) — a component with no input simply doesn't
    count, rather than being treated as 0."""
    raw_components = []
    for name, weight in weights.items():
        func = COMPONENT_FUNCS.get(name)
        normalized = func(inputs) if func is not None else None
        raw_components.append((name, normalized, weight))

    available_weight = sum(w for _, n, w in raw_components if n is not None)
    total_weight = sum(w for _, _, w in raw_components)
    coverage = available_weight / total_weight if total_weight > 0 else 0.0

    components = []
    value: float | None = None
    if available_weight > 0:
        value = sum(n * w for _, n, w in raw_components if n is not None) / available_weight

    for name, normalized, weight in raw_components:
        contribution = (
            (normalized * weight / available_weight)
            if normalized is not None and available_weight > 0
            else None
        )
        components.append(
            ComponentResult(
                # raw_value is intentionally always None: several components
                # (fundamental_quality, growth, technical_setup,
                # participation) blend two raw inputs, so there's no single
                # scalar to report here without misrepresenting a blend as
                # one number — the underlying metrics (RSI, D/E, margins,
                # ...) are already shown directly in the technicals/
                # fundamentals panels.
                component=name,
                raw_value=None,
                normalized_value=normalized,
                weight=weight,
                contribution=contribution,
            )
        )

    return ScoreResult(value=value, coverage=coverage, components=components)
