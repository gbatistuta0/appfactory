<!--
Source: store/privacy/privacy-policy.en.md. English is the reference version; the localize stage
translates it into privacy-policy.<lang>.md for every app language. Facts come from
backend/PRIVACY.md. `legal_render` fills the factory placeholders (APP_NAME, CONTROLLER,
SUPPORT_EMAIL, EFFECTIVE_DATE) and resolves the if-blocks from app.spec.json; the store stage fills the
product ones. backend/legal/build.ts refuses to publish while any {{PLACEHOLDER}} remains.
This comment is not published.
-->

# {{APP_NAME}} Privacy Policy

Effective date: {{EFFECTIVE_DATE}}

{{APP_NAME}} ("the app") is {{APP_PURPOSE}} for iPhone made by {{CONTROLLER}} ("we", "us"), who is the
data controller. This policy explains what data the app processes, why, who helps us process it, and
the choices you have. Contact: {{SUPPORT_EMAIL}}

## The short version

- You do not need an account. {{APP_NAME}} creates an anonymous account for you on first launch.
- Photos are sent for AI analysis and are not stored by us.
- Your answers and results are stored so the app works across launches. You can delete everything at
  any time in Settings → Delete account.
<!-- if:consent.health -->
- We only process your health data with your explicit consent.
<!-- endif -->
- We do not sell your data, do not show ads and do not track you across other apps.

## What we process and why

- **Photos** you take or pick: to {{ANALYSIS_PURPOSE}}. We do not store them. The photo is sent for
  analysis and discarded; only the result is saved. Photos are re-encoded on your phone first, which
  removes location and camera metadata.
- **Notes and descriptions** you type: same purpose as photos.
- **Onboarding answers**: {{ONBOARDING_DATA}}, to personalise the app. Stored in your profile.
- **Your results history**: to show your past results.
- **"Where did you hear about us?"**: to understand which channels bring users.
- **Anonymous user id**: to keep your data together and link your subscription.
- **Email address and Apple user id, only if you choose Sign in with Apple**: to restore your account
  on a new phone. Apple may give us a private relay address instead of your real one.
- **Subscription status and purchase history**: to unlock Premium and restore purchases.
- **App usage events** (for example "onboarding completed" or "paywall viewed") and an app-instance id:
  to understand how the app is used and improve it.
- **Analysis records** (status, response time, AI model, cost) and records of refused requests (for
  example when a daily limit is reached): to run the service, prevent abuse and control costs.

We do not collect your name, phone number, contacts or precise location.

<!-- if:consent.health -->
## Health data and your explicit consent

{{HEALTH_DATA}} are health data. Before you answer the body-related questions, the app asks for your
explicit consent with this statement: "{{CONSENT_STATEMENT}}" You cannot continue without it, and
{{APP_NAME}} does not analyse anything without it.

This consent is the legal basis for processing your health data under Article 9(2)(a) of the GDPR
(EU/EEA and UK) and the explicit consent (açık rıza) rules of the Turkish Personal Data Protection Law
No. 6698 (KVKK). You can withdraw it at any time by deleting your account in Settings or by writing to
us. Withdrawal does not affect processing that happened before it.

We use health data only to provide the app's features. We do not use it for advertising or marketing,
do not sell it, do not store it in iCloud, and share it only with the service providers below, who
process it on our behalf.

## Apple Health

If you allow it, {{APP_NAME}} reads {{HEALTHKIT_READ_TYPES}} from Apple Health to {{HEALTHKIT_PURPOSE}},
and writes {{HEALTHKIT_WRITE_TYPES}}. You choose each type in the Health permission sheet and can turn
any of them off at any time in the Health app. Data from Apple Health is never used for advertising or
marketing, never sold, never shared with data brokers, and never sent to the AI model. {{HEALTHKIT_SYNCED}}

<!-- endif -->
## Legal bases

- Providing the service you asked for (contract): your account, results, subscription and support.
- Our legitimate interest: keeping the service secure, preventing abuse, and understanding aggregate
  usage to improve the app.
- Your consent, where the law requires it.

## Service providers

- **Supabase**: database, anonymous accounts, Sign in with Apple, server functions. {{SUPABASE_REGION}}.
- **fal.ai**: gateway that sends the photo or text to the AI model. We switch off fal's request
  storage, and fal does not train on customer content. United States.
- **OpenRouter**: routes the request to the AI model. We only allow model hosts that do not store or
  train on requests. United States.
- **{{MODEL_PROVIDER}}**: the AI model that reads the photo or text. Reached only through OpenRouter
  under the no-data-collection routing.
- **RevenueCat**: manages subscriptions and purchase history. United States.
- **Google Firebase Analytics**: app usage statistics, without the advertising identifier. United
  States.
- **Apple**: payments, Sign in with Apple{{APPLE_HEALTH_SUFFIX}}.

Some providers are in the United States. Transfers abroad rely on the safeguards the law requires,
such as standard contractual clauses.

## AI results can be wrong

Results come from an AI model and can be wrong. Check them before you rely on them.

## How long we keep data

- Photos: not kept by us.
- Everything else is kept until you delete your account. Settings → Delete account removes your
  profile, results and all related records from our database immediately.
- RevenueCat keeps the purchase history of the deleted anonymous id, because Apple billing records
  require it. Your App Store subscription belongs to your Apple ID: deleting the account does not
  cancel it. Cancel it in your App Store account settings.

## Your rights

Depending on where you live (for example under the GDPR in the EU/EEA and UK, the KVKK in Türkiye,
the LGPD in Brazil, or US state laws), you can ask to access, correct, export or delete your data,
object to or restrict processing, and withdraw consent at any time. Most of this is available in the
app: edit your answers in Settings and delete everything with Delete account. For anything else,
write to {{SUPPORT_EMAIL}}. You can also complain to your local data protection authority.

## Children

{{APP_NAME}} is not meant for anyone under {{MIN_AGE}}, and we do not knowingly collect data from
children. If you believe a child has used the app, contact us and we will delete the data.

## Changes

If this policy changes, we will update the effective date above and, for important changes, tell you
in the app.

## Contact

{{CONTROLLER}}, {{SUPPORT_EMAIL}}
