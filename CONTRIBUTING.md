# Contributing

Contributions are welcome from researchers, practitioners, data providers and software developers. You can add a resource, correct a record, improve an example, report a problem or change the dashboard.

## Suggest a resource or correction

Open the appropriate issue and include the resource name, provider, primary-source URL and its concrete relevance to infrastructure research. For a correction, include the existing record ID, the proposed change and supporting evidence. A title match or provider name alone does not establish identity or relevance.

## Submit a pull request

1. Fork the repository and create a branch.
2. Edit the relevant record in `catalog/<type>/`, or add a new JSON file using a unique ID and matching filename. See the complete [examples](docs/examples/) and [schema](schema.md).
3. Preserve original titles, source URLs, identifiers and citations. Supply a descriptive English `title_en`. State uncertain fields explicitly. Do not invent coverage, access terms, performance claims or possible uses.
4. Add primary sources and access dates. Check the exact resource, including version and scope. Do not upload underlying datasets, installers, credentials or private correspondence.
5. Run `make validate test`. For dashboard changes, also run `make test-browser build` and inspect the page.
6. Open a pull request explaining the change and the checks performed.

Direct record edits are welcome. The maintainer reviews evidence, duplicate identity, schema consistency and relevance before merging. New vocabulary values require a definition in the schema and corresponding labels. Discuss incompatible schema changes in an issue first.

## Record types

- **Data:** a dataset or information source with a concrete infrastructure role.
- **Model:** an existing model, with its documented assumptions, inputs and outputs.
- **Platform:** software supporting simulation, model coupling or related infrastructure analysis.
- **Case study:** a documented real-world application, linked to its resources where established.

## Code and documentation

Keep changes focused and include a test when behaviour changes. Use clear English and concrete examples. Follow the [developer guide](docs/development.md). The [code of conduct](CODE_OF_CONDUCT.md) applies to issues and pull requests.

By submitting a contribution, you confirm that you can share it under the applicable repository licence: MIT for code, and CC BY 4.0 for original catalogue content and documentation. Preserve third-party attribution and terms. Contributions retain their authorship in Git history.
