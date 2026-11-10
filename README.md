# ha-blueprints

Reusable Home Assistant blueprints. No household entity IDs, credentials,
provider selection policy, or assistant personality is embedded in them.

## Blueprints

| Blueprint | What it does | Install |
| --- | --- | --- |
| [LLM weather forecast](weather/README.md) | Forecast reports and time-specific weather answers for Assist/LLM agents, with dates resolved in HA's timezone and provider data kept distinct from observations. Requires HA 2026.11.0+. | [![Import blueprint into Home Assistant](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2Ffarooqu%2Fha-blueprints%2Fmain%2Fweather%2Fllm_weather_forecast.yaml) |

Follow each blueprint's documentation for setup, usage, and normal HA re-imports.
