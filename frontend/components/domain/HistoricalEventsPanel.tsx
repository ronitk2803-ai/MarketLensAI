import { ProvenanceBadge } from "@/components/domain/ProvenanceBadge";
import { Delta } from "@/components/terminal/Delta";
import { Panel } from "@/components/terminal/Panel";
import { Stat } from "@/components/terminal/Stat";
import { DASH, fracPct, price, tradingDate } from "@/lib/format";
import type {
  ComparableHistoricalEpisode,
  CorporateAction,
  HistoricalEpisode,
  HistoricalEvents,
  Meta,
} from "@/lib/api";

/** Calendar days -> the unit people actually think in. Kept coarse on
 *  purpose: "about 17 months" is the honest resolution for something
 *  measured between two closes, and "512 days" invites false precision. */
function duration(days: number | null): string {
  if (days == null) return DASH;
  if (days < 45) return `${days}d`;
  const months = Math.round(days / 30.44);
  if (months < 24) return `${months} mo`;
  return `${(days / 365.25).toFixed(1)} yr`;
}

/** Splits and bonuses are already price-adjusted upstream, and a dividend's
 *  ex-date drop is both ordinary and tiny next to a 20% fall — flagging
 *  those would bury the signal (VEDL alone has 51 dividends on record).
 *  What's left — rights issues, demergers, anything we don't recognise —
 *  is unadjusted and can move the quoted price by tens of percent. */
const EXPLAINED_ACTION_TYPES = new Set(["split", "bonus", "dividend"]);

/**
 * A single session this large is worth a second look before reading the
 * fall as a market move. Measured across all 1,306 falls in the current
 * universe: -25% or worse in one session happens in 1% of them, and that
 * tail is dominated by unadjusted corporate actions (VEDL's demerger at
 * -64.9%, ABFRL's at -66.6%, BAJFINANCE's bonus+split at -79.9%) mixed
 * with a few genuine one-day crashes (ADANIENT -28.2% on 2023-02-01).
 * The copy below stays neutral about which, because the data can't say.
 */
const SUSPECT_SESSION_PCT = -25;

/** Unadjusted corporate actions that went ex inside a listed fall. */
function unexplainedActionsInsideFalls(
  episodes: HistoricalEpisode[],
  actions: CorporateAction[],
): CorporateAction[] {
  return actions.filter(
    (action) =>
      !EXPLAINED_ACTION_TYPES.has(action.type) &&
      episodes.some(
        (episode) =>
          action.ex_date >= episode.peak_date &&
          action.ex_date <= (episode.recovery_date ?? episode.trough_date),
      ),
  );
}

function Row({
  episode,
  showGap,
}: {
  episode: ComparableHistoricalEpisode;
  showGap: boolean;
}) {
  return (
    <tr className="border-b border-border/60 last:border-0 hover:bg-accent/40">
      <td className="px-3 py-1.5 whitespace-nowrap">
        {tradingDate(episode.peak_date)}
        <span className="px-1 text-muted-foreground">→</span>
        {tradingDate(episode.trough_date)}
      </td>
      <td className="px-2 py-1.5 text-right">
        <Delta value={episode.decline_pct} digits={1} showIcon={false} />
      </td>
      {showGap && (
        // Deliberately plain, not a Delta: a signed, coloured gap would read
        // as "better"/"worse" when it only means "nearer"/"further".
        <td className="num px-2 py-1.5 text-right text-muted-foreground">
          {episode.decline_gap_pp == null ? DASH : `${episode.decline_gap_pp.toFixed(1)} pp`}
        </td>
      )}
      <td className="num px-2 py-1.5 text-right">{duration(episode.peak_to_trough_days)}</td>
      <td className="px-2 py-1.5 whitespace-nowrap">
        {episode.recovery_date ? (
          tradingDate(episode.recovery_date)
        ) : (
          <span className="text-muted-foreground">not yet</span>
        )}
      </td>
      <td className="num px-2 py-1.5 text-right">{duration(episode.trough_to_recovery_days)}</td>
      <td className="num px-2 py-1.5 text-right text-muted-foreground">
        {fracPct(episode.fall_volatility)}
      </td>
    </tr>
  );
}

