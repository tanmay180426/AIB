from app.analytics.kpis import month_expr


class _Dialect:
    def __init__(self, name: str) -> None:
        self.name = name


class _Bind:
    def __init__(self, name: str) -> None:
        self.dialect = _Dialect(name)


class _DB:
    def __init__(self, name: str) -> None:
        self._bind = _Bind(name)

    def get_bind(self) -> _Bind:
        return self._bind


def test_month_expr_sqlite():
    assert "strftime" in month_expr(_DB("sqlite"))


def test_month_expr_postgresql():
    assert "to_char" in month_expr(_DB("postgresql"))


def test_month_expr_uses_column_name():
    assert "o.purchase_date" in month_expr(_DB("sqlite"), "o.purchase_date")
