You are the lead software architect and senior engineer for a new product.

IMPORTANT:
This first task is PLANNING ONLY.
Do NOT start implementing the application yet.
Do NOT generate large amounts of code.
Do NOT spend tokens repeatedly explaining your reasoning.

Your job in this phase is to:
1. Understand the complete product vision below.
2. Inspect the current repository.
3. Identify technical/data dependencies.
4. Identify risks and assumptions.
5. Produce a practical MVP architecture and implementation plan.
6. Break the build into small, independently implementable tasks suitable for Claude Pro usage limits.

Create/update:
docs/BUILD_PLAN.md

Keep the plan concise but complete.
Do not create the full application yet.

============================================================
1. PRODUCT VISION
============================================================

We are building an AI-powered investment intelligence platform.

Working project name:
MarketLensAI / temporary name only.

The final company/product name has NOT been finalized.

Do NOT tightly couple the codebase to the current name.

The platform initially focuses on Indian equities, especially NSE-listed stocks and the Nifty 500 universe.

The long-term platform should be capable of expanding to:

- US equities
- Mutual Funds
- ETFs
- Crypto
- Other global markets/assets

The product is NOT intended to be merely another stock screener.

Core vision:

HELP INVESTORS DISCOVER POTENTIAL INVESTMENT OPPORTUNITIES AND BUILD/CHALLENGE THEIR INVESTMENT CONVICTION USING MULTIPLE SOURCES OF EVIDENCE IN ONE PLACE.

The key transformation is:

DATA → INFORMATION → CONTEXT → INSIGHT → OPPORTUNITY

============================================================
2. WHY THIS PRODUCT EXISTS
============================================================

Current investment platforms provide fragmented information.

Users may use different platforms for:

- Price charts
- Technical analysis
- Financial statements
- Ratios
- News
- Company research
- Screening
- Portfolio tracking
- Market sentiment

The investor must manually connect these pieces.

We want to connect them.

Example:

A stock falls 25% in two weeks.

A conventional screener says:

Stock X
-25%

Our platform should ask:

WHY did it fall?

Did the underlying business deteriorate?

Was there temporary negative news?

Was the entire sector affected?

Did valuation compress?

Did technical damage occur?

Was trading volume unusual?

Did the market overreact?

Has something similar happened to this company before?

What happened after the previous event?

What does the current financial situation look like?

What are the bull and bear cases?

What should the investor monitor next?

This contextual analysis is central to the product.

============================================================
3. IMPORTANT FOUNDER INSPIRATION
============================================================

One of the ideas behind the product came from real investment experiences.

Example:

Paytm experienced a very sharp fall in 2024.

The founder of this product believed that the market reaction might create an opportunity because the long-term belief in management/business potential remained intact.

The stock initially continued falling, but eventually recovered substantially.

The important lesson is NOT "buy stocks after they fall."

The lesson is:

A large price decline can sometimes represent:

A) genuine deterioration

OR

B) temporary market overreaction.

An investor needs tools to distinguish between them.

The platform should help investigate this distinction.

Another personal example is Ola Electric.

The investment thesis is that even if one part of the business struggles, other potential areas such as battery manufacturing could become important long-term value drivers.

Again, the platform should help an investor TEST such a thesis rather than simply confirming it.

============================================================
4. CORE PRODUCT PHILOSOPHY
============================================================

We are NOT building an automatic trading or blind recommendation system.

AI must NOT simply say:

BUY

SELL

HOLD

Instead, AI should explain evidence.

For every important analysis, where data permits, present:

- What happened?
- Why did it happen?
- What changed?
- What did NOT change?
- Bull case
- Bear case
- Risks
- Supporting evidence
- Contradicting evidence
- What should be monitored?
- Confidence/uncertainty

The final investment decision belongs to the user.

The system should help users BUILD or CHALLENGE CONVICTION.

AI must distinguish facts from interpretation.

Avoid hallucinated information.

Do not present speculation as fact.

============================================================
5. THE MOST IMPORTANT DIFFERENTIATOR
============================================================

Opportunity Discovery.

Most platforms begin with:

"Tell me about this stock."

We also want:

"What deserves my attention?"

