"""Request-schema tests for `school_erp`'s HTTP layer.

**Why this file exists.** Every other `school_erp` test calls the application service directly,
so none of them ever *builds* a Pydantic request model — and a defect that lived entirely inside
one stayed invisible to a fully green suite while the whole school-finance write surface returned
`500` against the running API. The specific fault: `_MoneyValidatingModel` held its field list in
`_money_fields`, and Pydantic v2 turns any underscore-prefixed class attribute into a
`ModelPrivateAttr` descriptor, so `info.field_name in cls._money_fields` raised
`TypeError: argument of type 'ModelPrivateAttr' is not iterable` on creating a fee plan, issuing
an invoice, recording a payment, an income or an expense.

So these tests instantiate the models the way FastAPI does. They are cheap, and they cover the
seam between "the service is correct" and "a request can reach it".
"""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from raad.modules.school_erp.api.schemas import (
    CreateFeePlanRequest,
    IssueStudentInvoiceRequest,
    RecordExpenseRequest,
    RecordIncomeRequest,
    RecordStudentPaymentRequest,
    UpdateFeePlanRequest,
    _MoneyValidatingModel,
)

#: Every request model carrying an amount, with the minimum payload FastAPI would hand it.
_MONEY_REQUESTS = [
    (CreateFeePlanRequest, {"name": "Monthly transport", "currency": "USD"}),
    (UpdateFeePlanRequest, {"name": "Monthly transport", "currency": "USD"}),
    (
        IssueStudentInvoiceRequest,
        {
            "student_id": "01J8Z3K9G6X8YV5T4N2R7QSTDA",
            "period": "2026-09",
            "due_date": "2026-09-30",
            "currency": "USD",
        },
    ),
    (
        RecordStudentPaymentRequest,
        {"currency": "USD", "method": "cash", "received_on": "2026-09-08"},
    ),
    (RecordIncomeRequest, {"currency": "USD", "occurred_on": "2026-09-08"}),
    (RecordExpenseRequest, {"currency": "USD", "occurred_on": "2026-09-08"}),
]


class MoneyFieldDeclarationTests(unittest.TestCase):
    def test_every_money_model_declares_its_fields_as_a_readable_tuple(self) -> None:
        """The regression guard: a private-attribute name here is not readable from a validator.

        Asserting the *type* rather than only the behaviour means renaming this back to
        `_money_fields` fails here immediately, with the reason stated, rather than only showing
        up as a 500 from a route no unit test exercises.
        """
        for model, _ in _MONEY_REQUESTS:
            with self.subTest(model=model.__name__):
                self.assertIsInstance(model.MONEY_FIELDS, tuple)
                self.assertTrue(model.MONEY_FIELDS)

    def test_the_base_model_defaults_to_no_money_fields(self) -> None:
        self.assertEqual(_MoneyValidatingModel.MONEY_FIELDS, ())


class MoneyCoercionTests(unittest.TestCase):
    def test_every_money_request_can_be_constructed_at_all(self) -> None:
        """This is the test that would have caught the live 500 — nothing more elaborate."""
        for model, payload in _MONEY_REQUESTS:
            with self.subTest(model=model.__name__):
                instance = model(**payload, amount="50.00")
                self.assertEqual(instance.amount, "50.00")

    def test_a_float_amount_is_stringified_through_its_shortest_repr(self) -> None:
        # `12.1` must become "12.10", never "12.099999999999999" — the whole reason amounts
        # cross the wire as exact decimal strings in the first place.
        self.assertEqual(
            RecordStudentPaymentRequest(
                amount=12.1, currency="USD", method="cash", received_on="2026-09-08"
            ).amount,
            "12.10",
        )

    def test_amounts_are_quantised_to_two_places(self) -> None:
        self.assertEqual(
            RecordIncomeRequest(
                amount="10.005", currency="USD", occurred_on="2026-09-08"
            ).amount,
            "10.01",
        )

    def test_a_negative_amount_is_refused(self) -> None:
        with self.assertRaises(ValidationError):
            RecordExpenseRequest(
                amount="-5.00", currency="USD", occurred_on="2026-09-08"
            )

    def test_a_non_numeric_amount_is_refused(self) -> None:
        with self.assertRaises(ValidationError):
            RecordExpenseRequest(
                amount="fifty", currency="USD", occurred_on="2026-09-08"
            )

    def test_the_fee_plan_discount_defaults_to_zero_and_is_coerced_too(self) -> None:
        plan = CreateFeePlanRequest(name="Termly", amount=100, currency="USD")
        self.assertEqual(plan.amount, "100.00")
        self.assertEqual(plan.default_discount_amount, "0.00")

        discounted = CreateFeePlanRequest(
            name="Termly", amount=100, currency="USD", default_discount_amount=7.5
        )
        self.assertEqual(discounted.default_discount_amount, "7.50")

    def test_a_non_money_field_passes_through_untouched(self) -> None:
        """The validator runs on `"*"`, so it sees every field — it must only rewrite amounts."""
        plan = CreateFeePlanRequest(name="  Monthly  ", amount="10", currency="USD")
        self.assertEqual(plan.name, "  Monthly  ")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
