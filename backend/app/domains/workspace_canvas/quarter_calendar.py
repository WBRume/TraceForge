from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

QuarterKey = Annotated[str, Field(pattern=r"^(?:[1-8]\d{3}|9[0-8]\d{2}|99[0-8]\d|999[0-7])-Q[1-4]$")]
FiscalYear = Annotated[int, Field(ge=1000, le=9997)]
QuarterNumber = Annotated[int, Field(ge=1, le=4)]
CalendarFormat = Literal["months", "4-4-5", "4-5-4", "5-4-4"]
DAY = timedelta(days=1)


class FiscalYearOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")
    year: FiscalYear
    boundaries: tuple[date, date, date, date, date]


class CanvasCalendarSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: CalendarFormat = "months"
    start_month: int = Field(default=1, ge=1, le=12)
    timezone: str = Field(default="UTC", min_length=1, max_length=100)
    year_label: Literal["start", "end"] = "start"
    week_end: int = Field(default=5, ge=0, le=6)
    week_end_rule: Literal["last", "nearest"] = "nearest"
    extra_week_quarter: QuarterNumber = 4
    overrides: list[FiscalYearOverride] = Field(default_factory=list, max_length=48)

    @model_validator(mode="after")
    def check_calendar(self):
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("CANVAS_INVALID_TIMEZONE") from error
        if len({item.year for item in self.overrides}) != len(self.overrides):
            raise ValueError("CANVAS_DUPLICATE_FISCAL_YEAR")
        starts: dict[int, date] = {}
        for item in self.overrides:
            if any(left >= right for left, right in pairwise(item.boundaries)):
                raise ValueError("CANVAS_INVALID_QUARTER_BOUNDARIES")
            for year, boundary in ((item.year, item.boundaries[0]), (item.year + 1, item.boundaries[-1])):
                if starts.setdefault(year, boundary) != boundary:
                    raise ValueError("CANVAS_DISCONTINUOUS_FISCAL_YEARS")
        calendar = FiscalCalendar(self)
        for year in starts.keys() | {year - 1 for year in starts}:
            if (calendar.start(year + 1) - calendar.start(year)).days < 4:
                raise ValueError("CANVAS_DISCONTINUOUS_FISCAL_YEARS")
        return self


def month_start(value: date, offset: int = 0) -> date:
    year, month = divmod(value.year * 12 + value.month - 1 + offset, 12)
    return date(year, month + 1, 1)


class PeriodSlice(BaseModel):
    id: str
    index: int
    start: date
    end: date  # Inclusive in responses. Queries use the next day as their exclusive boundary.


class FiscalQuarter(BaseModel):
    id: QuarterKey
    year: FiscalYear
    label_year: int
    number: QuarterNumber
    start: date
    end: date
    months: list[PeriodSlice]


class CanvasCalendarView(BaseModel):
    settings: CanvasCalendarSettings
    can_edit: bool
    current: QuarterKey
    quarters: list[FiscalQuarter]


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date  # Exclusive
    zone: ZoneInfo

    def at_utc(self, day: date) -> datetime:
        return datetime.combine(day, time.min, self.zone).astimezone(UTC).replace(tzinfo=None)

    @property
    def utc_bounds(self) -> tuple[datetime, datetime]:
        return self.at_utc(self.start), self.at_utc(self.end)

    def contains(self, value: datetime) -> bool:
        instant = value.replace(tzinfo=UTC) if value.tzinfo is None else value
        return self.start <= instant.astimezone(self.zone).date() < self.end


