import enum

class PincodeStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    WAITLIST = "WAITLIST"


class CallStatus(str, enum.Enum):
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"
    CALLBACK_NEEDED = "CALLBACK_NEEDED"


class ChatRole(str, enum.Enum):
    user = "user"
    bot = "bot"


class SessionChannel(str, enum.Enum):
    web = "web"
    voice = "voice"


class SessionStatus(str, enum.Enum):
    active = "active"
    closed = "closed"
