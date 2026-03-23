import os
from datetime import datetime
from urllib.parse import quote_plus

import requests
from dotenv import load_dotenv

load_dotenv()

SERPAPI_KEY = os.getenv("SERPAPI_KEY") or os.getenv("API_KEY")
SERPAPI_ENABLED = os.getenv("SERPAPI_ENABLED", "true").lower() == "true"


def validate_hotel_config():
    if not SERPAPI_ENABLED:
        raise RuntimeError("Live SerpApi searches are currently disabled.")

    if not SERPAPI_KEY:
        raise RuntimeError(
            "Missing SerpApi credentials. Add SERPAPI_KEY to .env "
            "(API_KEY also works for backward compatibility)."
        )


def validate_hotel_inputs(location, check_in, check_out, adults):
    if not location.strip():
        raise RuntimeError("Destination is required.")

    try:
        check_in_date = datetime.strptime(check_in, "%Y-%m-%d").date()
        check_out_date = datetime.strptime(check_out, "%Y-%m-%d").date()
    except ValueError as exc:
        raise RuntimeError("Hotel dates must use YYYY-MM-DD format.") from exc

    if check_in_date >= check_out_date:
        raise RuntimeError("Check-out must be after check-in.")

    if adults <= 0:
        raise RuntimeError("Adults must be greater than 0.")


def extract_hotel_price(property_row):
    total_rate = property_row.get("total_rate", {})
    rate_per_night = property_row.get("rate_per_night", {})
    return (
        total_rate.get("extracted_lowest")
        or rate_per_night.get("extracted_lowest")
        or property_row.get("extracted_price")
    )


def extract_booking_link(property_row):
    direct_link = property_row.get("link")
    if direct_link:
        return direct_link

    prices = property_row.get("prices", [])
    if prices:
        return prices[0].get("link")

    return None


def extract_booking_source(property_row):
    prices = property_row.get("prices", [])
    if prices:
        return prices[0].get("source")
    return None


def build_google_hotels_fallback_link(location, check_in, check_out, adults):
    query = quote_plus(location)
    return (
        "https://www.google.com/travel/hotels"
        f"?q={query}&checkin={check_in}&checkout={check_out}&adults={adults}"
    )


def search_hotels(location, check_in, check_out, adults=1):
    validate_hotel_config()
    validate_hotel_inputs(location, check_in, check_out, adults)

    try:
        response = requests.get(
            "https://serpapi.com/search.json",
            params={
                "engine": "google_hotels",
                "q": location,
                "check_in_date": check_in,
                "check_out_date": check_out,
                "adults": adults,
                "hl": "en",
                "gl": "us",
                "currency": "USD",
                "api_key": SERPAPI_KEY,
            },
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Hotel search failed: {exc}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError("Hotel search returned invalid JSON.") from exc

    properties = data.get("properties", []) + data.get("ads", [])
    results = []
    for property_row in properties:
        price = extract_hotel_price(property_row)
        results.append(
            {
                "name": property_row.get("name", "Unnamed hotel"),
                "type": property_row.get("type", "hotel"),
                "description": property_row.get("description"),
                "hotel_class": property_row.get("hotel_class"),
                "overall_rating": property_row.get("overall_rating"),
                "reviews": property_row.get("reviews"),
                "price": price,
                "price_display": property_row.get("total_rate", {}).get("lowest")
                or property_row.get("rate_per_night", {}).get("lowest")
                or property_row.get("price")
                or "Price unavailable",
                "nightly_price_display": property_row.get("rate_per_night", {}).get("lowest"),
                "booking_link": extract_booking_link(property_row),
                "booking_source": extract_booking_source(property_row),
                "booking_link_type": (
                    "direct"
                    if extract_booking_link(property_row)
                    else "search"
                ),
                "amenities": property_row.get("amenities", [])[:4],
            }
        )

        if not results[-1]["booking_link"]:
            results[-1]["booking_link"] = build_google_hotels_fallback_link(
                location, check_in, check_out, adults
            )
        if not results[-1]["booking_source"]:
            results[-1]["booking_source"] = (
                "Google Hotels"
                if results[-1]["booking_link_type"] == "search"
                else "Hotel website"
            )

    priced_results = [row for row in results if isinstance(row["price"], (int, float))]
    unpriced_results = [row for row in results if not isinstance(row["price"], (int, float))]
    return sorted(priced_results, key=lambda row: row["price"]) + unpriced_results
