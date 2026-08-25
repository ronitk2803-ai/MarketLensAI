/**
 * Splits the AI summary's plain text into its synthesis paragraph plus
 * "Supporting factors" / "Risk factors" bullet lists, per the prompt shape
 * in company_summary.py._build_prompt.
 *
 * Deliberately tolerant: the model isn't guaranteed to follow the
 * requested headings exactly, so a summary that doesn't match the
 * expected shape falls back to `sections: null` and the caller just
 * renders the raw text as one block — a parsing miss should degrade to
 * "plain paragraph," never to a blank or broken panel.
 */
export interface ParsedAiSummary {
  intro: string;
  supportingFactors: string[];
  riskFactors: string[];
}

const SUPPORTING_HEADING = /^supporting factors:?$/i;
const RISK_HEADING = /^risk factors:?$/i;
const BULLET_PREFIX = /^[-•*]\s*/;

export function parseAiSummary(text: string): ParsedAiSummary | null {
  const lines = text.split("\n").map((l) => l.trim());

  const supportingIdx = lines.findIndex((l) => SUPPORTING_HEADING.test(l));
  const riskIdx = lines.findIndex((l) => RISK_HEADING.test(l));
  if (supportingIdx === -1 || riskIdx === -1) return null;

  const intro = lines.slice(0, Math.min(supportingIdx, riskIdx)).join(" ").trim();

  const bulletsBetween = (start: number, end: number): string[] =>
    lines
      .slice(start + 1, end)
      .filter((l) => l.length > 0)
      .map((l) => l.replace(BULLET_PREFIX, ""));

  // Handle either heading order, even though the prompt asks for
  // supporting-then-risk — a model that swaps them shouldn't break parsing.
  const [firstIdx, secondIdx] =
    supportingIdx < riskIdx ? [supportingIdx, riskIdx] : [riskIdx, supportingIdx];
  const firstBullets = bulletsBetween(firstIdx, secondIdx);
  const secondBullets = bulletsBetween(secondIdx, lines.length);

  const supportingFactors = supportingIdx < riskIdx ? firstBullets : secondBullets;
  const riskFactors = supportingIdx < riskIdx ? secondBullets : firstBullets;

  if (!intro && supportingFactors.length === 0 && riskFactors.length === 0) return null;

  return { intro, supportingFactors, riskFactors };
}
