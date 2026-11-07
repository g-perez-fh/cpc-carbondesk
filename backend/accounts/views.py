from rest_framework import generics, mixins, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import services
from .exceptions import AccountsError
from .mixins import OrganisationScopedMixin
from .models import Alert, AuditLog, ReductionTarget, Site, User
from .permissions import IsOrganisationAdmin, IsOrganisationAdminOrReadOnly, IsOrganisationMember
from .serializers import (
    AlertSerializer,
    AuditLogSerializer,
    LoginSerializer,
    MemberSerializer,
    OrganisationSerializer,
    ReductionTargetSerializer,
    RegisterSerializer,
    SiteSerializer,
    UserSerializer,
)


def session_payload(user):
    token, _ = Token.objects.get_or_create(user=user)
    return {"token": token.key, "user": UserSerializer(user).data}


class AccountsAPIMixin:
    """Turn any AccountsError raised by a service into a clean JSON error response."""

    def handle_exception(self, exc):
        if isinstance(exc, AccountsError):
            return Response(exc.as_response_data(), status=exc.status_code)
        return super().handle_exception(exc)


# Authentication --------------------------------------------------------------


class AuthView(AccountsAPIMixin, APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"


class RegisterView(AuthView):
    """Create a new organisation and its first administrator."""

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(session_payload(user), status=status.HTTP_201_CREATED)


class LoginView(AuthView):
    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        services.record_audit(actor=user, action=AuditLog.Action.LOGIN, instance=user)
        return Response(session_payload(user))


class LogoutView(APIView):
    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        services.record_audit(
            actor=request.user, action=AuditLog.Action.LOGOUT, instance=request.user
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(generics.RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


# Organisation structure ------------------------------------------------------


class OrganisationView(generics.RetrieveUpdateAPIView):
    serializer_class = OrganisationSerializer
    permission_classes = [IsOrganisationAdminOrReadOnly]

    def get_object(self):
        return self.request.user.organisation

    def perform_update(self, serializer):
        changes = services.describe_changes(serializer.instance, serializer.validated_data)
        organisation = serializer.save()
        if changes:
            services.record_audit(
                actor=self.request.user,
                action=AuditLog.Action.UPDATE,
                instance=organisation,
                organisation=organisation,
                changes=changes,
            )


class SiteViewSet(AccountsAPIMixin, OrganisationScopedMixin, viewsets.ModelViewSet):
    queryset = Site.objects.all()
    serializer_class = SiteSerializer
    permission_classes = [IsOrganisationAdminOrReadOnly]

    def perform_destroy(self, instance):
        services.delete_site(instance, actor=self.request.user)


class MemberViewSet(AccountsAPIMixin, OrganisationScopedMixin, viewsets.ModelViewSet):
    """Members of the organisation. Deleting a member deactivates the account."""

    queryset = User.objects.order_by("username")
    serializer_class = MemberSerializer
    permission_classes = [IsOrganisationAdminOrReadOnly]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def perform_destroy(self, instance):
        services.ensure_admin_remains(instance, is_active=False)
        if instance.is_active:
            instance.is_active = False
            instance.save(update_fields=["is_active"])
            Token.objects.filter(user=instance).delete()
            services.record_audit(
                actor=self.request.user,
                action=AuditLog.Action.UPDATE,
                instance=instance,
                changes={"is_active": {"from": True, "to": False}},
            )

    def perform_update(self, serializer):
        super().perform_update(serializer)
        if not serializer.instance.is_active:
            Token.objects.filter(user=serializer.instance).delete()


# Targets, alerts and audit history ---------------------------------------------


class ReductionTargetViewSet(AccountsAPIMixin, OrganisationScopedMixin, viewsets.ModelViewSet):
    queryset = ReductionTarget.objects.select_related("organisation")
    serializer_class = ReductionTargetSerializer
    permission_classes = [IsOrganisationAdminOrReadOnly]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def extra_save_kwargs(self):
        return {"created_by": self.request.user}

    @action(detail=False, methods=["post"], permission_classes=[IsOrganisationMember])
    def evaluate(self, request):
        """Check every target and create alerts for those at risk or off track."""
        alerts = services.evaluate_targets(request.user.organisation)
        return Response(AlertSerializer(alerts, many=True).data)


class AlertViewSet(
    OrganisationScopedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Alert.objects.all()
    serializer_class = AlertSerializer
    permission_classes = [IsOrganisationMember]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get("unread") in {"1", "true"}:
            queryset = queryset.filter(is_read=False)
        return queryset

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        alert = self.get_object()
        alert.is_read = True
        alert.save(update_fields=["is_read"])
        return Response(self.get_serializer(alert).data)

    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        updated = self.get_queryset().filter(is_read=False).update(is_read=True)
        return Response({"updated": updated})


class AuditLogPagination(PageNumberPagination):
    page_size = 50


class AuditLogViewSet(OrganisationScopedMixin, viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.select_related("actor")
    serializer_class = AuditLogSerializer
    permission_classes = [IsOrganisationAdmin]
    pagination_class = AuditLogPagination
