# WeatherAPI

A Python library for fetching weather data from multiple providers.

## Features
- Support for OpenWeatherMap, WeatherAPI, and AccuWeather
- Automatic caching with configurable TTL
- Async support via httpx
- Temperature unit conversion (C/F/K)

## Installation
pip install weatherapi

## Quick Start
from weatherapi import Weather
w = Weather(api_key="xxx")
print(w.current("London"))
