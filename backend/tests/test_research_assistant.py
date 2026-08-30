import dataclasses
import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.db.models import AppUser, Asset, Company, Industry, PriceOHLCV
from app.providers.ai.gemini_chat import FunctionCall, GeminiChatProvider, StepResult
from app.providers.errors import ProviderError
from app.services.portfolio import add_or_update_holding
from app.services.research_assistant import (
    MAX_TOOL_CALLS,
    SYSTEM_INSTRUCTION,
    TOOLS,
    _dispatch,
    _tool_company_overview,
    _tool_my_portfolio,
    _tool_my_watchlist,
    _tool_run_screen,
    _tool_thesis_detail,
    ask,
)
from app.services.thesis import TriggerInput, create_thesis
from app.services.watchlist import add_to_watchlist


def _user(db: Session, email: str) -> AppUser:
    user = AppUser(email=email, hashed_password="not-a-real-hash")
    db.add(user)
    db.flush()
    return user


def _asset(db: Session, symbol: str) -> Asset:
    asset = Asset(symbol=symbol, exchange="NSE", market="IN", name=f"{symbol} Ltd.")
    db.add(asset)
    db.flush()
    return asset


def _price(db: Session, asset: Asset, close: float, *, days_ago: int = 0) -> None:
    db.add(
        PriceOHLCV(
            asset_id=asset.id,
            date=dt.date.today() - dt.timedelta(days=days_ago),
            open=Decimal(str(close)),
            high=Decimal(str(close)),
            low=Decimal(str(close)),
            close=Decimal(str(close)),
            volume=1000,
            source="test",
        )
    )
    db.flush()


# --- _dispatch safety — this is where a model hallucination or a bad
# tool implementation must degrade to an error dict, never a 500. ---------


def test_dispatch_returns_an_error_dict_for_an_unknown_tool_name(db: Session) -> None:
    user = _user(db, "zzdispatch1@example.com")
    result = _dispatch(db, user, FunctionCall(name="not_a_real_tool", args={}))
    assert "error" in result
    assert "not_a_real_tool" in result["error"]


def test_dispatch_returns_an_error_dict_for_missing_required_args(db: Session) -> None:
    """The exact live bug found 2026-08-30: run_screen's industry param had
    no Python default even though the JSON schema marks it optional, so a
    bare {"screen_id": ...} call crashed with a TypeError instead of
    running. This pins the fix and guards every tool against a regression
    of the same shape — a required-in-schema arg is fine to omit and let
    Gemini's own validation catch, but an OPTIONAL one must never crash."""
    user = _user(db, "zzdispatch2@example.com")
    result = _dispatch(db, user, FunctionCall(name="get_company_overview", args={}))
    assert "error" in result
    assert "invalid arguments" in result["error"]


