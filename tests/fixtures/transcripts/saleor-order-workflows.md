Meeting: Sprint Planning — Fulfillment Flow Bugs
Date: February 5, 2026
Attendees: David (Backend Engineer), Anya (Ops Lead), Carlos (Warehouse Integrations), Priya (Backend Lead)

David: Let's go through the fulfillment issues. The main problem is that the transition from unfulfilled to fulfilled isn't handling warehouse allocation rollbacks when a fulfillment fails midway.

Anya: Right. So the order has its status — unfulfilled, partially fulfilled, fulfilled, returned, all that. And then each Fulfillment has its own status. The two are supposed to stay in sync but they're updated independently.

Carlos: The warehouse side is where it falls apart. When `orderFulfill` runs, it creates fulfillment lines, then calls `decrease_stock` to reduce quantities and clean up allocations. The problem is those happen in sequence — if `decrease_stock` succeeds but something blows up before the allocations get cleaned, you get orphaned allocation records.

David: Exactly. And since `available_quantity` on a Stock record is calculated as quantity minus allocations, orphaned allocations mean we're double-counting the reduction. The system thinks we have less stock than we do.

Anya: I pulled the numbers. 47 cases in the last 30 days where allocations stuck around after fulfillment completed. Stock quantities were correct but allocations were still sitting there.

Priya: That's not trivial. What's the fix?

Carlos: Wrap the stock decrease and allocation cleanup in a single transaction. Right now they're separate operations. `transaction.atomic` would do it.

David: I also want to bring up the webhook timing. The `FULFILLMENT_CREATED` webhook fires before the stock operations complete. So a downstream system that gets the webhook and immediately queries the order could see stale stock data.

Anya: We should defer webhook dispatch to after the transaction commits. Django's `on_commit` hook.

Carlos: There's another thing — the `orderFulfill` mutation allows partial fulfillment across multiple warehouses, but the warehouse selection doesn't optimize. An order could ship from three warehouses when two would've been enough.

Priya: That's an optimization. Let's focus on correctness first — the transaction fix and webhook timing. Optimization next sprint.

David: One more — `orderMarkAsDelivered` updates the fulfillment status but doesn't trigger stock reconciliation. If something's marked delivered but actually returned, stock never gets replenished until someone manually calls the return mutation.

Anya: And the return flow has its own bug. I've seen orders stuck in FULFILLED status even after all fulfillments are returned. The `update_order_status` function checks fulfillment states but doesn't handle the RETURNED status in all branches.

Priya: Can you file that as a specific bug? We should add tests for the full lifecycle — unfulfilled through partially returned through returned. The existing tests only cover the happy path.

David: I'll write those. We should also add a management command to find and clean up orphaned allocations as a safety net.

Carlos: And a database constraint on Stock so quantity can't go negative. Right now `decrease_stock` can produce negative values in a race condition.

Priya: Definitely. Alright — David owns the transaction boundary fix and test coverage, Carlos handles the cleanup command and the stock constraint, Anya takes the webhook timing with `on_commit` plus monitoring. All three for this sprint, we review PRs together before merge.
