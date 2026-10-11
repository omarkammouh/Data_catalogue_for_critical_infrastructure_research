# Catalogue schema

The catalogue is a metadata registry, not a data store. Nothing is downloaded. Every record keeps the links needed to obtain the resource later.

## Four record types

| Type | What it covers | Examples |
|---|---|---|
| `data` | Datasets and information sources describing infrastructure assets, networks, demand, hazards and performance | OpenStreetMap power lines, HIFLD, Copernicus DEM, national road registers, utility outage records |
| `model` | Existing analytical or numerical models of infrastructure behaviour, published as code, packaged software or documented methods | PyPSA, pandapower, EPANET, MATSim, SUMO, fragility curve libraries, OpenSees |
| `platform` | Simulation platforms and frameworks that host or couple models, run scenarios or provide digital-twin environments | OpenDSS, GridLAB-D, CityGML tooling, Modelica environments, HAZUS, coupled multi-sector frameworks |
| `case_study` | Documented real-world applications to infrastructure: where, why, against which hazards, with what outcome, and using which data, models and platforms (added 2026-09-24, user decision) | Climate-ADAPT case studies, a national agent-based transport model in operational use, the IN-CORE Galveston testbed, a utility's climate-proofing study for a major project |

Records of different types link to each other: a platform lists the models it runs, a model lists the datasets it consumes or was validated on, a dataset lists the models or platforms known to use it, and a case study lists the data, models and platforms it used (`resources_used`), so each tool shows where it has been applied.

## Shared fields (all types)

| Field | Notes |
|---|---|
| `id` | Stable slug, for example `data-osm-power-grid` |
| `type` | `data`, `model`, `platform` or `case_study` |
| `name` | Original resource title, preserved in its original language |
| `title_en` | Descriptive English display title based on the resource metadata, supplied for every new record. Optional in the JSON schema for legacy imports. Shown above the original `name`; searched and exported alongside it. Keep identity and deduplication tied to `name`, not this editorial title. |
| `provider` | Publisher, maintainer or organisation |
| `description` | One hundred to three hundred words of plain prose: contents, producer and purpose, coverage and resolution, format and access, licence and cost, caveats, simulation uses, related records |
| `homepage` | Landing page. Absolute HTTP(S) URL with a valid host and port and no whitespace. The JSON schema uses the catalogue's `http-url` format; original Unicode paths and provider query strings are preserved. |
| `access_links` | List of `{label, url, kind, note}` where kind is `download`, `api`, `repo`, `docs`, `paper`, `portal`, `viewer`, `contact`. URLs use the same `http-url` rule as `homepage`; API templates such as `/tiles/{z}/{x}/{y}` are allowed. A template is an endpoint description, not a verified concrete request. |
| `licence` | SPDX identifier where possible, otherwise free text |
| `licence_type` | Optional controlled licence type for the dashboard filter, a list from `pipeline/vocab/vocabulary.yaml` (added 2026-09-29, proposed) |
| `cost` | `free`, `freemium`, `paid`, `on_request`, `unknown` (use when the source does not establish feed-use charges) |
| `access_restrictions` | `none`, `registration`, `institutional`, `restricted`, `on_request`, `unknown`; details in `access_note` |
| `sectors` | List of two-level values from the sector hierarchy below, for example `energy.electricity`. Use the top level alone only when a resource spans the whole group |
| `geographic_scope` | `global`, `continental`, `national`, `regional`, `city`, `site` plus named areas; `unknown` when the source does not establish the geographic extent (added 2026-10-08) |
| `countries` | ISO 3166 alpha-2 codes where applicable |
| `simulation_uses` | List: `network_flow`, `cascading_failure`, `hazard_exposure`, `resilience`, `capacity_planning`, `agent_based`, `optimisation`, `digital_twin`, `emergency_response`, `climate_adaptation`, `water_quality` (chemical equilibria, contaminant concentrations, treatment or residence time in water infrastructure; added 2026-10-08 from EPA model metadata), `energy_system_planning`, `building_energy_performance`, `port_sedimentation`, `transport_emissions` (source-defined model uses added 2026-10-08; definitions below), `structural_design` (added 2026-10-09; definition below), `communication_system_performance` (added 2026-10-09; definition below), `building_hygrothermal_performance` (added 2026-10-09; definition below), `demand_forecasting` (added 2026-10-09; definition below), `life_cycle_assessment` (added 2026-10-09; definition below), `condition_monitoring` (added 2026-10-09; definition below), `power_quality` (added 2026-10-09; definition below). An empty list records that no specific use is established in inspected metadata; see the unknown-use rule below. |
| `maturity` | `active`, `maintained`, `stale`, `archived`, `unknown` |
| `last_updated` | Date of the resource, if known |
| `date_catalogued` | Date the record was added |
| `date_verified` | Date links were last checked; `null` when no link check is established. Reviewing saved metadata does not set a verification date. |
| `related_ids` | Links to other catalogue records |
| `tags` | Free keywords |
| `notes` | Quality remarks, known gaps, caveats |
| `sources` | Where the metadata came from: list of `{url, accessed, note}` |
| `discovery_routes` | Every route class (`R01` to `R51`, see `schema/vocab.yaml`) and source that found the record, with the query and date; drives the completeness metrics |
| `dedupe_keys` | Normalised `url`, `doi`, `repo` and `name` used by the deduplicator. Optional `exclude` lists reviewed supporting keys (`url`, `doi`, `repo`) that do not identify this resource. It suppresses explicit and automatically derived values for those keys. Explain the source-defined supporting role in `notes` and retain the links and individual native identifiers in the evidence. A shared catalogue page must not become the identity of each member (added 2026-10-09). |
| `languages` | ISO 639 codes of the resource's metadata and content; empty when not established. The language of our English description does not establish the source language. |
| `description_checked` | Date the description was checked against the source for the required content elements |
| `continents`, `countries`, `regions` | Continents from `africa`, `asia`, `europe`, `north_america`, `south_america`, `oceania`, `antarctica`; ISO 3166 alpha-2 codes; named subnational areas or cities |
| `link_health` | Result of the last link check, written by `pipeline/linkcheck.py`: `checked` (date), `dead` (URLs answering 404 or 410), `dead_since`, `wayback` (archived snapshot of a dead link), `unverified` (URLs that produced no definitive result at that check, for example hosts the checking environment could not reach). Every result is logged in `sources/linkchecks.jsonl` |
| `access_note` | Free text on how access works when it is not simply open |
| `hazards` | Optional on every type, expected on case studies: hazard types the resource addresses, from `flood`, `coastal_flood_storm_surge`, `sea_level_rise`, `drought`, `extreme_heat`, `cold_snow_ice`, `storm_wind`, `hail` (added 2026-09-26), `wildfire`, `earthquake`, `landslide`, `tsunami`, `volcanic`, `space_weather`, `cyber_attack`, `physical_attack_sabotage`, `pandemic`, `technological_failure`, `multi_hazard_climate_change` |

