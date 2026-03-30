Meeting: Sprint Planning — Custom Fields Rollout
Date: February 3, 2026
Attendees: Lena (Tech Lead), Raj (Full-Stack), Sofia (Frontend), Tomás (DevOps)

Lena: Today we need to plan the custom fields rollout. Marketing wants a `loyaltyPoints` integer on Customer, a `brandStory` localeText on Product, and a `hazmat` boolean on ProductVariant.

Raj: Vendure's `CustomFieldConfig` handles most of this declaratively. You define everything in the `customFields` property of `VendureConfig`. For loyaltyPoints it'd be type `int`, min zero, default zero.

Sofia: And `brandStory` as `localeText` means it supports translations per language, right? Stored in the translation table, not the main entity table?

Raj: Yeah, that's automatic. The GraphQL schema picks it up at startup too — `Product.customFields.brandStory` becomes queryable, and you get filter and sort inputs for free.

Sofia: Marketing wants a rich text editor for brandStory though, not a plain textarea.

Lena: Set the `ui` property to `{ component: 'rich-text-form-input' }`. That's one of the built-in custom field components.

Tomás: What's the migration story? Adding columns with `nullable: true` is fine, but non-nullable needs backfill.

Raj: LoyaltyPoints should be non-nullable with default zero — TypeORM handles the column with a DEFAULT constraint. Hazmat is non-nullable, default false. BrandStory can be nullable since not every product has one.

Lena: Run `schema:synchronize` in staging first. Custom field changes trigger TypeORM schema sync which can be destructive if you have manual schema modifications.

Tomás: Got it. I'll add a staging validation step to the CI pipeline. What about the `struct` type? Looks useful for complex data.

Raj: It stores JSON with defined sub-fields. But here's the thing — it's just `simple-json` in the database. No SQL-level querying or indexing on sub-fields. If you need to filter on a nested value, don't use struct.

Lena: For hazmat, there's actually a follow-up request to link each hazmat variant to a compliance document. That's where the `relation` type custom field comes in.

Sofia: How does that work in mutations? I remember the input naming being weird.

Raj: Yeah, when you query you get the full object via `customFields.complianceDocument`, but the input field is `customFields.complianceDocumentId`. For list relations it's `complianceDocumentIds`, plural. List relations create a junction table, singular ones add a foreign key.

Lena: And for loyaltyPoints, we should set `readonly: true` so storefront can display it but can't mutate it. `brandStory` same thing — public and readable but only editable from Admin.

Sofia: Good catch.

Raj: We should also add TypeScript declaration merging for type safety. Extend `CustomProductFields` and `CustomCustomerFields` interfaces from `@vendure/core`.

Lena: Alright — Raj handles the config changes and migration testing, Sofia customizes the Admin UI for brandStory, Tomás updates the deployment pipeline. I'll write the ComplianceDocument entity for the relation field. PR reviews by Wednesday.
