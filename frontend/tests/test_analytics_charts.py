from frontend.pages.analytics import scope_figure, site_figure, trend_figure


def test_scope_figure_keeps_scope_order_and_handles_missing_scopes():
    figure = scope_figure({"1": "400.00", "3": "50.50"})
    assert list(figure.data[0].values) == [400.0, 0.0, 50.5]
    assert figure.data[0].labels[0].startswith("Scope 1")


def test_trend_figure_uses_months_as_categories():
    figure = trend_figure([{"month": "2026-01", "kg_co2e": "100.00"}])
    assert list(figure.data[0].x) == ["2026-01"]
    assert list(figure.data[0].y) == [100.0]


def test_site_figure_puts_largest_site_on_top():
    figure = site_figure(
        [{"site": "Plant", "kg_co2e": "450.50"}, {"site": "Office", "kg_co2e": "250.00"}]
    )
    assert list(figure.data[0].y) == ["Office", "Plant"]
