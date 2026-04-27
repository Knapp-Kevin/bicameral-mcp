Meeting: Architecture Sync — Webhook Queue Choice
Date: April 12, 2026
Attendees: Carlos (Platform), Dana (SRE), Wei (Backend), Priya (Backend Lead)

Carlos: Quick decision today. We need to pick the queue backend for the new webhook delivery service. Wei drafted three options.

Wei: Yeah. So the three are: Redis Streams, BullMQ, and AWS SQS. I have a doc with the pros and cons.

Carlos: My initial take is Redis Streams. We already have Redis in the stack for the rate limiter, the consumer group semantics give us at-least-once for free, and we don't add another dependency.

Wei: That was my first instinct too. Streams is the cleanest fit on paper.

Dana: Let's go with Redis Streams then.

Carlos: Okay, decided. Let's do Redis Streams for the webhook queue.

Priya: Hold on. Dana, didn't infra block Streams last quarter?

Dana: Oh — yeah, you're right, I forgot. There was a moratorium after the consumer-group incident with the analytics team. Sorry, I should have flagged that earlier.

Carlos: Right, I remember now. So Streams is off the table.

Wei: Then BullMQ? It's also Redis-backed but not under the moratorium because it uses regular lists and sorted sets.

Carlos: Actually, I just remembered we got pushback from the infra team on running BullMQ in our Redis cluster too. They want job queues isolated from cache workloads to avoid memory pressure.

Dana: That's news to me. When was that?

Carlos: Two weeks ago. The platform-infra sync. They said any new job-queue workload should go on AWS-managed infrastructure, not our self-hosted Redis.

Wei: So neither Redis option is viable. That leaves SQS.

Carlos: Yeah. Let's go with SQS for the webhook queue.

Priya: SQS gives us managed retries, dead letter queues built in, and we don't have to worry about the Redis isolation issue. I'm fine with it.

Wei: Same. Costs are fine at our volume.

Dana: Wait — one consideration. SQS has visibility timeout semantics that are a little different from how BullMQ handles in-flight jobs. We need to make sure the worker shutdown handling is correct so we don't double-deliver.

Wei: Right. We'd set the visibility timeout to something like 5 minutes, set the max receive count to 6, and use a dead-letter queue for anything that exceeds that.

Carlos: Five-minute visibility timeout, six max receives, DLQ on overflow. That works.

Priya: And what about ordering? Some webhook events need to be delivered in order — like order.placed before order.fulfillment_created.

Wei: SQS standard isn't FIFO. We'd need SQS FIFO for that. But FIFO has lower throughput limits — 300 messages per second per group, or 3,000 with batching.

Carlos: Hmm. Per-merchant ordering or global ordering?

Wei: Per-merchant. Different merchants don't need ordering between each other.

Carlos: Okay so we use FIFO with the merchant ID as the message group ID. That gives us per-merchant ordering and the throughput limits should be fine because each merchant's traffic is way below 300/s.

Wei: Right.

Priya: So the final decision is SQS FIFO, message group keyed on merchant ID, 5-minute visibility timeout, 6 max receives, dead-letter queue on overflow.

Carlos: That's it. Wei, can you write up the final design and link the AWS docs in the spec?

Wei: Will do. Want me to delete the Redis Streams and BullMQ sections from the doc or keep them as "rejected" with rationale?

Carlos: Keep them as rejected. Future me will want to know why we didn't go that way.

Priya: Good. Done.
