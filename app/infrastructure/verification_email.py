from functools import lru_cache

from app.domain.authentication import EmailDeliveryUnavailableError


@lru_cache(maxsize=4)
def ses_client(region: str):
    import boto3
    from botocore.config import Config

    return boto3.client(
        "sesv2",
        region_name=region,
        config=Config(
            connect_timeout=3,
            read_timeout=8,
            retries={"mode": "standard", "total_max_attempts": 1},
        ),
    )


class SESVerificationEmailSender:
    def __init__(self, settings):
        self.settings = settings

    def send_code(self, recipient: str, code: str) -> None:
        self._send(recipient, code, recovery=False)

    def send_recovery_code(self, recipient: str, code: str) -> None:
        self._send(recipient, code, recovery=True)

    def _send(self, recipient: str, code: str, *, recovery: bool) -> None:
        subject = (
            "Recupera tu contraseña de EncuentraU"
            if recovery
            else "Verifica tu correo en EncuentraU"
        )
        purpose = "recuperación de contraseña" if recovery else "verificación"
        screen = "Recuperar contraseña" if recovery else "Verificar correo"
        if not self.settings.email_sender:
            raise EmailDeliveryUnavailableError
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            ses_client(self.settings.email_aws_region).send_email(
                FromEmailAddress=self.settings.email_sender.get_secret_value(),
                Destination={"ToAddresses": [recipient]},
                Content={
                    "Simple": {
                        "Subject": {
                            "Data": subject,
                            "Charset": "UTF-8",
                        },
                        "Body": {
                            "Text": {
                                "Charset": "UTF-8",
                                "Data": (
                                    f"Tu código de {purpose} de EncuentraU es: "
                                    f"{code}\n\n"
                                    "Vence en 10 minutos y solo puede usarse una vez. "
                                    f"Escríbelo en la pantalla {screen} "
                                    "de EncuentraU.\n\n"
                                    "Si no solicitaste este código, ignora el mensaje. "
                                    "No compartas el código ni tu contraseña "
                                    "con otras personas."
                                ),
                            }
                        },
                    }
                },
            )
        except (BotoCoreError, ClientError):
            # Translate provider failures without exposing recipients or SDK bodies.
            raise EmailDeliveryUnavailableError from None