Example:

User selects:

Universe:
Nifty 500

Condition:
Stock has fallen sharply

Period:
15 days

The platform should return stocks in descending order of decline.

But this is only the FIRST layer.

The next layer should identify which declines may deserve further research.

Example:

Stock A:
-30%
Fundamentals deteriorating
Negative structural news
High debt

Stock B:
-22%
Temporary regulatory/news event
Revenue trend intact
ROCE intact
Debt stable
Historical similar decline recovered

Stock B may deserve more attention.

The platform should help surface that distinction.

============================================================
6. OPPORTUNITY FINDER
============================================================

Initial opportunity screens should include:

- Stocks down sharply in last 5/10/15/30/60/90 days
- Stocks below 50 DMA
- Stocks below 100 DMA
- Stocks below 200 DMA
- Stocks with unusually high volume
- Stocks with improving fundamentals despite price weakness
- Stocks with valuation compression
- Stocks with improving earnings
- Stocks with declining debt
- Stocks with strong cash flow
- Stocks with positive/negative news shocks
- Potential recovery candidates
- Relative strength/weakness versus sector
- Relative strength/weakness versus Nifty

The system should support combinations later.

Example:

"Find Nifty 500 companies that:

fell >20% in 30 days
AND
ROCE >15%
AND
debt is declining
AND
cash flow is positive."

The architecture must support adding new screening conditions without rewriting the system.

============================================================
7. OPPORTUNITY SCORE
============================================================

There should eventually be a composite Opportunity Score.

IMPORTANT:

A single fixed weighting system must NOT be hardcoded forever.

Different industries have different meaningful indicators.

For example:

BANKING:
- NIM
- GNPA/NNPA
- credit growth
- CASA
- capital adequacy
- provisions

IT:
- revenue growth
- EBIT margin
- deal wins
- attrition
- client concentration
- cash generation

MANUFACTURING:
- capacity utilization
- order book
- ROCE
- debt
- operating leverage
- raw material costs

Therefore the scoring engine must support INDUSTRY-SPECIFIC WEIGHTS.

Initial weights can be rule-based/configurable.

Future versions should support:

- historical validation
- backtesting
- optimization
- learning/adaptive weights

Do NOT claim that a score predicts future returns.

The score represents "research attractiveness" or "opportunity characteristics", not a guaranteed return.

Make the scoring architecture configurable.

============================================================
8. SCORE COMPONENTS
============================================================

Potential components:

PRICE:
- absolute decline
- drawdown
- short/medium-term momentum

TECHNICAL:
- 20 DMA
- 50 DMA
- 100 DMA
- 200 DMA
- RSI
- MACD
- volatility
- relative strength

FUNDAMENTALS:
- revenue growth
- EBITDA growth
- PAT growth
- EPS growth
- ROE
- ROCE
- margins
- debt
- cash flow
- free cash flow

VALUATION:
- P/E
- P/B
- EV/EBITDA
- PEG where appropriate
- historical valuation comparison

MARKET PARTICIPATION:
- volume
- relative volume
- turnover
- delivery percentage where available
- free-float turnover where data is available

NEWS:
- event
- sentiment
- severity
- relevance
- temporary vs potentially structural classification

HISTORICAL:
- previous sharp falls
- reason for previous fall
- recovery after previous event
- similarity between historical and current event

MANAGEMENT/BUSINESS:
- promoter activity where reliable
- business quality indicators
- execution indicators

Not every metric will be available for every company/industry.

The scoring engine must gracefully handle missing data.

============================================================
9. VOLUME PHILOSOPHY
============================================================

Raw trading volume alone is not sufficient.

Example:

Company A:
10M shares outstanding
2M traded

Company B:
100M shares outstanding
5M traded

Raw volume says B traded more.

But A had 20% of shares traded versus 5% for B.

Therefore we want normalized metrics where data permits:

- Volume / shares outstanding
- Volume / free float
- Relative volume vs average
- Delivery percentage
- Turnover

IMPORTANT:

Do NOT describe free-float turnover as "percentage of investors who traded."

The same shares can change hands multiple times.

Use language such as:

"Percentage of free float traded."

