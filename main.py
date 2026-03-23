import json
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from flight_optimizer import scan_flight_prices
from hotel_optimizer import search_hotels

app = FastAPI(title="Flight Optimizer")
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

AIRPORT_SUGGESTIONS = [
    {"code": "ATL", "label": "Atlanta (ATL)"},
    {"code": "AUS", "label": "Austin (AUS)"},
    {"code": "BOS", "label": "Boston (BOS)"},
    {"code": "CLT", "label": "Charlotte (CLT)"},
    {"code": "DEN", "label": "Denver (DEN)"},
    {"code": "DFW", "label": "Dallas-Fort Worth (DFW)"},
    {"code": "EWR", "label": "Newark (EWR)"},
    {"code": "FLL", "label": "Fort Lauderdale (FLL)"},
    {"code": "JFK", "label": "New York JFK (JFK)"},
    {"code": "LAS", "label": "Las Vegas (LAS)"},
    {"code": "LAX", "label": "Los Angeles (LAX)"},
    {"code": "MCO", "label": "Orlando (MCO)"},
    {"code": "MIA", "label": "Miami (MIA)"},
    {"code": "MSP", "label": "Minneapolis (MSP)"},
    {"code": "ORD", "label": "Chicago O'Hare (ORD)"},
    {"code": "PHX", "label": "Phoenix (PHX)"},
    {"code": "SAN", "label": "San Diego (SAN)"},
    {"code": "SEA", "label": "Seattle (SEA)"},
    {"code": "SFO", "label": "San Francisco (SFO)"},
    {"code": "TPA", "label": "Tampa (TPA)"},
]
HOTEL_DESTINATION_SUGGESTIONS = [
    "Miami Beach",
    "Orlando",
    "New York City",
    "Las Vegas",
    "Los Angeles",
    "San Diego",
    "San Francisco",
    "Honolulu",
    "Nashville",
    "Chicago",
    "Paris",
    "London",
    "Rome",
    "Tokyo",
    "Cancun",
]
SAVED_SEARCHES_PATH = Path("data/saved_searches.json")


def format_date(value):
    if not value:
        return "-"
    return datetime.strptime(value, "%Y-%m-%d").strftime("%b %d, %Y")


def normalize_airport(value):
    cleaned = value.strip()
    if "(" in cleaned and cleaned.endswith(")"):
        code = cleaned.rsplit("(", 1)[-1].rstrip(")")
        return code.upper()
    return cleaned.upper()


def cabin_class_options():
    return [
        {"value": "economy", "label": "Economy"},
        {"value": "premium_economy", "label": "Premium Economy"},
        {"value": "business", "label": "Business"},
        {"value": "first", "label": "First"},
    ]


def sort_options():
    return [
        {"value": "price", "label": "Lowest price"},
        {"value": "departure", "label": "Earliest departure"},
        {"value": "trip_length", "label": "Shortest trip"},
    ]


def default_form_data():
    today = date.today()
    default_latest = today + timedelta(days=6)
    return {
        "origin": "CLT",
        "destination": "MIA",
        "earliest_departure": today.isoformat(),
        "latest_departure": default_latest.isoformat(),
        "trip_mode": "round_trip",
        "min_trip_length": 3,
        "max_trip_length": 7,
        "adults": 1,
        "cabin_class": "economy",
        "max_price": "",
        "sort_by": "price",
        "save_name": "",
    }


def default_hotel_form_data():
    today = date.today()
    return {
        "location": "Miami Beach",
        "check_in": today.isoformat(),
        "check_out": (today + timedelta(days=3)).isoformat(),
        "adults": 2,
    }


def default_planner_form_data():
    today = date.today()
    latest_departure = today + timedelta(days=4)
    return {
        "origin": "CLT",
        "destination": "MIA",
        "hotel_location": "Miami Beach",
        "earliest_departure": today.isoformat(),
        "latest_departure": latest_departure.isoformat(),
        "trip_mode": "round_trip",
        "min_trip_length": 3,
        "max_trip_length": 5,
        "adults": 2,
        "cabin_class": "economy",
        "max_price": "",
        "sort_by": "price",
    }


def load_saved_searches():
    if not SAVED_SEARCHES_PATH.exists():
        return []

    try:
        return json.loads(SAVED_SEARCHES_PATH.read_text())
    except json.JSONDecodeError:
        return []


def save_saved_search(name, form_data):
    SAVED_SEARCHES_PATH.parent.mkdir(parents=True, exist_ok=True)
    saved_searches = load_saved_searches()
    record = {"id": str(uuid4()), "name": name, "form_data": form_data}
    saved_searches.insert(0, record)
    SAVED_SEARCHES_PATH.write_text(json.dumps(saved_searches[:10], indent=2))


