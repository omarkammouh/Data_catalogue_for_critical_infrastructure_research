# Scope and methods

## Purpose and unit of description

The catalogue describes resources that can support infrastructure research and simulation. A record represents a dataset or information source, an existing model, a simulation platform, or a documented case study. The catalogue stores metadata and access links. It does not redistribute underlying datasets or executable model packages.

Scope covers energy, water, transport, digital infrastructure, the built environment, services, industry and cross-cutting infrastructure topics. Geographic coverage is global and resources may be in any language. Supporting resources qualify when source material establishes a concrete infrastructure role. A provider's name or a broad sector tag alone does not establish that role.

## Discovery and source evidence

Discovery uses provider catalogues, national and institutional portals, scientific publications, data repositories, software repositories and cross-references from existing resources. Searches combine infrastructure subjects with resource types and uses. Original-language descriptions and local terminology help locate resources outside English-language sources.

Primary provider pages, repository metadata and documentation supply evidence for descriptions, identifiers, access conditions and coverage. Each record carries source URLs and access dates where available. Discovery routes describe how a resource was located. They are distinct from the sources supporting its metadata.

Descriptions summarise the resource's contents, producer, coverage, format, access conditions and documented limitations. Potential simulation uses recorded as interpretations should be treated as such. Unstated or uncertain properties remain explicit. Neither a working link nor a familiar title establishes the accuracy of all associated metadata.

## Identity, classification and relationships

Stable IDs identify catalogue records. Original resource titles remain in `name`; `title_en` provides a descriptive English heading. Display titles are aids to discovery, not substitutes for source identity.

DOIs, canonical repository addresses, provider identifiers and resource scope support duplicate comparisons. Similar names alone are insufficient to establish that two entries represent the same resource. Related resources may legitimately share a provider or portal.

Controlled vocabularies classify sector, resource type, location, format and other attributes. A resource may span several sectors. Cross-references connect models, data, platforms and applications where the metadata establish a relationship. Vocabulary definitions are in [the schema](../schema.md).

## Checks and publication

The validator checks JSON structure, controlled values, IDs, required description elements and record references. These checks test metadata consistency; they do not execute models or test the contents of linked datasets. Dated link observations describe access at the time of observation.

A release fixes a snapshot of the record files. Its record counts, capture date and checksums support reproducibility. Public preparation removes internal working references and retains substantive resource evidence. Each later release records changes in the changelog.

## Dashboard

The dashboard derives filters from the released records and vocabularies. Values within one filter combine with OR by default, with an optional AND mode. Different filters combine with AND. An inverted index supports filtering and a trigram index supports text search. Shared URLs encode the selected filters and view.

The coverage view counts the records in the current selection. Multi-sector records may contribute to several counts. These counts describe this catalogue; they do not estimate the total population of resources that exists elsewhere.
