import importlib.util
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SERVER_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))


def _load_service_module(service: str, filename: str):
    service_dir = SERVER_ROOT / "services" / service
    schema_name = f"_{service.replace('-', '_')}_schemas_test"
    schema_spec = importlib.util.spec_from_file_location(schema_name, service_dir / "schemas.py")
    schema_module = importlib.util.module_from_spec(schema_spec)
    assert schema_spec and schema_spec.loader
    schema_spec.loader.exec_module(schema_module)

    module_name = f"_{service.replace('-', '_')}_{filename.replace('.', '_')}_test"
    module_spec = importlib.util.spec_from_file_location(module_name, service_dir / filename)
    module = importlib.util.module_from_spec(module_spec)
    assert module_spec and module_spec.loader
    previous = sys.modules.get("schemas")
    sys.modules["schemas"] = schema_module
    try:
        module_spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop("schemas", None)
        else:
            sys.modules["schemas"] = previous
    return module


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self._payload

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")


class HotelProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.search = _load_service_module("hotel-service", "search.py")

    def test_location_lookup_uses_trimmed_rapidapi_key(self):
        os.environ["RAPIDAPI_KEY"] = "  test-rapid-key  "
        captured = {}

        def fake_get(url, *, headers, params, timeout):
            captured.update(headers=headers, params=params, timeout=timeout)
            return FakeResponse(200, {"data": [{"id": "opaque-location-token"}]})

        with patch.object(self.search.requests, "get", side_effect=fake_get):
            location_id = self.search.find_location_id("London")

        self.assertEqual(location_id, "opaque-location-token")
        self.assertEqual(captured["headers"]["x-rapidapi-key"], "test-rapid-key")
        self.assertGreater(captured["timeout"], 0)

    def test_price_per_night_is_gross_total_divided_by_nights(self):
        os.environ["RAPIDAPI_KEY"] = "test-rapid-key"
        payload = {
            "data": [
                {
                    "name": "Test Hotel",
                    "priceBreakdown": {
                        "grossPrice": {"value": 300},
                        "excludedPrice": {"value": 30},
                    },
                    "reviewScore": 8.7,
                    "reviewCount": 42,
                    "reviewScoreWord": "Excellent",
                    "photoUrls": [],
                }
            ]
        }
        with patch.object(self.search.requests, "get", return_value=FakeResponse(200, payload)):
            hotels = self.search.search_hotels_at(
                "opaque-location-token", "2026-10-15", "2026-10-18", 1
            )

        self.assertEqual(len(hotels), 1)
        self.assertEqual(hotels[0].total_price, 300)
        self.assertEqual(hotels[0].price_per_night, 100)


class FlightLookupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.search = _load_service_module("flight-service", "search.py")

    def test_london_lookup_excludes_airports_from_other_cities(self):
        os.environ["RAPIDAPI_KEY"] = "test-rapid-key"
        payload = {
            "data": [
                {"type": "AIRPORT", "code": "LHR", "cityName": "London", "country": "GB"},
                {"type": "AIRPORT", "code": "LGW", "cityName": "London", "country": "GB"},
                {"type": "AIRPORT", "code": "YXU", "cityName": "London", "country": "CA"},
                {"type": "AIRPORT", "code": "ELS", "cityName": "East London", "country": "ZA"},
            ]
        }
        with patch.object(self.search.requests, "get", return_value=FakeResponse(200, payload)):
            codes = self.search.find_iata_codes("London")

        self.assertEqual(codes, ["LHR", "LGW"])


class GraphFailureTests(unittest.TestCase):
    def test_missing_hotel_is_incomplete_not_approved(self):
        from app.graph.nodes.evaluator import evaluator_agent

        result = evaluator_agent(
            {
                "trip_plan": SimpleNamespace(),
                "selected_flight": object(),
                "selected_hotel": None,
                "flight_options": [],
                "hotel_options": [],
                "refinement_count": 0,
                "hotel_failure_reason": "provider_unauthorized",
            }
        )

        self.assertEqual(result["evaluation_result"].action, "INCOMPLETE")

    def test_scheduler_does_not_call_llm_when_hotel_is_missing(self):
        from app.graph.nodes import scheduler

        state = {
            "trip_plan": SimpleNamespace(days=2, destination="London"),
            "selected_flight": object(),
            "selected_hotel": None,
            "extracted_activities": [
                SimpleNamespace(name="Tower of London", description="Historic tower", time_of_day="Morning")
            ],
            "events": [],
            "refresh": ["activities"],
        }
        with patch.object(scheduler, "invoke_tool_schema") as invoke:
            result = scheduler.activity_scheduling_agent(state)

        invoke.assert_not_called()
        self.assertIsNone(result["final_itinerary"])

    def test_chat_summary_explains_hotel_authentication_failure(self):
        from app.domain.conversation import summarize_completed_plan

        message = summarize_completed_plan(
            "vi",
            {
                "trip_plan": SimpleNamespace(),
                "final_itinerary": None,
                "hotel_failure_reason": "provider_unauthorized",
            },
        )

        self.assertIn("khách sạn", message.lower())
        self.assertIn("xác thực", message.lower())


if __name__ == "__main__":
    unittest.main()
