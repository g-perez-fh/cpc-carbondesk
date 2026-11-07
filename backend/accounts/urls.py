from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("sites", views.SiteViewSet)
router.register("departments", views.DepartmentViewSet)
router.register("members", views.MemberViewSet)
router.register("targets", views.ReductionTargetViewSet)
router.register("alerts", views.AlertViewSet)
router.register("audit-log", views.AuditLogViewSet)

urlpatterns = [
    path("register/", views.RegisterView.as_view(), name="register"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("me/", views.MeView.as_view(), name="me"),
    path("organisation/", views.OrganisationView.as_view(), name="organisation"),
    *router.urls,
]