def format_results(rows):
    formatted = []
    for row in rows:
        trip_label = (
            f"{row['trip_length']} days" if row["trip_length"] is not None else "One way"
        )
        airline_label = ", ".join(row.get("airline_names") or []) or "Not available"
        formatted.append(
            {
                **row,
                "formatted_outbound_date": format_date(row["outbound_date"]),
                "formatted_return_date": format_date(row["return_date"]),
                "formatted_trip_length": trip_label,
                "formatted_cabin_class": row["cabin_class"].replace("_", " ").title(),
                "formatted_airlines": airline_label,
                "formatted_booking_provider": row.get("booking_provider")
                or (
                    "Top results only"
                    if row.get("booking_token")
                    else "Booking details unavailable"
                ),
                "formatted_booking_action": (
                    "Book now" if row.get("booking_link_type") == "direct" else "Open search"
                ),
            }
        )
    return formatted


def sort_results(results, sort_by):
    if sort_by == "departure":
        return sorted(results, key=lambda row: (row["outbound_date"], row["price"]))
    if sort_by == "trip_length":
        return sorted(
            results,
            key=lambda row: (
                row["trip_length"] is None,
                row["trip_length"] or 0,
                row["price"],
            ),
        )
    return sorted(results, key=lambda row: row["price"])


def filter_results(results, max_price):
    if not max_price:
        return results

    try:
        limit = float(max_price)
    except ValueError:
        raise RuntimeError("Max price must be a number.")

    return [row for row in results if row["price"] <= limit]


def build_context(form_data=None, **overrides):
    today = date.today()
    context = {
        "form_data": form_data or default_form_data(),
        "results": [],
        "best_option": None,
        "error": None,
        "message": None,
        "job_complete": False,
        "min_departure": today.isoformat(),
        "airport_suggestions": AIRPORT_SUGGESTIONS,
        "saved_searches": load_saved_searches(),
        "cabin_classes": cabin_class_options(),
        "sort_options": sort_options(),
    }
    context.update(overrides)
    return context


def build_hotel_context(form_data=None, **overrides):
    today = date.today()
    context = {
        "hotel_form_data": form_data or default_hotel_form_data(),
        "hotel_results": [],
        "hotel_best_option": None,
        "hotel_error": None,
        "hotel_message": None,
        "min_stay_date": today.isoformat(),
        "hotel_destination_suggestions": HOTEL_DESTINATION_SUGGESTIONS,
    }
    context.update(overrides)
    return context


def build_planner_context(form_data=None, **overrides):
    today = date.today()
    context = {
        "planner_form_data": form_data or default_planner_form_data(),
        "planner_flight_results": [],
        "planner_hotel_results": [],
        "planner_best_flight": None,
        "planner_best_hotel": None,
        "planner_error": None,
        "planner_message": None,
        "min_departure": today.isoformat(),
        "airport_suggestions": AIRPORT_SUGGESTIONS,
        "hotel_destination_suggestions": HOTEL_DESTINATION_SUGGESTIONS,
        "cabin_classes": cabin_class_options(),
        "sort_options": sort_options(),
    }
    context.update(overrides)
    return context


def create_planner_form_data(
    origin,
    destination,
    hotel_location,
    earliest_departure,
    latest_departure,
    trip_mode,
    min_trip_length,
    max_trip_length,
    adults,
    cabin_class,
    max_price,
    sort_by,
):
    return {
        "origin": normalize_airport(origin),
        "destination": normalize_airport(destination),
        "hotel_location": hotel_location.strip(),
        "earliest_departure": earliest_departure,
        "latest_departure": latest_departure,
        "trip_mode": trip_mode,
        "min_trip_length": min_trip_length,
        "max_trip_length": max_trip_length,
        "adults": adults,
        "cabin_class": cabin_class,
        "max_price": max_price.strip(),
        "sort_by": sort_by,
    }


def validate_form_data(form_data):
    if not form_data["origin"] or not form_data["destination"]:
        raise RuntimeError("Origin and destination are required.")

    start = date.fromisoformat(form_data["earliest_departure"])
    end = date.fromisoformat(form_data["latest_departure"])

    if start > end:
        raise RuntimeError("Latest departure must be on or after the earliest departure date.")

    if form_data["adults"] <= 0:
        raise RuntimeError("Adults must be greater than 0.")

    if form_data["trip_mode"] == "round_trip":
        if form_data["min_trip_length"] <= 0 or form_data["max_trip_length"] <= 0:
            raise RuntimeError("Trip length values must be greater than 0.")

        if form_data["min_trip_length"] > form_data["max_trip_length"]:
            raise RuntimeError(
                "Minimum trip length must be less than or equal to maximum trip length."
            )


