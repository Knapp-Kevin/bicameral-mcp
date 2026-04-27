Meeting: Roadmap Sync — Q3 Planning
Date: April 8, 2026
Attendees: Priya (Backend Lead), Jin (CTO), Lena (Tech Lead), Tomás (DevOps)

Jin: Alright, Q3 planning. I want to get the wishlist on the table before we cut anything. Priya, you wanted to start?

Priya: Yeah. So big picture, we should probably look into vector embeddings for search someday. The keyword matching is starting to feel limited for some of our newer customer segments.

Jin: "Someday" being when?

Priya: I don't know, Q4 maybe? It's not blocking anything right now. I just want it on the radar.

Jin: Okay, parking it. Tomás, you had thoughts on the database situation?

Tomás: If infra approves, we'll switch from PostgreSQL to ScyllaDB for the analytics workload. I've been talking to the infra team about it but they're nervous about the operational story.

Lena: Do we have a date for the infra decision?

Tomás: No, they said they'd get back to me "soon." Honestly I'm not holding my breath.

Lena: Okay so that's a maybe. Let's not commit to anything depending on that.

Jin: Right. Park it as conditional. What about Redis? I keep hearing different things.

Priya: We're definitely not going to use Redis here. We looked at it last quarter and the ops complexity wasn't worth it for our scale. The in-memory cache we have is fine.

Jin: Good, that's clear at least. Lena, what about the auth rework?

Lena: We're keeping the existing webhook retry logic for now. There was talk about replacing it with a workflow-based system but the team consensus was that the current implementation works and we have higher priorities.

Priya: Yeah, agreed. Status quo on retry.

Jin: Okay. What else is on the wishlist?

Tomás: Eventually I'd love to see us migrate off the monolith. I know it's been talked about forever. But realistically that's not Q3.

Jin: Not Q3, agreed. It's also not Q4. Maybe 2027 if the customer growth justifies it.

Lena: There's also the GraphQL federation thing that came up in the architecture review. We discussed it but didn't decide anything.

Priya: I think we agreed to revisit it after we see how the storefront API holds up under the spring catalog launch.

Lena: Right, so deferred until we have load data.

Jin: Okay. Last thing — I want us to be more performance-focused going forward. That's a vibes statement, I know, but I want it in the team norms doc.

Priya: Sure. We can add it to the engineering principles page.

Jin: Great. Anything else?

Tomás: One real thing — I do need to know whether we're locking in the current observability stack or whether the Datadog migration is still happening.

Priya: That's a budget question. Let's move it to the next finance review.

Jin: Agreed. Park it. Okay, that's it for today.
