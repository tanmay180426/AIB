import pytest

from app.ai_assistant.context import grouped_answer, numerical_answer
from app.analytics import metrics
from app.analytics.filters import Filters
from tests.test_filtered_metrics import reference


@pytest.mark.parametrize('f', [Filters(), Filters(category='Books'), Filters(order_status='canceled')])
def test_ai_category_revenue_matches_filtered_analytics(reference, f):
    reference.info['dataset'].name = 'Test reference'
    answer = grouped_answer('What is revenue by category?', reference, f)
    for row in metrics.revenue_by_category(reference, f):
        assert f"{row['category']}: {row['revenue']:,.2f}" in answer
    k = metrics.kpis(reference, f)
    context = {'dataset': 'Test reference', 'kpis': k}
    for question, key in [('total revenue', 'total_revenue'), ('total orders', 'total_orders'),
                          ('unique customers', 'unique_customers'), ('average order value', 'avg_order_value')]:
        assert f"{k[key]:,.2f}" in numerical_answer(question, context)


def test_delivery_days_are_not_substituted_for_success_rates():
    context = {'dataset': 'Test', 'kpis': {'avg_delivery_days': 12.56}}
    assert '12.56' in numerical_answer('What is the average delivery time?', context)
    answer = numerical_answer('What is the delivery success rate?', context)
    assert 'cannot calculate' in answer
    assert '12.56' not in answer


@pytest.mark.parametrize('question', ['revenue by an unknown dimension', 'total revenue where amount > 10',
                                      'orders per customer', 'average revenue', 'median revenue',
                                      'highest revenue', 'average orders', 'median review score', 'total delivery time'])
def test_unsupported_numerical_intents_do_not_substitute_totals(question):
    answer = numerical_answer(question, {'dataset': 'Test', 'kpis': {'total_revenue': 999, 'total_orders': 100}})
    assert 'cannot calculate' in answer
    assert '999.00' not in answer
    assert '100.00' not in answer
