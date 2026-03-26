from __future__ import annotations

from app.services.telephony.base import TelephonyProviderRegistry
from app.services.telephony.providers.bolna import BolnaProvider
from app.services.telephony.providers.twilio import TwilioProvider
from app.services.telephony.providers.plivo import PlivoProvider
from app.services.telephony.providers.exotel import ExotelProvider
from app.services.telephony.providers.freeswitch import FreeSwitchProvider


def build_registry() -> TelephonyProviderRegistry:
    reg = TelephonyProviderRegistry()
    reg.register(BolnaProvider())
    reg.register(TwilioProvider())
    reg.register(PlivoProvider())
    reg.register(ExotelProvider())
    reg.register(FreeSwitchProvider())
    return reg
