from datetime import date
from decimal import Decimal

from rest_framework import serializers

from accounts.models import Site

from .calculations import CO2eCalculator, EmissionsError
from .models import ActivityRecord, EmissionFactor
from .services import create_activity, update_activity


class EmissionFactorSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        if self.instance:
            for field in ("unit", "scope"):
                if attrs.get(field, getattr(self.instance, field)) != getattr(self.instance, field):
                    raise serializers.ValidationError(
                        {field: "Add a new factor to change its unit or scope."}
                    )
        return attrs

    class Meta:
        model = EmissionFactor
        fields = ["id", "name", "scope", "unit", "kg_per_unit", "source", "year", "is_demo"]


class CompanyRelationsMixin:
    """Validate foreign keys against the current company, not all database rows."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        organisation = request.user.organisation if request else None
        self.fields["factor"].queryset = EmissionFactor.objects.filter(organisation=organisation)
        if "site" in self.fields:
            self.fields["site"].queryset = Site.objects.filter(organisation=organisation)


def calculate_inputs(data):
    factor = data["factor"]
    try:
        return CO2eCalculator(factor.kg_per_unit, factor.unit).calculate(
            data["quantity"], data["unit"]
        )
    except EmissionsError as exc:
        raise serializers.ValidationError({"unit": str(exc)}) from exc


class CalculationSerializer(CompanyRelationsMixin, serializers.Serializer):
    factor = serializers.PrimaryKeyRelatedField(queryset=EmissionFactor.objects.none())
    quantity = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=Decimal("0"))
    unit = serializers.CharField(max_length=30)

    activity = serializers.PrimaryKeyRelatedField(
        queryset=ActivityRecord.objects.none(), required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["activity"].queryset = ActivityRecord.objects.filter(
            organisation=self.context["request"].user.organisation
        )

    def validate(self, attrs):
        activity = attrs.get("activity")
        if activity and activity.factor_id == attrs["factor"].pk:
            try:
                attrs["kg_co2e"] = CO2eCalculator(activity.factor_value, activity.unit).calculate(
                    attrs["quantity"], attrs["unit"]
                )
            except EmissionsError as exc:
                raise serializers.ValidationError({"unit": str(exc)}) from exc
        else:
            attrs["kg_co2e"] = calculate_inputs(attrs)
        return attrs


class ActivityRecordSerializer(CompanyRelationsMixin, serializers.ModelSerializer):
    factor = serializers.PrimaryKeyRelatedField(queryset=EmissionFactor.objects.none())
    site = serializers.PrimaryKeyRelatedField(queryset=Site.objects.none())
    site_name = serializers.CharField(source="site.name", read_only=True)

    class Meta:
        model = ActivityRecord
        fields = [
            "id",
            "description",
            "date",
            "quantity",
            "unit",
            "factor",
            "site",
            "site_name",
            "category",
            "scope",
            "factor_value",
            "factor_source",
            "factor_year",
            "is_demo",
            "kg_co2e",
            "created_at",
        ]
        read_only_fields = [
            "category",
            "scope",
            "factor_value",
            "factor_source",
            "factor_year",
            "is_demo",
            "kg_co2e",
            "created_at",
        ]

    def validate_date(self, value):
        if value > date.today():
            raise serializers.ValidationError("Activity dates cannot be in the future.")
        return value

    def validate(self, attrs):
        if self.instance is None:
            calculate_inputs(attrs)
        else:
            factor = attrs.get("factor", self.instance.factor)
            same_factor = factor.pk == self.instance.factor_id
            value = self.instance.factor_value if same_factor else factor.kg_per_unit
            unit = self.instance.unit if same_factor else factor.unit
            try:
                CO2eCalculator(value, unit).calculate(
                    attrs.get("quantity", self.instance.quantity),
                    attrs.get("unit", self.instance.unit),
                )
            except EmissionsError as exc:
                raise serializers.ValidationError({"unit": str(exc)}) from exc
        return attrs

    def update(self, instance, validated_data):
        return update_activity(instance, **validated_data)

    def create(self, validated_data):
        return create_activity(**validated_data)


class ActivityFilterSerializer(serializers.Serializer):
    start = serializers.DateField(required=False)
    end = serializers.DateField(required=False)
    scope = serializers.ChoiceField(choices=[1, 2, 3], required=False)
    site = serializers.PrimaryKeyRelatedField(queryset=Site.objects.none(), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["site"].queryset = Site.objects.filter(
            organisation=self.context["request"].user.organisation
        )

    def validate(self, attrs):
        if "start" in attrs and "end" in attrs and attrs["start"] >= attrs["end"]:
            raise serializers.ValidationError(
                {"end": "End must be after start (end is exclusive)."}
            )
        return attrs
