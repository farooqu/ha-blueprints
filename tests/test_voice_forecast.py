"""Execute the imported YAML in disposable HA, including its weather service.

Run with a release-matched HA interpreter; see tests/README.md. No live HA,
credentials, external provider, model, or network forecast requests are used.
"""

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
import yaml
from homeassistant import config_entries, loader
from homeassistant.bootstrap import async_load_base_functionality
from homeassistant.components.weather import WeatherEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_system import METRIC_SYSTEM, US_CUSTOMARY_SYSTEM

BLUEPRINT = Path(__file__).parents[1] / "weather" / "voice_forecast.yaml"
ENTITY = "weather.fixture"


def period(stamp, temperature=None, **values):
    """Native provider data; HA, not the test, performs the unit conversions."""
    result = {"datetime": stamp, **values}
    if temperature is not None:
        result["native_temperature"] = temperature
    return result


def hourly(start, count, **values):
    base = datetime.fromisoformat(start).astimezone(UTC)
    return [
        period((base + timedelta(hours=i)).isoformat(), i, **values)
        for i in range(count)
    ]


class FixtureWeather(WeatherEntity):
    _attr_name = "Fixture"
    _attr_unique_id = "forecast_fixture"
    _attr_should_poll = False
    _attr_condition = None  # Observations need not be available for forecasts.
    _attr_native_temperature_unit = "°C"
    _attr_native_wind_speed_unit = "km/h"
    _attr_native_precipitation_unit = "mm"

    def __init__(self, forecasts, features):
        self.entity_id = ENTITY
        self.forecasts = forecasts
        self._attr_supported_features = features

    async def forecast(self, kind):
        result = self.forecasts.get(kind, [])
        if isinstance(result, Exception):
            raise result
        await asyncio.sleep(0)
        return deepcopy(result)

    async def async_forecast_daily(self):
        return await self.forecast("daily")

    async def async_forecast_hourly(self):
        return await self.forecast("hourly")

    async def async_forecast_twice_daily(self):
        return await self.forecast("twice_daily")


