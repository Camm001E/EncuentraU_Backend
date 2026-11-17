from typing import Protocol


class VerificationEmailSender(Protocol):
    def send_code(self, recipient: str, code: str) -> None: ...

    def send_recovery_code(self, recipient: str, code: str) -> None: ...
