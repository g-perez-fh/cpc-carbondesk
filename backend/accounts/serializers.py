from django.contrib.auth import authenticate
from rest_framework import serializers

from . import services
from .models import Alert, AuditLog, Organisation, ReductionTarget, Site, User

# Business-rule errors from services (accounts.exceptions) are not caught here: they
# pass through validation and are turned into JSON responses by AccountsAPIMixin.


class OrganisationScopedSerializer(serializers.ModelSerializer):
    """Gives validators access to the requesting user's organisation."""

    @property
    def organisation(self):
        return self.context["request"].user.organisation

    def scoped(self, queryset):
        queryset = queryset.filter(organisation=self.organisation)
        return queryset.exclude(pk=self.instance.pk) if self.instance else queryset


class OrganisationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organisation
        fields = ["id", "name", "industry", "country", "employee_count", "created_at"]
        read_only_fields = ["created_at"]


class SiteSerializer(OrganisationScopedSerializer):
    class Meta:
        model = Site
        fields = ["id", "name", "location", "created_at"]
        read_only_fields = ["created_at"]

    def validate_name(self, value):
        if self.scoped(Site.objects).filter(name__iexact=value).exists():
            raise serializers.ValidationError("A site with this name already exists.")
        return value


class UserSerializer(serializers.ModelSerializer):
    organisation = OrganisationSerializer(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "is_active",
            "organisation",
        ]
        read_only_fields = fields


class MemberSerializer(serializers.ModelSerializer):
    """Admins create and edit members of their own organisation."""

    password = serializers.CharField(
        write_only=True, required=False, style={"input_type": "password"}
    )

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "is_active",
            "password",
            "last_login",
        ]
        read_only_fields = ["last_login"]

    def validate(self, attrs):
        if self.instance is None and not attrs.get("password"):
            raise serializers.ValidationError({"password": "This field is required."})
        if self.instance is not None:
            if "username" in attrs and attrs["username"] != self.instance.username:
                raise serializers.ValidationError({"username": "Usernames cannot be changed."})
            if "password" in attrs:
                raise serializers.ValidationError(
                    {"password": "Members change their own password."}
                )
            services.ensure_admin_remains(
                self.instance, role=attrs.get("role"), is_active=attrs.get("is_active")
            )
        return attrs

    def create(self, validated_data):
        return services.create_member(**validated_data)


class RegisterSerializer(serializers.Serializer):
    organisation_name = serializers.CharField(max_length=200)
    industry = serializers.CharField(max_length=120, required=False, allow_blank=True)
    country = serializers.CharField(max_length=80, required=False, allow_blank=True)
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField(required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def create(self, validated_data):
        return services.register_organisation(**validated_data)


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate(self, attrs):
        user = authenticate(
            self.context.get("request"), username=attrs["username"], password=attrs["password"]
        )
        if user is None:
            raise serializers.ValidationError("Invalid username or password.")
        attrs["user"] = user
        return attrs


class ReductionTargetSerializer(OrganisationScopedSerializer):
    target_kg_co2e = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    progress = serializers.SerializerMethodField()

    class Meta:
        model = ReductionTarget
        fields = [
            "id",
            "scope",
            "baseline_year",
            "baseline_kg_co2e",
            "target_year",
            "reduction_percent",
            "target_kg_co2e",
            "progress",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_progress(self, target):
        return services.target_progress(target).as_dict()

    def validate(self, attrs):
        merged = {
            field: attrs.get(field, getattr(self.instance, field, None))
            for field in ("scope", "baseline_year", "target_year")
        }
        services.check_target(
            self.organisation,
            scope=merged["scope"] or ReductionTarget.Scope.ALL,
            baseline_year=merged["baseline_year"],
            target_year=merged["target_year"],
            exclude=self.instance,
        )
        return attrs


class AlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = Alert
        fields = ["id", "level", "message", "target", "is_read", "created_at"]
        read_only_fields = fields


class AuditLogSerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source="actor.username", default=None, read_only=True)

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "actor",
            "action",
            "object_type",
            "object_id",
            "object_repr",
            "changes",
            "created_at",
        ]
        read_only_fields = fields
