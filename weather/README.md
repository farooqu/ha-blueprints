# LLM weather forecast

[`voice_forecast.yaml`](voice_forecast.yaml) is a **script
blueprint for Home Assistant 2026.11.0 or newer**. It returns structured forecast
data for voice or text-based Assist/LLM agents, not spoken text or current
observations. The filename stays unchanged for existing blueprint imports.

## Installation and updates

[![Import this blueprint into Home Assistant](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Ffarooqu%2Fha-blueprints%2Fmain%2Fweather%2Fvoice_forecast.yaml)

The button opens Home Assistant's import dialog with this blueprint URL prefilled.

Installation and re-import use the [public GitHub mirror](https://github.com/farooqu/ha-blueprints).
The button and the blueprint's `source_url` point to its public raw YAML, so HA
does not need a forge login or credentials in the URL.

1. Select the button above, or import the [raw YAML URL](https://raw.githubusercontent.com/farooqu/ha-blueprints/main/weather/voice_forecast.yaml)
   through Settings → Automations & scenes → Blueprints.
2. Create a script, select any forecast-capable weather entity, and review the
   four configurable clock boundaries. No composite weather entity is required.
3. Give the script a factual name/description for its forecast location and
   expose the **script** to Assist. Enable Home Assistant tools in your chosen
   LLM agent. This does not add a local sentence-matching forecast intent.
4. For another location, create another script instance; do not ask the model to
   invent weather entity IDs or geographic coordinates.

Update with HA's normal **re-import** on the existing blueprint. The `source_url`
is stable; no custom deployment is involved. Re-import reloads the consuming
scripts in HA 2026.11, retaining configured inputs and refreshing their Assist
field metadata. Start a new conversation if an agent retains old tool metadata.
Re-import replaces the imported blueprint; review local edits first.

## Tool inputs

The model selects concepts; the script resolves actual dates in **HA's timezone**.
Only `day` is always required. Defaults are applied at runtime, not just in the UI.

| Field | Meaning |
| --- | --- |
| `day` | `today`, `tomorrow`, `day_after_tomorrow`, or an English weekday identifier (`monday` … `sunday`). Weekdays include today. |
| `weeks_later` | 0 by default; 1 adds seven days to a named weekday's nearest occurrence. No start-of-week convention. |
| `days` | Integer 1–7, default 1: consecutive anchor dates. |
| `detail` | `overview` (default) for compact full-day outlooks; `hourly` for changes throughout a full day. Day-parts and explicit clock windows always require hourly samples. |
| `part_of_day` | `full_day` (default), `morning`, `afternoon`, `evening`, `night`, or `hours`. |
| `start_time` | Required only with `hours`: local 24-hour `HH:MM` or `HH:MM:00`. |
| `end_time` | Only with `hours`: exclusive local end. Earlier than start crosses midnight; equal is invalid. Omit for one elapsed hour, including an exact “at” request. |

Examples of arguments, not complete HA action YAML:

```yaml
# Tomorrow, without a date/time lookup or model date arithmetic:
day: tomorrow
```

```yaml
# How will the weather change throughout tomorrow?
day: tomorrow
detail: hourly
```

```yaml
# Three separate mornings, not the intervening afternoons and nights:
day: friday
days: 3
part_of_day: morning
```

```yaml
# A midnight-crossing range; no model duration calculation:
day: tomorrow
part_of_day: hours
start_time: '23:00'
end_time: '02:00'
```

The default boundaries are morning 06:00–12:00, afternoon 12:00–18:00,
evening 18:00–22:00, and night 22:00–06:00 the following date. Installers can
change them; these are clock-window conventions, not universal language rules,
sunrise/sunset, or provider day/night labels. Night belongs to its **starting**
date. `days` repeats the selected window independently on each anchor date.

Clarify ambiguous “next Friday,” AM/PM, or early-morning “tonight.” There is no
implicit weekend, calendar week, free-form date parser, absolute-date input,
historical weather, or arbitrary-location lookup. Machine enum identifiers do
not require English conversation. The blueprint neither picks a model nor
forces a speaking language/style.

Full days end at the next **calendar midnight**, not 24 elapsed hours. Filtering
uses UTC instants, preserving both repeated fall-back hours and offset changes.
Nonexistent or ambiguous explicit/configured boundaries produce structured
errors instead of guessed times; an otherwise unambiguous window may span a
transition. No DST fold-choice parameter is exposed.

## Provider behavior and result contract

- **Full-day overviews:** prefer daily → twice-daily → hourly. NWS's hourly + twice-daily
  capabilities work without calling its unsupported daily action. All day/night
  records survive, rather than only the first period.
- **Explicit `detail: hourly`, day-parts, and clock times:** hourly samples are
  required. Coarse data is separated
  into `context` with `precision_unavailable`, never relabeled as hourly data.
  A minute-level range returns only actual in-window samples. An “at” request
  requires a sample exactly at its start; no interpolation is performed.
- If a supported type has no matching data, the next supported type can be tried,
  once per type. A partial answer is not filled with another forecast type.
- Maximum **72 returned rows** across windows, including context. Exceeding this
  returns `request_too_large`, not a truncated answer. Seven-day hourly-only
  requests may need narrowing, including with `detail: hourly`. Coarse full-day
  data is usually much smaller.

`detail: hourly` changes the requested resolution, not the window boundaries:
full days still run between HA-local calendar midnights, including 23/25-hour
DST days. Available hourly samples and summaries are returned unchanged, without
automatic day-part grouping or lossy compression. Missing hours remain partial;
daily/day-night values never fill the gaps. `overview` is the existing behavior,
so callers that omit `detail` are unchanged.

The native mapping returned by the script contains:

- `schema_version: 2`, `status: ok|partial|error`, `resolved_at`, `timezone`,
  `forecast_type`, `units`, and `windows`. Early input/entity errors return a
  smaller error envelope.
- `error` only when there is an error; counted `warnings` only when nonempty.
- Each window has requested offset-bearing start/end, coverage, and `periods`.
  `context` and `summary` appear only when nonempty. Window `status` is omitted
  when `ok`; `partial` and `error` remain explicit, with an error code when needed.
- Partial/error responses retain `source_entity` and, when available,
  `available_first_start` / `available_last_start` for diagnostics. Those are
  source timestamps, **not** guaranteed interval/horizon endpoints.

Schema v2 removes duplicated date echoes (`requested_windows`, `anchor_date`),
coverage counts/first/last timestamps and basis, empty metadata, and the constant
`forecast_issue_time: unknown`. Requested dates remain in `requested_start`.
Coverage basis follows `forecast_type`: daily records are date-based, twice-daily
records have provider period starts, and hourly records are timestamped samples.
All forecast periods, nonempty context, and nonempty summaries are preserved,
including summary sample counts and every tied timestamp. Consumers of the v1
response must account for the removed/optional keys.

Forecast issue time remains **unknown**. `resolved_at` and entity observation
update timestamps are retrieval/observation metadata, not forecast issue times.

An Assist tool call wraps that mapping inside HA's `result`; directly calling
the script action with response data returns the mapping itself. Do not use
`script.turn_on` when you need the return value.

Records retain condition, temperature, optional provider low, precipitation
probability/amount, sustained wind/gust, and boolean `is_daytime` when supplied.
They do not promise UV, humidity, pressure, or other unprojected fields. Missing
values are omitted, never changed to zero. Measurements without unit labels are
omitted with `missing_unit:<dimension>`; units come from the selected entity,
including HA's unit overrides, without another conversion or rounding step.

| Forecast type | Temperature labels |
| --- | --- |
| Daily | `provider_high` / `provider_low`, only when supplied by that daily record. |
| Twice-daily | `period_temperature` with `is_daytime`; an optional actual provider `templow` is preserved as `provider_low`. No synthetic daily extrema. |
| Hourly | `temperature_sample`; summary `sample_temperature_min` / `sample_temperature_max` with contributing count and times. **Not provider daily extrema.** |

Other summaries are `max_period_precipitation_probability` and, for hourly
samples, `max_sample_wind_speed`. Each includes value, contributing count, and
matching timestamps. The highest **period** chance is not a calculated day-wide
probability. Precipitation amounts stay on their provider records; they are not
summed, prorated, or inferred from probability/condition. Wind gusts are distinct
from sustained wind. There are **no averages** or modal-condition summaries;
the records retain precipitation timing and condition transitions.

## Coverage, missing data, and limitations

HA's common forecast API supplies start timestamps but no universal period end
or issue time. Coarse temporal completeness is therefore `unknown`. Twice-daily
carry-in records are marked as context, with unknown end, not stretched across a
gap. A previous-night context value is excluded from the anchor day's summary.

Hourly coverage reports missing expected samples on a nominal one-hour grid,
using the provider's actual sample phase, not an assumed whole-clock-hour phase.
`missing_hourly_starts` is omitted when there are no listed gaps. Check
`sample_grid_complete`, not that list's absence, to establish grid completeness.
If timestamps do not establish one phase, `sample_grid_complete` is null rather
than an invented coverage claim. Even a complete sample grid does not establish
continuous precipitation-amount coverage. Earlier-today gaps are reported, not
backfilled from observations. Partial multi-day results identify failed windows.

Malformed/naive timestamps and invalid measurements are skipped with counted
warnings; daily date-only labels are accepted. Identical duplicate records are
deduplicated. Conflicting records at the same instant are excluded rather than
arbitrarily selected. Offset-distinct repeated hours are different instants.
Aware daily timestamps are associated by their HA-local date; integrations that
mislabel UTC midnight as an unrelated local date need fixing at their source.

Error codes include `invalid_request`, `past_window`, `nonexistent_local_time`,
`ambiguous_local_time`, `entity_not_found`, `no_forecast_support`,
`forecast_failed`, `no_data`, `out_of_range`, `precision_unavailable`, and
`request_too_large`. Empty provider data is not automatically a short horizon.
Ordinary provider failures are handled, but broken script/template configuration
and HA's parallel-run limit can still fail at the platform level; inspect traces.

## Validation

See [`tests/README.md`](../tests/README.md) for reproducible disposable-HA tests.
The project's Python 3.13 + PyYAML/yamllint setup provides YAML tooling only.
HA 2026.11 requires Python ≥3.14.2; no live HA credentials are needed by the tests.
