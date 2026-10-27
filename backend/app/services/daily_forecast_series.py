"""Validated adapter for the project's unified daily aggregate series.

This is a data contract only. It does not invoke, register, or route to a model.
Provenance is returned separately from the date/target frame consumed by a
time-series feature builder.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
import math
import re

import pandas as pd
from sqlalchemy import select

from app.services.datasets import storage_table


TARGETS = {
    "orders": {
        "column": "orders_unified",
        "definition": "Daily count of source order records, then the separately generated synthetic order-count target.",
        "unit": "orders/day",
        "definition_status": "documented_project_definition",
        "requires_currency": False,
        "nonnegative": True,
        "integer": True,
    },
    "revenue": {
        "column": "revenue_unified",
        "definition": "Daily sum of item price, excluding freight; generated extension values are synthetic.",
        "unit": "source_currency_unverified",
        "definition_status": "documented_definition_currency_unverified",
        "requires_currency": True,
        "nonnegative": True,
        "integer": False,
    },
    "profit": {
        "column": "profit_unified",
        "definition": "Daily sum of source item_profit, then the separately generated synthetic target; formula is unaudited.",
        "unit": "unknown_units",
        "definition_status": "provisional_formula_and_units_unverified",
        "requires_currency": True,
        "nonnegative": False,
        "integer": False,
    },
}

DATE_COLUMN = "date"
ORIGIN_COLUMN = "data_origin"
ORIGINS = {"source_observed", "synthetic_extension"}


@dataclass(frozen=True)
class DailyForecastSeries:
    """Daily target history plus a separate, audit-only provenance sidecar."""

    target: str
    target_column: str
    dates: tuple[date, ...]
    values: tuple[float, ...]
    provenance: tuple[str, ...]
    definition: str
    unit: str
    definition_status: str
    currency_code: str | None = None
    source_provenance_independently_certified: bool = False

    @property
    def provenance_counts(self) -> dict[str, int]:
        return {origin: self.provenance.count(origin) for origin in sorted(ORIGINS)
                if origin in self.provenance}

    @property
    def warnings(self) -> tuple[str, ...]:
        warnings = ["Source provenance is documented by the dataset package but is not independently certified."]
        if "synthetic_extension" in self.provenance:
            warnings.append("Series includes generated synthetic-extension observations; these are not verified transactions.")
        if self.target == "revenue":
            warnings.append("Revenue currency is unverified; do not label or convert it as BRL or another currency.")
        elif self.target == "profit":
            warnings.append("Profit is provisional: its formula, units, and currency have not been independently verified.")
        return tuple(warnings)

    def to_model_frame(self) -> pd.DataFrame:
        """Return only the date and target series; provenance is not a feature."""
        return pd.DataFrame({"date": self.dates, self.target: self.values})


def _as_day(value, row_number: int) -> date:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        return value
    elif isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            try:
                return date.fromisoformat(text)
            except ValueError:
                raise ValueError(f"Invalid ISO calendar date at row {row_number}.") from None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"Invalid ISO calendar date at row {row_number}.") from None
    else:
        raise ValueError(f"Invalid ISO calendar date at row {row_number}.")

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    if parsed.time() != time.min:
        raise ValueError(f"Daily date at row {row_number} must normalize to midnight UTC.")
    return parsed.date()


def validate_daily_frame(frame: pd.DataFrame, target: str, *, require_verified_currency: bool = False) -> DailyForecastSeries:
    """Validate the unified daily schema without imputing or coercing meaning."""
    if target not in TARGETS:
        raise ValueError(f"Unsupported daily forecasting target '{target}'.")
    spec = TARGETS[target]
    if require_verified_currency and spec["requires_currency"]:
        if target == "revenue":
            raise ValueError("Revenue currency is unverified; a currency-dependent operation is not permitted.")
        raise ValueError("Profit currency and units are unverified; a currency-dependent operation is not permitted.")

    required = {DATE_COLUMN, ORIGIN_COLUMN, spec["column"]}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError("Daily series is missing required columns: " + ", ".join(missing) + ".")
    if frame.empty:
        raise ValueError("Daily series contains no observations.")

    dates = tuple(_as_day(value, index + 1) for index, value in enumerate(frame[DATE_COLUMN].tolist()))
    for previous, current in zip(dates, dates[1:]):
        gap = (current - previous).days
        if gap == 0:
            raise ValueError(f"Duplicate daily date: {current.isoformat()}.")
        if gap < 0:
            raise ValueError("Daily dates must be strictly chronological.")
        if gap > 1:
            raise ValueError(f"Missing daily date(s) between {previous.isoformat()} and {current.isoformat()}; gaps are not filled.")

    raw_origins = frame[ORIGIN_COLUMN].tolist()
    if any(not isinstance(value, str) or value not in ORIGINS for value in raw_origins):
        raise ValueError("data_origin must contain only source_observed or synthetic_extension.")
    provenance = tuple(raw_origins)

    if "source_data_flag" in frame.columns:
        flags = frame["source_data_flag"].tolist()
        for index, (flag, origin) in enumerate(zip(flags, provenance), start=1):
            try:
                numeric_flag = float(flag)
            except (TypeError, ValueError):
                raise ValueError(f"source_data_flag must be numeric 0/1 at row {index}.") from None
            expected = 1.0 if origin == "source_observed" else 0.0
            if not math.isfinite(numeric_flag) or numeric_flag != expected:
                raise ValueError(f"source_data_flag conflicts with data_origin at row {index}.")

    values = []
    for index, value in enumerate(frame[spec["column"]].tolist(), start=1):
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"Target '{spec['column']}' must be numeric at row {index}.") from None
        if not math.isfinite(numeric):
            raise ValueError(f"Target '{spec['column']}' must be finite at row {index}.")
        if spec["nonnegative"] and numeric < 0:
            raise ValueError(f"Target '{spec['column']}' cannot be negative at row {index}.")
        if spec["integer"] and not numeric.is_integer():
            raise ValueError(f"Orders must be whole daily counts at row {index}.")
        values.append(numeric)

    return DailyForecastSeries(
        target=target,
        target_column=spec["column"],
        dates=dates,
        values=tuple(values),
        provenance=provenance,
        definition=spec["definition"],
        unit=spec["unit"],
        definition_status=spec["definition_status"],
    )


def load_daily_forecast_series(db, dataset, target: str, *, require_verified_currency: bool = False) -> DailyForecastSeries:
    """Load one authorized/resolved tabular dataset through explicit daily columns.

    The caller must first apply the application's dataset authorization/resolution
    path. This adapter never changes registry semantics or invokes model code.
    """
    resolved = getattr(db, "info", {}).get("dataset")
    if resolved is None or getattr(resolved, "id", None) != getattr(dataset, "id", None):
        raise ValueError("Resolve and authorize the dataset through the application before loading daily targets.")
    if getattr(dataset, "status", None) != "READY":
        raise ValueError("Daily forecasting requires a READY dataset.")
    if getattr(dataset, "adapter", None) != "tabular" or getattr(dataset, "source_type", None) == "bundle":
        raise ValueError("Daily forecasting requires one uploaded tabular dataset, not a warehouse or bundle.")

    spec = TARGETS.get(target)
    if spec is None:
        raise ValueError(f"Unsupported daily forecasting target '{target}'.")
    profile = {column.get("name"): column for column in dataset.profile.get("columns", [])}
    required = (DATE_COLUMN, ORIGIN_COLUMN, spec["column"])
    for name in required:
        column = profile.get(name)
        if column is None:
            raise ValueError(f"Daily series is missing required column '{name}'.")
        if column.get("missing", 0):
            raise ValueError(f"Daily series column '{name}' contains missing values.")
    if profile[DATE_COLUMN].get("dtype") != "datetime":
        raise ValueError("Daily series date column must be validated as a date by Dataset Manager.")
    if profile[spec["column"]].get("dtype") != "numeric":
        raise ValueError(f"Daily series target '{spec['column']}' must be numeric.")

    table = storage_table(dataset, db)
    selected = [table.c[profile[name]["storage"]].label(name) for name in required]
    if "source_data_flag" in profile:
        selected.append(table.c[profile["source_data_flag"]["storage"]].label("source_data_flag"))
    rows = db.execute(select(*selected).order_by(table.c.row_id)).mappings().all()
    if len(rows) != getattr(dataset, "row_count", None):
        raise ValueError("Stored daily row count does not match the dataset registry.")
    frame = pd.DataFrame([dict(row) for row in rows])
    return validate_daily_frame(frame, target, require_verified_currency=require_verified_currency)
