from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.domains.workspace_canvas.quarter_calendar import CanvasCalendarSettings, FiscalCalendar


def test_monthly_fiscal_quarter_crosses_year_with_exact_local_boundary():
    calendar = FiscalCalendar(CanvasCalendarSettings(start_month=11, year_label="end", timezone="Asia/Hong_Kong"))
    quarter = calendar.quarter(2025, 1)
    assert quarter.label_year == 2026
    assert (quarter.start, quarter.end) == (date(2025, 11, 1), date(2026, 1, 31))
    assert [part.start.month for part in quarter.months] == [11, 12, 1]
    assert calendar.at(datetime(2025, 10, 31, 15, 59, 59, tzinfo=UTC)).id == "2024-Q4"
    assert calendar.at(datetime(2025, 10, 31, 16, tzinfo=UTC)).id == "2025-Q1"
    assert calendar.at(datetime(2026, 1, 31, 16, tzinfo=UTC)).id == "2025-Q2"
    leap = FiscalCalendar(CanvasCalendarSettings()).quarter(2024, 1)
    assert leap.months[1].end == date(2024, 2, 29)


@pytest.mark.parametrize(
    ("pattern", "lengths"), [("4-4-5", [28, 28, 42]), ("4-5-4", [28, 35, 35]), ("5-4-4", [35, 28, 35])]
)
def test_week_based_year_adds_a_week_to_a_configured_quarter(pattern, lengths):
    calendar = FiscalCalendar(CanvasCalendarSettings(format=pattern, start_month=2, extra_week_quarter=2))
    quarters = [calendar.quarter(2023, number) for number in range(1, 5)]
    assert calendar.start(2023) == date(2023, 1, 29)
    assert calendar.start(2024) == date(2024, 2, 4)
    assert [(item.end - item.start).days + 1 for item in quarters] == [91, 98, 91, 91]
    assert [(item.end - item.start).days + 1 for item in quarters[1].months] == lengths
    assert (calendar.slice(quarters[1], "W14").end - calendar.slice(quarters[1], "W14").start).days == 7
    with pytest.raises(ValueError, match="CANVAS_INVALID_QUARTER_SLICE"):
        calendar.slice(quarters[1], "W15")


def test_custom_transition_keeps_four_periods_and_one_shared_year_boundary():
    override = {"year": 2026, "boundaries": ["2026-08-01", "2026-09-01", "2027-02-01", "2027-04-01", "2027-06-01"]}
    calendar = FiscalCalendar(CanvasCalendarSettings.model_validate({"start_month": 8, "overrides": [override]}))
    quarters = [calendar.quarter(2026, number) for number in range(1, 5)]
    assert [item.start for item in quarters] == [date.fromisoformat(value) for value in override["boundaries"][:4]]
    assert quarters[0].end == date(2026, 8, 31)
    assert quarters[1].end == date(2027, 1, 31)
    assert quarters[-1].end + timedelta(days=1) == calendar.quarter(2027, 1).start
    assert calendar.quarter(2025, 4).end + timedelta(days=1) == quarters[0].start
    with pytest.raises(ValidationError, match="CANVAS_DISCONTINUOUS_FISCAL_YEARS"):
        CanvasCalendarSettings.model_validate(
            {
                "overrides": [
                    override,
                    {
                        "year": 2027,
                        "boundaries": ["2027-06-02", "2027-09-01", "2027-12-01", "2028-03-01", "2028-06-01"],
                    },
                ]
            }
        )
    with pytest.raises(ValidationError, match="CANVAS_INVALID_QUARTER_BOUNDARIES"):
        CanvasCalendarSettings.model_validate(
            {"overrides": [{**override, "boundaries": list(reversed(override["boundaries"]))}]}
        )
    with pytest.raises(ValidationError, match="CANVAS_INVALID_TIMEZONE"):
        CanvasCalendarSettings(timezone="Not/AZone")


def test_long_transition_moves_the_following_start_without_gaps():
    calendar = FiscalCalendar(
        CanvasCalendarSettings.model_validate(
            {
                "start_month": 7,
                "overrides": [
                    {
                        "year": 2026,
                        "boundaries": [
                            "2026-07-01",
                            "2027-01-01",
                            "2027-04-01",
                            "2027-07-01",
                            "2027-10-01",
                        ],
                    }
                ],
            }
        )
    )
    assert calendar.quarter(2026, 1).end == date(2026, 12, 31)
    assert calendar.quarter(2026, 4).end == date(2027, 9, 30)
    assert calendar.quarter(2027, 1).start == date(2027, 10, 1)
    assert calendar.at(datetime(2027, 10, 1, tzinfo=UTC)).id == "2027-Q1"
    assert all(calendar.quarter(2027, index).start <= calendar.quarter(2027, index).end for index in range(1, 5))