@pytest_asyncio.fixture
async def ha(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    loader.async_setup(hass)
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    assert await async_load_base_functionality(hass)
    old_zone = dt_util.DEFAULT_TIME_ZONE
    dt_util.set_default_time_zone(ZoneInfo("UTC"))
    hass.config.time_zone = "UTC"
    hass.config.units = METRIC_SYSTEM
    instant = datetime(2030, 1, 1, tzinfo=UTC)

    def now(zone=None):
        return instant.astimezone(zone or dt_util.DEFAULT_TIME_ZONE)

    def clock(value, zone="UTC"):
        nonlocal instant
        instant = datetime.fromisoformat(value)
        dt_util.set_default_time_zone(ZoneInfo(zone))
        hass.config.time_zone = zone

    async def create(forecasts, features=2, inputs=None):
        path = tmp_path / "blueprints" / "script" / "test" / "voice_forecast.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(BLUEPRINT.read_text())
        assert await async_setup_component(hass, "weather", {})
        provider = FixtureWeather(forecasts, features)
        await hass.data["weather"].async_add_entities([provider])
        config = {
            "script": {
                "forecast_fixture": {
                    "use_blueprint": {
                        "path": "test/voice_forecast.yaml",
                        "input": {
                            "weather_entity": ENTITY,
                            **(inputs or {}),
                        },
                    }
                }
            }
        }
        (tmp_path / "configuration.yaml").write_text(yaml.safe_dump(config))
        assert await async_setup_component(hass, "script", config)
        await hass.async_block_till_done()
        assert hass.states.get("script.forecast_fixture").state != "unavailable"
        return provider

    async def call(**args):
        result = await hass.services.async_call(
            "script", "forecast_fixture", args, blocking=True, return_response=True
        )
        assert isinstance(result, dict), result
        return result

    with patch.object(dt_util, "now", now):
        try:
            yield hass, create, call, clock
        finally:
            await hass.async_stop(force=True)
            dt_util.set_default_time_zone(old_zone)


async def test_nws_day_night(ha):
    hass, create, call, _ = ha
    await create(
        {
            "twice_daily": [
                period("2029-12-31T18:00:00+00:00", 7, is_daytime=False),
                period(
                    "2030-01-01T06:00:00+00:00",
                    24,
                    is_daytime=True,
                    precipitation_probability=20,
                ),
                period(
                    "2030-01-01T18:00:00+00:00",
                    9,
                    is_daytime=False,
                    precipitation_probability=80,
                ),
            ]
        },
        features=6 | 8,
    )
    result = await call(day="today")
    assert result["schema_version"] == 2
    assert result["status"] == "ok"
    assert result["forecast_type"] == "twice_daily"
    assert not {
        "source_entity",
        "forecast_issue_time",
        "available_first_start",
        "available_last_start",
        "requested_windows",
        "error",
        "warnings",
    }.intersection(result)
    window = result["windows"][0]
    assert not {"anchor_date", "status", "error"}.intersection(window)
    assert [r["period_temperature"] for r in window["periods"]] == [24, 9]
    assert [r["is_daytime"] for r in window["periods"]] == [True, False]
    assert window["context"][0]["context"] == "carry_in_context"
    assert window["coverage"] == {"temporal_completeness": "unknown"}
    assert not any("provider_low" in r for r in window["periods"])
    assert window["summary"]["max_period_precipitation_probability"]["value"] == 80
    assert hass.states.get(ENTITY).state == "unknown"


async def test_hourly_extrema_and_units(ha):
    hass, create, call, _ = ha
    await create(
        {
            "hourly": [
                period("2030-01-01T09:00:00Z", 4, precipitation_probability=0),
                period(
                    "2030-01-01T10:00:00Z",
                    17,
                    precipitation_probability=80,
                    native_wind_speed=12,
                ),
                period("2030-01-01T11:00:00Z", 10, precipitation_probability=20),
                period("2030-01-01T12:00:00Z", 99),
            ]
        }
    )
    result = await call(
        day="today", part_of_day="hours", start_time="09:00", end_time="12:00"
    )
    assert result["status"] == "ok"
    window = result["windows"][0]
    assert "context" not in window
    assert window["summary"]["sample_temperature_min"]["value"] == 4
    assert window["summary"]["sample_temperature_max"]["value"] == 17
    assert window["summary"]["sample_temperature_max"]["at"] == [
        "2030-01-01T10:00:00+00:00"
    ]
    assert [r["precipitation_probability"] for r in window["periods"]] == [0, 80, 20]
    assert all(
        "precipitation" not in r and "provider_high" not in r for r in window["periods"]
    )
    assert result["units"]["temperature"] == "°C"
    assert window["summary"]["max_sample_wind_speed"]["sample_count"] == 1
    hass.config.units = US_CUSTOMARY_SYSTEM
    hass.data["weather"].get_entity(ENTITY).async_write_ha_state()
    converted = await call(day="today", part_of_day="hours", start_time="09:00")
    assert converted["units"]["temperature"] == "°F"
    # HA's default Fahrenheit precision is whole degrees (4°C → 39°F).
    assert converted["windows"][0]["periods"][0]["temperature_sample"] == 39


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"day": "weekend"},
        {"day": "today", "days": 1.5},
        {"day": "today", "days": True},
        {"day": "today", "days": "2"},
        {"day": "today", "detail": "daily"},
        {"day": "today", "detail": None},
        {"day": "today", "weeks_later": 1},
        {"day": "today", "start_time": "12:00"},
        {"day": "today", "part_of_day": "hours"},
        {"day": "today", "part_of_day": "hours", "start_time": "24:00"},
        {
            "day": "today",
            "part_of_day": "hours",
            "start_time": "12:00",
            "end_time": "12:00",
        },
    ],
)
async def test_invalid_request(ha, args):
    _, create, call, _ = ha
    await create({})
    result = await call(**args)
    assert result["schema_version"] == 2
    assert result["status"] == "error"
    assert result["error"]["code"] == "invalid_request"


