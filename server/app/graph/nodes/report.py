"""Node ve ban do Folium va soan bao cao Markdown/HTML."""


import folium
import folium.plugins
import markdown2
import os
from app.domain.reply_format import (
    format_event_options_markdown,
    format_flight_options_markdown,
    format_hotel_options_markdown,
)
from app.domain.planning_issues import collect_planning_issues
from app.domain.photos import verified_photo_url
from app.core.config import OUTPUT_DIR
from app.graph.state import TripState
from datetime import datetime, timedelta


def _report_stem(state: TripState) -> str:
    """Tên file report theo PHIÊN chat, không dùng chung một file cho mọi người."""
    for key in ("session_id", "telemetry_run_id"):
        value = state.get(key)
        if value:
            safe = "".join(ch for ch in str(value) if ch.isalnum() or ch in "-_")[:64]
            if safe:
                return safe
    return "unsessioned"


def map_generator_node(state: TripState) -> dict:
    """Generates an interactive Folium map from the final itinerary and returns its HTML content."""
    print("--- Running Map Generator ---")
    final_itinerary = state.get("final_itinerary")

    if final_itinerary and final_itinerary.daily_plans:
        geocoded_count = sum(1 for day in final_itinerary.daily_plans for act in day.activities if act.latitude)
        print(f"-> Itinerary received. Found {geocoded_count} geocoded activities to plot on the map.")
    
    

    if not final_itinerary or not final_itinerary.daily_plans:
        return {"map_html": None} 

    first_coord = None
    all_coords = [] 
    for day in final_itinerary.daily_plans:
        for activity in day.activities:
            if activity.latitude and activity.longitude:
                coord = (activity.latitude, activity.longitude)
                all_coords.append(coord)
                if first_coord is None:
                    first_coord = coord
    
    if not first_coord:
        print("-> No coordinates found in the itinerary to create a map.")
        return {"map_html": None}

    m = folium.Map(location=first_coord, zoom_start=13)

    marker_cluster = folium.plugins.MarkerCluster().add_to(m)
    
    colors = ['blue', 'green', 'purple', 'orange', 'darkred', 'cadetblue', 'pink', 'lightgray']
    
    activity_counter = 1
    for i, day_plan in enumerate(final_itinerary.daily_plans):
        day_color = colors[i % len(colors)] 
        for activity in day_plan.activities:
            if activity.latitude and activity.longitude:
                popup_html = f"<b>Day {day_plan.day}: {activity.name}</b><br>{activity.description}"
                folium.Marker(
                    [activity.latitude, activity.longitude],
                    popup=popup_html,
                    tooltip=f"Day {day_plan.day} - {activity_counter}. {activity.name}",
                    icon=folium.Icon(color=day_color, icon='info-sign')
                ).add_to(marker_cluster) 
                activity_counter += 1

    if all_coords:
        m.fit_bounds(m.get_bounds())

    map_html_content = m._repr_html_()
    
    print(f"-> Interactive map HTML generated.")
    
    return {"map_html": map_html_content}

VI_MONTHS = [
    "", "tháng 1", "tháng 2", "tháng 3", "tháng 4", "tháng 5", "tháng 6",
    "tháng 7", "tháng 8", "tháng 9", "tháng 10", "tháng 11", "tháng 12",
]

