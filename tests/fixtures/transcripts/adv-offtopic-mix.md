Meeting: Q2 Operating Review
Date: April 11, 2026
Attendees: Jin (CTO), Lena (Tech Lead), Anya (Product), Sara (Customer Success), Tomás (DevOps), Priya (Backend Lead)

Jin: Welcome to the Q2 OR. We have 60 minutes, lots to cover, let's keep it tight. Anya, OKR review first.

Anya: Right. Headline: we're at 78% on the conversion-rate OKR, 62% on the activation-funnel OKR, and 91% on the customer satisfaction NPS target. The conversion number is the one I'm worried about. We're underpacing.

Jin: Why?

Anya: A few reasons. The competitive pressure from the new entrant in the mid-market segment is real. Also our pricing experiment from March didn't move the needle the way we expected. Marketing thinks we need to revisit the value-prop messaging.

Sara: From the customer side, I'd say the bigger issue is that the prospects who do convert are taking longer to do it. Sales cycle is up about 11 days quarter-over-quarter.

Anya: Yeah, that tracks. We may need to rethink the trial flow.

Jin: Okay. Park the conversion thing — Anya, can you and Sara own a follow-up next week with a proposal?

Anya: Sure.

Jin: Headcount status. Where are we?

Lena: We made the senior backend hire — Marcus starts next Monday. Still looking for the SRE-2 role. We had two finalists last week, one withdrew, the other we're going to make an offer to this Friday.

Jin: Good. The SRE role is critical. Tomás, you're going to need help once Marcus comes in and starts shipping faster.

Tomás: Yeah, the on-call rotation is already brutal with just me and Dana.

Jin: I hear you. Let's get the offer out. Sara, customer escalations?

Sara: Two big ones this week. AcmeCorp had a multi-tenant data leak scare on Tuesday — turned out to be a false alarm, their staging instance was misconfigured on their side, not ours. But it cost us about three hours of incident response time. The other one is GlobeMart — they're churning unless we ship the multi-currency feature by end of May. That's the third time they've raised it.

Jin: Multi-currency. Priya, where are we on that?

Priya: Spec is done, the engineering work is roughly two weeks once we start. Right now it's queued behind the auth middleware refactor.

Lena: Speaking of which — oh, by the way, Priya's going to do the auth middleware refactor next sprint to use JWTs instead of session cookies. Lena flagged it in the SOC2 review and we need it landed before the audit window closes in June.

Jin: Wait, that's the first I'm hearing of that.

Lena: Yeah, came out of the SOC2 prep meeting Tuesday. The auditors flagged the cookie-based session handling as a finding. Priya volunteered to own it.

Priya: It's a small thing, maybe three days. I can fit it in alongside the multi-currency spec work.

Jin: Okay. Document it in the sprint plan so we don't lose track.

Sara: Back on the customer side — GlobeMart is also asking for SAML SSO. We don't currently support it.

Anya: SAML is going to come up more and more from the enterprise tier. We should add it to the pricing matrix as a "request" feature so prospects know it's on the radar.

Jin: Sales enablement, not engineering work. Tag it in the CRM. Tomás, any infrastructure issues?

Tomás: One thing — the staging cluster auto-scaling has been flapping. I'm investigating but I haven't found the root cause yet. It's not impacting customers but it's annoying.

Jin: Time-box it. If you don't find it by end of week, file it as a known issue and move on. The autoscaler was always brittle.

Tomás: Got it.

Jin: Anything else? Hiring? Customers? Roadmap?

Anya: One thing — the marketing team wants us to draft a blog post about the platform architecture. Something for SEO. They asked if engineering could provide a one-pager.

Lena: I can do that. It's basically the architecture diagram from the design partner deck plus a paragraph.

Jin: Great. Last thing — fundraising. We're closing the bridge round next month. I'll send a separate memo. Don't share externally yet.

Anya: Got it.

Jin: Okay, that's the OR. Thanks everyone. Sara and Anya, follow-up on conversion next week.
