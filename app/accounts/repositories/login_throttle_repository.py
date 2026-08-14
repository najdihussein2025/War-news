from sqlalchemy.orm import Session

from app.accounts.models import LoginThrottle


class LoginThrottleRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, client_ip: str) -> LoginThrottle | None:
        return self.db.get(LoginThrottle, client_ip)

    def get_or_create(self, client_ip: str) -> LoginThrottle:
        throttle = self.get(client_ip)
        if throttle is None:
            throttle = LoginThrottle(
                client_ip=client_ip,
                failed_attempts=0,
                locked_until=None,
            )
            self.db.add(throttle)
        return throttle

    def save(self, throttle: LoginThrottle) -> LoginThrottle:
        self.db.add(throttle)
        self.db.commit()
        self.db.refresh(throttle)
        return throttle
