from datetime import date

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.mixins import OrganisationScopedMixin
from accounts.permissions import CanEditDataOrReadOnly, IsOrganisationMember

from . import services
from .context import MAX_YEAR, MIN_YEAR, build_snapshot
from .exceptions import AssistantError
from .models import Conversation, MonthlySummary
from .serializers import (
    ConversationDetailSerializer,
    ConversationSerializer,
    GenerateSummarySerializer,
    MessageSerializer,
    MonthlySummarySerializer,
    SendMessageSerializer,
)


class AssistantAPIMixin:
    """Turn any AssistantError raised by a service into a clean JSON error response."""

    def handle_exception(self, exc):
        if isinstance(exc, AssistantError):
            return Response(exc.as_response_data(), status=exc.status_code)
        return super().handle_exception(exc)


class ConversationViewSet(
    AssistantAPIMixin,
    OrganisationScopedMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Each user only sees their own conversations."""

    queryset = Conversation.objects.all()
    permission_classes = [IsOrganisationMember]
    audit = False

    def get_queryset(self):
        queryset = super().get_queryset().filter(user=self.request.user)
        if self.action == "retrieve":
            queryset = queryset.prefetch_related("messages")
        return queryset

    def get_serializer_class(self):
        return ConversationDetailSerializer if self.action == "retrieve" else ConversationSerializer

    def extra_save_kwargs(self):
        return {"user": self.request.user}

    @action(detail=True, methods=["post"])
    def messages(self, request, pk=None):
        conversation = self.get_object()
        serializer = SendMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        question, answer = services.send_message(conversation, serializer.validated_data["content"])
        return Response(
            {
                "question": MessageSerializer(question).data,
                "answer": MessageSerializer(answer).data,
            },
            status=status.HTTP_201_CREATED,
        )


class RecommendationsView(AssistantAPIMixin, APIView):
    """Ranked reduction measures with indicative savings for a year (default: current)."""

    permission_classes = [IsOrganisationMember]

    def get(self, request):
        try:
            year = int(request.query_params.get("year", date.today().year))
        except ValueError:
            return Response({"year": ["Enter a valid year."]}, status=status.HTTP_400_BAD_REQUEST)
        # The snapshot also needs the previous year and next January as an
        # exclusive end date, so both neighbouring years must be representable.
        if not MIN_YEAR <= year <= MAX_YEAR:
            return Response(
                {"year": [f"Enter a year between {MIN_YEAR} and {MAX_YEAR}."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        snapshot = build_snapshot(request.user.organisation, year=year)
        return Response(
            {
                "year": year,
                "totals": {f"scope_{s}": str(v) for s, v in snapshot.totals.items()},
                "total": str(snapshot.total),
                "recommendations": [r.as_dict() for r in snapshot.recommendations],
            }
        )


class MonthlySummaryViewSet(
    AssistantAPIMixin,
    OrganisationScopedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = MonthlySummary.objects.select_related("generated_by")
    serializer_class = MonthlySummarySerializer
    permission_classes = [CanEditDataOrReadOnly]

    def create(self, request):
        """Generate (or regenerate) the summary for ``{"month": "YYYY-MM"}``."""
        serializer = GenerateSummarySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        summary = services.generate_monthly_summary(
            request.user.organisation, serializer.validated_data["month"], user=request.user
        )
        return Response(MonthlySummarySerializer(summary).data, status=status.HTTP_201_CREATED)
