"""Users, Organisation & Targets errors, each carrying the HTTP status its view should return."""


class AccountsError(Exception):
    """Base class for accounts errors. Subclasses set error_code, status_code, default_message.

    ``field`` names the request field the error belongs to, if any, so the frontend
    can show it next to that input.
    """

    error_code = "accounts_error"
    status_code = 400
    default_message = "The request could not be completed."
    field = None

    def __init__(self, message=None):
        self.message = message or self.default_message
        super().__init__(self.message)

    def as_response_data(self):
        data = {"error": self.error_code, "detail": self.message}
        if self.field:
            data["field"] = self.field
        return data


class LastAdminError(AccountsError):
    """The change would leave an organisation without an active administrator."""

    error_code = "last_admin"
    status_code = 409
    default_message = "An organisation needs at least one active administrator."


class WeakPasswordError(AccountsError):
    """The password fails Django's password validators (too short, too common, ...)."""

    error_code = "weak_password"
    status_code = 400
    default_message = "This password is too weak."
    field = "password"


class SiteInUseError(AccountsError):
    """The site still has activity records, so deleting it would lose history."""

    error_code = "site_in_use"
    status_code = 400
    default_message = "This site has activity records and cannot be deleted."


class InvalidTargetError(AccountsError):
    """A reduction target's years are inconsistent or duplicate an existing target."""

    error_code = "invalid_target"
    status_code = 400
    default_message = "This reduction target is not valid."
    field = "target_year"
