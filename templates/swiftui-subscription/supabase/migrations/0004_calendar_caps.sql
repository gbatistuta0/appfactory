-- 0004_calendar_caps.sql — subscriber caps reset at the user's local midnight (profiles.timezone),
-- not on a rolling 24 h window. A timezone change is honoured at most once per 24 h for the cap
-- window (anti-abuse: hopping timezones must not mint extra days).

-- Reject unknown IANA names on write (PostgREST answers 400).
create or replace function public.validate_timezone() returns trigger
language plpgsql set search_path = public, pg_catalog as $$
begin
  if new.timezone is not null and not exists (select 1 from pg_timezone_names where name = new.timezone) then
    raise exception 'unknown timezone: %', new.timezone using errcode = '22023';
  end if;
  return new;
end; $$;
revoke all on function public.validate_timezone() from public, anon, authenticated;
create trigger profiles_validate_timezone before insert or update of timezone on public.profiles
  for each row execute function public.validate_timezone();

-- The caller's current cap day: the timezone used, when that local day started and when it ends
-- (both UTC instants). Applies the once-per-24 h rule and persists the result:
--   no cap timezone yet            → adopt the profile timezone (first setting is not a "change")
--   profile timezone differs       → adopt it if the last adopted change is ≥ 24 h old, else keep
--   no profile / no timezone       → UTC
-- Service role only (called by the edge functions).
create or replace function public.cap_day(p_user uuid)
returns table (timezone text, day_start timestamptz, resets_at timestamptz)
language plpgsql security definer set search_path = public, pg_catalog as $$
declare
  p record;
  tz text := 'UTC';
begin
  select pr.timezone, pr.cap_timezone, pr.cap_timezone_changed_at into p
    from profiles pr where pr.id = p_user for update;
  if found then
    tz := coalesce(p.cap_timezone, 'UTC');
    if p.timezone is not null then
      if p.cap_timezone is null then
        update profiles set cap_timezone = p.timezone where id = p_user;
        tz := p.timezone;
      elsif p.timezone <> p.cap_timezone
            and (p.cap_timezone_changed_at is null or now() - p.cap_timezone_changed_at >= interval '24 hours') then
        update profiles set cap_timezone = p.timezone, cap_timezone_changed_at = now() where id = p_user;
        tz := p.timezone;
      end if;
    end if;
  end if;
  return query select tz,
    (date_trunc('day', now() at time zone tz)) at time zone tz,
    (date_trunc('day', now() at time zone tz) + interval '1 day') at time zone tz;
end; $$;
revoke all on function public.cap_day(uuid) from public, anon, authenticated;
