#!/usr/bin/env python3
"""OpenWeather MCP Server implementation."""

import argparse
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

import requests
from loguru import logger
from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field


# Set up logging
logger.remove()
logger.add(sys.stderr, level=os.getenv('FASTMCP_LOG_LEVEL', 'WARNING'))
log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'openweather_server.log')
try:
    logger.add(log_path, rotation="10 MB", retention="1 week")
except OSError:
    logger.warning(f"Could not write to log file at {log_path}, falling back to stderr only")

# Initialize FastMCP server
mcp = FastMCP(
    'openweather-mcp-server',
    instructions="""
    # OpenWeather MCP Server

    This server provides tools to interact with OpenWeather API, focusing on current weather and weather forecasts.

    ## Features

    - Get current weather data using coordinates
    - Get weather forecast data using coordinates

    ## Prerequisites

    No API key is required as this server uses the Open-Meteo API which is free and does not require authentication.

    ## Important Note

    This server ONLY accepts latitude and longitude coordinates. You must first obtain coordinates for a location
    before you can get weather data. This design forces a two-step process:
    1. Get coordinates for a location (using another service like aws-location-mcp-server)
    2. Use those coordinates to get weather data

    ## Best Practices

    - Use the get_current_weather_by_coordinates tool for current conditions
    - Use the get_forecast_by_coordinates tool when you need multi-day weather forecasts
    - For temperature units, you can specify 'metric' (Celsius), 'imperial' (Fahrenheit), or 'standard' (Kelvin)
    """,
    dependencies=[
        'requests',
        'pydantic',
    ],
)


