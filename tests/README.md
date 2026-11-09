# Disposable Home Assistant validation

These tests execute `weather/voice_forecast.yaml` itself, not a Python
reimplementation of its templates. Each test has a fresh temporary HA config
directory and stops its HA instance at teardown. There are no live HA calls,
external forecast requests, deployment, public listeners, or model requests.

Requirements: `uv`, Python ≥3.14.2, and the pinned packages below. Keep this
environment separate from the project's Python 3.13 YAML environment.

```sh
uv python install 3.14
uv venv --python 3.14 .venv-ha
uv pip install --python .venv-ha/bin/python -r tests/requirements.txt
.venv-ha/bin/python -m pytest -q
```

YAML hygiene (using the project-level Orb tooling):

```sh
.venv/bin/yamllint weather/voice_forecast.yaml
```

The tests use HA's actual blueprint loading/substitution and schema validation,
script service, template sandbox, weather service/feature checks, and forecast
unit conversion. A native-unit fixture weather entity replaces only the remote
weather provider. The clock and HA timezone are controlled independently.

The lifecycle test serves the draft on an ephemeral **loopback-only** HTTP
endpoint within the test. It exercises HA's normal URL importer and re-import
storage/reload path, checks persisted inputs and refreshed exported field schema,
and invokes the exposed Assist script tool to verify native response propagation.
The listener is closed at test teardown; nothing is published to the forge.

Cases discriminate NWS day/night values from means, provider daily extrema from
sample extrema, maximum period probability from day-wide probability, unknown
amounts from zero, sample precision from horizon availability, and partial data
from silently truncated data. They also cover local midnight, repeated parts,
cross-midnight intervals, 23/25-hour days, non-one-hour DST transitions, unknown
observations, real metric/customary conversion, malformed/duplicate records,
missing units, provider exceptions, and parallel request isolation.

HA/dependency deprecation warnings are left visible. These tests do **not**
certify a live provider's forecast accuracy, the public mirror URL's
accessibility, a browser UI flow, or an LLM's interpretation/spoken summary.
Evaluate the latter separately with a chosen model; every spoken number should
trace to a returned value, unit, date, and semantic label.