============================================================
10. HISTORICAL EVENT / RECOVERY ENGINE
============================================================

This is an important differentiator.

When a stock experiences a major fall, look for comparable historical events.

Example:

2024:
Stock fell 40%
Reason: regulatory event
Fundamentals remained stable
Recovery occurred over X months

Current:
Stock falls 35%
Reason: potentially similar event

The platform should eventually compare:

- magnitude
- duration
- volatility
- news/event type
- fundamentals
- valuation
- sector environment

Then present historical context.

Do NOT present historical recovery as a prediction.

It is context only.

============================================================
11. COMPANY RESEARCH PAGE
============================================================

Every stock should eventually have a comprehensive but clean company page.

Sections:

1. Company header
2. Current price
3. Market cap
4. Sector/industry
5. Price chart
6. Performance
7. Technical indicators
8. Fundamentals
9. Financial statements
10. Valuation
11. News
12. Corporate events
13. AI analysis
14. Opportunity Score
15. Risk indicators
16. Peer comparison
17. Historical events
18. What changed?
19. What to monitor?

Avoid displaying every metric simultaneously.

Prioritize useful information.

============================================================
12. FINANCIAL ANALYSIS
============================================================

Initial financial information:

INCOME STATEMENT:
- revenue
- EBITDA
- EBIT
- PAT
- EPS

BALANCE SHEET:
- debt
- cash
- equity
- working capital

CASH FLOW:
- operating cash flow
- investing cash flow
- financing cash flow
- free cash flow

RATIOS:
- ROE
- ROCE
- debt/equity
- margins
- asset turnover

Historical trends matter more than one isolated value.

============================================================
13. TECHNICAL ANALYSIS
============================================================

Initial indicators:

- 20 DMA
- 50 DMA
- 100 DMA
- 200 DMA
- RSI
- MACD
- volatility
- drawdown
- relative strength
- relative volume

Technical indicators are supporting signals.

We are NOT building a day-trading terminal.

============================================================
14. NEWS INTELLIGENCE
============================================================

We do not want a simple news feed.

Eventually:

- collect relevant news
- deduplicate identical stories
- summarize
- classify sentiment
- identify event type
- estimate relevance
- connect news to price movement

AI should answer:

"Why is this stock falling?"

using actual available evidence.

The system must clearly distinguish:

known information

from

AI interpretation.

============================================================
15. PORTFOLIO
============================================================

Users should eventually be able to:

- add holdings
- edit holdings
- import holdings
- import Zerodha CSV
- track average price
- current value
- P&L
- allocation
- sector exposure
- concentration

Future:

AI Portfolio Analysis

Examples:

"Your portfolio has high exposure to financial services."

"Three holdings contribute most of your portfolio concentration."

============================================================
16. WATCHLIST
============================================================

Users can add stocks.

Future intelligent alerts:

- price movement
- major news
- earnings
- technical break
- valuation change
- unusual volume
- fundamental change

Do not implement unnecessary alert complexity in V1.

============================================================
17. STOCK SCREENER
============================================================

Users should be able to create filters.

Examples:

Revenue growth >15%

ROCE >20%

Debt declining

Stock down >20%

Price below 200 DMA

Positive cash flow

Then combine conditions.

The architecture should make it easy to add new filters later.

============================================================
18. AI RESEARCH ASSISTANT
============================================================

Future natural-language questions:

"Why did this stock fall?"

"Compare this company with its competitors."

"Has this happened before?"

"What would invalidate my thesis?"

"Find companies where the market may be overreacting to temporary bad news."

"Analyze this company for a 5-year investment thesis."

"Summarize what changed in my portfolio this week."

AI responses must be grounded in application data.

============================================================
19. DATA STRATEGY
============================================================

This is CRITICAL.

Initial project budget is close to ZERO.

We want to use free data wherever realistically possible.

Before choosing any external API:

- verify current availability
- verify free tier
- verify rate limits
- verify redistribution/use restrictions
- verify reliability
- verify whether historical data is available
- verify whether the source can legally support the intended use

Do NOT assume an API is free simply because it has a public endpoint.

Do not hard-code the system to one provider.

Create a DATA PROVIDER ABSTRACTION.