REPORT_LABELS = {
    "en": {
        "failed_title": "Trip Plan Could Not Be Generated",
        "no_flights": "Sorry, no flights matching your criteria were found.",
        "no_hotels": "Sorry, no hotels matching your criteria were found.",
        "failed_generic": "A valid trip plan could not be generated with the available options. Please try modifying your request.",
        "title": "Your Trip to {destination} ({start} - {end})",
        "budget_summary": "Budget Summary",
        "flight_hotel_cost": "Flight + Hotel Cost",
        "daily_spending": "Estimated Daily Spending (for {days} days)",
        "total_cost": "Total Estimated Cost",
        "your_budget": "Your Total Budget",
        "under_budget": "Plan is **€{amount:,.2f} under budget**.",
        "over_budget": "Plan is **€{amount:,.2f} over budget**.",
        "status": "Status",
        "flight_info": "Flight Information",
        "airline": "Airline",
        "total_price_people": "Total Price (for {person} people)",
        "time": "Time",
        "details": "Details",
        "airport": "Airport",
        "depart": "Depart",
        "return": "Return",
        "total_journey": "Total Journey",
        "layover": "Layover",
        "at": "at",
        "arriving": "Arriving At",
        "other_flights": "Other Booking.com options",
        "other_hotels": "Other hotel options",
        "hotel_info": "Hotel Information",
        "rating": "Rating",
        "based_on": "based on {count} reviews",
        "taxes": "Taxes and Fees",
        "total_price_stay": "Total Price (for {nights} nights, {person} people)",
        "location": "Location",
        "on_maps": "on Google Maps",
        "events": "Events & Concerts During Your Stay",
        "date": "Date",
        "event": "Event",
        "venue": "Venue",
        "daily": "Daily Itinerary",
        "no_activities": "No specific activities planned for this trip.",
        "day": "Day {day}",
    },
    "vi": {
        "failed_title": "Không tạo được kế hoạch chuyến đi",
        "no_flights": "Không tìm thấy chuyến bay phù hợp.",
        "no_hotels": "Không tìm thấy khách sạn phù hợp.",
        "failed_generic": "Không tạo được kế hoạch hợp lệ với các lựa chọn hiện có. Bạn thử điều chỉnh yêu cầu nhé.",
        "title": "Chuyến đi tới {destination} ({start} - {end})",
        "budget_summary": "Tổng quan ngân sách",
        "flight_hotel_cost": "Chi phí máy bay + khách sạn",
        "daily_spending": "Chi tiêu hàng ngày ước tính (trong {days} ngày)",
        "total_cost": "Tổng chi phí ước tính",
        "your_budget": "Ngân sách của bạn",
        "under_budget": "Kế hoạch **tiết kiệm €{amount:,.2f}** so với ngân sách.",
        "over_budget": "Kế hoạch **vượt ngân sách €{amount:,.2f}**.",
        "status": "Tình trạng",
        "flight_info": "Thông tin chuyến bay",
        "airline": "Hãng bay",
        "total_price_people": "Tổng giá (cho {person} người)",
        "time": "Giờ",
        "details": "Chi tiết",
        "airport": "Sân bay",
        "depart": "Chiều đi",
        "return": "Chiều về",
        "total_journey": "Tổng hành trình",
        "layover": "Quá cảnh",
        "at": "tại",
        "arriving": "Hạ cánh",
        "other_flights": "Các lựa chọn khác từ Booking.com",
        "other_hotels": "Các khách sạn khác",
        "hotel_info": "Thông tin khách sạn",
        "rating": "Đánh giá",
        "based_on": "dựa trên {count} đánh giá",
        "taxes": "Thuế và phí",
        "total_price_stay": "Tổng giá (cho {nights} đêm, {person} người)",
        "location": "Vị trí",
        "on_maps": "trên Google Maps",
        "events": "Sự kiện trong thời gian lưu trú",
        "date": "Ngày",
        "event": "Sự kiện",
        "venue": "Địa điểm",
        "daily": "Lịch trình từng ngày",
        "no_activities": "Chưa có hoạt động cụ thể cho chuyến đi này.",
        "day": "Ngày {day}",
    },
}

def _report_language(state: TripState) -> str:
    raw = (state.get("language") or "en").strip().lower().replace("_", "-")
    if "-" in raw:
        raw = raw.split("-", 1)[0]
    return raw if raw in REPORT_LABELS else "en"

def _report_labels(language: str) -> dict:
    return REPORT_LABELS.get(language, REPORT_LABELS["en"])

