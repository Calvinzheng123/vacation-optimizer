import argparse
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode

import requests
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SERPAPI_KEY = os.getenv("SERPAPI_KEY") or os.getenv("API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SERPAPI_ENABLED = os.getenv("SERPAPI_ENABLED", "true").lower() == "true"
MAX_LIVE_COMBINATIONS = int(os.getenv("MAX_LIVE_COMBINATIONS", "40"))

CABIN_CLASS_MAP = {
    "economy": "1",
    "premium_economy": "2",
    "business": "3",
    "first": "4",
}
MAX_PARALLEL_LOOKUPS = 6
MAX_PARALLEL_BOOKING_LOOKUPS = 4
MAX_BOOKING_DETAILS_RESULTS = 5


def get_supabase_client():
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None

    return create_client(SUPABASE_URL, SUPABASE_KEY)


def validate_config():
    if not SERPAPI_ENABLED:
        raise RuntimeError("Live SerpApi searches are currently disabled.")

    if not SERPAPI_KEY:
        raise RuntimeError(
            "Missing SerpApi credentials. Add SERPAPI_KEY to .env "
            "(API_KEY also works for backward compatibility)."
        )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Scan a range of trip windows and rank them by lowest flight price."
    )
    parser.add_argument("--origin", default="CLT", help="Origin airport code, e.g. CLT")
    parser.add_argument(
        "--destination", default="MIA", help="Destination airport code, e.g. MIA"
    )
    parser.add_argument(
        "--start-date",
        default="2026-06-10",
        help="First outbound date to scan in YYYY-MM-DD format",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="How many outbound dates to scan, starting from start-date",
    )
    parser.add_argument(
        "--trip-length",
        type=int,
        default=3,
        help="Trip length in days before the return flight",
    )
    parser.add_argument(
        "--trip-mode",
        choices=["round_trip", "one_way"],
        default="round_trip",
        help="Search round-trip or one-way fares",
    )
    parser.add_argument("--adults", type=int, default=1, help="Number of adult travelers")
    parser.add_argument(
        "--cabin-class",
        choices=sorted(CABIN_CLASS_MAP),
        default="economy",
        help="Cabin class to search",
    )
    return parser.parse_args()


def normalize_inputs(
    start_date,
    days_to_scan,
    min_trip_length,
    max_trip_length,
    trip_mode,
    adults,
    cabin_class,
):
    try:
        datetime.strptime(start_date, "%Y-%m-%d")
    except ValueError as exc:
        raise RuntimeError("start-date must use YYYY-MM-DD format.") from exc

    if days_to_scan <= 0:
        raise RuntimeError("days must be greater than 0.")

    if adults <= 0:
        raise RuntimeError("adults must be greater than 0.")

    if cabin_class not in CABIN_CLASS_MAP:
        raise RuntimeError("Unsupported cabin class.")

    if trip_mode not in {"round_trip", "one_way"}:
        raise RuntimeError("trip-mode must be round_trip or one_way.")

    if trip_mode == "round_trip":
        if min_trip_length <= 0 or max_trip_length <= 0:
            raise RuntimeError("trip lengths must be greater than 0.")

        if min_trip_length > max_trip_length:
            raise RuntimeError(
                "min-trip-length must be less than or equal to max-trip-length."
            )


def can_use_cache(trip_mode, adults, cabin_class):
    return trip_mode == "round_trip" and adults == 1 and cabin_class == "economy"


def build_search_params(
    origin,
    destination,
    outbound_date,
    return_date,
    trip_mode,
    adults,
    cabin_class,
):
    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": outbound_date,
        "currency": "USD",
        "hl": "en",
        "gl": "us",
        "type": "1" if trip_mode == "round_trip" else "2",
        "travel_class": CABIN_CLASS_MAP[cabin_class],
        "adults": str(adults),
        "api_key": SERPAPI_KEY,
    }

    if trip_mode == "round_trip" and return_date:
        params["return_date"] = return_date

    return params


def get_cheapest_flight(
    origin,
    destination,
    outbound_date,
    return_date,
    trip_mode="round_trip",
    adults=1,
    cabin_class="economy",
):
    url = "https://serpapi.com/search.json"
    params = build_search_params(
        origin=origin,
        destination=destination,
        outbound_date=outbound_date,
        return_date=return_date,
        trip_mode=trip_mode,
        adults=adults,
        cabin_class=cabin_class,
    )

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"SerpApi request failed for {outbound_date} -> {return_date}: {exc}")
        return None

    try:
        data = response.json()
    except ValueError:
        print(f"SerpApi returned invalid JSON for {outbound_date} -> {return_date}")
        return None

    flights = data.get("best_flights", []) + data.get("other_flights", [])
    priced_flights = [
        flight for flight in flights if isinstance(flight.get("price"), (int, float))
    ]
    if not priced_flights:
        return None

    return min(priced_flights, key=lambda flight: flight["price"])