def test_dispatch_swallows_an_unexpected_exception_from_a_handler(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(db: Session, user: AppUser, **kwargs: object) -> dict:
        raise RuntimeError("something genuinely broke")

    original = TOOLS["get_company_overview"]
    broken = dataclasses.replace(original, handler=boom)
    monkeypatch.setitem(TOOLS, "get_company_overview", broken)

    user = _user(db, "zzdispatch3@example.com")
    result = _dispatch(db, user, FunctionCall(name="get_company_overview", args={"symbol": "X"}))
    assert "error" in result
    assert "unexpectedly" in result["error"]


def test_run_screen_with_no_industry_argument_does_not_crash(db: Session) -> None:
    """Direct regression test for the same bug, at the tool level rather
    than through _dispatch's TypeError-catching path."""
    result = _tool_run_screen(db, None, "unusual_volume")  # type: ignore[arg-type]
    assert "error" not in result


def test_run_screen_rejects_an_unknown_screen_id(db: Session) -> None:
    result = _tool_run_screen(db, None, "not_a_real_screen")  # type: ignore[arg-type]
    assert "error" in result
    assert "available_screens" in result


# --- Individual tools — a representative sample, not exhaustive; the
# underlying services (scoring, technicals, historical_episodes, ...) are
# already tested on their own. These check the wrapping: unknown-symbol
# handling and ownership scoping. ------------------------------------------


def test_company_overview_reports_an_unknown_symbol_without_crashing(db: Session) -> None:
    result = _tool_company_overview(db, None, "ZZNOTREAL")  # type: ignore[arg-type]
    assert "error" in result


def test_company_overview_returns_real_data_for_a_known_symbol(db: Session) -> None:
    asset = _asset(db, "ZZASSIST1")
    industry = Industry(code="ZZINDASSIST", name="Test Industry")
    db.add(industry)
    db.flush()
    db.add(Company(asset_id=asset.id, sector="Test Sector", industry_id=industry.id))
    _price(db, asset, 123.45)

    result = _tool_company_overview(db, None, "zzassist1")  # type: ignore[arg-type]

    assert result["symbol"] == "ZZASSIST1"
    assert result["sector"] == "Test Sector"
    assert result["industry"] == "Test Industry"
    assert result["latest_close"] == pytest.approx(123.45)


def test_my_portfolio_is_scoped_to_the_calling_user_only(db: Session) -> None:
    alice = _user(db, "zzassist-alice@example.com")
    bob = _user(db, "zzassist-bob@example.com")
    asset = _asset(db, "ZZASSIST2")
    _price(db, asset, 100.0)
    add_or_update_holding(db, alice.id, "ZZASSIST2", quantity=10, avg_cost=90)

    alice_result = _tool_my_portfolio(db, alice)
    bob_result = _tool_my_portfolio(db, bob)

    assert len(alice_result["holdings"]) == 1
    assert alice_result["holdings"][0]["symbol"] == "ZZASSIST2"
    assert bob_result["holdings"] == []


def test_my_watchlist_is_scoped_to_the_calling_user_only(db: Session) -> None:
    alice = _user(db, "zzassist-alice2@example.com")
    bob = _user(db, "zzassist-bob2@example.com")
    _asset(db, "ZZASSIST3")
    add_to_watchlist(db, alice.id, "ZZASSIST3")

    assert _tool_my_watchlist(db, alice)["symbols"] == ["ZZASSIST3"]
    assert _tool_my_watchlist(db, bob)["symbols"] == []


def test_thesis_detail_returns_an_error_for_another_users_thesis(db: Session) -> None:
    """Same 'not yours' / 'doesn't exist' indistinguishability every other
    ownership-scoped lookup in this app already follows."""
    alice = _user(db, "zzassist-alice3@example.com")
    bob = _user(db, "zzassist-bob3@example.com")
    asset = _asset(db, "ZZASSIST4")
    thesis = create_thesis(
        db,
        user_id=alice.id,
        asset=asset,
        title="Alice's thesis",
        body="body",
        stance="bull",
        conviction=3,
        triggers=[TriggerInput(metric="debt_to_equity", operator="gt", threshold=1.5)],
    )

    bob_result = _tool_thesis_detail(db, bob, thesis.id)
    alice_result = _tool_thesis_detail(db, alice, thesis.id)

    assert "error" in bob_result
    assert alice_result["title"] == "Alice's thesis"
    assert len(alice_result["triggers"]) == 1
    assert alice_result["triggers"][0]["currently_breached"] is False


# --- The orchestration loop — mocked GeminiChatProvider.step, so this
# tests control flow (multi-turn, raw_part echoing, MAX_TOOL_CALLS),
# not real Gemini behavior (that's the live smoke test, not a CI test). ---


def test_ask_returns_the_final_answer_after_one_tool_call(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user(db, "zzassist-loop1@example.com")
    steps = iter(
        [
            StepResult(
                function_call=FunctionCall(name="get_my_watchlist", args={}),
                text=None,
                raw_part={"functionCall": {"name": "get_my_watchlist", "args": {}}},
            ),
            StepResult(function_call=None, text="You have no watchlist symbols.", raw_part={}),
        ]
    )
    monkeypatch.setattr(GeminiChatProvider, "step", lambda self, **kwargs: next(steps))

    answer = ask(db, user, "what's on my watchlist?", api_keys=["fake-key"])

    assert answer.text == "You have no watchlist symbols."
    assert answer.tools_used == ["get_my_watchlist"]


def test_ask_echoes_the_raw_part_verbatim_into_the_next_turn(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pins the fix for the live 400 ('missing thought_signature') — the
    conversation history sent on turn 2 must contain the exact raw_part
    from turn 1, not a hand-reconstructed functionCall dict."""
    user = _user(db, "zzassist-loop2@example.com")
    raw_part_with_signature = {
        "functionCall": {"name": "get_my_watchlist", "args": {}},
        "thoughtSignature": "abc123",
    }
    steps = iter(
        [
            StepResult(
                function_call=FunctionCall(name="get_my_watchlist", args={}),
                text=None,
                raw_part=raw_part_with_signature,
            ),
            StepResult(function_call=None, text="done", raw_part={}),
        ]
    )
    seen_contents = []

    def fake_step(self: GeminiChatProvider, **kwargs: object) -> StepResult:
        seen_contents.append(kwargs["contents"])
        return next(steps)

    monkeypatch.setattr(GeminiChatProvider, "step", fake_step)
    ask(db, user, "question", api_keys=["fake-key"])

    # The second call's contents must include turn 1's raw_part unchanged.
    second_call_contents = seen_contents[1]
    model_turn = next(c for c in second_call_contents if c["role"] == "model")
    assert model_turn["parts"][0] == raw_part_with_signature


def test_ask_raises_after_exhausting_max_tool_calls(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _user(db, "zzassist-loop3@example.com")

    def always_calls_a_tool(self: GeminiChatProvider, **kwargs: object) -> StepResult:
        return StepResult(
            function_call=FunctionCall(name="get_my_watchlist", args={}),
            text=None,
            raw_part={"functionCall": {"name": "get_my_watchlist", "args": {}}},
        )

    monkeypatch.setattr(GeminiChatProvider, "step", always_calls_a_tool)

    with pytest.raises(ProviderError, match="more than"):
        ask(db, user, "question", api_keys=["fake-key"])


def test_ask_dispatches_an_unknown_tool_name_as_an_error_response_not_a_crash(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the model hallucinates a tool name mid-conversation, the loop
    must feed back an error and keep going, not raise out of ask()."""
    user = _user(db, "zzassist-loop4@example.com")
    steps = iter(
        [
            StepResult(
                function_call=FunctionCall(name="totally_made_up", args={}),
                text=None,
                raw_part={"functionCall": {"name": "totally_made_up", "args": {}}},
            ),
            StepResult(function_call=None, text="I couldn't find that tool.", raw_part={}),
        ]
    )
    monkeypatch.setattr(GeminiChatProvider, "step", lambda self, **kwargs: next(steps))

    answer = ask(db, user, "question", api_keys=["fake-key"])
    assert answer.text == "I couldn't find that tool."


def test_max_tool_calls_is_a_small_positive_bound() -> None:
    """Sanity guard: this is a real safety bound, not accidentally 0 or
    unbounded."""
    assert 0 < MAX_TOOL_CALLS <= 10


def test_system_instruction_carries_the_no_advice_and_sebi_language() -> None:
    assert "recommend" in SYSTEM_INSTRUCTION.lower()
    assert "sebi" in SYSTEM_INSTRUCTION.lower()
    assert "investment advice" in SYSTEM_INSTRUCTION.lower()


def test_every_tool_schema_only_exposes_arguments_its_handler_accepts_with_defaults() -> None:
    """Guards the exact live bug class found 2026-08-30 across the whole
    registry at once, not just run_screen: any parameter the JSON schema
    doesn't list as required must have a Python default, or a model that
    (correctly, per the schema) omits it will crash the handler."""
    import inspect

    for name, tool in TOOLS.items():
        required = set(tool.parameters.get("required", []))
        properties = set(tool.parameters.get("properties", {}))
        optional = properties - required
        sig = inspect.signature(tool.handler)
        for param_name in optional:
            assert param_name in sig.parameters, f"{name}: {param_name} not in handler signature"
            assert sig.parameters[param_name].default is not inspect.Parameter.empty, (
                f"{name}: {param_name} is optional in the schema but has no Python default"
            )
