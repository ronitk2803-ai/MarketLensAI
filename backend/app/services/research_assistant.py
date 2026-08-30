"""NL Research Assistant (Build_plan.md §N/§S step 25, Screener.md §18) —
the app's remaining un-built P2 feature, unblocked once the Gemini auth
and model-overload bugs (app/providers/ai/gemini_summary.py) were fixed.

**Grounded by construction, not by instruction.** The model has no tools
that let it invent a number — every tool here reads through an existing,
already-tested service (scoring, technicals, fundamentals, historical
falls, news, corporate actions, screener, portfolio, watchlist, thesis)
and returns exactly what that service would show a human reading the
company page. There is no "general knowledge" fallback path: the system
instruction tells the model to say so when a tool has nothing, not to
fill the gap from what it already knows about the company — the same
"missing, never fabricated" rule every engine in this codebase follows
(SUMMARISER.md §2).

**Read-only by construction, not by convention.** Every tool wraps a
`get_*`/`list_*` service function; none of them can create, update, or
delete anything. The three user-scoped tools (portfolio/watchlist/thesis)
take `current_user` from the authenticated request context, never as a
model-supplied argument — the tool's JSON schema doesn't expose a user_id
parameter at all, so there is no argument for the model to get wrong or
be steered into supplying, by a prompt injection or otherwise.

**One HTTP request, several LLM turns.** Unlike company_summary.py (one
prompt in, one summary out), a single question here can take multiple
tool-calling round trips — the model asks for data, gets it, asks for
more, and only then answers. MAX_TOOL_CALLS bounds that loop; app/
providers/ai/gemini_chat.py's own deadline is the backstop under it.
"""

import datetime as dt
import logging
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AppUser, Asset, ThesisEvent
from app.engines.opportunity.registry import SCREEN_LABELS
from app.providers.ai.gemini_chat import FunctionCall, GeminiChatProvider
from app.providers.errors import ProviderError
from app.services.adjusted_prices import get_adjusted_bars
from app.services.corporate_actions import get_stored_corporate_actions
from app.services.fundamentals import get_or_fetch_ratios
from app.services.historical_episodes import get_historical_falls
from app.services.news import get_or_fetch_news
from app.services.opportunities import list_industries, run_ranked_screen_with_sparklines
from app.services.portfolio import list_holdings
from app.services.scoring import gather_score_inputs, get_or_compute_score
from app.services.technicals import compute_technicals
from app.services.thesis import get_thesis, list_theses
from app.services.watchlist import get_watchlist_symbols

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS = 6

_NO_ADVICE_RULES = (
    "Rules, all mandatory:\n"
    "- Do not recommend buying, selling, or holding.\n"
    "- Do not say whether now is a good or bad time to invest.\n"
    "- Do not predict where a price is headed or suggest a time horizon.\n"
    "- Do not use language that implies a verdict, like \"looks attractive\" "
    "or \"warrants caution\" — state the underlying fact and let it stand "
    "on its own.\n"
    "- If you notice yourself about to write a recommendation, stop and "
    "rephrase as a plain observation instead."
)

# Mirrors product_principles.md's "How AI must behave" — offered as a
# structure to reach for on a genuine multi-factor analysis question, not
# a template to force onto "has this happened before?" or "what's in my
# portfolio?", which don't have a bull/bear case to report.
_ANALYSIS_STRUCTURE = (
    "For a genuine analysis question (not a lookup), where the data "
    "supports it, structure the answer around: what happened, why, what "
    "changed, what didn't, supporting evidence, contradicting evidence, "
    "and what to monitor next. Skip sections the data doesn't support "
    "rather than padding them — an empty section is worse than no section."
)

SYSTEM_INSTRUCTION = (
    "You are MarketLens AI's research assistant, helping someone research "
    "Indian equities using only the tools provided. You have NO knowledge "
    "of any company's current numbers, news, or price action beyond what a "
    "tool call returns in this conversation — never state a metric, price, "
    "or fact you have not just received from a tool. If a tool reports data "
    "as unavailable or a symbol as unknown, say so plainly rather than "
    "filling the gap from general knowledge.\n\n"
    "Call whichever tools the question needs, in whatever order makes "
    "sense — you may call several before answering. Once you have enough "
    "to answer, respond in plain text, not another tool call.\n\n"
    f"{_NO_ADVICE_RULES}\n\n"
    f"{_ANALYSIS_STRUCTURE}\n\n"
    "This product is not a SEBI-registered investment adviser or research "
    "analyst, and nothing here is investment advice — every answer is "
    "research context only."
)