def perform_search(form_data):
    validate_form_data(form_data)
    days_to_scan = (
        date.fromisoformat(form_data["latest_departure"])
        - date.fromisoformat(form_data["earliest_departure"])
    ).days + 1

    results = scan_flight_prices(
        origin=form_data["origin"],
        destination=form_data["destination"],
        start_date=form_data["earliest_departure"],
        days_to_scan=days_to_scan,
        min_trip_length=form_data["min_trip_length"],
        max_trip_length=form_data["max_trip_length"],
        trip_mode=form_data["trip_mode"],
        adults=form_data["adults"],
        cabin_class=form_data["cabin_class"],
    )
    results = filter_results(results, form_data["max_price"])
    results = sort_results(results, form_data["sort_by"])
    return format_results(results)


def create_form_data(
    origin,
    destination,
    earliest_departure,
    latest_departure,
    trip_mode,
    min_trip_length,
    max_trip_length,
    adults,
    cabin_class,
    max_price,
    sort_by,
    save_name="",
):
    return {
        "origin": normalize_airport(origin),
        "destination": normalize_airport(destination),
        "earliest_departure": earliest_departure,
        "latest_departure": latest_departure,
        "trip_mode": trip_mode,
        "min_trip_length": min_trip_length,
        "max_trip_length": max_trip_length,
        "adults": adults,
        "cabin_class": cabin_class,
        "max_price": max_price.strip(),
        "sort_by": sort_by,
        "save_name": save_name.strip(),
    }


def format_hotel_results(rows):
    formatted = []
    for row in rows:
        formatted.append(
            {
                **row,
                "formatted_hotel_class": (
                    f"{row['hotel_class']}-star" if row.get("hotel_class") else "Class not listed"
                ),
                "formatted_rating": (
                    f"{row['overall_rating']} / 5"
                    if row.get("overall_rating") is not None
                    else "Rating not listed"
                ),
                "formatted_reviews": (
                    f"{row['reviews']} reviews"
                    if row.get("reviews") is not None
                    else "Review count not listed"
                ),
                "formatted_amenities": ", ".join(row.get("amenities") or []) or "Amenities not listed",
                "formatted_booking_action": (
                    "Direct hotel link"
                    if row.get("booking_link_type") == "direct"
                    else "Google Hotels search link"
                ),
            }
        )
    return formatted


@app.get("/", response_class=HTMLResponse)
def index(request: Request, saved: str | None = None):
    form_data = default_form_data()
    if saved:
        for record in load_saved_searches():
            if record["id"] == saved:
                form_data.update(record["form_data"])
                break

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=build_context(form_data=form_data),
    )


@app.get("/hotels", response_class=HTMLResponse)
def hotels_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="hotels.html",
        context=build_hotel_context(),
    )


@app.get("/planner", response_class=HTMLResponse)
def planner_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="planner.html",
        context=build_planner_context(),
    )


@app.get("/saved-searches/{search_id}")
def apply_saved_search(search_id: str):
    for record in load_saved_searches():
        if record["id"] == search_id:
            return RedirectResponse(url=f"/?saved={search_id}", status_code=303)
    return RedirectResponse(url="/", status_code=303)


@app.post("/saved-searches", response_class=HTMLResponse)
def save_search(
    request: Request,
    origin: str = Form(...),
    destination: str = Form(...),
    earliest_departure: str = Form(...),
    latest_departure: str = Form(...),
    trip_mode: str = Form(...),
    min_trip_length: int = Form(...),
    max_trip_length: int = Form(...),
    adults: int = Form(...),
    cabin_class: str = Form(...),
    max_price: str = Form(""),
    sort_by: str = Form("price"),
    save_name: str = Form(...),
):
    form_data = create_form_data(
        origin,
        destination,
        earliest_departure,
        latest_departure,
        trip_mode,
        min_trip_length,
        max_trip_length,
        adults,
        cabin_class,
        max_price,
        sort_by,
        save_name,
    )

    if not form_data["save_name"]:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context=build_context(
                form_data=form_data,
                error="Give the saved search a short name first.",
            ),
        )

    save_saved_search(form_data["save_name"], {k: v for k, v in form_data.items() if k != "save_name"})

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=build_context(form_data=form_data, message="Saved search added."),
    )