async def test_calendar_and_repeated_windows(ha):
    _, create, call, clock = ha
    clock("2030-01-02T00:30:00+00:00", "America/Los_Angeles")  # Still Tuesday locally.
    await create({"hourly": hourly("2030-01-01T00:00:00-08:00", 72)})
    result = await call(day="tuesday", days=3, part_of_day="morning")
    assert [w["requested_start"][:10] for w in result["windows"]] == [
        "2030-01-01",
        "2030-01-02",
        "2030-01-03",
    ]
    assert result["windows"][0]["error"]["code"] == "past_window"
    assert result["status"] == "partial"
    assert [len(w["periods"]) for w in result["windows"]] == [0, 6, 6]
    assert all("T06:00:00-08:00" in w["requested_start"] for w in result["windows"])
    shifted = await call(day="tuesday", weeks_later=1)
    assert shifted["windows"][0]["requested_start"] == "2030-01-08T00:00:00-08:00"
    tomorrow = await call(day="tomorrow")
    assert tomorrow["windows"][0]["requested_start"] == "2030-01-02T00:00:00-08:00"


async def test_midnight_and_exact_hour(ha):
    _, create, call, _ = ha
    await create({"hourly": hourly("2030-01-01T00:00:00Z", 49)})
    result = await call(
        day="today", part_of_day="hours", start_time="23:00", end_time="02:00"
    )
    assert [r["temperature_sample"] for r in result["windows"][0]["periods"]] == [
        23,
        24,
        25,
    ]
    at = await call(day="today", part_of_day="hours", start_time="15:00")
    assert [r["temperature_sample"] for r in at["windows"][0]["periods"]] == [15]
    between = await call(day="today", part_of_day="hours", start_time="15:30")
    assert between["error"]["code"] == "precision_unavailable"
    assert between["windows"][0]["periods"] == []


@pytest.mark.parametrize(
    "date,zone,start,count,offset_end",
    [
        (
            "2030-03-09T12:00:00-05:00",
            "America/New_York",
            "2030-03-10T00:00:00-05:00",
            23,
            "-04:00",
        ),
        (
            "2030-11-02T12:00:00-04:00",
            "America/New_York",
            "2030-11-03T00:00:00-04:00",
            25,
            "-05:00",
        ),
    ],
)
@pytest.mark.parametrize("detail", ["overview", "hourly"])
async def test_dst_whole_days(ha, date, zone, start, count, offset_end, detail):
    _, create, call, clock = ha
    clock(date, zone)
    await create({"hourly": hourly(start, count)})
    result = await call(day="tomorrow", detail=detail)
    window = result["windows"][0]
    assert result["status"] == "ok"
    assert len(window["periods"]) == count
    assert window["requested_end"].endswith(offset_end)
    assert window["coverage"]["sample_grid_complete"] is True
    assert "missing_hourly_starts" not in window["coverage"]
    assert len({p["datetime"] for p in window["periods"]}) == count


@pytest.mark.parametrize(
    "date,zone,time,code",
    [
        (
            "2030-03-09T12:00:00-05:00",
            "America/New_York",
            "02:30",
            "nonexistent_local_time",
        ),
        (
            "2030-11-02T12:00:00-04:00",
            "America/New_York",
            "01:30",
            "ambiguous_local_time",
        ),
        (
            "2030-10-05T12:00:00+10:30",
            "Australia/Lord_Howe",
            "02:15",
            "nonexistent_local_time",
        ),
        (
            "2030-04-06T12:00:00+11:00",
            "Australia/Lord_Howe",
            "01:45",
            "ambiguous_local_time",
        ),
    ],
)
async def test_dst_clock_boundaries(ha, date, zone, time, code):
    _, create, call, clock = ha
    clock(date, zone)
    await create({})
    result = await call(day="tomorrow", part_of_day="hours", start_time=time)
    assert result["error"]["code"] == code


async def test_capabilities_and_horizons(ha):
    _, create, call, _ = ha
    await create(
        {
            "hourly": [period("2030-01-01T09:00:00Z", 12)],
            "twice_daily": [period("2030-01-02T18:00:00Z", 9, is_daytime=False)],
        },
        features=6,
    )
    coarse = await call(day="tomorrow", part_of_day="night")
    assert coarse["error"]["code"] == "precision_unavailable"
    assert "summary" not in coarse["windows"][0]
    assert coarse["windows"][0]["periods"] == []
    assert coarse["windows"][0]["context"][0]["period_temperature"] == 9
    far = await call(day="tuesday", weeks_later=1)
    assert far["error"]["code"] == "out_of_range"


