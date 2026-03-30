Meeting: Sprint Planning — Checkout Validation Hooks
Date: February 7, 2026
Attendees: Lena (Security), Kai (Plugin Architect), Sofia (Payments Engineer), Marco (Frontend)

Kai: The goal this sprint is making the checkout pipeline more extensible. Merchants want to inject custom validation at different stages — before adding lines, during shipping selection, before payment. Right now the plugin hooks are notification-only, they fire after the fact.

Lena: Right, the PluginManager has hooks like `checkout_created` and `checkout_updated`, but a plugin can't reject an operation. It just gets notified.

Kai: So the key change is synchronous validation hooks that can return an error and abort the mutation. A plugin raises a `ValidationError` that propagates back through the GraphQL response.

Sofia: Take `checkoutCreate` — the plugin hook fires after the database save. We need a pre-validation hook that runs after input cleaning but before the save.

Marco: From the frontend, we need these to come back as structured GraphQL errors. The current `CheckoutError` type has codes like `INSUFFICIENT_STOCK`, `INVALID_SHIPPING_METHOD`. We'd need something like `EXTERNAL_VALIDATION_ERROR` with a metadata field for plugin-specific details.

Kai: Yeah, the plugin's validate method returns a list of error objects with field, message, and optional metadata. The mutation maps those to GraphQL errors.

Lena: We should be careful about what data plugins can access. Don't expose raw querysets to third-party plugins — use serialized data, same as webhook payloads.

Sofia: Speaking of which, the sync webhook pattern already exists for tax calculations. The checkout mutation calls the PluginManager, it sends an HTTP request to the external service, waits for the response. We could use the exact same flow for validation.

Marco: What's the latency hit? Tax webhooks already add 200 to 400 milliseconds. Another sync webhook could push `checkoutComplete` over a second.

Sofia: We measured — `checkoutComplete` averages 800ms right now with payment, order creation, stock allocation. A validation webhook pushes that to maybe 1.2 seconds worst case.

Kai: We can cache it. The Checkout has a `last_change` timestamp — if nothing's changed since the last validation, skip the webhook. Store results in Redis with a TTL.

Lena: That works as long as we invalidate when lines change, addresses update, or shipping method changes. Those mutations all update `last_change`.

Kai: We'd also need a circuit breaker. If a plugin's validation endpoint goes down, we can't let it block all checkouts. Three consecutive timeouts and we skip that validation, let the checkout proceed.

Sofia: Per-app, per-event-type circuit breaker. Track failures in Redis with a sliding window.

Marco: Should this work with the app webhook model too? Third-party apps register webhooks with event types. If an app registers for something like `CHECKOUT_VALIDATE_COMPLETE`, the PluginManager should route to that app's webhook URL.

Kai: Yeah, the WebhookPlugin already bridges the plugin system and the webhook system for tax calculations. Same pattern.

Lena: I'll write the security spec for data access boundaries and the circuit breaker behavior. We should also audit-log validation rejections so merchants can debug blocked checkouts.

Sofia: I'll prototype the hooks and test against our tax service integration. Target is base implementation ready for review by end of sprint.

Kai: Let's check in Thursday on the plugin changes — that's the critical path.
