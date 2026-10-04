# User guide

[Open the catalogue](https://omarkammouh.github.io/Data_catalogue_for_critical_infrastructure_research/).

## Search and select

The initial load retrieves the full metadata snapshot. Progress shows how many parts have arrived. Keep the page open until results appear. A failed part produces an error with a reload control, so a partial catalogue is not presented as complete.

Enter words in the search box to search names, English display titles, providers, descriptions and tags. Search tolerates small spelling differences. Use filters to narrow the result by type, infrastructure sector, country, licence, access conditions, format or another available property. Long lists can be searched within their filter.

Selecting several values in one filter normally accepts any of them. For example, selecting two countries includes records associated with either. Selecting a country and a resource type requires both conditions. The “match all” control requires every selected value within that filter. Date and numeric range filters include their endpoints.

Applied filters appear as removable chips. Clear all returns to the whole catalogue. Browser back and forward restore earlier selections. Copy the browser address to share the selection; it refers to the currently hosted snapshot, which can change with later releases.

## Read a record

Use list or table view to browse results. Open a record to inspect its original title, description, provider, access links, source references and dates. The English heading helps discovery; the original title preserves the provider's name for the resource. An interface-language change does not translate every resource description.

Links open the provider's resource or documentation. Check which link is a landing page, API, repository, article or download. Registration, payment and access restrictions belong to the provider. Follow the provider's current terms.

The detail view supports copying a resource citation. Cite both the catalogue version and the actual resources used in your work where appropriate.

## Export and coverage

Export saves the current selection as CSV or JSON metadata, including filter information. Nested properties in CSV may be encoded as JSON. Whole-snapshot compressed downloads are available from [GitHub releases](https://github.com/omarkammouh/Data_catalogue_for_critical_infrastructure_research/releases).

The coverage view shows counts by resource type, sector and data family for the current selection. Records can belong to multiple sectors, so sector counts are not necessarily additive.

## Accessibility and display

Use the theme control for light, dark or system appearance. Press `/` to focus search. Navigate controls with Tab; arrow keys move between result cards and Enter opens a record. Escape returns from a detail view. Filters use a panel on small screens. Reduced-motion preferences are respected.

## Troubleshooting

If loading fails, check the connection and reload. When serving locally, use an HTTP server through `make serve`; the split build cannot load its parts by opening `index.html` directly. If a provider link fails, report the record ID and URL using the broken-link issue form. A link that works on one network may be restricted on another.
