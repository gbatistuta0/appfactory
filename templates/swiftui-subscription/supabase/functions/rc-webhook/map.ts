// RC webhook event → revenue_events row. Field names are verified against fixtures/ (premortem C).
export interface RevRow {
  id: string;
  app: string;
  user_id: string;
  type: string;
  price_usd: number | null;
  price_local: number | null;
  currency: string | null;
  is_trial: boolean;
  sign: number;
  country: string | null;
  store: string | null;
  ts: string;
}

const NEGATIVE = new Set(["CANCELLATION", "REFUND", "BILLING_ISSUE", "EXPIRATION"]);
const TRIAL = new Set(["TRIAL_STARTED", "TRIAL_CANCELLED"]);

export function mapEvent(ev: Record<string, any>, app: string): RevRow {
  const type = String(ev.type);
  return {
    id: String(ev.id),
    app,
    user_id: String(ev.app_user_id),
    type,
    price_usd: ev.price != null ? Number(ev.price) : null, // RC gross USD estimate
    price_local: ev.price_in_purchased_currency != null ? Number(ev.price_in_purchased_currency) : null,
    currency: ev.currency ?? null,
    is_trial: TRIAL.has(type) || ev.period_type === "TRIAL",
    sign: NEGATIVE.has(type) ? -1 : 1,
    country: ev.country_code ?? null,
    store: ev.store ?? null,
    ts: new Date(Number(ev.event_timestamp_ms ?? Date.now())).toISOString(),
  };
}
