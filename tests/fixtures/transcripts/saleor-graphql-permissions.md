Meeting: Sprint Planning — Channel-Scoped Permissions
Date: February 6, 2026
Attendees: Priya (Backend Lead), Tomasz (API Engineer), Lena (Security), Marco (Frontend)

Priya: Alright, the permissions rework. The core problem is that permissions are global right now. If someone has MANAGE_ORDERS, they can touch orders in every channel. That's not gonna work with 14 multi-channel tenants.

Tomasz: Yeah. The permission groups just use Django's auth system, and the `@permission_required` decorator on mutations checks whether the JWT includes the right permission string. Zero awareness of which channel the resource belongs to.

Lena: Nine of those tenants have filed requests for channel-scoped permissions. The JWT payload is just a flat list of codenames — like `order.manage_orders`. No channel context at all.

Marco: From the frontend side, when we call `productCreate` we pass the channel slug in the input, but the resolver only checks that you have `MANAGE_PRODUCTS` globally. Same with `orderUpdate`. The channel argument is there for business logic but nobody checks authorization against it.

Priya: So we need to extend the permission checking. Tomasz, how does the resolver flow work right now?

Tomasz: Take `productCreate`. The mutation class declares a `permissions` attribute, the base mutation calls `check_permissions` during dispatch, and that hits `effective_permissions` from the JWT or from the user's groups in the database. That's it. No channel in the picture.

Lena: So `check_permissions` is our interception point. We could add a channel mapping to the JWT — instead of a flat `"order.manage_orders"`, the claim becomes a dict mapping to specific channel slugs, or `["*"]` for global.

Priya: I like it. But existing tokens with the flat format need to keep working. Flat string should be treated as equivalent to all channels.

Tomasz: Agreed. For something like `orderUpdate`, the order already has a channel foreign key, so we can resolve the channel from the instance and check against the scoped permissions.

Marco: What about `checkoutComplete`? That triggers a bunch of side effects — creates the order, processes payment, fires webhooks. The permission check needs to happen early, before any of that.

Lena: Yeah, definitely gate on the checkout's channel before calling `checkout_complete`. We can't have a half-created order because the permission check failed late.

Priya: We also need to scope the App permission model. Third-party apps should only access channels they're installed for. We could add a channel_access relationship on the App model.

Tomasz: And on the query side — the `products` resolver filters by channel for storefront visibility, but staff users can see products from any channel through the dashboard API. That's a separate authorization gap.

Marco: Can we add metrics on how many API calls would be affected?

Priya: Good idea. Tomasz, draft an RFC for the JWT structure and the modified `check_permissions` flow. Target is feature branch by end of sprint with migration scripts to default existing permission groups to all-channel access. Lena handles security review, Marco coordinates the dashboard UI for channel-scoped assignment. Let's sync Thursday.