def _format_report_date(date_str: str, language: str) -> str:
    dt_obj = datetime.strptime(date_str, "%Y-%m-%d")
    if language == "vi":
        return f"{dt_obj.day} {VI_MONTHS[dt_obj.month]} {dt_obj.year}"
    return dt_obj.strftime("%B %d, %Y")

def report_formattor_node(state: TripState) -> dict:
    """Takes the final trip plan and generates a richly formatted Markdown report with all details."""
    print("--- Report Formatter is running ---")
    itinerary = state.get("final_itinerary")
    trip_plan = state.get("trip_plan")
    evaluation = state.get("evaluation_result")
    events = state.get("events")
    map_html_content = state.get("map_html")
    language = _report_language(state)
    labels = _report_labels(language)
    
    if not itinerary or not trip_plan or not itinerary.selected_flight or not itinerary.selected_hotel:
        final_report_md = f"# {labels['failed_title']}\n\n"
        issues = collect_planning_issues(state, language)
        final_report_md += "\n".join(f"- {issue}" for issue in issues)
        if not issues:
            final_report_md += labels["failed_generic"]
        flight_list = format_flight_options_markdown(
            state.get("flight_options") or [],
            language,
        )
        hotel_list = format_hotel_options_markdown(
            state.get("hotel_options") or [],
            language,
            destination=getattr(trip_plan, "destination", None) if trip_plan else None,
            include_photos=False,
        )
        if flight_list:
            final_report_md += "\n\n" + flight_list + "\n"
        if hotel_list:
            final_report_md += "\n\n" + hotel_list + "\n"
    else:
        def format_duration(minutes: int) -> str:
            if not minutes: return ""
            hours, mins = divmod(minutes, 60)
            return f"{hours}h {mins}m"
            
        def format_date(date_str: str) -> str:
            return _format_report_date(date_str, language)

        md = (
            f"# {labels['title'].format(destination=trip_plan.destination, start=format_date(trip_plan.start_date), end=format_date(trip_plan.end_date))}\n\n"
        )
        
        md += f"## {labels['budget_summary']}\n"
        total_cost = evaluation.total_cost
        budget = trip_plan.budget

        flight_and_hotel_cost = itinerary.selected_flight.price + itinerary.selected_hotel.total_price
        total_daily_spending = total_cost - flight_and_hotel_cost

        md += f"- **{labels['flight_hotel_cost']}:** €{flight_and_hotel_cost:,.2f}\n"
        if total_daily_spending > 0:
            md += f"- **{labels['daily_spending'].format(days=trip_plan.days)}:** €{total_daily_spending:,.2f}\n"
        md += f"------------------------------------\n"
        md += f"- **{labels['total_cost']}:** €{total_cost:,.2f}\n"
        if budget is not None:
            from app.domain.money import budget_label as format_budget

            md += f"- **{labels['your_budget']}:** {format_budget(trip_plan)}\n\n"
            if getattr(trip_plan, "children_charged_as_adults", False):
                if language == "vi":
                    note = (
                        f"Lưu ý: {trip_plan.children} trẻ em chưa có tuổi nên tạm tính như "
                        "người lớn. Cho mình tuổi của bé thì mình tính lại theo giá trẻ em."
                    )
                else:
                    note = (
                        f"Note: {trip_plan.children} child(ren) have no stated age, so they are "
                        "priced as adults. Share their ages and this will be recalculated."
                    )
                md += f"- {note}\n\n"
            if total_cost <= budget:
                md += f"- **{labels['status']}:** {labels['under_budget'].format(amount=budget - total_cost)}\n\n"
            else:
                md += f"- **{labels['status']}:** {labels['over_budget'].format(amount=total_cost - budget)}\n\n"
        else:
            md += "\n"

        md += f"## {labels['flight_info']}\n"
        flight = itinerary.selected_flight
        dep_leg = flight.departure_leg
        ret_leg = flight.return_leg
        
        md += f"**{labels['airline']}:** {dep_leg.airline}\n"
        md += f"**{labels['total_price_people'].format(person=trip_plan.person)}:** €{flight.price:,.2f}\n\n"
        md += f"|  | {labels['time']} | {labels['details']} | {labels['airport']} |\n"
        md += "|:---|:---|:---|:---|\n"
        
        aircraft_dep = f"({dep_leg.aircraft_type})" if dep_leg.aircraft_type else ""
        details_depart = f"**{dep_leg.flight_number}** {aircraft_dep}"
        md += f"| **{labels['depart']}**<br>*{format_date(trip_plan.start_date)}* | **{dep_leg.departure_time}** | {details_depart} | **{dep_leg.departure_airport}** |\n"
        md += f"| | *{format_duration(dep_leg.duration_minutes)}* | {labels['total_journey']} | |\n"

        if dep_leg.is_layover:
            md += f"| | | *{format_duration(dep_leg.layover_duration_minutes)} {labels['layover']}* | *{labels['at']} {dep_leg.layover_airport}* |\n"
        md += f"| | **{dep_leg.arrival_time}** | {labels['arriving']} | **{dep_leg.arrival_airport}** |\n"
        md += "| | | | |\n"

        if ret_leg:
            aircraft_ret = f"({ret_leg.aircraft_type})" if ret_leg.aircraft_type else ""
            details_return = f"**{ret_leg.flight_number}** {aircraft_ret}"
            md += f"| **{labels['return']}**<br>*{format_date(trip_plan.end_date)}* | **{ret_leg.departure_time}** | {details_return} | **{ret_leg.departure_airport}** |\n"
            md += f"| | *{format_duration(ret_leg.duration_minutes)}* | {labels['total_journey']} | |\n"

            if ret_leg.is_layover:
                md += f"| | | *{format_duration(ret_leg.layover_duration_minutes)} {labels['layover']}* | *{labels['at']} {ret_leg.layover_airport}* |\n"
            md += f"| | **{ret_leg.arrival_time}** | {labels['arriving']} | **{ret_leg.arrival_airport}** |\n\n"
        else:
            md += "\n"

        other_flights = format_flight_options_markdown(
            [item for item in (state.get("flight_options") or []) if item != flight],
            language,
            limit=6,
            heading=False,
        )
        if other_flights:
            md += f"### {labels['other_flights']}\n{other_flights}\n\n"


        num_nights = (datetime.strptime(trip_plan.end_date, "%Y-%m-%d") - datetime.strptime(trip_plan.start_date, "%Y-%m-%d")).days
        hotel = itinerary.selected_hotel
        
        md += f"## {labels['hotel_info']}\n"
        
        # Anh Booking.com co chu ky; mot chu ky lem (hoac het han) lam CDN tra 401 va
        # report — duoc luu lai de hien thi nhieu lan — dinh bieu tuong anh vo.
        photo_url = verified_photo_url(hotel.main_photo_url)
        if photo_url:
            md += f"![{hotel.hotel_name}]({photo_url})\n\n"
        else:
            print("-> Bo anh khach san: CDN tu choi URL (chu ky sai/het han).")

        md += f"### {hotel.hotel_name}\n"
        md += f"**{labels['rating']}:** {hotel.rating} / 10.0 ({hotel.rating_word} {labels['based_on'].format(count=hotel.review_count)})\n"
        md += f"**{labels['taxes']}:** ~€{hotel.price_per_night:,.2f}\n" 
        md += f"**{labels['total_price_stay'].format(nights=num_nights, person=trip_plan.person)}:** €{hotel.total_price:,.2f}\n"
        
        google_maps_url = f"https://www.google.com/maps/search/?api=1&query={hotel.hotel_name.replace(' ', '+')}"
        md += f"- **{labels['location']}:** [{hotel.hotel_name} {labels['on_maps']}]({google_maps_url})\n\n"

        other_hotels = format_hotel_options_markdown(
            [
                item
                for item in (state.get("hotel_options") or [])
                if getattr(item, "hotel_name", None) != hotel.hotel_name
            ],
            language,
            limit=6,
            heading=False,
            include_photos=False,
        )
        if other_hotels:
            md += f"### {labels['other_hotels']}\n{other_hotels}\n\n"

        if events:
            md += f"---\n\n## {labels['events']}\n"
            event_list = format_event_options_markdown(events, language, heading=False)
            md += event_list + "\n\n"

        
        md += f"---\n\n## {labels['daily']}\n"
        if not itinerary.daily_plans:
            md += labels["no_activities"]
        else:
            start_date_obj = datetime.strptime(trip_plan.start_date, "%Y-%m-%d")
            activity_counter = 1
            for day_plan in itinerary.daily_plans:
                current_date = start_date_obj + timedelta(days=day_plan.day - 1)
                md += f"\n### {labels['day'].format(day=day_plan.day)} - {format_date(current_date.strftime('%Y-%m-%d'))}\n"
                for activity in day_plan.activities:
                    md += f"- **{activity.time_of_day}: {activity_counter}. {activity.name}**\n"
                    md += f"  - *{activity.description}*\n"
                
                    if activity.latitude and activity.longitude:
                        location_url = f"https://www.google.com/maps?q={activity.latitude},{activity.longitude}"
                        md += f"  - {labels['location']}: [{activity.name}]({location_url})\n"
                    else:
                        location_url = f"https://www.google.com/maps?q={activity.name.replace(' ', '+')}+{trip_plan.destination.replace(' ', '+')}"
                        md += f"  - {labels['location']}: [{activity.name}]({location_url})\n"
                
                    activity_counter += 1

        final_report_md = md

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    # Mỗi phiên một file riêng: trước đây tất cả ghi vào MỘT file nên chat chạy song
    # song ghi đè lẫn nhau, và mở lại chat cũ không biết report nào là của mình.
    stem = _report_stem(state)
    reports_dir = os.path.join(OUTPUT_DIR, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    md_path = os.path.join(reports_dir, f"{stem}.md")
    html_path = os.path.join(reports_dir, f"{stem}.html")
    # Bản "mới nhất" giữ lại cho tiện mở nhanh khi debug; có thể bị lượt chat khác ghi đè.
    latest_md_path = os.path.join(OUTPUT_DIR, "trip_itinerary.md")
    latest_html_path = os.path.join(OUTPUT_DIR, "trip_itinerary.html")

    try:
        for path in (md_path, latest_md_path):
            with open(path, "w", encoding="utf-8") as f: f.write(final_report_md)
        print(f"-> Markdown report saved to: {md_path}")
        print(f"-> Latest copy (co the bi luot chat khac ghi de): {latest_md_path}")
        
        css_style = """<style> 
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 2rem auto; padding: 2rem; background: linear-gradient(to right, #f8f9fa, #ffffff); border: 1px solid #e1e1e1; box-shadow: 0 2px 8px rgba(0,0,0,0.05); border-radius: 8px; } 
            h1, h2, h3 { color: #2c3e50; border-bottom: 2px solid #f0f0f0; padding-bottom: 10px; } 
            h1 { font-size: 2.5em; text-align: center; } 
            h2 { font-size: 2em; } 
            code { background-color: #ecf0f1; padding: 2px 5px; border-radius: 4px; font-size: 0.9em; } 
            .map-container { margin-top: 30px; border-top: 2px solid #f0f0f0; padding-top: 20px; }
            iframe { width: 100%; height: 500px; border: none; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
        </style>"""

        html_body = markdown2.markdown(final_report_md, extras=["tables", "fenced-code-blocks"])

        full_html = f'<!DOCTYPE html><html lang="{language}"><head><meta charset="UTF-8"><title>AI Trip Plan</title>{css_style}</head><body>{html_body}</body></html>'
        for path in (html_path, latest_html_path):
            with open(path, "w", encoding="utf-8") as f: f.write(full_html)
        print(f"-> HTML report saved to: {html_path}")
    except Exception as e:
        print(f"An error occurred while saving files: {e}")

    return {
        "markdown_report": final_report_md,
        "map_html": map_html_content 
    }
