-- 0003_consent.sql — explicit consent before the first analysis (GDPR Art. 9 / KVKK for health
-- data; generally any app that processes sensitive photos).
--
-- Decision: the column always exists (one schema for every app); whether `analyze` enforces it is
-- the REQUIRE_CONSENT secret, written from spec.consent.health by backend_deploy. When enforced,
-- `analyze` answers 403 consent_required while consent_health_at is null.
--
-- The app upserts consent_health_at when the user agrees and sets it to null to withdraw.
-- The server stamps the time itself, so a client cannot backdate consent.

create or replace function public.stamp_consent() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.consent_health_at is not null
     and (tg_op = 'INSERT' or old.consent_health_at is null) then
    new.consent_health_at = now();                 -- newly given: server time
  elsif new.consent_health_at is not null then
    new.consent_health_at = old.consent_health_at; -- already given: keep the original time
  end if;
  return new;
end; $$;
revoke all on function public.stamp_consent() from public, anon, authenticated;

create trigger profiles_consent before insert or update on public.profiles
  for each row execute function public.stamp_consent();
