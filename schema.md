# Catalogue schema

The catalogue is a metadata registry, not a data store. Nothing is downloaded. Every record keeps the links needed to obtain the resource later.

## Four record types

| Type | What it covers | Examples |
|---|---|---|
| `data` | Datasets and information sources describing infrastructure assets, networks, demand, hazards and performance | OpenStreetMap power lines, HIFLD, Copernicus DEM, national road registers, utility outage records |
| `model` | Existing analytical or numerical models of infrastructure behaviour, published as code, packaged software or documented methods | PyPSA, pandapower, EPANET, MATSim, SUMO, fragility curve libraries, OpenSees |
| `platform` | Simulation platforms and frameworks that host or couple models, run scenarios or provide digital-twin environments | OpenDSS, GridLAB-D, CityGML tooling, Modelica environments, HAZUS, coupled multi-sector frameworks |
| `case_study` | Documented real-world applications to infrastructure: where, why, against which hazards, with what outcome, and using which data, models and platforms | Climate-ADAPT case studies, a national agent-based transport model in operational use, the IN-CORE Galveston testbed, a utility's climate-proofing study for a major project |

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
| `homepage` | Landing page |
| `access_links` | List of `{label, url, kind, note}` where kind is `download`, `api`, `repo`, `docs`, `paper`, `portal`, `viewer`, `contact` |
| `licence` | SPDX identifier where possible, otherwise free text |
| `licence_type` | Optional controlled licence type for the dashboard filter, a list from `pipeline/vocab/vocabulary.yaml` |
| `cost` | `free`, `freemium`, `paid`, `on_request` |
| `access_restrictions` | `none`, `registration`, `institutional`, `restricted`, `on_request`; details in `access_note` |
| `sectors` | List of two-level values from the sector hierarchy below, for example `energy.electricity`. Use the top level alone only when a resource spans the whole group |
| `geographic_scope` | `global`, `continental`, `national`, `regional`, `city`, `site` plus named areas |
| `countries` | ISO 3166 alpha-2 codes where applicable |
| `simulation_uses` | List: `network_flow`, `cascading_failure`, `hazard_exposure`, `resilience`, `capacity_planning`, `agent_based`, `optimisation`, `digital_twin`, `emergency_response`, `climate_adaptation` |
| `maturity` | `active`, `maintained`, `stale`, `archived`, `unknown` |
| `last_updated` | Date of the resource, if known |
| `date_catalogued` | Date the record was added |
| `date_verified` | Date links were last checked |
| `related_ids` | Links to other catalogue records |
| `tags` | Free keywords |
| `notes` | Quality remarks, known gaps, caveats |
| `sources` | Where the metadata came from: list of `{url, accessed, note}` |
| `discovery_routes` | Every route class (`R01` to `R51`, see `schema/vocab.yaml`) and source that found the record, with the query and date; drives the completeness metrics |
| `dedupe_keys` | Normalised `url`, `doi`, `repo` and `name` used by the deduplicator |
| `languages` | ISO 639 codes of the resource's metadata and content |
| `description_checked` | Date the description was checked against the source for the required content elements |
| `continents`, `countries`, `regions` | Continents from `africa`, `asia`, `europe`, `north_america`, `south_america`, `oceania`, `antarctica`; ISO 3166 alpha-2 codes; named subnational areas or cities |
| `link_health` | Result of the last link check, written by `pipeline/linkcheck.py`: `checked` (date), `dead` (URLs answering 404 or 410), `dead_since`, `wayback` (archived snapshot of a dead link), `unverified` (URLs that produced no definitive result at that check, for example hosts the checking environment could not reach). Every result is logged in `sources/linkchecks.jsonl` |
| `access_note` | Free text on how access works when it is not simply open |
| `hazards` | Optional on every type, expected on case studies: hazard types the resource addresses, from `flood`, `coastal_flood_storm_surge`, `sea_level_rise`, `drought`, `extreme_heat`, `cold_snow_ice`, `storm_wind`, `hail` (added 2026-09-26), `wildfire`, `earthquake`, `landslide`, `tsunami`, `volcanic`, `space_weather`, `cyber_attack`, `physical_attack_sabotage`, `pandemic`, `technological_failure`, `multi_hazard_climate_change` |

