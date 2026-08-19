# Product Principles — `mlai`

> The rules we build by. Every feature, prompt, and UI decision should be checkable against these.

## The 15 principles
1. **Opportunity discovery over information overload.**
2. **Evidence over opinions.**
3. **Explain rather than blindly recommend.**
4. **Industry-specific analysis matters.**
5. **Historical context matters.**
6. **Data quality matters.**
7. **Minimize external dependencies.**
8. **Minimize API calls.**
9. **Minimize unnecessary database storage.**
10. **Modular architecture is mandatory.**
11. **Build for future expansion.**
12. **Ship quickly, but don't create needless technical debt.**
13. **Never expose secrets.**
14. **Never present speculation as fact.**
15. **The user remains the final decision-maker.**

## How AI must behave
For every important analysis (where data permits), present:
- What happened? • Why did it happen? • What changed? • What did **not** change?
- Bull case • Bear case • Risks
- Supporting evidence • Contradicting evidence
- What to monitor next • Confidence / uncertainty

AI must **distinguish facts from interpretation**, avoid hallucination, and never present speculation as fact. Every AI claim is grounded in and cited to data we hold.

## Language rules (positioning)
The product is **investment research / intelligence / education**, not regulated personalized advice.

**Avoid:** "guaranteed winner", "risk-free", "this stock will go up".
**Use:** "potential opportunity", "research candidate", "signals suggest", "historical context", "risks include".

The **Opportunity Score** represents *research attractiveness / opportunity characteristics* — **never a predicted return.**

## Engineering principles
- **Modularity is non-negotiable.** A new feature = new module + existing interfaces, not a rewrite.
- **Don't couple to India.** India is the first market, not the permanent architecture. Domain models stay market-agnostic.
- **Don't couple to a brand name.** Use codename `mlai`.
- **Don't couple to a data provider.** Everything external sits behind a provider interface.
- **Compute, don't fetch** what we can derive (e.g. technical indicators).
- **Cache + freshness first;** avoid repeated API calls for the same data.
- **Provenance everywhere:** `source + as_of + confidence` on every datapoint.

## Security baseline
API keys in env vars only; never committed, never sent to the frontend. Validate inputs, secure auth, rate-limit sensitive endpoints, least-privilege DB access.

*See also: [`founder_vision.md`](founder_vision.md), [`architecture.md`](architecture.md).*