Example concept:

MarketDataProvider
FundamentalDataProvider
NewsProvider
CompanyDataProvider

Then providers can be replaced later.

If a provider disappears, we should not rewrite the application.

============================================================
20. DATA STORAGE STRATEGY
============================================================

We do NOT want to store everything.

Initial principle:

STORE ONLY WHAT WE NEED.

Historical price data may be cached/stored locally if doing so reduces repeated API calls.

Do not blindly store millions of unnecessary records.

We are okay with slightly slower performance initially if it reduces cost.

Use:

- caching
- freshness rules
- batch requests
- incremental updates
- indexes
- background jobs where appropriate

Avoid repeated API calls for the same data.

============================================================
21. DATABASE PHILOSOPHY
============================================================

Initial database:

PostgreSQL

But design the data layer so it can scale.

Potential core entities:

User
Portfolio
Holding
Watchlist
Asset
Company
Market
Price
FinancialMetric
FinancialStatement
NewsArticle
CorporateEvent
Opportunity
Score
ScoreComponent
Industry
HistoricalEvent

Exact schema should be proposed in BUILD_PLAN.md.

Do not create unnecessary tables.

============================================================
22. ARCHITECTURE
============================================================

Initial direction:

Frontend:
Next.js / React

Backend:
FastAPI / Python

Database:
PostgreSQL

Future caching:
Redis if needed

Conceptual architecture:

Next.js
   ↓
FastAPI
   ↓
Application Services
   ↓
Data Provider Layer
   ↓
PostgreSQL / Cache

Analysis Engine should be separate from data ingestion.

Opportunity Engine should be separate from UI.

AI layer should be separate from core financial calculations.

============================================================
23. MODULARITY
============================================================

This is NON-NEGOTIABLE.

We expect many future features.

Do not build a monolithic application.

A new feature should ideally involve:

new module/service
+
existing interfaces

rather than rewriting the application.

Avoid hard-coding India-specific assumptions into core domain models.

India is the FIRST market, not necessarily the permanent architecture.

============================================================
24. UI / UX
============================================================

The product should feel:

- professional
- clean
- fast
- subtle
- trustworthy
- serious

Design inspiration:

Apple
Bloomberg
Linear
Notion

Avoid:

- excessive colors
- excessive animation
- clutter
- casino/trading-app aesthetics
- unnecessary cards
- information overload

The UI should make financial information understandable.

Desktop first is acceptable, but design responsively.

Performance is important.

============================================================
25. MVP
============================================================

The target is a PUBLIC MVP quickly.

We want a usable product in approximately one week.

MVP priority:

P0:
- project foundation
- stock universe
- stock search
- company page
- price history/chart
- basic financial data
- basic technical indicators
- news
- opportunity finder
- basic opportunity score

P1:
- authentication
- portfolio
- watchlist
- Zerodha CSV import
- AI company analysis

P2:
- historical event analysis
- advanced screener
- industry-specific scoring
- intelligent alerts

Prioritize working functionality over visual perfection.

However, architecture must not prevent future features.

============================================================
26. PERFORMANCE / API EFFICIENCY
============================================================

Do NOT make unnecessary API calls.

Example of BAD architecture:

Every page refresh:
10 external API calls

Instead:

Request
→ cache lookup
→ freshness check
→ existing data if valid
→ refresh only if necessary

Prefer:

- batching
- caching
- scheduled updates
- background processing
- local calculations

Calculate indicators ourselves when appropriate.

============================================================
27. SECURITY
============================================================

Even though this starts as a hobby project:

- never expose API keys
- environment variables only
- never commit secrets
- validate inputs
- secure authentication
- secure database access
- rate-limit sensitive endpoints
- do not expose provider credentials to frontend

Financial data does not mean we should treat user data casually.

============================================================
28. REGULATORY / PRODUCT POSITIONING
============================================================

The product should initially be positioned as:

Investment research / intelligence / education.

Do not build the MVP around personalized regulated investment advice.

Avoid language that guarantees returns.

Avoid:

"Guaranteed winner"

"Risk-free"

"This stock will go up"

Use evidence-based language:

"Potential opportunity"

"Research candidate"