@app.post("/search", response_class=HTMLResponse)
def search(
    request: Request,
    origin: str = Form(...),
    destination: str = Form(...),
    earliest_departure: str = Form(...),
    latest_departure: str = Form(...),
    trip_mode: str = Form(...),
    min_trip_length: int = Form(...),
    max_trip_length: int = Form(...),
    adults: int = Form(...),
    cabin_class: str = Form(...),
    max_price: str = Form(""),
    sort_by: str = Form("price"),
    save_name: str = Form(""),
):
    form_data = create_form_data(
        origin,
        destination,
        earliest_departure,
        latest_departure,
        trip_mode,
        min_trip_length,
        max_trip_length,
        adults,
        cabin_class,
        max_price,
        sort_by,
        save_name,
    )

    try:
        validate_form_data(form_data)
        filter_results([], form_data["max_price"])
    except RuntimeError as exc:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context=build_context(form_data=form_data, error=str(exc)),
        )

    try:
        results = perform_search(form_data)
    except RuntimeError as exc:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context=build_context(form_data=form_data, error=str(exc)),
        )

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=build_context(
            form_data=form_data,
            results=results,
            best_option=results[0] if results else None,
            message="Search complete.",
            job_complete=True,
        ),
    )


@app.post("/hotels/search", response_class=HTMLResponse)
def hotel_search(
    request: Request,
    location: str = Form(...),
    check_in: str = Form(...),
    check_out: str = Form(...),
    adults: int = Form(...),
):
    form_data = {
        "location": location.strip(),
        "check_in": check_in,
        "check_out": check_out,
        "adults": adults,
    }

    try:
        results = format_hotel_results(
            search_hotels(
                location=form_data["location"],
                check_in=form_data["check_in"],
                check_out=form_data["check_out"],
                adults=form_data["adults"],
            )
        )
    except RuntimeError as exc:
        return templates.TemplateResponse(
            request=request,
            name="hotels.html",
            context=build_hotel_context(form_data=form_data, hotel_error=str(exc)),
        )

    return templates.TemplateResponse(
        request=request,
        name="hotels.html",
        context=build_hotel_context(
            form_data=form_data,
            hotel_results=results,
            hotel_best_option=results[0] if results else None,
            hotel_message="Hotel search complete.",
        ),
    )


@app.post("/planner/search", response_class=HTMLResponse)
def planner_search(
    request: Request,
    origin: str = Form(...),
    destination: str = Form(...),
    hotel_location: str = Form(...),
    earliest_departure: str = Form(...),
    latest_departure: str = Form(...),
    trip_mode: str = Form(...),
    min_trip_length: int = Form(...),
    max_trip_length: int = Form(...),
    adults: int = Form(...),
    cabin_class: str = Form(...),
    max_price: str = Form(""),
    sort_by: str = Form("price"),
):
    form_data = create_planner_form_data(
        origin,
        destination,
        hotel_location,
        earliest_departure,
        latest_departure,
        trip_mode,
        min_trip_length,
        max_trip_length,
        adults,
        cabin_class,
        max_price,
        sort_by,
    )

    try:
        flight_results = perform_search(
            {
                "origin": form_data["origin"],
                "destination": form_data["destination"],
                "earliest_departure": form_data["earliest_departure"],
                "latest_departure": form_data["latest_departure"],
                "trip_mode": form_data["trip_mode"],
                "min_trip_length": form_data["min_trip_length"],
                "max_trip_length": form_data["max_trip_length"],
                "adults": form_data["adults"],
                "cabin_class": form_data["cabin_class"],
                "max_price": form_data["max_price"],
                "sort_by": form_data["sort_by"],
                "save_name": "",
            }
        )
        hotel_results = format_hotel_results(
            search_hotels(
                location=form_data["hotel_location"],
                check_in=form_data["earliest_departure"],
                check_out=form_data["latest_departure"],
                adults=form_data["adults"],
            )
        )
    except RuntimeError as exc:
        return templates.TemplateResponse(
            request=request,
            name="planner.html",
            context=build_planner_context(form_data=form_data, planner_error=str(exc)),
        )

    return templates.TemplateResponse(
        request=request,
        name="planner.html",
        context=build_planner_context(
            form_data=form_data,
            planner_flight_results=flight_results,
            planner_hotel_results=hotel_results,
            planner_best_flight=flight_results[0] if flight_results else None,
            planner_best_hotel=hotel_results[0] if hotel_results else None,
            planner_message="Trip planner search complete.",
        ),
    )
