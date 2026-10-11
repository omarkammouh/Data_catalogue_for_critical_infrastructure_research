# Visitor statistics

The dashboard supports Cloudflare Web Analytics for aggregate visits and page views, countries, referral sites, device types and browsers. Statistics are viewed privately in the owner's Cloudflare account. This does not identify visitors by name or email. Counts start after activation; older visits cannot be reconstructed by this integration. Browser blocking and privacy preferences can reduce the recorded totals.

## Account and configuration

The public site identifier is configured. Statistics are available only to the owner through the Cloudflare account, under Web Analytics. The catalogue remains publicly accessible.

## Activation

In Cloudflare, open **Web Analytics**, add `omarkammouh.github.io` as a site and copy the public site token from its JavaScript installation snippet. Put that 32-character token in `SITE_TOKEN` in `src/analytics.js`, in both maintained repositories, then rebuild and publish. This public identifier belongs in the browser; do not use a Cloudflare API key or API access token. An empty token disables analytics completely.

The script runs only on the HTTPS public catalogue path. Local previews, downloaded copies and other websites do not send visits. It respects Do Not Track and Global Privacy Control. Automatic single-page navigation measurement is disabled, so changing searches, filters or views does not count as another page load. This integration does not send custom search or resource-click events.

The external script loads asynchronously. The catalogue works if that script is blocked or unavailable. When configured, the footer links to Cloudflare's explanation of its analytics. Cloudflare describes the service as privacy-first and says it does not collect or use visitors' personal data. This statement describes the provider's service, not a guarantee that every visit is counted or that visitors can be identified.

## Checks

Run `node --test tests/analytics.test.cjs` from the dashboard directory. These tests use a simulated browser document and never send analytics. After activation, check the live page and confirm an incoming visit in the Cloudflare account before reporting collection as working.

Website-only changes are bundled into the next Zenodo archive. The same public-host restriction remains in archived source, so opening an archived copy does not report visits.

## Provider documentation

Checked 11 October 2026:

- [Service and privacy overview](https://developers.cloudflare.com/web-analytics/about/)
- [Site setup](https://developers.cloudflare.com/web-analytics/get-started/)
- [Available dimensions](https://developers.cloudflare.com/web-analytics/data-metrics/dimensions/)
- [Disable automatic SPA measurements](https://developers.cloudflare.com/web-analytics/get-started/web-analytics-spa/)