def extract_airlines(flight_result):
    airlines = []
    for segment in flight_result.get("flights", []):
        airline = segment.get("airline")
        if airline and airline not in airlines:
            airlines.append(airline)
    return airlines


def build_booking_link(booking_request):
    if not booking_request:
        return None

    url = booking_request.get("url")
    post_data = booking_request.get("post_data")
    if not url:
        return None

    if not post_data:
        return url

    query_string = urlencode(parse_qsl(post_data, keep_blank_values=True))
    if not query_string:
        return url

    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{query_string}"


def build_google_flights_fallback_link(
    origin,
    destination,
    outbound_date,
    return_date,
    trip_mode,
):
    flight_path = f"{origin}.{destination}.{outbound_date}"
    if trip_mode == "round_trip" and return_date:
        flight_path = f"{flight_path}.{return_date}"

    return f"https://www.google.com/flights#flt={flight_path};c:USD;e:1;sd:1;t:f"


def get_booking_details(booking_token):
    if not booking_token:
        return {}

    try:
        response = requests.get(
            "https://serpapi.com/search.json",
            params={
                "engine": "google_flights",
                "booking_token": booking_token,
                "api_key": SERPAPI_KEY,
            },
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"SerpApi booking lookup failed for token {booking_token[:12]}...: {exc}")
        return {}

    try:
        data = response.json()
    except ValueError:
        print("SerpApi returned invalid JSON for booking lookup")
        return {}

    options = data.get("booking_options", [])
    if not options:
        return {}

    first_option = options[0]
    booking_info = (
        first_option.get("together")
        or first_option.get("departing")
        or first_option.get("returning")
        or {}
    )

    return {
        "booking_provider": booking_info.get("book_with"),
        "booking_link": build_booking_link(booking_info.get("booking_request")),
    }


def get_cached_price(supabase, origin, destination, outbound_date, return_date):
    if supabase is None:
        return None

    try:
        result = (
            supabase.table("flight_quotes")
            .select("price")
            .eq("origin", origin)
            .eq("destination", destination)
            .eq("outbound_date", outbound_date)
            .eq("return_date", return_date)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        print(
            "Supabase cache lookup failed for "
            f"{origin} -> {destination} on {outbound_date}: {exc}"
        )
        return None

    if result.data:
        return result.data[0]["price"]
    return None


def save_price(supabase, origin, destination, outbound_date, return_date, price):
    if supabase is None:
        return

    payload = {
        "origin": origin,
        "destination": destination,
        "outbound_date": outbound_date,
        "return_date": return_date,
        "price": price,
    }

    try:
        supabase.table("flight_quotes").upsert(
            payload,
            on_conflict="origin,destination,outbound_date,return_date",
        ).execute()
    except Exception as exc:
        print(
            "Supabase cache save failed for "
            f"{origin} -> {destination} on {outbound_date}: {exc}"
        )


def build_result_row(
    origin,
    destination,
    outbound_date,
    return_date,
    trip_length,
    price,
    trip_mode,
    adults,
    cabin_class,
    airline_names=None,
    booking_token=None,
    booking_provider=None,
    booking_link=None,
    source="live",
    booking_link_type="direct",
):
    return {
        "origin": origin,
        "destination": destination,
        "outbound_date": outbound_date,
        "return_date": return_date,
        "trip_length": trip_length,
        "price": price,
        "trip_mode": trip_mode,
        "adults": adults,
        "cabin_class": cabin_class,
        "airline_names": airline_names or [],
        "booking_token": booking_token,
        "booking_provider": booking_provider,
        "booking_link": booking_link,
        "source": source,
        "booking_link_type": booking_link_type,
    }


def enrich_results_with_booking_details(results):
    live_rows = [
        row
        for row in sorted(results, key=lambda row: row["price"])
        if row.get("booking_token")
    ][:MAX_BOOKING_DETAILS_RESULTS]
    if not live_rows:
        return

    max_workers = min(MAX_PARALLEL_BOOKING_LOOKUPS, len(live_rows))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(get_booking_details, row["booking_token"]): row
            for row in live_rows
        }

        for future in as_completed(future_map):
            row = future_map[future]
            details = future.result()
            row["booking_provider"] = details.get("booking_provider")
            row["booking_link"] = details.get("booking_link")


