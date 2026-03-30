Meeting: Sprint Planning — Search Index Performance
Date: February 6, 2026
Attendees: Carlos (Platform Lead), Wei (Backend), Aisha (SRE), Marcus (Senior Engineer)

Carlos: Last night's full reindex of 12,000 variants took 40 minutes and pegged the database at 95% CPU. The spring catalog launch is adding another 8,000 variants so we need to fix this now.

Wei: So the `DefaultSearchPlugin` maintains a denormalized `search_index_item` table. Every product or variant change fires an event that triggers an index update through the job queue.

Marcus: And the job queue is the first problem. The `SqlJobQueueStrategy` polls the database every 200 milliseconds per queue. With all the queues we're running — search updates, collection filters, emails — the polling alone generates hundreds of queries per second.

Carlos: Have we considered `BullMQJobQueuePlugin`? That's Redis-backed, push-based instead of polling.

Wei: I looked at it. BullMQ would solve the polling overhead, but the real bottleneck is the reindex itself. When you trigger a full reindex, it iterates through every variant, loads all its relations, and upserts into the search table. It's basically N+1 queries.

Aisha: What about `bufferUpdates`? If we enable that on the search plugin, individual changes don't immediately trigger index updates. They buffer and you flush them manually.

Wei: That's what I was going to propose. The buffer de-duplicates by entity ID. So if a variant gets updated five times during a bulk import, it only gets reindexed once when you flush. That's a huge win for the nightly catalog sync — right now every CSV row triggers a separate index update.

Carlos: Nice. What about collection filters? That's the other thing that kills us.

Marcus: When a collection's filters change, the system re-evaluates every variant against every collection. We have 85 collections with dynamic facet-based filters. Updating a facet value on a product cascades into collection re-evaluation, which cascades into search index updates.

Aisha: That's the one that really hurts.

Carlos: Should we look at ElasticsearchPlugin as an alternative?

Wei: It replaces the DefaultSearchPlugin entirely — you can't run both. The index lives in Elasticsearch instead of the database, which offloads the query pressure. Better full-text search too. But it adds operational complexity.

Aisha: We could use a managed Elasticsearch service. Even without that, just getting the index writes out of the primary database would help a lot.

Marcus: We should also split the workers. Right now one worker handles everything — search indexing, emails, collection filters. We could dedicate one worker to search using the `activeQueues` option and let another handle everything else. That way reindex doesn't block order confirmation emails.

Aisha: Here's my proposal. Short-term: enable `bufferUpdates`, switch to BullMQ, split into two workers. That gets us through the spring launch. Long-term: evaluate Elasticsearch next sprint.

Carlos: What metrics should we track?

Aisha: Reindex duration, database CPU during reindex, job queue depth, and p95 search latency. Right now search queries take 800ms at p95 during reindex because the database is saturated. Target should be under 200ms.

Carlos: Good. Wei takes the buffer config and BullMQ migration, Marcus sets up the dual-worker deployment, Aisha instruments the metrics. We'll review Elasticsearch next sprint once we have baseline numbers.
