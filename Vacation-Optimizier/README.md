# Vacation Optimizer

A FastAPI app for comparing flexible flight windows, hotel options, and combined trip plans using SerpApi.

## Features

- Flexible flight search across date windows and trip lengths
- One-way and round-trip flight modes
- Airline display and ticket/search links
- Hotel search with destination suggestions
- Combined planner view for flights and hotels
- Saved flight searches
- Render-ready deployment with `render.yaml`
- Environment controls for enabling/disabling live SerpApi usage

## Stack

- FastAPI
- Jinja2 templates
- SerpApi
- Supabase for cached flight prices
- Render for deployment

## Project Structure

```text
main.py                  FastAPI routes and page rendering
flight_optimizer.py      Flight search, caching, and booking-link logic
hotel_optimizer.py       Hotel search and booking-link logic
templates/               HTML templates for flights, hotels, and planner
static/                  Shared CSS
data/saved_searches.json Local saved search storage
render.yaml              Render blueprint config
```

## Local Setup

1. Create and activate a virtual environment if you want one.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Add environment variables in `.env`:

```env
SERPAPI_KEY=your_serpapi_key
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key
SERPAPI_ENABLED=true
MAX_LIVE_COMBINATIONS=15
```

4. Run the app:

```bash
uvicorn main:app --reload
```

5. Open:

- `http://127.0.0.1:8000/` for flights
- `http://127.0.0.1:8000/hotels` for hotels
- `http://127.0.0.1:8000/planner` for the combined planner

## Environment Controls

The app includes two simple usage controls:

- `SERPAPI_ENABLED=true|false`
  - Turns live SerpApi searches on or off
- `MAX_LIVE_COMBINATIONS=15`
  - Caps how many live flight combinations one search can run

Examples:

```env
SERPAPI_ENABLED=false
```

Disables all live searches.

```env
SERPAPI_ENABLED=true
MAX_LIVE_COMBINATIONS=10
```

Allows live searches with a tighter flight-query cap.

## Deploying To Render

This repo includes [render.yaml](./render.yaml) for Render Blueprint deploys.

1. Push the repo to GitHub.
2. In Render, create a new `Blueprint`.
3. Select the repo.
4. Fill in these secret environment variables:

- `SERPAPI_KEY`
- `SUPABASE_URL`
- `SUPABASE_KEY`

The app will start with:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

## Notes

- Flight cache rows currently store price only, so richer metadata like airline names and booking links are strongest on live results.
- Hotel booking links may be direct seller links or generated Google Hotels search links when a direct seller link is not available.
- Rotate any exposed API keys or secrets before publishing the repo.