def scan_flight_prices(
    origin,
    destination,
    start_date,
    days_to_scan,
    min_trip_length=1,
    max_trip_length=1,
    trip_mode="round_trip",
    adults=1,
    cabin_class="economy",
):
    validate_config()
    normalize_inputs(
        start_date,
        days_to_scan,
        min_trip_length,
        max_trip_length,
        trip_mode,
        adults,
        cabin_class,
    )

    supabase = get_supabase_client()
    use_cache = can_use_cache(trip_mode, adults, cabin_class)
    results = []
    current = datetime.strptime(start_date, "%Y-%m-%d")
    live_queries = []
    total_combinations = days_to_scan * (
        (max_trip_length - min_trip_length + 1) if trip_mode == "round_trip" else 1
    )

    if total_combinations > MAX_LIVE_COMBINATIONS:
        raise RuntimeError(
            "This search is too wide for live mode right now. "
            f"Try {MAX_LIVE_COMBINATIONS} combinations or fewer, or narrow your dates/trip length."
        )

    for _ in range(days_to_scan):
        outbound_date = current.strftime("%Y-%m-%d")
        trip_lengths = (
            range(min_trip_length, max_trip_length + 1)
            if trip_mode == "round_trip"
            else [None]
        )

        for trip_length in trip_lengths:
            return_date = (
                (current + timedelta(days=trip_length)).strftime("%Y-%m-%d")
                if trip_length is not None
                else None
            )

            cached_price = None
            if use_cache and return_date is not None:
                cached_price = get_cached_price(
                    supabase, origin, destination, outbound_date, return_date
                )

            if cached_price is not None:
                price = cached_price
                print(f"[SUPABASE CACHE] {outbound_date} -> {return_date}: ${price}")
                results.append(
                    build_result_row(
                        origin=origin,
                        destination=destination,
                        outbound_date=outbound_date,
                        return_date=return_date,
                        trip_length=trip_length,
                        price=price,
                        trip_mode=trip_mode,
                        adults=adults,
                        cabin_class=cabin_class,
                        airline_names=[],
                        source="cache",
                        booking_link=build_google_flights_fallback_link(
                            origin,
                            destination,
                            outbound_date,
                            return_date,
                            trip_mode,
                        ),
                        booking_link_type="search",
                    )
                )
            else:
                live_queries.append(
                    {
                        "origin": origin,
                        "destination": destination,
                        "outbound_date": outbound_date,
                        "return_date": return_date,
                        "trip_length": trip_length,
                        "trip_mode": trip_mode,
                        "adults": adults,
                        "cabin_class": cabin_class,
                    }
                )

        current += timedelta(days=1)

    if live_queries:
        max_workers = min(MAX_PARALLEL_LOOKUPS, len(live_queries))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(
                    get_cheapest_flight,
                    query["origin"],
                    query["destination"],
                    query["outbound_date"],
                    query["return_date"],
                    query["trip_mode"],
                    query["adults"],
                    query["cabin_class"],
                ): query
                for query in live_queries
            }

            for future in as_completed(future_map):
                query = future_map[future]
                flight = future.result()
                price = flight.get("price") if flight else None
                print(
                    "[SERPAPI]        "
                    f"{query['outbound_date']} -> {query['return_date']}: ${price}"
                )

                if use_cache and price is not None and query["return_date"] is not None:
                    save_price(
                        supabase,
                        query["origin"],
                        query["destination"],
                        query["outbound_date"],
                        query["return_date"],
                        price,
                    )

                if price is not None:
                    results.append(
                        build_result_row(
                            origin=query["origin"],
                            destination=query["destination"],
                            outbound_date=query["outbound_date"],
                            return_date=query["return_date"],
                            trip_length=query["trip_length"],
                            price=price,
                            trip_mode=query["trip_mode"],
                            adults=query["adults"],
                            cabin_class=query["cabin_class"],
                            airline_names=extract_airlines(flight),
                            booking_token=flight.get("booking_token"),
                            source="live",
                            booking_link=build_google_flights_fallback_link(
                                query["origin"],
                                query["destination"],
                                query["outbound_date"],
                                query["return_date"],
                                query["trip_mode"],
                            ),
                            booking_link_type="search",
                        )
                    )

    enrich_results_with_booking_details(results)
    return sorted(results, key=lambda row: row["price"])


def main():
    args = parse_args()

    try:
        results = scan_flight_prices(
            origin=args.origin.upper(),
            destination=args.destination.upper(),
            start_date=args.start_date,
            days_to_scan=args.days,
            min_trip_length=args.trip_length,
            max_trip_length=args.trip_length,
            trip_mode=args.trip_mode,
            adults=args.adults,
            cabin_class=args.cabin_class,
        )
    except RuntimeError as exc:
        print(exc)
        return 1

    print("\nCheapest windows:")
    for row in results:
        trip_label = (
            f"{row['outbound_date']} -> {row['return_date']}"
            if row["trip_mode"] == "round_trip"
            else row["outbound_date"]
        )
        print(f"{trip_label} | ${row['price']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