## Derived dashboard fields

Dashboard builds add missing `data_resource_type` values under the documented conservative representation rules and export `data_resource_type_basis` as the reason. Source-record classifications take priority.

Dashboard builds add `catalogues` (a list of stable source-catalogue IDs) and
`catalogue_membership_evidence` (evidence strings grouped by catalogue ID).
These fields are derived from saved discovery routes and reviewed mappings;
they are not required in source records. A record may belong to several
catalogues. Empty membership means the available evidence has not established
a catalogue group. It does not exclude the resource from the inventory.
Definitions and maintenance rules are in [dashboard/README.md](dashboard/README.md#catalogues).

## Type-specific fields

### `data`

| Field | Notes |
|---|---|
| `catalogue_index_id` | Optional stable source catalogue ID represented by a `data_catalogue` record. Enables navigation to individually listed members; it does not assert membership of the catalogue record in itself. |
| `data_resource_type` | Optional `dataset`, `data_catalogue`, `information_source` or `unknown`. A data catalogue indexes or links to multiple resources and can include subjects outside our scope. It is distinct from membership in `catalogues`. Explicit values take priority. In the dashboard, legacy records with a structured data representation and no document or catalogue/standards/planning family are labelled `dataset`; document-only records are `information_source`; other records stay `unknown`. This metadata classification does not establish current availability or complete inventory coverage. |
| `data_family` | List of values from the data family vocabulary below, by the role the data plays in a simulation |
| `data_kind` | `asset_inventory`, `network_topology`, `time_series`, `raster`, `tabular`, `survey`, `event_record`, `document`, `stream`, `imagery`, `unknown` (source metadata does not establish a listed representation; added 2026-10-09) |
| `formats` | GeoJSON, Shapefile, CSV, NetCDF, GeoPackage, API JSON, and so on |
| `spatial_resolution` | Free text or numeric with unit |
| `spatial_resolution_class` | Optional controlled form of `spatial_resolution` for the dashboard filter, from `pipeline/vocab/vocabulary.yaml` (added 2026-09-29, proposed) |
| `spatial_resolution_m` | Optional structured form for the dashboard's range facet: finest ground resolution in metres (added 2026-09-26) |
| `temporal_coverage` | Start and end, or snapshot date |
| `temporal_coverage_years` | Optional structured form for the range facet: `{start: year, end: year or null}`, `null` while the resource is still extended (added 2026-09-26) |
| `temporal_resolution` | Hourly, daily, annual, none |
| `temporal_resolution_class` | Optional controlled form of `temporal_resolution` (the dashboard's time step filter), from `pipeline/vocab/vocabulary.yaml` (added 2026-09-29, proposed) |
| `crs` | Coordinate reference system if spatial |
| `size` | Approximate, if published |
| `size_bytes` | Optional structured form for the range facet: total size in bytes as the provider states it (added 2026-09-26) |
| `schema_summary` | Key attributes available |
| `update_frequency` | How often the source refreshes |

### `model`

| Field | Notes |
|---|---|
| `model_kind` | `physical`, `statistical`, `agent_based`, `network`, `optimisation`, `fragility`, `economic`, `hybrid`, `discrete_event` (queueing and process simulation driven by events in time, added 2026-09-26) |
| `language` | Python, Julia, C++, MATLAB, and so on (also allowed on `platform` records, user decision 2026-09-30) |
| `inputs` | Data the model needs |
| `outputs` | What it produces |
| `validated_on` | Datasets or cases it has been validated against |
| `repository` | Code location |
| `citation` | Reference paper or DOI |
| `runs_on` | Platform record ids, if any |

### `case_study`

| Field | Notes |
|---|---|
| `case_study_kind` | Purpose: `risk_vulnerability_assessment`, `adaptation_planning`, `design_retrofit`, `operations_control`, `emergency_response_evacuation`, `post_event_analysis`, `recovery_restoration`, `investment_appraisal`, `policy_evaluation`, `testbed_demonstration` |
| `resources_used` | Record ids of the data, models and platforms used; names where a resource is not catalogued yet (each such name is a candidate) |
| `outcomes` | What the study found or achieved, in a sentence or two |
| `study_period` | Year or range of the study or project |
| `organisations` | Organisations that carried out or commissioned it (the `provider` is the publisher of the case-study page) |

Place is given by the shared fields `geographic_scope`, `countries` and `regions`; hazards by `hazards`; sectors by `sectors`.

### `platform`

| Field | Notes |
|---|---|
| `platform_kind` | `simulation_engine`, `coupling_framework`, `digital_twin`, `gis_environment`, `cloud_service`, `modelling_suite`, `data_preparation_tool` (a tool whose job is to assemble a model's inputs from public data, added 2026-09-26) |
| `hosted_models` | Model record ids or names |
| `interfaces` | GUI, CLI, API, co-simulation standards such as FMI or HELICS |
| `deployment` | Desktop, server, cloud, web |
| `language` | Programming language of the software, same vocabulary as on `model` (allowed on platforms since 2026-09-30) |
| `open_source` | Boolean when established; `null` when source-code availability is unknown (added 2026-10-09). An open deposit or reuse licence alone does not establish availability of source code. |
| `supported_sectors` | Same vocabulary as `sectors` |
| `interoperability` | Standards and formats it reads or writes |

## Sector hierarchy

Two-level values written `group.sector`. Every group and sector is in scope. Add a sector here before using it.

### Inclusion boundary confirmed on 3 October 2026

The user confirmed the systems listed below as the inclusion scope. A resource must describe, model, operate or provide evidence about one of these systems, or provide a source-supported input to its simulation. Weather, population, terrain and governance resources can qualify where their simulation role is concrete. General subject relevance, the publishing organisation and existing sector tags do not establish this role. For example, healthcare service capacity can qualify; clinical drug evidence does not qualify merely because it is health-related. Likewise, an agency's staff travel expenses do not describe the infrastructure it regulates.

The four record types, all countries and languages, and the existing access policy remain applicable. Paid, restricted, on-request and historical resources are not excluded solely for those characteristics. Scope eligibility and record completeness are separate assessments. A confirmed out-of-scope record is logged and archived before removal. Insufficient evidence is recorded as unresolved rather than treated as proof of exclusion. All-entry audits require one assessment per starting record and an exact inventory reconciliation, including removals and any concurrent changes.

The user changed the audit sequence on 4 October 2026: first assess every record from its saved title and description. Investigate external sources only where those fields leave the decision uncertain. A title/description decision does not imply fresh provider verification. Preserve the original identity, field evidence, uncertainty and prior source assessments.

| Group | Sectors |
|---|---|
| `energy` | `electricity`, `gas_hydrogen`, `oil_fuels`, `district_heating_cooling`, `nuclear` |
| `water` | `drinking_water`, `wastewater`, `stormwater_drainage`, `irrigation`, `dams_flood_defences` |
| `transport` | `road`, `rail`, `public_transit`, `aviation`, `maritime_ports`, `inland_waterways`, `pipelines`, `active_mobility`, `logistics_freight` |
| `digital` | `telecom`, `data_centres`, `satellite_positioning`, `broadcasting`, `internet_exchange` |
| `built_environment` | `buildings`, `critical_facilities`, `public_space` |
| `services` | `healthcare`, `emergency_services`, `waste`, `food_supply` |
| `industry` | `manufacturing_chemical`, `mining_materials`, `financial`, `agriculture` |
| `cross_cutting` | `space`, `green_blue`, `multi_sector` |

## Data family vocabulary

The role a dataset plays in a simulation. A record may carry several. Add a family here before using it; a record that fits none is a signal to add one, not to force a fit.

| Group | Families |
|---|---|
| Core | `system_description`, `demand_operation`, `hazards`, `vulnerability_fragility`, `reference_context` |
| Events and lifecycle | `historical_events`, `recovery_restoration`, `condition_ageing`, `interdependencies` |
| Economy and society | `economic_financial`, `governance_regulation`, `behavioural_social`, `social_vulnerability_equity`, `health_impacts`, `security_threat` |
| Flows and services | `supply_chains_logistics`, `cross_border_flows`, `service_performance`, `critical_facilities`, `emergency_management` |
| Physical setting | `resource_potential`, `weather_observations`, `subsurface_geotechnical`, `vegetation_land_cover`, `space_weather`, `environmental_impact`, `imagery_remote_sensing` |
| Assets and technology | `equipment_specifications`, `distributed_flexible_resources`, `planned_future_infrastructure`, `telecom_coverage_spectrum`, `cyber_control` |
| Time and futures | `sensor_realtime_streams`, `scenarios_projections`, `synthetic_benchmark` |
| Meta | `standards_ontologies`, `planning_regulatory_documents`, `catalogues_registries`, `calibration_validation`, `crowdsourced_public_reports` |

## Filter vocabularies

The licence filter includes `conflicting` when reviewed sources disagree on a resource's licence, or specify different terms whose compatibility has not been established. Preserve each source statement and leave the applicable terms unresolved. This differs from `not_stated`, where no usable statement was found, and `varies`, where terms explicitly differ by constituent item (added 2026-10-07).

The free-text fields behind the dashboard filters are licence, formats, update frequency, time step, spatial resolution, programming language, interfaces, deployment and maturity. Each maps onto a short controlled vocabulary in `pipeline/vocab/vocabulary.yaml`, described in `pipeline/vocab/README.md` and confirmed on 2026-09-29. The build applies the mapping to records that still carry free text. `pipeline/vocab_map.py rewrite --apply` wrote (on 2026-09-29, for all 13,279 records) the controlled values into the records: `licence_type` (a list) beside the licence text, `spatial_resolution_class` and `temporal_resolution_class` beside their free text, and the vocabulary values in place of the free text in the other fields. A controlled value stored in a record wins over the mapping.

## Machine-readable source

`schema/vocab.yaml` holds every controlled vocabulary above plus the route classes, route families, cell statuses, coverage priors and candidate statuses. `schema/record.schema.json` holds the structural schema. This document explains them; `pipeline/validate.py` checks that the three agree and that every record passes. Add a value to `vocab.yaml` first, then here, then use it.

## Description standard

The description is one hundred to three hundred words of plain prose. It must state: what the resource contains; who produces it and why; spatial and temporal coverage and resolution; format and access method; licence and cost; known gaps or caveats; which simulation uses it serves; and which other catalogued resources it relates to. The validator checks length and the presence of these elements. Every record carries a full description; there are no partial tiers.

## Storage

Records live as one JSON file per record under `catalog/<type>/<id>.json`. Candidates found by sweeps live under `sources/candidates/` and never in the catalogue until fully described. `pipeline/compile.py` builds `catalog/catalog.json` and a SQLite file for the dashboard. Controlled vocabularies above may grow as records reveal new categories; add a value to this file before using it.

### Source-defined simulation uses added 2026-10-08

- `energy_system_planning`: Source-established modelling of infrastructure energy production and consumption across an explicit territorial or system scenario, including model inputs or outputs used to plan energy-system transitions.
- `building_energy_performance`: Source-established calculation or simulation of energy use and associated performance in buildings from physical building characteristics and equipment; includes explicitly calculated diagnostic outputs.
- `port_sedimentation`: Source-established modelling or calculation of sediment accumulation or loss in port infrastructure using bathymetric measurements or sediment-model inputs/outputs.
- `transport_emissions`: Source-established calculation or modelling of pollutant emissions from transport operations, using vehicle, fuel and traffic-condition emission factors or associated model outputs.

These values require the modelling or calculation role stated by the source. A general energy, building, bathymetry or transport subject does not establish that role.

### Source-defined structural design use added 2026-10-09

`structural_design`: Source-established engineering sizing, load assessment or structural-response modelling for physical infrastructure assets, including anchors, moorings and structural connections. A general engineering subject alone is insufficient.

### Source-defined communication performance use added 2026-10-09

`communication_system_performance`: Source-established modelling or testing of communication-system performance, including signal quality, modulation, bandwidth, noise and transmitter or detector response in telecommunications infrastructure. Generic materials or photonics research without this system role does not qualify.

### Source-defined building heat and moisture use added 2026-10-09

`building_hygrothermal_performance`: Source-established modelling, testing or validation of heat and moisture behaviour and associated deterioration in building envelopes, including insulation systems, masonry and embedded structural components.

### Infrastructure demand forecasting (2026-10-09)

`demand_forecasting`: Source-established forecasting or modelling of demand for infrastructure services or energy carriers, including fuel sales and service consumption. Generic economic prediction without an explicit infrastructure demand role does not qualify.

### Source-defined infrastructure life-cycle assessment use added 2026-10-09

`life_cycle_assessment`: Source-established modelling of environmental impacts or costs over the life cycle of physical infrastructure, including probabilistic assessment of building insulation systems. A generic sustainability subject does not establish this use. The RIBuild LCA/LCC tool, DOI 10.5281/zenodo.3903571, establishes the need for this value.

### Source-defined infrastructure condition monitoring use added 2026-10-09

`condition_monitoring`: Source-established modelling, prediction or validation of physical infrastructure asset condition, including defect detection, deterioration and maintenance needs. Explicit structural-health-monitoring crack-detection training for bridge decks, walls and pavements establishes this use. Generic visual or manufacturing benchmarks without a concrete infrastructure-system role do not qualify.

### Source-defined power quality use added 2026-10-09

`power_quality`: Source-established modelling, prediction or validation of electrical-grid voltage and current waveform quality or the accuracy of grid measurement chains. This includes harmonics, subharmonics and instrument-transformer frequency response. IT4PQ native records 10068934, 7432234 and 6104280 establish these roles. An electrical-sector tag alone does not establish this use.

### Unknown simulation uses (2026-10-09)

`simulation_uses: []` means that the inspected metadata do not establish a specific use from the controlled vocabulary. Do not assign network flow to a street-name table that has no geometry or connectivity. This does not change inclusion criteria: a record must independently describe an in-scope infrastructure resource, and supporting resources still need a source-established concrete role in infrastructure simulation. A sector tag, empty list or possible use does not establish inclusion. Preserve the source-defined contents and unknown use in the description. The dashboard omits the empty list from use-specific filter values.
