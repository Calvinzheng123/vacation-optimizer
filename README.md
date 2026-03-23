# Vacation Optimizer

Vacation Optimizer is a travel planning web app for comparing flexible flight windows, hotel options, and full trip combinations in one place at
https://vacation-optimizer.onrender.com

## What It Does

- Flexible flight search across date windows and trip lengths
- One-way and round-trip flight modes
- Airline display and flight search links
- Hotel search with destination suggestions and booking/search links
- Combined planner view for comparing flights and hotels together
- Saved searches for repeated routes

## App Views

- Flights
  Compare route/date combinations, flexible stay lengths, airlines, and fare options.

- Hotels
  Search hotel options by destination and stay dates with pricing, ratings, and booking/search links.

- Planner
  Run flight and hotel searches together so the best options can be reviewed side by side.

## Why It’s Useful

- It supports flexible trip planning instead of single fixed-date searches.
- It helps compare airfare and hotel options without bouncing between separate tools.
- It keeps the experience lightweight and browser-based.

## Built With

- FastAPI
- Jinja2 templates
- SerpApi
- Supabase for cached flight prices

## Notes

- Flight cache rows currently store price only, so richer metadata like airline names and booking links are strongest on live results.
- Hotel booking links may be direct seller links or generated Google Hotels search links when a direct seller link is not available.
- Live search behavior can still be paused with the `SERPAPI_ENABLED` environment switch when needed.