## Type-specific fields

### `data`

| Field | Notes |
|---|---|
| `data_family` | List of values from the data family vocabulary below, by the role the data plays in a simulation |
| `data_kind` | `asset_inventory`, `network_topology`, `time_series`, `raster`, `tabular`, `survey`, `event_record`, `document`, `stream`, `imagery` |
| `formats` | GeoJSON, Shapefile, CSV, NetCDF, GeoPackage, API JSON, and so on |
| `spatial_resolution` | Free text or numeric with unit |
| `spatial_resolution_class` | Optional controlled form of `spatial_resolution` for the dashboard filter, from `pipeline/vocab/vocabulary.yaml` |
| `spatial_resolution_m` | Optional structured form for the dashboard's range facet: finest ground resolution in metres (added 2026-09-26) |
| `temporal_coverage` | Start and end, or snapshot date |
| `temporal_coverage_years` | Optional structured form for the range facet: `{start: year, end: year or null}`, `null` while the resource is still extended (added 2026-09-26) |
| `temporal_resolution` | Hourly, daily, annual, none |
| `temporal_resolution_class` | Optional controlled form of `temporal_resolution` (the dashboard's time step filter), from `pipeline/vocab/vocabulary.yaml` |
| `crs` | Coordinate reference system if spatial |
| `size` | Approximate, if published |
| `size_bytes` | Optional structured form for the range facet: total size in bytes as the provider states it (added 2026-09-26) |
| `schema_summary` | Key attributes available |
| `update_frequency` | How often the source refreshes |

### `model`

| Field | Notes |
|---|---|
| `model_kind` | `physical`, `statistical`, `agent_based`, `network`, `optimisation`, `fragility`, `economic`, `hybrid`, `discrete_event` (queueing and process simulation driven by events in time, added 2026-09-26) |
| `language` | Python, Julia, C++, MATLAB, and so on (also allowed on `platform` records) |
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
| `open_source` | Boolean |
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

The free-text fields behind the dashboard filters are licence, formats, update frequency, time step, spatial resolution, programming language, interfaces, deployment and maturity. Each maps onto a short controlled vocabulary in `pipeline/vocab/vocabulary.yaml`, described in `pipeline/vocab/README.md` and confirmed on 2026-09-29. The build applies the mapping to records that still carry free text. `pipeline/vocab_map.py rewrite --apply` wrote (on 2026-09-29, for all 13,279 records) the controlled values into the records: `licence_type` (a list) beside the licence text, `spatial_resolution_class` and `temporal_resolution_class` beside their free text, and the vocabulary values in place of the free text in the other fields. A controlled value stored in a record wins over the mapping.

## Machine-readable source

`schema/vocab.yaml` holds every controlled vocabulary above plus the route classes, route families, cell statuses, coverage priors and candidate statuses. `schema/record.schema.json` holds the structural schema. This document explains them; `pipeline/validate.py` checks that the three agree and that every record passes. Add a value to `vocab.yaml` first, then here, then use it.

## Description standard

The description is one hundred to three hundred words of plain prose. It must state: what the resource contains; who produces it and why; spatial and temporal coverage and resolution; format and access method; licence and cost; known gaps or caveats; which simulation uses it serves; and which other catalogued resources it relates to. The validator checks length and the presence of these elements. Every record carries a full description; there are no partial tiers.

## Storage

Records live as one JSON file per record under `project/catalog/<type>/<id>.json`. Candidates found by sweeps live under `project/sources/candidates/` and never in the catalogue until fully described. `pipeline/compile.py` builds `project/catalog/catalog.json` and a SQLite file for the dashboard. Controlled vocabularies above may grow as records reveal new categories; add a value to this file before using it.