@dataclass(frozen=True, slots=True)
class AssistantAnswer:
    text: str
    tools_used: list[str]


def _find_asset(db: Session, symbol: str) -> Asset | None:
    return (
        db.query(Asset)
        .filter_by(symbol=symbol.strip().upper(), market="IN", active=True)
        .one_or_none()
    )


def _jsonable(value: Any) -> Any:
    """Recursively converts dataclass/Decimal/date fields tool results
    commonly carry into plain JSON-safe types — a functionResponse body
    is serialized straight into the request Gemini gets next, so anything
    left as a Decimal or a date object would fail at that boundary, not
    here, which is a much harder place to debug."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "__dataclass_fields__"):
        return {f: _jsonable(getattr(value, f)) for f in value.__dataclass_fields__}
    return value


def _unknown_symbol(symbol: str) -> dict:
    return {"error": f"{symbol!r} is not a known, active NSE equity in this app's universe."}


# --- Tool implementations — every one either takes (db, symbol) for a
# public lookup, or (db, current_user) for a user-scoped read. None take
# a user_id or symbol pair the model could use to reach another user's
# data. ------------------------------------------------------------------


def _tool_company_overview(db: Session, _user: AppUser, symbol: str) -> dict:
    asset = _find_asset(db, symbol)
    if asset is None:
        return _unknown_symbol(symbol)
    bars, price_source = get_adjusted_bars(db, asset, lookback_days=10)
    latest = bars[-1] if bars else None
    return _jsonable(
        {
            "symbol": asset.symbol,
            "name": asset.name,
            "sector": asset.company.sector if asset.company else None,
            "industry": (
                asset.company.industry.name if asset.company and asset.company.industry else None
            ),
            "latest_close": latest.close if latest else None,
            "latest_close_date": latest.date if latest else None,
            "price_source": price_source,
        }
    )


def _tool_score(db: Session, _user: AppUser, symbol: str) -> dict:
    asset = _find_asset(db, symbol)
    if asset is None:
        return _unknown_symbol(symbol)
    score, components = get_or_compute_score(db, asset)
    return _jsonable(
        {
            "symbol": asset.symbol,
            "value": score.value,
            "coverage": score.coverage,
            "confidence": score.confidence,
            "components": [
                {
                    "component": c.component,
                    "normalized_value": c.normalized_value,
                    "weight": c.weight,
                }
                for c in components
            ],
            "note": "0-100 research attractiveness, not a predicted return.",
        }
    )


def _tool_technicals(db: Session, _user: AppUser, symbol: str) -> dict:
    asset = _find_asset(db, symbol)
    if asset is None:
        return _unknown_symbol(symbol)
    result = compute_technicals(db, asset, lookback_days=120)
    s = result.snapshot
    return _jsonable(
        {
            "symbol": asset.symbol,
            "as_of": s.as_of,
            "close": s.close,
            "dma20": s.dma20,
            "dma50": s.dma50,
            "dma100": s.dma100,
            "dma200": s.dma200,
            "rsi14": s.rsi14,
            "macd_histogram": s.macd_histogram,
            "volatility20_annualized": s.volatility20,
            "drawdown_pct_from_peak": s.drawdown_pct,
        }
    )


def _tool_fundamentals(db: Session, _user: AppUser, symbol: str) -> dict:
    asset = _find_asset(db, symbol)
    if asset is None:
        return _unknown_symbol(symbol)
    ratios = get_or_fetch_ratios(db, asset)
    return _jsonable(
        {
            "symbol": asset.symbol,
            "ratios": {r.metric: r.value for r in ratios},
            "confidence": "low",
            "note": "Single, uncross-checked source — always low confidence by design.",
        }
    )


def _tool_historical_falls(db: Session, _user: AppUser, symbol: str) -> dict:
    asset = _find_asset(db, symbol)
    if asset is None:
        return _unknown_symbol(symbol)
    result = get_historical_falls(db, asset)
    current = None
    if result.current is not None:
        current = {
            "peak_date": result.current.episode.peak_date,
            "decline_pct": result.current.episode.decline_pct,
            "current_drawdown_pct": result.current.current_drawdown_pct,
            "peak_to_trough_days": result.current.episode.peak_to_trough_days,
            "still_making_new_lows": result.current.trough_is_latest_bar,
        }
    return _jsonable(
        {
            "symbol": asset.symbol,
            "history_start": result.history_start,
            "min_decline_pct_to_count": result.min_decline_pct,
            "current_fall": current,
            "comparable_past_falls": [
                {
                    "peak_date": c.episode.peak_date,
                    "trough_date": c.episode.trough_date,
                    "decline_pct": c.episode.decline_pct,
                    "peak_to_trough_days": c.episode.peak_to_trough_days,
                    "recovered": c.episode.recovery_date is not None,
                    "recovery_date": c.episode.recovery_date,
                    "trough_to_recovery_days": c.episode.trough_to_recovery_days,
                }
                for c in result.comparable
            ],
            "note": (
                "Historical context only — how this company's own past falls "
                "unfolded, not a forecast or a recovery estimate."
            ),
        }
    )


def _tool_news(db: Session, _user: AppUser, symbol: str) -> dict:
    asset = _find_asset(db, symbol)
    if asset is None:
        return _unknown_symbol(symbol)
    articles = get_or_fetch_news(db, asset)
    return _jsonable(
        {
            "symbol": asset.symbol,
            "articles": [
                {
                    "published_at": a.published_at.date(),
                    "source": a.source,
                    "title": a.title,
                }
                for a in articles[:12]
            ],
        }
    )


def _tool_corporate_actions(db: Session, _user: AppUser, symbol: str) -> dict:
    asset = _find_asset(db, symbol)
    if asset is None:
        return _unknown_symbol(symbol)
    actions = get_stored_corporate_actions(db, asset.id)
    return _jsonable(
        {
            "symbol": asset.symbol,
            "actions": [
                {"type": a.type, "ex_date": a.ex_date, "ratio": a.ratio, "amount": a.amount}
                for a in actions
            ],
        }
    )


def _tool_peer_comparison(db: Session, _user: AppUser, symbol: str) -> dict:
    """Reuses the exact percentile fields the Opportunity Score itself was
    built from (app/services/scoring.py, §X.4) — the same numbers, not a
    second independently-computed comparison that could disagree."""
    asset = _find_asset(db, symbol)
    if asset is None:
        return _unknown_symbol(symbol)
    inputs = gather_score_inputs(db, asset)
    industry = asset.company.industry.name if asset.company and asset.company.industry else None
    percentiles = {
        "price_to_book": inputs.price_to_book_percentile,
        "trailing_pe": inputs.trailing_pe_percentile,
        "debt_to_equity": inputs.debt_to_equity_percentile,
        "gross_margins": inputs.gross_margins_percentile,
        "revenue_growth": inputs.revenue_growth_percentile,
        "earnings_growth": inputs.earnings_growth_percentile,
    }
    available = {k: v for k, v in percentiles.items() if v is not None}
    return _jsonable(
        {
            "symbol": asset.symbol,
            "industry": industry,
            "percentile_vs_industry_peers": available,
            "note": (
                "0-100, higher always means more attractive relative to "
                "same-industry peers. Metrics missing here didn't have "
                "enough peers with data to rank against (fewer than 3) — "
                "not that the company scored zero."
                if available
                else "Not enough same-industry peers with data to rank against yet."
            ),
        }
    )


def _tool_run_screen(
    db: Session, _user: AppUser, screen_id: str, industry: str | None = None
) -> dict:
    if screen_id not in SCREEN_LABELS:
        return {
            "error": f"unknown screen_id {screen_id!r}",
            "available_screens": SCREEN_LABELS,
        }
    if industry is not None:
        valid_industries = {code for code, _ in list_industries(db)}
        if industry not in valid_industries:
            return {
                "error": f"unknown industry {industry!r}",
                "available_industries": sorted(valid_industries),
            }
    output = run_ranked_screen_with_sparklines(db, screen_id, industry=industry)
    return _jsonable(
        {
            "screen": screen_id,
            "screen_label": SCREEN_LABELS[screen_id],
            "industry_filter": industry,
            "hits": [
                {
                    "symbol": r.hit.asset.symbol,
                    "name": r.hit.asset.name,
                    "opportunity_score": r.opportunity_score,
                    "metrics": r.hit.metrics,
                }
                for r in output.ranked[:15]
            ],
            "total_hits": len(output.ranked),
        }
    )


def _tool_my_portfolio(db: Session, user: AppUser) -> dict:
    holdings = list_holdings(db, user.id)
    return _jsonable(
        {
            "holdings": [
                {
                    "symbol": h.symbol,
                    "quantity": h.quantity,
                    "average_cost": h.avg_cost,
                    "last_price": h.last_price,
                    "market_value": h.market_value,
                    "unrealized_pnl": h.unrealized_pnl,
                    "unrealized_pnl_pct": h.unrealized_pnl_pct,
                }
                for h in holdings
            ],
        }
    )


def _tool_my_watchlist(db: Session, user: AppUser) -> dict:
    return _jsonable({"symbols": get_watchlist_symbols(db, user.id)})


def _tool_my_theses(db: Session, user: AppUser) -> dict:
    theses = list_theses(db, user.id)
    return _jsonable(
        {
            "theses": [
                {
                    "id": t.id,
                    "asset_symbol": t.asset.symbol,
                    "title": t.title,
                    "stance": t.stance,
                    "conviction": t.conviction,
                    "status": t.status,
                }
                for t in theses
            ],
        }
    )


def _tool_thesis_detail(db: Session, user: AppUser, thesis_id: int) -> dict:
    thesis = get_thesis(db, user.id, thesis_id)
    if thesis is None:
        # Same 404-not-403 ownership-scoping convention as every other
        # user-owned lookup in this app (SUMMARISER.md §3) — "not yours"
        # and "doesn't exist" are indistinguishable on purpose.
        return {"error": f"no thesis with id {thesis_id} for this account"}
    # No `events` relationship on Thesis itself — same direct query
    # app/api/v1/theses.py's own GET /{id} uses.
    events = (
        db.query(ThesisEvent)
        .filter(ThesisEvent.thesis_id == thesis_id)
        .order_by(ThesisEvent.fired_at.desc())
        .all()
    )
    return _jsonable(
        {
            "id": thesis.id,
            "asset_symbol": thesis.asset.symbol,
            "title": thesis.title,
            "body": thesis.body,
            "stance": thesis.stance,
            "conviction": thesis.conviction,
            "status": thesis.status,
            "triggers": [
                {
                    "metric": trig.metric,
                    "operator": trig.operator,
                    "threshold": trig.threshold,
                    "description": trig.description,
                    "currently_breached": trig.currently_breached,
                }
                for trig in thesis.triggers
            ],
            "events": [
                {
                    "trigger_id": e.trigger_id,
                    "metric": e.trigger.metric,
                    "fired_at": e.fired_at,
                    "observed_value": e.observed_value,
                    "note": e.note,
                }
                for e in events
            ],
        }
    )


@dataclass(frozen=True, slots=True)
class Tool:
    description: str
    parameters: dict[str, Any]
    # (db, current_user, **model_supplied_args) -> JSON-safe dict. The
    # model never supplies current_user — it isn't in `parameters`, so
    # there's no argument name for the model to fill in even if it tried.
    handler: Callable[..., dict]


_SYMBOL_PARAM = {"symbol": {"type": "STRING", "description": "NSE ticker symbol, e.g. RELIANCE"}}

TOOLS: dict[str, Tool] = {
    "get_company_overview": Tool(
        "Sector, industry, name, and latest close for a company.",
        {"type": "OBJECT", "properties": _SYMBOL_PARAM, "required": ["symbol"]},
        _tool_company_overview,
    ),
    "get_opportunity_score": Tool(
        "The Opportunity Score (0-100 research attractiveness, not a "
        "return prediction) and its component breakdown for a company.",
        {"type": "OBJECT", "properties": _SYMBOL_PARAM, "required": ["symbol"]},
        _tool_score,
    ),
    "get_technicals": Tool(
        "Moving averages, RSI, MACD, volatility, and drawdown for a company.",
        {"type": "OBJECT", "properties": _SYMBOL_PARAM, "required": ["symbol"]},
        _tool_technicals,
    ),
    "get_fundamentals": Tool(
        "Financial ratios (P/E, P/B, D/E, margins, growth) for a company.",
        {"type": "OBJECT", "properties": _SYMBOL_PARAM, "required": ["symbol"]},
        _tool_fundamentals,
    ),
    "get_historical_falls": Tool(
        "Whether a company is currently in a price fall, and how its past "
        "falls of similar size unfolded and recovered. Use this for "
        "'has this happened before?' questions.",
        {"type": "OBJECT", "properties": _SYMBOL_PARAM, "required": ["symbol"]},
        _tool_historical_falls,
    ),
    "get_recent_news": Tool(
        "Recent dated headlines for a company.",
        {"type": "OBJECT", "properties": _SYMBOL_PARAM, "required": ["symbol"]},
        _tool_news,
    ),
    "get_corporate_actions": Tool(
        "Splits, bonuses, dividends, rights issues, and demergers on "
        "record for a company — useful for explaining a price move that "
        "might be mechanical rather than a market reaction.",
        {"type": "OBJECT", "properties": _SYMBOL_PARAM, "required": ["symbol"]},
        _tool_corporate_actions,
    ),
    "compare_with_industry_peers": Tool(
        "How a company's valuation, leverage, margins, and growth rank as "
        "a percentile against other companies in the same industry. Use "
        "this for 'compare with competitors' questions.",
        {"type": "OBJECT", "properties": _SYMBOL_PARAM, "required": ["symbol"]},
        _tool_peer_comparison,
    ),
    "run_screen": Tool(
        "Run one of this app's registered market screens across the whole "
        "universe — e.g. sharp recent declines, unusual volume, below a "
        "moving average. Use this for 'find companies where...' questions. "
        f"Valid screen_id values: {', '.join(SCREEN_LABELS)}.",
        {
            "type": "OBJECT",
            "properties": {
                "screen_id": {"type": "STRING", "enum": list(SCREEN_LABELS)},
                "industry": {
                    "type": "STRING",
                    "description": "Optional industry code to filter to. Omit for all industries.",
                },
            },
            "required": ["screen_id"],
        },
        _tool_run_screen,
    ),
    "get_my_portfolio": Tool(
        "This user's own portfolio holdings, valuations, and unrealized "
        "P&L. Takes no arguments — always the signed-in user's own data.",
        {"type": "OBJECT", "properties": {}},
        _tool_my_portfolio,
    ),
    "get_my_watchlist": Tool(
        "This user's own watchlist symbols. Takes no arguments.",
        {"type": "OBJECT", "properties": {}},
        _tool_my_watchlist,
    ),
    "list_my_theses": Tool(
        "This user's own investment theses with stance, conviction, and "
        "status. Takes no arguments.",
        {"type": "OBJECT", "properties": {}},
        _tool_my_theses,
    ),
    "get_thesis_detail": Tool(
        "One of this user's own theses in full, including its invalidation "
        "triggers and any that have fired. Use this for 'what would "
        "invalidate my thesis?' questions — get the thesis_id from "
        "list_my_theses first.",
        {
            "type": "OBJECT",
            "properties": {"thesis_id": {"type": "INTEGER"}},
            "required": ["thesis_id"],
        },
        _tool_thesis_detail,
    ),
}


def _function_declarations() -> list[dict]:
    return [
        {"name": name, "description": tool.description, "parameters": tool.parameters}
        for name, tool in TOOLS.items()
    ]


def _dispatch(db: Session, user: AppUser, call: FunctionCall) -> dict:
    tool = TOOLS.get(call.name)
    if tool is None:
        # The model hallucinated a tool name — tell it so rather than
        # crashing the request. It has the exact list already (it's what
        # `tools` declared), so this should be rare.
        return {"error": f"no such tool: {call.name!r}"}
    try:
        return tool.handler(db, user, **call.args)
    except TypeError as error:
        # A malformed/missing required argument — same reasoning as the
        # unknown-tool branch: feed it back rather than 500ing the whole
        # question over one bad call.
        return {"error": f"invalid arguments for {call.name}: {error}"}
    except Exception:
        logger.exception("research_assistant: tool %s failed", call.name)
        return {"error": f"{call.name} failed unexpectedly — try a different question"}


def ask(db: Session, user: AppUser, question: str, *, api_keys: list[str]) -> AssistantAnswer:
    """Runs the full tool-calling conversation for one question and
    returns the model's final grounded answer. Stateless across calls —
    Build_plan.md §S step 25 is scoped to single-question research, not a
    persisted multi-turn chat thread; see the module docstring."""
    provider = GeminiChatProvider(api_keys)
    tools = _function_declarations()
    contents: list[dict] = [{"role": "user", "parts": [{"text": question}]}]
    tools_used: list[str] = []

    for _ in range(MAX_TOOL_CALLS):
        result = provider.step(
            system_instruction=SYSTEM_INSTRUCTION, contents=contents, tools=tools
        )
        if result.text is not None:
            return AssistantAnswer(text=result.text, tools_used=tools_used)

        call = result.function_call
        assert call is not None  # StepResult guarantees exactly one is set
        tools_used.append(call.name)
        tool_result = _dispatch(db, user, call)

        # The exact raw part Gemini returned, not a hand-built
        # {"functionCall": {...}} dict — see StepResult's docstring on
        # thoughtSignature, which a reconstructed part would silently drop.
        contents.append({"role": "model", "parts": [result.raw_part]})
        contents.append(
            {
                "role": "user",
                "parts": [{"functionResponse": {"name": call.name, "response": tool_result}}],
            }
        )

    # Exhausted MAX_TOOL_CALLS without a final answer — a real, if rare,
    # outcome (a question needing more lookups than the cap allows), not
    # an error worth a 500. Say so rather than silently returning nothing.
    raise ProviderError(
        "gemini_chat",
        f"the assistant needed more than {MAX_TOOL_CALLS} tool calls to answer — "
        "try a narrower question",
    )
