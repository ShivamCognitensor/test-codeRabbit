from __future__ import annotations

from app.services.telephony.base import TelephonyProviderRegistry
from app.services.telephony.providers.bolna import BolnaProvider
from app.services.telephony.providers.twilio import TwilioProvider
from app.services.telephony.providers.plivo import PlivoProvider
from app.services.telephony.providers.exotel import ExotelProvider
from app.services.telephony.providers.freeswitch import FreeSwitchProvider


def build_registry() -> TelephonyProviderRegistry:
    """
    Create a TelephonyProviderRegistry pre-populated with the application's supported telephony provider instances.
    
    The returned registry has the following providers registered, in order: BolnaProvider, TwilioProvider, PlivoProvider, ExotelProvider, FreeSwitchProvider.
    
    Returns:
        TelephonyProviderRegistry: A registry containing the registered provider instances in registration order.
    """
    reg = TelephonyProviderRegistry()
    reg.register(BolnaProvider())
    reg.register(TwilioProvider())
    reg.register(PlivoProvider())
    reg.register(ExotelProvider())
    reg.register(FreeSwitchProvider())
    return reg