async def test_daily_fallback_and_no_cross_type_splicing(ha):
    _, create, call, _ = ha
    await create(
        {
            "daily": [period("2030-01-02", 25, native_templow=11)],
            "hourly": hourly("2030-01-01T00:00:00Z", 48),
        },
        features=3,
    )
    today = await call(day="today")
    assert today["forecast_type"] == "hourly"
    two_days = await call(day="today", days=2)
    assert two_days["forecast_type"] == "daily"
    assert two_days["status"] == "partial"
    assert two_days["windows"][0]["periods"] == []
    assert two_days["windows"][1]["periods"][0]["provider_high"] == 25
    assert two_days["windows"][1]["periods"][0]["provider_low"] == 11


async def test_full_day_detail_selects_resolution(ha):
    _, create, call, _ = ha
    await create(
        {
            "daily": [period("2030-01-01", 31, native_templow=11)],
            "twice_daily": [
                period("2030-01-01T06:00:00Z", 24, is_daytime=True),
                period("2030-01-01T18:00:00Z", 9, is_daytime=False),
            ],
            "hourly": hourly("2030-01-01T00:00:00Z", 25),
        },
        features=7,
    )
    default = await call(day="today")
    assert await call(day="today", detail="overview") == default
    assert default["forecast_type"] == "daily"
    assert default["windows"][0]["periods"][0]["provider_high"] == 31
    detailed = await call(day="today", detail="hourly")
    assert detailed["status"] == "ok"
    assert detailed["forecast_type"] == "hourly"
    assert [r["temperature_sample"] for r in detailed["windows"][0]["periods"]] == list(
        range(24)
    )
    assert detailed["windows"][0]["summary"]["sample_temperature_max"]["value"] == 23


@pytest.mark.parametrize(
    "kind,features", [("daily", 1), ("twice_daily", 4), ("twice_daily", 6)]
)
async def test_full_day_hourly_unavailable_is_coarse_context(ha, kind, features):
    _, create, call, _ = ha
    await create(
        {
            kind: [period("2030-01-02T06:00:00Z", 24, is_daytime=True)],
            "hourly": hourly("2030-01-01T00:00:00Z", 24),
        },
        features=features,
    )
    result = await call(day="tomorrow", detail="hourly")
    assert result["status"] == "error"
    assert result["error"]["code"] == "precision_unavailable"
    assert result["forecast_type"] == kind
    assert result["windows"][0]["periods"] == []
    assert result["windows"][0]["context"][0]["datetime"] == "2030-01-02T06:00:00+00:00"
    assert "summary" not in result["windows"][0]


async def test_full_day_hourly_partial_is_not_filled_with_daily(ha):
    _, create, call, _ = ha
    await create(
        {
            "daily": [period("2030-01-01", 31, native_templow=11)],
            "hourly": [
                period("2030-01-01T09:00:00Z", 4),
                period("2030-01-01T11:00:00Z", 17),
            ],
        },
        features=3,
    )
    result = await call(day="today", detail="hourly")
    assert result["status"] == "partial"
    assert result["forecast_type"] == "hourly"
    assert [r["temperature_sample"] for r in result["windows"][0]["periods"]] == [4, 17]
    assert (
        "2030-01-01T10:00:00+00:00"
        in result["windows"][0]["coverage"]["missing_hourly_starts"]
    )


@pytest.mark.parametrize("count,code", [(72, None), (73, "request_too_large")])
@pytest.mark.parametrize("detail", ["overview", "hourly"])
async def test_payload_boundary(ha, count, code, detail):
    _, create, call, _ = ha
    await create({"hourly": hourly("2030-01-01T00:00:00Z", count)})
    result = await call(day="today", days=4, detail=detail)
    if code:
        assert result["error"]["code"] == code
        assert result["error"]["requested_records"] == 73
        assert result["windows"] == []
    else:
        assert result["status"] == "partial"
        assert sum(len(w["periods"]) for w in result["windows"]) == 72


