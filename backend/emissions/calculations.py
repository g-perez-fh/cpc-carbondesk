"""Small calculation class shared by previews and saved activities."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext


class EmissionsError(ValueError):
    """An activity cannot be calculated with the supplied inputs."""


class CO2eCalculator:
    def __init__(self, kg_per_unit, unit):
        self.set_factor(kg_per_unit, unit)

    def set_factor(self, kg_per_unit, unit):
        value = self._decimal(kg_per_unit)
        if not isinstance(unit, str) or not unit.strip():
            raise EmissionsError("A unit is required.")
        self._kg_per_unit = value
        self._unit = unit.strip()

    def get_factor(self):
        return self._kg_per_unit

    def get_unit(self):
        return self._unit

    @staticmethod
    def _decimal(value):
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise EmissionsError("Enter a valid number.") from exc
        if not number.is_finite() or number < 0:
            raise EmissionsError("Enter a finite, non-negative number.")
        return number

    def calculate(self, quantity, unit):
        if unit != self._unit:
            raise EmissionsError(f"Use {self._unit}; automatic unit conversion is not supported.")
        amount = self._decimal(quantity)
        with localcontext() as context:
            context.prec = 40
            result = amount * self._kg_per_unit
            if result > Decimal("999999999999999999.99"):
                raise EmissionsError("The calculated result is too large to store.")
            return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