export function HistoricalEventsPanel({
  symbol,
  events,
  meta,
  corporateActions,
}: {
  symbol: string;
  events: HistoricalEvents;
  meta: Meta;
  corporateActions: CorporateAction[];
}) {
  const { current, comparable } = events;
  const threshold = events.min_decline_pct.toFixed(0);
  const showGap = current !== null;

  const listed: HistoricalEpisode[] = [
    ...(current ? [current as HistoricalEpisode] : []),
    ...comparable,
  ];
  const suspectActions = unexplainedActionsInsideFalls(listed, corporateActions);
  // Checked independently of the actions list, because the dangerous case
  // is exactly the one our corporate-actions source never recorded: VEDL's
  // demerger shows up as a -64.9% session with no action on file at all.
  const suspectSessions = listed.filter(
    (episode) => episode.worst_session_pct <= SUSPECT_SESSION_PCT,
  );

  const footnote = (
    <>
      Historical context only — how {symbol}&rsquo;s own past falls unfolded, not a forecast, a
      recovery estimate, or a buy/sell/hold view. A fall here is a close {threshold}% or more
      below its own running peak, measured on corporate-action-adjusted closes; it ends the
      first day the price closes back at that peak. History begins{" "}
      {tradingDate(events.history_start)} — when this deployment started tracking {symbol}, not
      its listing date — so an earlier or deeper fall may exist and simply isn&rsquo;t in this
      data. Falls are compared on magnitude, duration and volatility only; the news or event
      behind each one, the fundamentals, the valuation and the sector conditions are not
      compared, and two falls of the same size can have entirely different causes.
    </>
  );

  return (
    <Panel
      title="Historical falls"
      actions={
        <ProvenanceBadge
          source={meta.source}
          asOf={meta.as_of}
          confidence={meta.confidence}
        />
      }
      bodyClassName="p-0"
      footnote={footnote}
      fullscreenable
    >
      {current && (
        <div className="flex flex-wrap items-start gap-y-2 border-b border-border px-3 py-2">
          <Stat
            label="Current fall"
            glossaryKey="historical_fall"
            value={<Delta value={current.decline_pct} digits={1} showIcon={false} />}
            hint={`from ${tradingDate(current.peak_date)}`}
          />
          <Stat label="Peak" value={price(current.peak_close)} hint={tradingDate(current.peak_date)} />
          <Stat
            label="Low so far"
            value={price(current.trough_close)}
            hint={
              current.trough_is_latest_bar
                ? "still making new lows"
                : tradingDate(current.trough_date)
            }
            hintTone={current.trough_is_latest_bar ? "text-down" : undefined}
          />
          <Stat
            label="Down now"
            value={<Delta value={current.current_drawdown_pct} digits={1} showIcon={false} />}
            hint="peak to latest close"
          />
          <Stat label="Falling for" value={duration(current.peak_to_trough_days)} />
          <Stat
            label="Worst day"
            value={<Delta value={current.worst_session_pct} digits={1} showIcon={false} />}
            hint={tradingDate(current.worst_session_date)}
          />
          <Stat label="Volatility" value={fracPct(current.fall_volatility)} hint="annualized" />
        </div>
      )}

      {comparable.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-border text-left text-[11px] text-muted-foreground">
                <th className="px-3 py-1.5 font-normal">Peak → Low</th>
                <th className="px-2 py-1.5 text-right font-normal">Fell</th>
                {showGap && <th className="px-2 py-1.5 text-right font-normal">vs current</th>}
                <th className="px-2 py-1.5 text-right font-normal">Fall took</th>
                <th className="px-2 py-1.5 font-normal">Back to peak</th>
                <th className="px-2 py-1.5 text-right font-normal">Recovery took</th>
                <th className="px-2 py-1.5 text-right font-normal">Volatility</th>
              </tr>
            </thead>
            <tbody>
              {/* Server order, never re-sorted here — the ranking is the
                  API's contract and the "vs current" column is its receipt. */}
              {comparable.map((episode) => (
                <Row key={episode.peak_date} episode={episode} showGap={showGap} />
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="px-3 py-3 text-[13px] text-muted-foreground">
          {current
            ? `No earlier fall of ${threshold}% or more to compare this one against — the history here begins ${tradingDate(events.history_start)}.`
            : `${symbol} is not ${threshold}% or more below its highest close since ${tradingDate(events.history_start)}, and there's no earlier fall that large on record.`}
        </p>
      )}

      {(suspectSessions.length > 0 ||
        suspectActions.length > 0 ||
        events.excluded_left_censored > 0) && (
        <div className="space-y-1 border-t border-border px-3 py-2 text-[11px] text-muted-foreground">
          {suspectSessions.map((episode) => (
            <p key={`session-${episode.peak_date}`}>
              The fall from {tradingDate(episode.peak_date)} includes a single session of{" "}
              <span className="num text-down">{episode.worst_session_pct.toFixed(1)}%</span> on{" "}
              {tradingDate(episode.worst_session_date)}. A drop that large in one day is often a
              corporate action rather than a price move — only splits and bonuses are adjusted
              here, so a demerger or rights issue is carried through as a decline. Worth checking
              before reading this as a market fall.
            </p>
          ))}
          {suspectActions.map((action) => (
            <p key={`${action.type}-${action.ex_date}`}>
              A {action.type} went ex on {tradingDate(action.ex_date)}, inside one of these falls.
              It is not price-adjusted here, so part of the decline may be mechanical.
            </p>
          ))}
          {events.excluded_left_censored > 0 && (
            <p>
              {events.excluded_left_censored} earlier{" "}
              {events.excluded_left_censored === 1 ? "fall was" : "falls were"} already underway
              when this history begins, so {events.excluded_left_censored === 1 ? "its" : "their"}{" "}
              depth is only a lower bound and {events.excluded_left_censored === 1 ? "it is" : "they are"} not
              listed as comparable.
            </p>
          )}
        </div>
      )}
    </Panel>
  );
}