class FiscalCalendar:
    def __init__(self, settings: CanvasCalendarSettings):
        self.settings = settings
        self.zone = ZoneInfo(settings.timezone)
        self.overrides = {item.year: item.boundaries for item in settings.overrides}
        self.boundary_overrides = {item.year + 1: item.boundaries[-1] for item in settings.overrides}
        self.boundary_overrides.update({item.year: item.boundaries[0] for item in settings.overrides})

    def _regular_start(self, year: int) -> date:
        first = date(year, self.settings.start_month, 1)
        if self.settings.format == "months":
            return first
        month_end = first - DAY
        offset = (month_end.weekday() - self.settings.week_end) % 7
        if self.settings.week_end_rule == "nearest" and offset > 3:
            offset -= 7
        return first - timedelta(days=offset)

    def start(self, year: int) -> date:
        return self.boundary_overrides.get(year) or self._regular_start(year)

    def boundaries(self, year: int) -> tuple[date, ...]:
        if year in self.overrides:
            return self.overrides[year]
        first, end = self.start(year), self.start(year + 1)
        regular_first, regular_end = self._regular_start(year), self._regular_start(year + 1)
        if self.settings.format == "months":
            middle = [month_start(regular_first, 3 * part) for part in range(1, 4)]
        else:
            extra = (regular_end - regular_first).days - 364
            middle = [
                regular_first + timedelta(days=91 * part + (extra if part >= self.settings.extra_week_quarter else 0))
                for part in range(1, 4)
            ]
        if not first < middle[0] < middle[1] < middle[2] < end:
            # A neighboring transition year may move a shared boundary past a regular cut.
            middle = [first + timedelta(days=(end - first).days * part // 4) for part in range(1, 4)]
        return (first, *middle, end)

    def _months(self, year: int, start: date, end: date) -> list[PeriodSlice]:
        days = (end - start).days
        if self.settings.format != "months" and year not in self.overrides and days in {91, 98}:
            lengths = [int(weeks) * 7 for weeks in self.settings.format.split("-")]
            starts = [start, start + timedelta(days=lengths[0]), start + timedelta(days=sum(lengths[:2])), end]
        else:
            starts = [start]
            while (next_month := month_start(starts[-1], 1)) < end:
                starts.append(next_month)
            starts.append(end)
        return [
            PeriodSlice(id=f"M{index}", index=index, start=left, end=right - DAY)
            for index, (left, right) in enumerate(pairwise(starts), 1)
        ]

    def quarter(self, year: int, number: int) -> FiscalQuarter:
        boundaries = self.boundaries(year)
        start, end = boundaries[number - 1 : number + 1]
        label_year = boundaries[0].year if self.settings.year_label == "start" else (boundaries[-1] - DAY).year
        return FiscalQuarter(
            id=f"{year:04}-Q{number}",
            year=year,
            label_year=label_year,
            number=number,
            start=start,
            end=end - DAY,
            months=self._months(year, start, end),
        )

    def period(self, key: str) -> FiscalQuarter:
        return self.quarter(int(key[:4]), int(key[-1]))

    def at(self, instant: datetime) -> FiscalQuarter:
        value = instant.replace(tzinfo=UTC) if instant.tzinfo is None else instant
        day = value.astimezone(self.zone).date()
        year = day.year
        while day < self.start(year):
            year -= 1
        while day >= self.start(year + 1):
            year += 1
        number = next(index for index, end in enumerate(self.boundaries(year)[1:], 1) if day < end)
        return self.quarter(year, number)

    def dates(self, period: FiscalQuarter | PeriodSlice) -> DateRange:
        return DateRange(period.start, period.end + DAY, self.zone)

    def slice(self, quarter: FiscalQuarter, key: str | None) -> DateRange:
        if key is None:
            return self.dates(quarter)
        index = int(key[1:])
        if key[0] == "M" and index <= len(quarter.months):
            return self.dates(quarter.months[index - 1])
        if key[0] == "W":
            start = quarter.start + timedelta(weeks=index - 1)
            if start <= quarter.end:
                return DateRange(start, min(start + timedelta(days=7), quarter.end + DAY), self.zone)
        raise ValueError("CANVAS_INVALID_QUARTER_SLICE")

    def view(self, can_edit: bool, year: int | None = None) -> CanvasCalendarView:
        current = self.at(datetime.now(UTC))
        return CanvasCalendarView(
            settings=self.settings,
            can_edit=can_edit,
            current=current.id,
            quarters=[self.quarter(year or current.year, index) for index in range(1, 5)],
        )
