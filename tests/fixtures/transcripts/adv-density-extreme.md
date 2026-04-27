Meeting: Architecture Sync — Rate Limiter Rework
Date: April 10, 2026
Attendees: Carlos (Platform), Dana (SRE), Priya (Backend Lead)

Carlos: Quick one. The rate limiter situation is finally going to get fixed this sprint. I want to lock in the design and split the work.

Priya: Go.

Carlos: Okay so the plan: we'll move the rate limiter from the in-memory implementation to Redis with a 100-requests-per-minute cap keyed on user ID hash, add Prometheus counters for hits and misses, switch the lease TTL from 60 seconds to 300 seconds, and emit a structured log line on every reject so we can correlate with the auth service's audit trail.

Dana: That's a lot in one sentence.

Carlos: Yeah but it all hangs together. The Redis migration unblocks the TTL change because in-memory can't survive a pod restart, and once we have Redis we want metrics and we want logs, so we may as well do it all at once.

Priya: Fine. Let's also talk about the queue rework while we have everyone here. Dana, you brought it up last week.

Dana: Yeah. So the background job queue. Currently we use the SQL polling strategy. It's been fine but it's getting expensive query-wise and the latency is bad.

Carlos: What about Redis Streams? We're already going to have Redis for the rate limiter.

Dana: Hmm, Redis Streams. Let me think. The consumer groups are nice for the at-least-once semantics. But the ops side — I don't love managing Streams. The XADD / XREADGROUP semantics are subtle and we've had bad experiences when consumers fall behind.

Carlos: Hmm. What's the alternative?

Dana: BullMQ is the obvious one. It's also Redis-backed under the hood but the operational interface is way friendlier. Built-in retries, exponential backoff, dead letter queue, dashboard.

Carlos: Yeah but I just remembered — infra blocked Redis Streams last quarter. They had a bad incident with another team's consumer-group setup and there's a soft moratorium on it.

Priya: Wait, that's news to me. So Streams is off the table?

Carlos: Effectively, yes. I'd have to fight infra to use it and I don't have the political capital this sprint.

Dana: Then BullMQ it is. It uses regular Redis lists and sorted sets, not Streams, so it's not under the moratorium.

Carlos: Does BullMQ handle our retry semantics? We need exponential backoff with a max of 6 retries before dead-lettering, like the webhook delivery flow.

Dana: Yes, that's literally a built-in option. You set the backoff strategy to exponential, set the max attempts, configure the dead letter queue, done.

Carlos: Okay. So BullMQ for the queue, with built-in exponential backoff, capped at 6 retries, dead letter queue enabled.

Priya: Good. Anything else on the queue?

Dana: We should also configure separate concurrency limits per queue. Right now everything shares one worker pool and it causes head-of-line blocking when the email queue gets backed up.

Carlos: Use BullMQ's worker concurrency option. We can set, say, 5 workers for emails and 20 for the order processing queue.

Dana: Yeah, exactly that.

Priya: Okay, so to summarize — Redis, rate limiter rework with all the bells and whistles in one sentence, and BullMQ for the queue with the retry config and per-queue concurrency.

Carlos: That's it. I'll spec out the rate limiter rework today, Dana takes the BullMQ migration, we sync Friday.

Dana: One more thing — for the BullMQ migration, can we ship it behind a feature flag? I want to be able to fall back to SQL polling if something goes sideways during the cutover.

Carlos: Yes, definitely. Use the existing feature flag service. Default off, flip on per environment.

Priya: Good. Done. Five minutes early.