async def test_gaps_optional_fields_and_conflicts(ha):
    _, create, call, _ = ha
    await create(
        {
            "hourly": [
                period("bad", 100),
                period("2030-01-01T09:00:00Z", 4),
                period("2030-01-01T11:00:00Z", 10, precipitation_probability=0),
                period("2030-01-01T11:00:00Z", 10, precipitation_probability=0),
                period("2030-01-01T12:00:00Z", 90),
                period("2030-01-01T12:00:00Z", 99),
            ]
        }
    )
    result = await call(
        day="today", part_of_day="hours", start_time="09:00", end_time="13:00"
    )
    assert result["status"] == "partial"
    window = result["windows"][0]
    assert [r["temperature_sample"] for r in window["periods"]] == [4, 10]
    assert "precipitation_probability" not in window["periods"][0]
    assert window["periods"][1]["precipitation_probability"] == 0
    assert window["coverage"]["missing_hourly_starts"] == [
        "2030-01-01T10:00:00+00:00",
        "2030-01-01T12:00:00+00:00",
    ]
    assert "invalid_timestamp" in result["warnings"]
    assert "conflicting_timestamp" in result["warnings"]


@pytest.mark.parametrize(
    "forecast,code",
    [([], "no_data"), (HomeAssistantError("offline"), "forecast_failed")],
)
async def test_empty_vs_provider_failure(ha, forecast, code):
    _, create, call, _ = ha
    await create({"hourly": forecast})
    result = await call(day="today")
    assert result["error"]["code"] == code


async def test_concurrent_requests(ha):
    _, create, call, _ = ha
    await create({"hourly": hourly("2030-01-01T00:00:00Z", 48)})
    first, second = await asyncio.gather(
        call(day="today", part_of_day="hours", start_time="09:00"),
        call(day="tomorrow", part_of_day="hours", start_time="17:00"),
    )
    assert first["windows"][0]["periods"][0]["temperature_sample"] == 9
    assert second["windows"][0]["periods"][0]["temperature_sample"] == 41


async def test_subhour_range_is_precision_not_horizon_failure(ha):
    _, create, call, _ = ha
    await create({"hourly": hourly("2030-01-01T14:00:00Z", 4)})
    result = await call(
        day="today", part_of_day="hours", start_time="15:10", end_time="15:20"
    )
    assert result["error"]["code"] == "precision_unavailable"
    assert result["windows"][0]["requested_start"] == "2030-01-01T15:10:00+00:00"
    assert result["windows"][0]["periods"] == []


@pytest.mark.parametrize("second,complete", [("10:30", True), ("10:00", None)])
async def test_hourly_grid_uses_provider_phase(ha, second, complete):
    _, create, call, _ = ha
    await create(
        {
            "hourly": [
                period("2030-01-01T09:30:00Z", 4),
                period(f"2030-01-01T{second}:00Z", 17),
            ]
        }
    )
    result = await call(
        day="today", part_of_day="hours", start_time="09:15", end_time="11:15"
    )
    window = result["windows"][0]
    assert len(window["periods"]) == 2
    assert window["coverage"]["sample_grid_complete"] is complete
    assert "missing_hourly_starts" not in window["coverage"]
    assert window["coverage"]["temporal_completeness"] == "unknown"


@pytest.mark.parametrize("kind,features", [("daily", 1), ("twice_daily", 4)])
async def test_coarse_only_provider_cannot_answer_intraday(ha, kind, features):
    _, create, call, _ = ha
    await create(
        {kind: [period("2030-01-01T06:00:00Z", 24, is_daytime=True)]},
        features=features,
    )
    result = await call(day="today", part_of_day="morning")
    assert result["status"] == "error"
    assert result["error"]["code"] == "precision_unavailable"
    assert result["windows"][0]["periods"] == []
    assert "summary" not in result["windows"][0]
    assert len(result["windows"][0]["context"]) == 1


async def test_errors_preserve_resolved_windows(ha):
    _, create, call, _ = ha
    await create({"hourly": hourly("2030-01-01T00:00:00Z", 24)})
    result = await call(day="tomorrow", part_of_day="morning")
    assert result["error"]["code"] == "out_of_range"
    assert result["source_entity"] == ENTITY
    assert result["available_first_start"] == "2030-01-01T00:00:00+00:00"
    assert result["available_last_start"] == "2030-01-01T23:00:00+00:00"
    assert result["windows"][0]["requested_start"] == "2030-01-02T06:00:00+00:00"
    assert result["windows"][0]["periods"] == []


