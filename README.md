# OpenWeather MCP Server

An OpenWeather Model Context Protocol (MCP) server that provides weather data using the Open-Meteo API.

## Features

- Get current weather data using coordinates only
- Get weather forecast data using coordinates only
- No API key required (uses Open-Meteo API)
- Caching for improved performance
- Support for metric, imperial, and standard units

## Important Note

This server ONLY accepts latitude and longitude coordinates. You must first obtain coordinates for a location before you can get weather data. This design forces a two-step process:

1. Get coordinates for a location (using another service like aws-location-mcp-server)
2. Use those coordinates to get weather data

## Installation

### From Source

```bash
# Clone the repository
git clone <repository-url>
cd openweather-mcp-server

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows, use: .venv\Scripts\activate

# Install the package in development mode
pip install -e .
```

When you're done working with the project, you can deactivate the virtual environment:

```bash
deactivate
```

## Usage

### Running the Server

You can run the server using the CLI:

```bash
# Run with standard stdio transport (for use with MCP clients)
python openweather_server_cli.py

# Run with SSE transport (for web-based clients)
python openweather_server_cli.py --sse --port 8888
```

### MCP Configuration

To use this server with MCP clients, add the following configuration to your `mcp.json` file:

```json
{
  "servers": [
    {
      "name": "openweather",
      "command": "python /path/to/openweather-mcp-server/openweather_server_cli.py",
      "transport": "stdio"
    }
  ]
}
```

Replace `/path/to/openweather-mcp-server` with the actual path to your installation.

### Environment Variables

- `FASTMCP_LOG_LEVEL`: Set the logging level (default: WARNING)

## Available Tools

### get_current_weather_by_coordinates

Get current weather using latitude and longitude coordinates.

```python
get_current_weather_by_coordinates(
    latitude: float,  # Latitude coordinate
    longitude: float,  # Longitude coordinate
    units: str = "metric"  # Units of measurement (metric, imperial, standard)
)
```

### get_forecast_by_coordinates

Get weather forecast using latitude and longitude coordinates.

```python
get_forecast_by_coordinates(
    latitude: float,  # Latitude coordinate
    longitude: float,  # Longitude coordinate
    days: int = 3,  # Number of days (1-16)
    units: str = "metric"  # Units of measurement (metric, imperial, standard)
)
```

## License

MIT License