class WeatherClient:
    """OpenWeather client wrapper for Open-Meteo API."""

    def __init__(self):
        """Initialize the OpenWeather client."""
        self.base_url = "https://api.open-meteo.com/v1"
        self.geocoding_url = "https://geocoding-api.open-meteo.com/v1/search"
        logger.info("Initializing WeatherClient")
        
        # Configure requests session with optimized settings
        self.session = requests.Session()
        
        # Set optimized timeouts and connection pooling
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=3
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        
        # Weather code mapping
        self.weather_codes = {
            0: "Clear sky",
            1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
            45: "Fog", 48: "Depositing rime fog",
            51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
            56: "Light freezing drizzle", 57: "Dense freezing drizzle",
            61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
            66: "Light freezing rain", 67: "Heavy freezing rain",
            71: "Slight snow fall", 73: "Moderate snow fall", 75: "Heavy snow fall",
            77: "Snow grains",
            80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
            85: "Slight snow showers", 86: "Heavy snow showers",
            95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail"
        }
        
        # Simple caches
        self._geocode_cache = {}
        self._weather_cache = {}
    
    def geocode_location(self, location: str) -> tuple:
        """Convert location name to coordinates using Open-Meteo Geocoding API.
        
        Args:
            location: Location name (city, address, landmark, etc.)
            
        Returns:
            Tuple of (latitude, longitude, location_name) or (None, None, None) if not found
        """
        # Check cache first
        if location in self._geocode_cache:
            cache_entry = self._geocode_cache[location]
            # Check if cache entry is still valid (less than 24 hours old)
            if datetime.now() - cache_entry['timestamp'] < timedelta(hours=24):
                logger.debug(f"Using cached geocoding for {location}")
                return cache_entry['latitude'], cache_entry['longitude'], cache_entry['name']
        
        logger.debug(f"Geocoding location: {location}")
        
        try:
            params = {
                'name': location,
                'count': 1,
                'language': 'en',
                'format': 'json'
            }
            
            response = self.session.get(self.geocoding_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if not data.get('results') or len(data['results']) == 0:
                logger.warning(f"No geocoding results found for {location}")
                return None, None, None
            
            result = data['results'][0]
            latitude = result.get('latitude')
            longitude = result.get('longitude')
            name = result.get('name', '')
            country = result.get('country', '')
            admin1 = result.get('admin1', '')
            
            # Create a formatted location name
            location_name = name
            if admin1 and admin1 != name:
                location_name += f", {admin1}"
            if country:
                location_name += f", {country}"
            
            # Cache the result
            self._geocode_cache[location] = {
                'latitude': latitude,
                'longitude': longitude,
                'name': location_name,
                'timestamp': datetime.now()
            }
            
            logger.debug(f"Geocoded {location} to {latitude}, {longitude} ({location_name})")
            return latitude, longitude, location_name
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error geocoding location {location}: {str(e)}")
            return None, None, None
        except Exception as e:
            logger.error(f"Unexpected error geocoding location {location}: {str(e)}")
            return None, None, None


# Initialize the weather client
weather_client = WeatherClient()



@mcp.tool()
async def get_current_weather_by_coordinates(
    ctx: Context,
    latitude: float = Field(description="Latitude coordinate"),
    longitude: float = Field(description="Longitude coordinate"),
    units: str = Field(
        default="metric",
        description="Units of measurement (metric, imperial, standard)",
        enum=["metric", "imperial", "standard"]
    ),
) -> Dict[str, Any]:
    """Get current weather using latitude and longitude coordinates.
    
    ## Usage
    
    This tool retrieves the current weather conditions for specified coordinates.
    It's useful when you already have precise location data.
    
    ## Result Interpretation
    
    The result includes:
    - location: The coordinates
    - current: Current weather conditions including temperature, humidity, etc.
    - units: The units used for measurements
    
    Args:
        ctx: MCP context for logging and error handling
        latitude: Latitude coordinate
        longitude: Longitude coordinate
        units: Units of measurement (metric, imperial, standard)
        
    Returns:
        Dictionary containing the current weather data
    """
    logger.debug(f"Getting current weather for coordinates: {latitude}, {longitude}, units: {units}")
    
    try:
        # Create cache key
        cache_key = f"{latitude}_{longitude}_{units}_current"
        
        # Check cache
        if cache_key in weather_client._weather_cache:
            cache_entry = weather_client._weather_cache[cache_key]
            # Check if cache entry is still valid (less than 1 hour old)
            if datetime.now() - cache_entry['timestamp'] < timedelta(hours=1):
                logger.debug(f"Using cached weather data for {latitude}, {longitude}")
                return cache_entry['data']
        
        # Prepare API parameters
        temperature_unit = "celsius" if units == "metric" else "fahrenheit" if units == "imperial" else "kelvin"
        wind_speed_unit = "kmh" if units == "metric" else "mph" if units == "imperial" else "ms"
        
        params = {
            'latitude': latitude,
            'longitude': longitude,
            'current': 'temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,rain,showers,snowfall,weather_code,cloud_cover,pressure_msl,surface_pressure,wind_speed_10m,wind_direction_10m,wind_gusts_10m',
            'temperature_unit': temperature_unit,
            'wind_speed_unit': wind_speed_unit,
            'timezone': 'auto'
        }
        
        # Make API request
        response = weather_client.session.get(f"{weather_client.base_url}/forecast", params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Process current weather data
        current_data = data.get('current', {})
        
        if not current_data:
            error_msg = "No current weather data available"
            logger.error(error_msg)
            await ctx.error(error_msg)
            return {"error": error_msg}
        
        # Get weather description from code
        weather_code = current_data.get('weather_code')
        weather_description = weather_client.weather_codes.get(weather_code, "Unknown")
        
        # Format the result
        result = {
            'location': f"Coordinates ({latitude}, {longitude})",
            'current': {
                'time': current_data.get('time'),
                'temperature': current_data.get('temperature_2m'),
                'apparent_temperature': current_data.get('apparent_temperature'),
                'humidity': current_data.get('relative_humidity_2m'),
                'precipitation': current_data.get('precipitation'),
                'rain': current_data.get('rain'),
                'snowfall': current_data.get('snowfall'),
                'cloud_cover': current_data.get('cloud_cover'),
                'pressure': current_data.get('pressure_msl'),
                'wind_speed': current_data.get('wind_speed_10m'),
                'wind_direction': current_data.get('wind_direction_10m'),
                'wind_gusts': current_data.get('wind_gusts_10m'),
                'weather_code': weather_code,
                'weather_description': weather_description
            },
            'units': {
                'temperature': temperature_unit,
                'wind_speed': wind_speed_unit,
                'precipitation': 'mm'
            }
        }
        
        # Cache the result
        weather_client._weather_cache[cache_key] = {
            'data': result,
            'timestamp': datetime.now()
        }
        
        logger.debug(f"Successfully retrieved current weather for coordinates: {latitude}, {longitude}")
        return result
        
    except requests.exceptions.RequestException as e:
        error_msg = f"API request error: {str(e)}"
        logger.error(error_msg)
        await ctx.error(error_msg)
        return {"error": error_msg}
        
    except Exception as e:
        error_msg = f"Error fetching current weather: {str(e)}"
        logger.error(error_msg)
        await ctx.error(error_msg)
        return {"error": error_msg}



@mcp.tool()
async def get_forecast_by_coordinates(
    ctx: Context,
    latitude: float = Field(description="Latitude coordinate"),
    longitude: float = Field(description="Longitude coordinate"),
    days: int = Field(
        default=3,
        description="Number of days (1-16)",
        ge=1,
        le=16
    ),
    units: str = Field(
        default="metric",
        description="Units of measurement (metric, imperial, standard)",
        enum=["metric", "imperial", "standard"]
    ),
) -> Dict[str, Any]:
    """Get weather forecast using latitude and longitude coordinates.
    
    ## Usage
    
    This tool retrieves a multi-day weather forecast for specified coordinates.
    It's useful when you already have precise location data.
    
    ## Result Interpretation
    
    The result includes:
    - location: The coordinates
    - forecast: Daily weather forecasts including temperature, precipitation, etc.
    - units: The units used for measurements
    
    Args:
        ctx: MCP context for logging and error handling
        latitude: Latitude coordinate
        longitude: Longitude coordinate
        days: Number of days to forecast (1-16)
        units: Units of measurement (metric, imperial, standard)
        
    Returns:
        Dictionary containing the forecast data
    """
    logger.debug(f"Getting forecast for coordinates: {latitude}, {longitude}, days: {days}, units: {units}")
    
    try:
        # Create cache key
        cache_key = f"{latitude}_{longitude}_{days}_{units}_forecast"
        
        # Check cache
        if cache_key in weather_client._weather_cache:
            cache_entry = weather_client._weather_cache[cache_key]
            # Check if cache entry is still valid (less than 3 hours old)
            if datetime.now() - cache_entry['timestamp'] < timedelta(hours=3):
                logger.debug(f"Using cached forecast data for {latitude}, {longitude}")
                return cache_entry['data']
        
        # Prepare API parameters
        temperature_unit = "celsius" if units == "metric" else "fahrenheit" if units == "imperial" else "kelvin"
        wind_speed_unit = "kmh" if units == "metric" else "mph" if units == "imperial" else "ms"
        
        params = {
            'latitude': latitude,
            'longitude': longitude,
            'daily': 'weather_code,temperature_2m_max,temperature_2m_min,apparent_temperature_max,apparent_temperature_min,sunrise,sunset,precipitation_sum,rain_sum,showers_sum,snowfall_sum,precipitation_hours,precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max,wind_direction_10m_dominant',
            'temperature_unit': temperature_unit,
            'wind_speed_unit': wind_speed_unit,
            'timezone': 'auto',
            'forecast_days': min(days, 16)  # Open-Meteo supports up to 16 days
        }
        
        # Make API request
        response = weather_client.session.get(f"{weather_client.base_url}/forecast", params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Process forecast data
        daily_data = data.get('daily', {})
        
        if not daily_data or not daily_data.get('time'):
            error_msg = "No forecast data available"
            logger.error(error_msg)
            await ctx.error(error_msg)
            return {"error": error_msg}
        
        # Format the daily forecasts
        daily_forecasts = []
        
        for i in range(len(daily_data['time'])):
            # Get weather description from code
            weather_code = daily_data.get('weather_code', [])[i] if 'weather_code' in daily_data else None
            weather_description = weather_client.weather_codes.get(weather_code, "Unknown") if weather_code is not None else "Unknown"
            
            daily_forecast = {
                'date': daily_data['time'][i],
                'weather_code': weather_code,
                'weather_description': weather_description,
                'temperature_max': daily_data.get('temperature_2m_max', [])[i] if 'temperature_2m_max' in daily_data else None,
                'temperature_min': daily_data.get('temperature_2m_min', [])[i] if 'temperature_2m_min' in daily_data else None,
                'apparent_temperature_max': daily_data.get('apparent_temperature_max', [])[i] if 'apparent_temperature_max' in daily_data else None,
                'apparent_temperature_min': daily_data.get('apparent_temperature_min', [])[i] if 'apparent_temperature_min' in daily_data else None,
                'sunrise': daily_data.get('sunrise', [])[i] if 'sunrise' in daily_data else None,
                'sunset': daily_data.get('sunset', [])[i] if 'sunset' in daily_data else None,
                'precipitation_sum': daily_data.get('precipitation_sum', [])[i] if 'precipitation_sum' in daily_data else None,
                'rain_sum': daily_data.get('rain_sum', [])[i] if 'rain_sum' in daily_data else None,
                'snowfall_sum': daily_data.get('snowfall_sum', [])[i] if 'snowfall_sum' in daily_data else None,
                'precipitation_hours': daily_data.get('precipitation_hours', [])[i] if 'precipitation_hours' in daily_data else None,
                'precipitation_probability': daily_data.get('precipitation_probability_max', [])[i] if 'precipitation_probability_max' in daily_data else None,
                'wind_speed_max': daily_data.get('wind_speed_10m_max', [])[i] if 'wind_speed_10m_max' in daily_data else None,
                'wind_gusts_max': daily_data.get('wind_gusts_10m_max', [])[i] if 'wind_gusts_10m_max' in daily_data else None,
                'wind_direction': daily_data.get('wind_direction_10m_dominant', [])[i] if 'wind_direction_10m_dominant' in daily_data else None
            }
            
            daily_forecasts.append(daily_forecast)
        
        # Format the result
        result = {
            'location': f"Coordinates ({latitude}, {longitude})",
            'forecast': daily_forecasts,
            'units': {
                'temperature': temperature_unit,
                'wind_speed': wind_speed_unit,
                'precipitation': 'mm'
            }
        }
        
        # Cache the result
        weather_client._weather_cache[cache_key] = {
            'data': result,
            'timestamp': datetime.now()
        }
        
        logger.debug(f"Successfully retrieved forecast for coordinates: {latitude}, {longitude}")
        return result
        
    except requests.exceptions.RequestException as e:
        error_msg = f"API request error: {str(e)}"
        logger.error(error_msg)
        await ctx.error(error_msg)
        return {"error": error_msg}
        
    except Exception as e:
        error_msg = f"Error fetching forecast: {str(e)}"
        logger.error(error_msg)
        await ctx.error(error_msg)
        return {"error": error_msg}


def main():
    """Run the MCP server with CLI argument support."""
    parser = argparse.ArgumentParser(
        description='An OpenWeather Model Context Protocol (MCP) server'
    )
    parser.add_argument('--sse', action='store_true', help='Use SSE transport')
    parser.add_argument('--port', type=int, default=8888, help='Port to run the server on')

    args = parser.parse_args()

    # Log startup information
    logger.info('Starting OpenWeather MCP Server')

    # Run server with appropriate transport
    if args.sse:
        logger.info(f'Using SSE transport on port {args.port}')
        mcp.settings.port = args.port
        mcp.run(transport='sse')
    else:
        logger.info('Using standard stdio transport')
        mcp.run()


if __name__ == '__main__':
    main()