"Signals suggest"

"Historical context"

"Risks include"

============================================================
29. FUTURE EXPANSION
============================================================

Architecture should eventually support:

India equities
↓
US equities
↓
Mutual funds
↓
ETFs
↓
Crypto
↓
Global assets

Do not implement all of this now.

Build abstractions so expansion is possible.

============================================================
30. NAMING
============================================================

The company/product name is NOT finalized.

Current names discussed include:

MarketLensAI
Bexara
Drovex
Grivo
Fenlo
Aventra
Aventrax
Invora
Nivesta
IdeaPicker

Do NOT hard-code any of these into core business logic.

Use a temporary project identifier.

The final brand will be decided separately.

============================================================
31. DEVELOPMENT PROCESS
============================================================

We are using:

ChatGPT:
Product strategy
Architecture
Feature design
Algorithms
Data strategy
Code review
Debugging
Product decisions

Claude Code:
Implementation
Testing
Refactoring
Repository changes

Because Claude is being used under a Claude Pro subscription with usage limitations:

IMPORTANT CODING WORKFLOW:

Do NOT ask Claude to generate the whole application in one huge response.

Build feature-by-feature.

For each feature:

1. Read relevant specification.
2. Inspect only relevant code.
3. Implement.
4. Run tests.
5. Fix errors.
6. Commit.
7. Move to next feature.

Prompts should be short and specific.

Do not repeatedly restate the product vision.

Documentation should be the source of truth.

============================================================
32. DOCUMENTATION
============================================================

Create:

docs/
    founder_vision.md
    product_principles.md
    architecture.md
    data_strategy.md
    roadmap.md
    decision_log.md
    build_plan.md

Feature specifications should eventually live under:

docs/features/

Each feature should document:

Purpose
User problem
Inputs
Outputs
Business logic
Data requirements
API requirements
UI requirements
Edge cases
Acceptance criteria

============================================================
33. PROJECT PRINCIPLES
============================================================

1. Opportunity discovery over information overload.
2. Evidence over opinions.
3. Explain rather than blindly recommend.
4. Industry-specific analysis matters.
5. Historical context matters.
6. Data quality matters.
7. Minimize external dependencies.
8. Minimize API calls.
9. Minimize unnecessary database storage.
10. Modular architecture is mandatory.
11. Build for future expansion.
12. Ship quickly but do not create technical debt unnecessarily.
13. Never expose secrets.
14. Never present speculation as fact.
15. User remains the final decision maker.

============================================================
34. WHAT YOU MUST DO NOW
============================================================

DO NOT IMPLEMENT THE APPLICATION YET.

First inspect the current repository.

Then create:

docs/BUILD_PLAN.md

The build plan must contain:

A. Recommended repository structure

B. Technology decisions and alternatives

C. Database architecture

D. Backend architecture

E. Frontend architecture

F. Data provider abstraction

G. Initial Indian market data strategy

H. Free/low-cost data-source feasibility assessment

I. Caching strategy

J. API strategy

K. Opportunity Engine architecture

L. Scoring Engine architecture

M. Industry-specific scoring design

N. AI architecture

O. Authentication approach

P. Security considerations

Q. MVP scope

R. P0/P1/P2 feature priorities

S. Exact implementation sequence

T. Estimated complexity per feature

U. Risks/blockers

V. Questions that MUST be resolved before coding

W. Definition of Done for the MVP

IMPORTANT:

Do not assume unavailable data.

If a feature requires data that may not be freely available, explicitly flag it.

Where possible, recommend a fallback.

Do not select a paid provider just because it is easier.

The initial project should prioritize FREE or very-low-cost infrastructure.

============================================================
35. MOST IMPORTANT RULE
============================================================

Do not over-engineer the first version.

We need a real working MVP quickly.

But do not build a throwaway prototype that must be rewritten immediately.

Find the balance:

FAST + MODULAR + LOW COST + EXTENSIBLE.

After creating docs/BUILD_PLAN.md, give a very short summary of:

1. Architecture chosen
2. Biggest data risks
3. P0 build sequence
4. Any decisions we need to make before implementation

Then STOP.

Do not start coding until the build plan has been reviewed and approved.