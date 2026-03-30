Meeting: Sprint Planning — Webhook Notifications
Date: February 4, 2026
Attendees: Dana (SRE), Marcus (Developer Experience), Lina (Backend Engineer), Amir (PM)

Amir: So we keep getting merchant requests for webhooks on order events. Right now they're polling our API for status changes, which is like 40 requests per minute per active store. We need to build actual webhook delivery.

Marcus: So Medusa already has a notification module. There's an `AbstractNotificationProviderService` you can extend — it's what the email and SMS providers use. We'd basically create a webhook provider that does HTTP POSTs instead.

Lina: Before we get into that — which events are we actually exposing? The event bus already emits a ton of order lifecycle stuff.

Amir: Start with the five merchants ask for most — `order.placed`, `order.completed`, `order.canceled`, `order.refund_created`, and `order.fulfillment_created`. We can expand later.

Dana: How reliable is the event bus? Like, what's backing it?

Marcus: Redis Streams with consumer groups. So if a subscriber fails to process, the message stays pending and can be reclaimed. It's at-least-once.

Lina: Right, which is fine for getting events to our handler. But from us to the merchant's endpoint — that's the part that's gonna be flaky. Endpoints go down, timeouts, whatever. We need retries.

Dana: Exponential backoff. Start at 30 seconds, ramp up to — I don't know, maybe cap at 4 hours? Six retries total. If all fail, dead letter queue.

Marcus: For the DLQ we could use another Redis stream. And then expose an admin endpoint so merchants can see failed deliveries and retry manually.

Lina: Okay let me sketch the flow. Workflow bound to each order event, the step calls the webhook provider, provider looks up registered endpoints for that merchant — we'd need a `WebhookEndpoint` model with the URL, a secret for signing, which events they're subscribed to. For each matching endpoint, POST the payload with an HMAC signature header.

Dana: SHA-256 with the endpoint's secret as the key. Standard stuff.

Amir: What do we actually send in the payload?

Lina: I was thinking a standard envelope — event name, timestamp, and then the full order data. Same shape as what the admin API returns so merchants don't have to learn a new format.

Marcus: Include an idempotency key too. UUID per delivery attempt so they can deduplicate.

Dana: What about bursts? If a merchant gets 500 orders at once we don't want to hammer their endpoint.

Lina: Per-endpoint rate limiter. Token bucket, maybe 10 per second. Overflow gets queued.

Amir: And merchants manage their endpoints how?

Marcus: Admin API. CRUD routes for webhook endpoints, plus a test endpoint that sends a ping so they can verify things work before subscribing to real events.

Dana: I want observability on this. Can we emit our own events — like `webhook.delivered`, `webhook.failed` — so I can build dashboards?

Marcus: Yeah, the EventBusService is injectable in the workflow step. Easy.

Lina: Timeline — I think about ten working days total. Data model and service, two days. Provider, one day. Workflows, two. Admin routes, one. Retry logic, two. Tests, two.

Marcus: Should the webhook thing be its own module or part of the notification module? I think standalone is cleaner. We can always link them later through `defineLink`.

Amir: Fine with me. Lina, draft the module structure by Wednesday. Marcus, workflow definitions. Dana, monitoring. Let's sync Friday.
