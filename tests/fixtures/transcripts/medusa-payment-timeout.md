Meeting: Sprint Planning — Checkout Reliability
Date: February 5, 2026
Attendees: Priya (Backend Lead), Carlos (Payments), Dana (SRE), Amir (PM)

Amir: Okay so first thing — the checkout failures. Dana, you pinged about this on Friday?

Dana: Yeah. So I was looking at the dashboards and, um, roughly 3% of checkout completions are failing. Mostly timeouts. The p99 on the cart completion endpoint went from like 4 seconds to almost 12 in the last two weeks.

Priya: Is that all Stripe or are we seeing it across providers?

Dana: Mostly Stripe. Like 2% is Stripe, and then there's a smaller chunk from PayPal, and a few from community payment providers that are just... returning weird stuff.

Carlos: Yeah I've been digging into this. So the issue is basically — when you go through checkout, the cart completion strategy calls authorize on the payment provider, and there's just no timeout on that call. We're relying on whatever Stripe's SDK does internally, which I think defaults to like 80 seconds? Something crazy.

Priya: 80 seconds? That's — yeah no, our API gateway times out way before that.

Dana: Right, it's 30 seconds on the gateway. So the customer gets a 504, but the Stripe call is still running in the background. And then we end up with this orphaned payment session sitting in pending state.

Amir: So are people getting charged?

Carlos: Usually not, because authorize is just the hold step — the actual charge is capture, which happens later. But here's the thing, um, if Stripe does eventually authorize after our gateway already timed out, the session never updates. And then when the customer retries, we create a whole new session. So they could end up with two holds on their card.

Amir: That's... not great.

Carlos: No. Not great at all.

Priya: What about that is_initiated flag on payment sessions? Could we use that to detect stale ones?

Carlos: I looked at it. It only tells you if the session was started on the provider side. Doesn't really help with the timeout case. What I think we need is — like, a wrapper. Put a 12-second ceiling on the authorize call in the payment provider service, and if it exceeds that, just return requires_more status and let the frontend handle a retry.

Priya: Hmm, does the cart completion strategy actually handle requires_more today?

Carlos: Yeah, it returns a 200 with the cart body. The storefront checks for that and can redirect to additional auth. So we'd basically be reusing that same flow for timeouts, which is kind of elegant actually.

Dana: I'd also want some kind of background sweeper. Like, a job that finds payment sessions stuck in pending for more than 5 minutes and voids them. We already have the cancel method on the abstract processor.

Priya: That makes sense. Use the job scheduler service for that?

Dana: Yeah, that's what I was thinking.

Amir: So timeline? This is kind of blocking our checkout conversion stuff.

Carlos: The timeout wrapper is probably two days. The sweeper job is another day. And then Priya mentioned we should validate the responses from providers too — some of the community ones are returning undefined instead of a proper response object, which... yeah.

Priya: Right, we should guard against that. If a provider gives us garbage back from authorize, just throw an error with the right type. Half a day maybe.

Carlos: So a week-ish total with tests.

Priya: Let's do the timeout wrapper first since that covers the bulk of it. Carlos, can you also emit an event when a timeout happens? Like payment.authorization_timeout or something? So we can hook monitoring to it.

Carlos: Yeah sure, through the event bus.

Dana: I'll set up a dashboard for that. And an alert if it crosses 1%.

Amir: Perfect. Let's check in Thursday.
