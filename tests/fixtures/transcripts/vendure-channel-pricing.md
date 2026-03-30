Meeting: Sprint Planning — Multi-Channel Pricing
Date: February 4, 2026
Attendees: Priya (Backend Lead), Marcus (Senior Engineer), Dana (Product Engineer)

Priya: Alright, so the main thing today is pricing across our three channels — default, EU, and APAC. Price updates in one channel aren't syncing to the others and merchants are confused.

Marcus: Yeah so the thing to know is that prices aren't on the variant itself. Each variant has separate `ProductVariantPrice` records per channel. When you look up a price, the `ProductVariantService` resolves the right one for the active channel and currency.

Dana: And the default sync strategy only syncs prices with the same currency code. Our EU channel is EUR, APAC is SGD, default is USD. So turning on `syncPricesAcrossChannels` does nothing for us because the currencies differ.

Priya: Right. So we need a custom `ProductVariantPriceUpdateStrategy`.

Marcus: The interface has `onPriceCreated`, `onPriceUpdated`, `onPriceDeleted`. Each gets the affected price and all prices for that variant. You return the updated prices and the framework persists them.

Dana: Where do we get conversion rates? I'd rather not hardcode them. The strategy extends `InjectableStrategy`, so we can inject a service.

Priya: Good. But there's a tax subtlety. Each channel can have a different `defaultTaxZone` and the `pricesIncludeTax` flag. If both channels include tax but with different zones, you can't just do a naive currency conversion. You'd need to strip tax, convert, then reapply the destination zone's rate.

Marcus: So we'd need the `TaxRateService` to get the applicable rate for the variant's tax category in each channel's zone.

Dana: And channels can support multiple currencies. The EU channel might have EUR and GBP. So our strategy needs to iterate per currency within each channel, not just per channel.

Priya: That's a lot of price records. For 5,000 variants across 3 channels with 2 currencies each, that's 30,000 records. Make sure the conversion lookups are batched.

Marcus: The `createOrUpdateProductVariantPrice` method handles the upsert logic — if a price for that variant, channel, and currency exists it updates, otherwise creates. So our strategy just returns the right values.

Priya: Marcus, prototype this sprint. Start with a static rate table, we'll swap in the live service later. Write integration tests against a multi-channel fixture with at least two currencies per channel.

Dana: I'll update the Admin UI to surface what exchange rates are being applied. Custom field on Channel should work.

Priya: Perfect. Reconvene Thursday.
