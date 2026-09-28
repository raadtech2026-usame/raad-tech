/**
 * Client-side preview of the server's default payment split (ADR-0047 §3,
 * `school_erp.domain.entities.allocate_pro_rata`): the total is shared in proportion to each
 * student's remaining balance, each share rounded down to the cent, leftover cents handed out
 * one at a time in line order to lines that still have room.
 *
 * **Preview only.** The server computes and validates the real split; this exists so the
 * payment form can show the bursar where the money will go before they confirm. Arithmetic is
 * done in integer cents, never on floats, so the preview cannot drift from the server by a cent.
 */

export function toCents(amount: string): number {
  const [whole, fraction = ""] = amount.trim().split(".");
  const cents = Number(whole) * 100 + Number((fraction + "00").slice(0, 2));
  return Number.isFinite(cents) ? cents : NaN;
}

export function fromCents(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  const abs = Math.abs(cents);
  return `${sign}${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, "0")}`;
}

export interface AllocationLine {
  lineId: string;
  balanceDue: string;
}

/** Returns `lineId -> amount` for every line that receives money, or `null` when the total is
 * not payable (zero, or more than the lines still owe). */
export function allocateProRata(total: string, lines: AllocationLine[]): Map<string, string> | null {
  const totalCents = toCents(total);
  const open = lines
    .map((line) => ({ lineId: line.lineId, capacity: toCents(line.balanceDue) }))
    .filter((line) => line.capacity > 0);
  const outstanding = open.reduce((sum, line) => sum + line.capacity, 0);
  if (!Number.isFinite(totalCents) || totalCents <= 0 || totalCents > outstanding) return null;

  const shares = open.map((line) => Math.floor((totalCents * line.capacity) / outstanding));
  let leftover = totalCents - shares.reduce((sum, share) => sum + share, 0);
  let index = 0;
  while (leftover > 0) {
    const position = index % open.length;
    if (shares[position] < open[position].capacity) {
      shares[position] += 1;
      leftover -= 1;
    }
    index += 1;
  }
  const result = new Map<string, string>();
  open.forEach((line, position) => {
    if (shares[position] > 0) result.set(line.lineId, fromCents(shares[position]));
  });
  return result;
}
