Meeting: Sprint Planning — Plugin Migration
Date: February 3, 2026
Attendees: Jun (Platform Architect), Elena (Senior Backend), Marcus (Developer Experience), Priya (Backend Lead)

Jun: Alright so the big thing this sprint — we need to start moving our plugins to v2 modules. The PluginManager is getting fully deprecated and we've got seven plugins in prod.

Elena: Seven, yeah.

Jun: So we need a plan. Elena, what actually breaks?

Elena: Basically everything about how a plugin gets loaded. In v1 the PluginManager just scans your directories, finds services, subscribers, routes — registers it all with the awilix container automatically. In v2, none of that exists. You export a class with the `@Module` decorator and you're responsible for wiring everything yourself.

Marcus: The service base class is different too. You extend `AbstractModuleService` instead of `TransactionBaseService`. Which honestly is nicer — if you define your models with the `model.define` utility you get CRUD for free. But it's still a rewrite.

Priya: What about DI? We inject services by name in the constructor everywhere — like `constructor({ productService, manager })`. Is that the same?

Elena: Kind of. Awilix is still there under the hood, but scoping is way tighter. You can't just reach into another module's internal services anymore.

Jun: That's the biggest breaking change honestly. Our fulfillment plugin directly imports `OrderService` from core. Can't do that. In v2 you go through the `Modules` registry and resolve by name.

Priya: Okay, that's going to be a thing.

Jun: Yeah.

Marcus: But the really painful part is subscribers. In v1 you just drop a class in the `subscribers/` folder and it auto-registers. In v2 that whole pattern is gone — subscribers become workflows. You use `createWorkflow` and `createStep`, bind it to an event. It's fundamentally different.

Elena: And it's not a mechanical conversion. I did the inventory-sync subscriber last week and it took a full day because the original had side effects that don't fit the step model. Workflows have retry and compensation built in, so you have to actually rethink the logic.

Priya: Great. So how much of this is just... grunt work?

Elena: A lot. Per plugin it's roughly — convert the service, convert subscribers to workflows, convert the API routes to the new handler pattern, move the config from `plugins` to `modules` in the config file, regenerate migrations. Five steps, each one non-trivial.

Marcus: Step zero is auditing dependencies. Figure out which core services each plugin touches and map them to the v2 module equivalents. Our fulfillment plugin alone hits three different core services.

Jun: Okay let's split these up. Elena, fulfillment and inventory — they're the most complex. Marcus, notification and webhook. I'll do pricing and loyalty. Priya, search?

Priya: Sure. The search plugin mostly wraps the `AbstractSearchService` — does that survive?

Elena: It's a module type now. Same methods basically — `createIndex`, `addDocuments`, `search` — but different class structure.

Marcus: One thing — should we keep backward compat for the v1 API routes? Some storefront clients haven't updated.

Jun: Yeah, run both in parallel for one release cycle. Use the `middlewares.ts` pattern to register the legacy routes alongside the new ones. Let's target end of sprint for first two migrations each with integration tests passing. Check in Wednesday.
