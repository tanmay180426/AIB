"""Shared past-only feature contract for explicit synthetic model versions."""
import numpy as np
import pandas as pd

FEATURES = ['lag1', 'lag7', 'lag14', 'lag30', 'roll7', 'roll30', 'std7', 'std30',
            'weekday_sin', 'weekday_cos', 'month_sin', 'month_cos']


def features(history, day):
    values = np.asarray(history, dtype=float)[-30:]
    if len(values) != 30 or not np.isfinite(values).all():
        raise ValueError('Thirty consecutive finite observations are required.')
    day = pd.Timestamp(day)
    return [values[-1], values[-7], values[-14], values[-30], values[-7:].mean(),
            values.mean(), values[-7:].std(), values.std(),
            np.sin(2*np.pi*day.dayofweek/7), np.cos(2*np.pi*day.dayofweek/7),
            np.sin(2*np.pi*(day.month-1)/12), np.cos(2*np.pi*(day.month-1)/12)]


def recursive(model, history, dates):
    values = list(np.asarray(history, dtype=float)[-30:])
    result = []
    for day in dates:
        value = float(model.predict([features(values, day)])[0])
        if not np.isfinite(value):
            raise ValueError('Non-finite model output.')
        result.append(value)
        # Preserve model outputs, including negatives, through recursion.
        values.append(value)
    return result