async def test_missing_units_and_unknown_values(ha):
    hass, create, call, _ = ha
    await create(
        {
            "hourly": [
                period("2030-01-01T09:00:00Z", 18, precipitation_probability=None),
                period("2030-01-01T10:00:00Z", 20, precipitation_probability=0),
            ]
        }
    )
    attrs = dict(hass.states.get(ENTITY).attributes)
    attrs.pop("temperature_unit")
    hass.states.async_set(ENTITY, "unknown", attrs)
    result = await call(
        day="today", part_of_day="hours", start_time="09:00", end_time="11:00"
    )
    assert "temperature" not in result["units"]
    assert result["status"] == "partial"
    assert "missing_unit:temperature" in result["warnings"]
    assert all("temperature_sample" not in r for r in result["windows"][0]["periods"])
    assert (
        result["windows"][0]["summary"]["max_period_precipitation_probability"][
            "sample_count"
        ]
        == 1
    )


async def test_import_reimport_and_assist_response(ha):
    import probatio
    from aiohttp import web
    from homeassistant.components.blueprint.importer import fetch_blueprint_from_url
    from homeassistant.components.homeassistant.exposed_entities import (
        async_expose_entity,
    )
    from homeassistant.components.script.helpers import async_get_blueprints
    from homeassistant.components.script.llm import async_get_tools
    from homeassistant.helpers import llm

    hass, create, call, _ = ha
    content = BLUEPRINT.read_text()

    async def serve(_):
        return web.Response(text=content, content_type="text/plain")

    app = web.Application()
    app.router.add_get("/voice_forecast.yaml", serve)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    url = f"http://127.0.0.1:{runner.addresses[0][1]}/voice_forecast.yaml"
    try:
        assert await async_setup_component(hass, "network", {})
        imported = await fetch_blueprint_from_url(hass, url)
        assert imported.blueprint.metadata["source_url"] == url
        assert (
            imported.blueprint.metadata["homeassistant"]["min_version"] == "2026.11.0"
        )
        assert imported.blueprint.validate() is None
        # The ordinary importer wrote/read a blueprint, not a custom deploy path.
        blueprints = async_get_blueprints(hass)
        await blueprints.async_add_blueprint(
            imported.blueprint, "test/voice_forecast.yaml"
        )
        await create(
            {"hourly": hourly("2030-01-01T00:00:00Z", 24)},
            inputs={"morning_start": "08:00:00"},
        )
        assert await async_setup_component(hass, "homeassistant", {})
        async_expose_entity(hass, "conversation", "script.forecast_fixture", True)
        context = llm.LLMContext(
            platform="test",
            context=None,
            language="en",
            assistant="conversation",
            device_id=None,
        )

        def tool():
            tools = async_get_tools(hass, context, llm.LLM_API_ASSIST)
            return next(t for t in tools.tools if t.name == "script__forecast_fixture")

        first_tool = tool()
        schema = probatio.to_openapi(
            first_tool.parameters, custom_serializer=llm.selector_serializer
        )
        assert schema["required"] == ["day"]
        assert set(schema["properties"]) == {
            "day",
            "weeks_later",
            "days",
            "part_of_day",
            "detail",
            "start_time",
            "end_time",
        }
        assert "tomorrow" in schema["properties"]["day"]["enum"]
        assert schema["properties"]["detail"]["enum"] == ["overview", "hourly"]
        args = {"day": "today", "part_of_day": "morning"}
        result = await first_tool.async_call(
            hass, llm.ToolInput(first_tool.name, args), context
        )
        assert (
            result.data["result"]["windows"][0]["requested_start"]
            == "2030-01-01T08:00:00+00:00"
        )

        content = content.replace(
            "name: Starting day", "name: Starting day (re-imported)"
        )
        content = content.replace(
            "Required. Select the spoken", "Updated contract. Select the spoken"
        )
        updated = await fetch_blueprint_from_url(hass, url)
        await blueprints.async_add_blueprint(
            updated.blueprint, "test/voice_forecast.yaml", allow_override=True
        )
        await hass.async_block_till_done()
        refreshed = tool()
        updated_schema = probatio.to_openapi(
            refreshed.parameters, custom_serializer=llm.selector_serializer
        )
        assert "Updated contract" in updated_schema["properties"]["day"]["description"]
        after = await call(**args)
        assert after["windows"][0]["requested_start"] == "2030-01-01T08:00:00+00:00"
        loaded = await blueprints.async_get_blueprint("test/voice_forecast.yaml")
        assert loaded.metadata["source_url"] == url
    finally:
        await runner.cleanup()
