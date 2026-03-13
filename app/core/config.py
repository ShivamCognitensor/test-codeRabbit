"""Unified configuration for the merged FinAI service.

This repo now contains:
- The new service code (routers under `/api/v1/...`)
- The legacy service code (routers under `/v1/...`)

Both codepaths read configuration from `app.core.config`.
To avoid breaking legacy imports, we keep the new (UPPER_SNAKE_CASE) settings
*and* provide compatibility properties/methods used by the legacy codebase.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional, Set

from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # ---------------------------------------------------------------------
    # New service canonical settings (UPPERCASE)
    # ---------------------------------------------------------------------

    # Server
    HOST: str = Field(default="0.0.0.0", validation_alias=AliasChoices("HOST", "APP_HOST"))
    PORT: int = Field(default=8007, validation_alias=AliasChoices("PORT", "APP_PORT"))
    DEBUG: bool = Field(default=False, validation_alias=AliasChoices("DEBUG"))
    LOG_LEVEL: str = Field(default="INFO", validation_alias=AliasChoices("LOG_LEVEL"))
    LOG_JSON: bool = Field(default=False, validation_alias=AliasChoices("LOG_JSON"))
    APP_ENV: str = Field(default="dev", validation_alias=AliasChoices("APP_ENV"))

    # Database
    # Prefer DATABASE_URL (new). Accept DATABASE_URL_ASYNC (legacy).
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/lms_finai_db",
        validation_alias=AliasChoices("DATABASE_URL", "DATABASE_URL_ASYNC"),
    )
    # Alembic / sync URL (optional, legacy)
    DATABASE_URL_SYNC: Optional[str] = Field(default=None, validation_alias=AliasChoices("DATABASE_URL_SYNC"))

    # Service URLs
    IDENTITY_SERVICE_URL: str = Field(default="http://localhost:8001", validation_alias=AliasChoices("IDENTITY_SERVICE_URL"))
    CONFIG_SERVICE_URL: str = Field(default="http://localhost:8002", validation_alias=AliasChoices("CONFIG_SERVICE_URL"))
    LEAD_OPS_SERVICE_URL: str = Field(default="http://localhost:8003", validation_alias=AliasChoices("LEAD_OPS_SERVICE_URL"))
    AUDIT_SERVICE_URL: str = Field(default="http://localhost:8004", validation_alias=AliasChoices("AUDIT_SERVICE_URL"))
    NOTIFICATION_SERVICE_URL: str = Field(default="http://localhost:8005", validation_alias=AliasChoices("NOTIFICATION_SERVICE_URL"))

    # Service-to-Service Auth
    SERVICE_CLIENT_ID: str = Field(default="finai-service", validation_alias=AliasChoices("SERVICE_CLIENT_ID"))
    SERVICE_CLIENT_SECRET: str = Field(default="finai-secret-key-123", validation_alias=AliasChoices("SERVICE_CLIENT_SECRET"))
    SERVICE_NAME: str = Field(default="lms-finai", validation_alias=AliasChoices("SERVICE_NAME"))

    # JWT
    JWKS_URL: Optional[str] = Field(default="http://localhost:8001/jwks.json", validation_alias=AliasChoices("JWKS_URL"))
    JWT_AUDIENCE: Optional[str] = Field(default="lms", validation_alias=AliasChoices("JWT_AUDIENCE"))

    # OpenAI
    OPENAI_API_KEY: Optional[str] = Field(default=None, validation_alias=AliasChoices("OPENAI_API_KEY"))
    OPENAI_BASE_URL: Optional[str] = Field(default=None, validation_alias=AliasChoices("OPENAI_BASE_URL"))
    OPENAI_ORG_ID: Optional[str] = Field(default=None, validation_alias=AliasChoices("OPENAI_ORG_ID"))
    OPENAI_PROJECT_ID: Optional[str] = Field(default=None, validation_alias=AliasChoices("OPENAI_PROJECT_ID"))
    OPENAI_CHAT_MODEL: str = Field(default="gpt-4o-mini", validation_alias=AliasChoices("OPENAI_CHAT_MODEL"))
    OPENAI_WHISPER_MODEL: str = Field(default="gpt-4o-mini-transcribe", validation_alias=AliasChoices("OPENAI_WHISPER_MODEL"))
    OPENAI_TTS_MODEL: str = Field(default="tts-1", validation_alias=AliasChoices("OPENAI_TTS_MODEL"))
    OPENAI_TTS_VOICE: str = Field(default="nova", validation_alias=AliasChoices("OPENAI_TTS_VOICE"))

    # -----------------------------------------------------------------
    # Local / open-source audio model configuration
    # -----------------------------------------------------------------
    # STT selection: whisper | canary | openai
    STT_PROVIDER: str = Field(default="whisper", validation_alias=AliasChoices("STT_PROVIDER"))
    # faster-whisper model name (e.g. deepdml/faster-whisper-large-v3-turbo-ct2)
    WHISPER_MODEL_NAME: str = Field(default="deepdml/faster-whisper-large-v3-turbo-ct2", validation_alias=AliasChoices("WHISPER_MODEL_NAME"))
    # Optional overrides
    WHISPER_DEVICE: Optional[str] = Field(default=None, validation_alias=AliasChoices("WHISPER_DEVICE"))
    WHISPER_COMPUTE_TYPE: Optional[str] = Field(default=None, validation_alias=AliasChoices("WHISPER_COMPUTE_TYPE"))
    # Canary Qwen 2.5B (NeMo SALM)
    CANARY_MODEL_NAME: str = Field(default="nvidia/canary-qwen-2.5b", validation_alias=AliasChoices("CANARY_MODEL_NAME"))

    # TTS selection: kokoro | fish | openai
    TTS_PROVIDER: str = Field(default="kokoro", validation_alias=AliasChoices("TTS_PROVIDER"))
    TTS_DEFAULT_VOICE: str = Field(default="af_heart", validation_alias=AliasChoices("TTS_DEFAULT_VOICE"))
    # Fish Speech (OpenAI-compatible TTS server)
    FISH_TTS_BASE_URL: Optional[str] = Field(default=None, validation_alias=AliasChoices("FISH_TTS_BASE_URL"))
    FISH_TTS_API_KEY: Optional[str] = Field(default=None, validation_alias=AliasChoices("FISH_TTS_API_KEY"))
    FISH_TTS_MODEL: Optional[str] = Field(default=None, validation_alias=AliasChoices("FISH_TTS_MODEL"))

    # -----------------------------------------------------------------
    # FinAI Voicebot Service (remote local models: STT + LLM + TTS)
    # -----------------------------------------------------------------
    VOICEBOT_REMOTE_BASE_URL: Optional[str] = Field(default="http://3.109.92.183:8010", validation_alias=AliasChoices("VOICEBOT_REMOTE_BASE_URL"))
    VOICEBOT_REMOTE_API_KEY: Optional[str] = Field(default=None, validation_alias=AliasChoices("VOICEBOT_REMOTE_API_KEY"))
    VOICEBOT_REMOTE_DEFAULT_STACK: str = Field(default="voicefin_meta_v1", validation_alias=AliasChoices("VOICEBOT_REMOTE_DEFAULT_STACK"))
    VOICEBOT_REMOTE_TIMEOUT_S: int = Field(default=120, validation_alias=AliasChoices("VOICEBOT_REMOTE_TIMEOUT_S"))

    # Local LLM for the open-source realtime gateway (OpenAI-compatible)
    LOCAL_LLM_BASE_URL: Optional[str] = Field(default=None, validation_alias=AliasChoices("LOCAL_LLM_BASE_URL"))
    LOCAL_LLM_API_KEY: Optional[str] = Field(default=None, validation_alias=AliasChoices("LOCAL_LLM_API_KEY"))
    LOCAL_LLM_MODEL: Optional[str] = Field(default=None, validation_alias=AliasChoices("LOCAL_LLM_MODEL"))
    # Post-call analytics (OpenAI compatible)
    ANALYTICS_PROVIDER: str = Field(default="openai", validation_alias=AliasChoices("ANALYTICS_PROVIDER"))
    ANALYTICS_MODEL: Optional[str] = Field(default=None, validation_alias=AliasChoices("ANALYTICS_MODEL"))
    ANALYTICS_BASE_URL: Optional[str] = Field(default=None, validation_alias=AliasChoices("ANALYTICS_BASE_URL"))
    ANALYTICS_API_KEY: Optional[str] = Field(default=None, validation_alias=AliasChoices("ANALYTICS_API_KEY"))


    # Knowledge Base (RAG)
    KB_ENABLED: bool = Field(default=False, validation_alias=AliasChoices("KB_ENABLED"))
    KB_DOCS_PATH: str = Field(default="./kb_docs", validation_alias=AliasChoices("KB_DOCS_PATH"))
    KB_INDEX_DIR: str = Field(default="./kb_index", validation_alias=AliasChoices("KB_INDEX_DIR"))
    KB_EMBED_MODEL: str = Field(default="text-embedding-3-small", validation_alias=AliasChoices("KB_EMBED_MODEL"))
    KB_TOP_K: int = Field(default=5, validation_alias=AliasChoices("KB_TOP_K"))
    KB_MIN_SCORE: float = Field(default=0.20, validation_alias=AliasChoices("KB_MIN_SCORE"))

    # Redis
    REDIS_URL: Optional[str] = Field(default=None, validation_alias=AliasChoices("REDIS_URL"))

    # Bolna.ai
    BOLNA_API_BASE: str = Field(default="https://api.bolna.ai", validation_alias=AliasChoices("BOLNA_API_BASE"))
    BOLNA_API_KEY: Optional[str] = Field(default=None, validation_alias=AliasChoices("BOLNA_API_KEY"))
    BOLNA_DEFAULT_AGENT_ID: Optional[str] = Field(default=None, validation_alias=AliasChoices("BOLNA_DEFAULT_AGENT_ID"))
    BOLNA_DEFAULT_FROM_PHONE_NUMBER: Optional[str] = Field(default=None, validation_alias=AliasChoices("BOLNA_DEFAULT_FROM_PHONE_NUMBER"))
    BOLNA_WEBHOOK_SECRET: Optional[str] = Field(default=None, validation_alias=AliasChoices("BOLNA_WEBHOOK_SECRET"))
    BOLNA_WEBHOOK_SECRET_HEADER: str = Field(default="X-Bolna-Webhook-Secret", validation_alias=AliasChoices("BOLNA_WEBHOOK_SECRET_HEADER"))

    # Optional shared secret for legacy OpenAI-compatible endpoint (Bolna LLM server)
    LLM_SECRET_HEADER_NAME: str = Field(default="X-LLM-Secret", validation_alias=AliasChoices("LLM_SECRET_HEADER_NAME"))

    # ---------------------------------------------------------------------
    # Telephony gateway (multi-provider) + voice engine
    # ---------------------------------------------------------------------
    TELEPHONY_DEFAULT_PROVIDER: str = Field(default="bolna", validation_alias=AliasChoices("TELEPHONY_DEFAULT_PROVIDER"))
    TELEPHONY_PUBLIC_HTTP_BASE: Optional[str] = Field(default=None, validation_alias=AliasChoices("TELEPHONY_PUBLIC_HTTP_BASE"))
    TELEPHONY_PUBLIC_WS_BASE: Optional[str] = Field(default=None, validation_alias=AliasChoices("TELEPHONY_PUBLIC_WS_BASE"))
    TELEPHONY_SESSION_TTL_SECONDS: int = Field(default=3600, validation_alias=AliasChoices("TELEPHONY_SESSION_TTL_SECONDS"))

    # Twilio
    TWILIO_ACCOUNT_SID: Optional[str] = Field(default=None, validation_alias=AliasChoices("TWILIO_ACCOUNT_SID"))
    TWILIO_AUTH_TOKEN: Optional[str] = Field(default=None, validation_alias=AliasChoices("TWILIO_AUTH_TOKEN"))
    TWILIO_FROM_PHONE_NUMBER: Optional[str] = Field(default=None, validation_alias=AliasChoices("TWILIO_FROM_PHONE_NUMBER"))

    # Plivo
    PLIVO_AUTH_ID: Optional[str] = Field(default=None, validation_alias=AliasChoices("PLIVO_AUTH_ID"))
    PLIVO_AUTH_TOKEN: Optional[str] = Field(default=None, validation_alias=AliasChoices("PLIVO_AUTH_TOKEN"))
    PLIVO_FROM_PHONE_NUMBER: Optional[str] = Field(default=None, validation_alias=AliasChoices("PLIVO_FROM_PHONE_NUMBER"))

    # Exotel
    EXOTEL_API_KEY: Optional[str] = Field(default=None, validation_alias=AliasChoices("EXOTEL_API_KEY"))
    EXOTEL_API_TOKEN: Optional[str] = Field(default=None, validation_alias=AliasChoices("EXOTEL_API_TOKEN"))
    EXOTEL_ACCOUNT_SID: Optional[str] = Field(default=None, validation_alias=AliasChoices("EXOTEL_ACCOUNT_SID"))
    EXOTEL_DOMAIN: Optional[str] = Field(default="api.in.exotel.com", validation_alias=AliasChoices("EXOTEL_DOMAIN"))
    EXOTEL_CALLERID: Optional[str] = Field(default=None, validation_alias=AliasChoices("EXOTEL_CALLERID"))
    # Exotel Call Flow URL that contains AgentStream applet (required for outbound dial)
    EXOTEL_FLOW_URL: Optional[str] = Field(default=None, validation_alias=AliasChoices("EXOTEL_FLOW_URL"))

    # FreeSWITCH (SIP gateway) - optional
    FREESWITCH_ESL_HOST: Optional[str] = Field(default=None, validation_alias=AliasChoices("FREESWITCH_ESL_HOST"))
    FREESWITCH_ESL_PORT: int = Field(default=8021, validation_alias=AliasChoices("FREESWITCH_ESL_PORT"))
    FREESWITCH_ESL_PASSWORD: Optional[str] = Field(default=None, validation_alias=AliasChoices("FREESWITCH_ESL_PASSWORD"))
    # Example: external or internal (sofia profile)
    FREESWITCH_SOFIA_PROFILE: str = Field(default="external", validation_alias=AliasChoices("FREESWITCH_SOFIA_PROFILE"))
    # If using a registered SIP gateway: e.g. my_gateway
    FREESWITCH_SIP_GATEWAY: Optional[str] = Field(default=None, validation_alias=AliasChoices("FREESWITCH_SIP_GATEWAY"))
    # Audio streaming WS endpoint selection
    FREESWITCH_STREAM_MODE: str = Field(default="mod_audio_stream", validation_alias=AliasChoices("FREESWITCH_STREAM_MODE"))
    FREESWITCH_STREAM_SAMPLE_RATE: int = Field(default=16000, validation_alias=AliasChoices("FREESWITCH_STREAM_SAMPLE_RATE"))

    # OpenAI Realtime (audio-to-audio)
    OPENAI_REALTIME_URL: Optional[str] = Field(default="wss://api.openai.com/v1/realtime", validation_alias=AliasChoices("OPENAI_REALTIME_URL"))
    OPENAI_REALTIME_MODEL: Optional[str] = Field(default=None, validation_alias=AliasChoices("OPENAI_REALTIME_MODEL"))
    OPENAI_TRANSCRIBE_MODEL: Optional[str] = Field(default=None, validation_alias=AliasChoices("OPENAI_TRANSCRIBE_MODEL"))
    OPENAI_REALTIME_START_WITH_GREETING: bool = Field(default=True, validation_alias=AliasChoices("OPENAI_REALTIME_START_WITH_GREETING"))

    # Local realtime gateway (audio-to-audio, open-source models) - optional
    LOCAL_A2A_WS_URL: Optional[str] = Field(default=None, validation_alias=AliasChoices("LOCAL_A2A_WS_URL"))
    LOCAL_A2A_API_KEY: Optional[str] = Field(default=None, validation_alias=AliasChoices("LOCAL_A2A_API_KEY"))
    LOCAL_A2A_MODEL: Optional[str] = Field(default=None, validation_alias=AliasChoices("LOCAL_A2A_MODEL"))


    LLM_SHARED_SECRET: Optional[str] = Field(default=None, validation_alias=AliasChoices("LLM_SHARED_SECRET"))

    # Campaign runner
    CAMPAIGN_TICK_SECONDS: int = Field(default=30, validation_alias=AliasChoices("CAMPAIGN_TICK_SECONDS"))
    CAMPAIGN_DEFAULT_CALLS_PER_MINUTE: int = Field(default=6, validation_alias=AliasChoices("CAMPAIGN_DEFAULT_CALLS_PER_MINUTE"))
    CAMPAIGN_DEFAULT_BATCH_SIZE: int = Field(default=25, validation_alias=AliasChoices("CAMPAIGN_DEFAULT_BATCH_SIZE"))
    CAMPAIGN_DEFAULT_TIMEZONE: str = Field(default="Asia/Kolkata", validation_alias=AliasChoices("CAMPAIGN_DEFAULT_TIMEZONE"))
    CAMPAIGN_UPLOAD_PATH: str = Field(default="/tmp/campaigns", validation_alias=AliasChoices("CAMPAIGN_UPLOAD_PATH"))
    MAX_CAMPAIGN_CONTACTS: int = Field(default=10000, validation_alias=AliasChoices("MAX_CAMPAIGN_CONTACTS"))

    # Security
    API_KEY_HEADER_NAME: str = Field(default="X-API-Key", validation_alias=AliasChoices("API_KEY_HEADER_NAME"))
    API_KEYS: Optional[str] = Field(default=None, validation_alias=AliasChoices("API_KEYS"))

    # Limits
    MAX_AUDIO_MB: int = Field(default=25, validation_alias=AliasChoices("MAX_AUDIO_MB"))
    WS_MAX_BUFFER_SECONDS: int = Field(default=20, validation_alias=AliasChoices("WS_MAX_BUFFER_SECONDS"))
    REQUEST_TIMEOUT: float = Field(default=30.0, validation_alias=AliasChoices("REQUEST_TIMEOUT"))

    # Contextual chat
    ENRICH_USER_CONTEXT: bool = Field(default=True, validation_alias=AliasChoices("ENRICH_USER_CONTEXT"))
    CHATBOT_MAX_HISTORY: int = Field(default=10, validation_alias=AliasChoices("CHATBOT_MAX_HISTORY"))

    # Public chat
    PUBLIC_CHAT_ENABLED: bool = Field(default=True, validation_alias=AliasChoices("PUBLIC_CHAT_ENABLED"))
    PUBLIC_CHAT_MAX_MESSAGES: int = Field(default=10, validation_alias=AliasChoices("PUBLIC_CHAT_MAX_MESSAGES"))
    PUBLIC_CHAT_SESSION_TTL: int = Field(default=3600, validation_alias=AliasChoices("PUBLIC_CHAT_SESSION_TTL"))
    PUBLIC_CHAT_RATE_LIMIT: int = Field(default=20, validation_alias=AliasChoices("PUBLIC_CHAT_RATE_LIMIT"))
    PUBLIC_CHAT_MAX_MESSAGE_LENGTH: int = Field(default=500, validation_alias=AliasChoices("PUBLIC_CHAT_MAX_MESSAGE_LENGTH"))

    # ---------------------------------------------------------------------
    # Legacy compatibility properties (lowercase names used in v17)
    # ---------------------------------------------------------------------

    @property
    def app_env(self) -> str:
        """
        Expose the application's environment name for legacy compatibility.
        
        Returns:
            The application environment name.
        """
        return self.APP_ENV

    @property
    def app_host(self) -> str:
        """
        Get the configured application host.
        
        Returns:
            str: The configured HOST value.
        """
        return self.HOST

    @property
    def app_port(self) -> int:
        """
        Legacy lowercase accessor for the application's configured network port.
        
        Returns:
            int: The configured port number.
        """
        return self.PORT

    @property
    def log_level(self) -> str:
        """
        Gets the configured log level.
        
        Returns:
            The configured log level as a string.
        """
        return self.LOG_LEVEL

    @property
    def log_json(self) -> bool:
        """
        Whether logs should be emitted in JSON format.
        
        @returns:
            `True` if logging is configured to use JSON, `False` otherwise.
        """
        return bool(self.LOG_JSON)

    @property
    def openai_api_key(self) -> str:
        """
        Compatibility accessor that exposes the configured OpenAI API key for legacy code.
        
        Returns:
            str: The OpenAI API key, or an empty string if not set.
        """
        return self.OPENAI_API_KEY or ""

    @property
    def openai_base_url(self) -> Optional[str]:
        """
        Compatibility accessor that returns the configured OpenAI base URL.
        
        Returns:
            The configured OpenAI base URL as a string, or None if not set.
        """
        return self.OPENAI_BASE_URL

    @property
    def openai_org_id(self) -> Optional[str]:
        """
        Expose the OpenAI organization identifier for legacy/compatibility access.
        
        Returns:
            `str` containing the OpenAI organization identifier, or `None` if it is not configured.
        """
        return self.OPENAI_ORG_ID

    @property
    def openai_project_id(self) -> Optional[str]:
        """
        Expose the configured OpenAI project identifier.
        
        Returns:
            The OpenAI project identifier if configured, otherwise None.
        """
        return self.OPENAI_PROJECT_ID

    @property
    def openai_chat_model(self) -> str:
        """
        Get the configured OpenAI chat model name.
        
        Returns:
            The OpenAI chat model identifier.
        """
        return self.OPENAI_CHAT_MODEL

    @property
    def openai_whisper_model(self) -> str:
        """
        Legacy compatibility accessor for the configured OpenAI Whisper model name.
        
        Returns:
            str: The OpenAI Whisper model name from configuration.
        """
        return self.OPENAI_WHISPER_MODEL

    @property
    def openai_tts_model(self) -> str:
        """
        Provide the configured OpenAI TTS model name for backward compatibility.
        
        Returns:
            openai_tts_model (str): The OpenAI Text-to-Speech model identifier.
        """
        return self.OPENAI_TTS_MODEL

    @property
    def openai_tts_voice(self) -> str:
        """
        Get the configured OpenAI text-to-speech voice identifier.
        
        Returns:
            openai_tts_voice (str): The OpenAI TTS voice identifier.
        """
        return self.OPENAI_TTS_VOICE

    @property
    def kb_enabled(self) -> bool:
        """
        Indicates whether the knowledge base (RAG) feature is enabled.
        
        Returns:
            `true` if the knowledge base is enabled, `false` otherwise.
        """
        return self.KB_ENABLED

    @property
    def kb_docs_path(self) -> str:
        """
        Path to the knowledge base documents directory.
        
        Returns:
            The filesystem path to the knowledge base documents directory as a string.
        """
        return self.KB_DOCS_PATH

    @property
    def kb_index_dir(self) -> str:
        """
        Path to the directory used to store knowledge-base (RAG) index files.
        
        Returns:
            The filesystem path to the KB index directory.
        """
        return self.KB_INDEX_DIR

    @property
    def kb_embed_model(self) -> str:
        """
        Get the embedding model identifier configured for the knowledge base.
        
        Returns:
            embedding_model (str): The embedding model name or identifier from KB_EMBED_MODEL.
        """
        return self.KB_EMBED_MODEL

    @property
    def kb_top_k(self) -> int:
        """
        Access the knowledge-base retrieval top-k value.
        
        Returns:
            int: Number of top documents to return for knowledge-base (RAG) retrieval.
        """
        return self.KB_TOP_K

    @property
    def kb_min_score(self) -> float:
        """
        Minimum similarity score threshold used to filter knowledge-base retrieval results.
        
        Returns:
            The configured minimum similarity score as a float.
        """
        return self.KB_MIN_SCORE

    @property
    def redis_url(self) -> Optional[str]:
        """
        Get the configured Redis connection URL.
        
        Returns:
            `str` containing the Redis URL, or `None` if not set.
        """
        return self.REDIS_URL

    @property
    def database_url_async(self) -> str:
        # Legacy expects an async URL
        """
        Expose the async database connection URL for legacy compatibility.
        
        Returns:
            The async database connection URL.
        """
        return self.DATABASE_URL

    @property
    def database_url_sync(self) -> str:
        """
        Provide a database URL suitable for synchronous clients (falls back from the configured async URL when needed).
        
        Returns:
            str: The synchronous database URL. If `DATABASE_URL_SYNC` is set, that value is returned; otherwise, if `DATABASE_URL` contains `+asyncpg` it is replaced with `+psycopg2`; otherwise `DATABASE_URL` is returned.
        """
        if self.DATABASE_URL_SYNC:
            return self.DATABASE_URL_SYNC
        # Best-effort convert async URL to sync URL for Alembic
        url = self.DATABASE_URL
        if "+asyncpg" in url:
            return url.replace("+asyncpg", "+psycopg2")
        return url

    @property
    def lead_ops_service_url(self) -> Optional[str]:
        """
        Legacy-compatible accessor for the Lead Ops service URL.
        
        Returns:
            The Lead Ops service URL as a string, or `None` if not configured.
        """
        return self.LEAD_OPS_SERVICE_URL

    @property
    def lms_config_service_url(self) -> Optional[str]:
        """
        Compatibility accessor that returns the configured Configuration Service URL.
        
        Returns:
            The configuration service URL as a string, or `None` if not set.
        """
        return self.CONFIG_SERVICE_URL

    @property
    def enrich_user_context(self) -> bool:
        """
        Indicates whether enrichment of user context is enabled.
        
        Returns:
            True if user context enrichment is enabled, False otherwise.
        """
        return self.ENRICH_USER_CONTEXT

    @property
    def jwks_url(self) -> Optional[str]:
        """
        Get the configured JWKS endpoint URL used for JWT verification.
        
        Returns:
            str | None: The JWKS URL used to validate JWTs, or `None` if not configured.
        """
        return self.JWKS_URL

    @property
    def jwt_audience(self) -> Optional[str]:
        """
        Legacy-compatible accessor for the JWT audience setting.
        
        Returns:
            The `JWT_AUDIENCE` value if set, `None` otherwise.
        """
        return self.JWT_AUDIENCE

    @property
    def api_key_header_name(self) -> str:
        """
        Expose the configured API key header name for legacy compatibility.
        
        Returns:
            str: The configured API key header name.
        """
        return self.API_KEY_HEADER_NAME

    @property
    def api_keys(self) -> Optional[str]:
        """
        Get the raw API_KEYS configuration string.
        
        Returns:
            `str` containing comma-separated API keys, or `None` if not set.
        """
        return self.API_KEYS

    def parsed_api_keys(self) -> Set[str]:
        """
        Parse the API_KEYS setting into a set of individual API key strings.
        
        Returns:
            A set of trimmed, non-empty API key strings; an empty set if the API_KEYS setting is empty.
        """
        if not self.API_KEYS:
            return set()
        return {k.strip() for k in self.API_KEYS.split(",") if k.strip()}

    @property
    def max_audio_mb(self) -> int:
        """Maximum allowed audio size in megabytes.
        
        Returns:
            int: The configured maximum audio file size in megabytes.
        """
        return self.MAX_AUDIO_MB

    @property
    def ws_max_buffer_seconds(self) -> int:
        """
        Get the configured maximum WebSocket buffer duration in seconds.
        
        Returns:
            int: The maximum WebSocket buffer duration in seconds.
        """
        return self.WS_MAX_BUFFER_SECONDS

    @property
    def bolna_api_key(self) -> Optional[str]:
        """
        Access the configured Bolna.ai API key.
        
        Returns:
            str: The Bolna.ai API key, or `None` if not configured.
        """
        return self.BOLNA_API_KEY

    @property
    def bolna_api_base(self) -> str:
        """
        Provide the configured Bolna API base URL.
        
        Returns:
            bolna_api_base (str): The value of `BOLNA_API_BASE`.
        """
        return self.BOLNA_API_BASE

    @property
    def bolna_default_agent_id(self) -> Optional[str]:
        """
        Compatibility accessor that exposes the configured default agent ID for Bolna.ai.
        
        Returns:
            str or None: The Bolna.ai default agent identifier if configured, otherwise None.
        """
        return self.BOLNA_DEFAULT_AGENT_ID

    @property
    def bolna_default_from_phone_number(self) -> Optional[str]:
        """
        Expose the configured default sender phone number for the Bolna.ai integration.
        
        Returns:
            `str` containing the default "from" phone number if set, `None` otherwise.
        """
        return self.BOLNA_DEFAULT_FROM_PHONE_NUMBER

    @property
    def llm_secret_header_name(self) -> str:
        """
        Get the configured HTTP header name for the LLM shared secret.
        
        Returns:
            The configured HTTP header name for the LLM shared secret.
        """
        return self.LLM_SECRET_HEADER_NAME

    @property
    def llm_shared_secret(self) -> Optional[str]:
        """
        Access the LLM shared secret used to authenticate internal LLM requests.
        
        Returns:
            str or None: The configured LLM shared secret, or `None` if not set.
        """
        return self.LLM_SHARED_SECRET

    @property
    def bolna_webhook_secret(self) -> Optional[str]:
        """
        Access the configured Bolna webhook secret.
        
        Returns:
            str | None: The webhook secret used to verify Bolna webhook requests, or None if not configured.
        """
        return self.BOLNA_WEBHOOK_SECRET

    @property
    def bolna_webhook_secret_header(self) -> str:
        """
        Header name used to verify Bolna.ai webhook payloads.
        
        Returns:
            str: The configured HTTP header name that carries the Bolna webhook secret.
        """
        return self.BOLNA_WEBHOOK_SECRET_HEADER

    @property
    def campaign_tick_seconds(self) -> int:
        """
        Campaign runner tick interval in seconds.
        
        Returns:
            int: Number of seconds between campaign runner ticks.
        """
        return self.CAMPAIGN_TICK_SECONDS

    @property
    def campaign_default_calls_per_minute(self) -> int:
        """
        Provides the default number of campaign calls allowed per minute.
        
        Returns:
            int: The configured calls-per-minute limit for campaigns.
        """
        return self.CAMPAIGN_DEFAULT_CALLS_PER_MINUTE

    @property
    def campaign_default_batch_size(self) -> int:
        """
        Expose the configured default batch size used by the campaign runner.
        
        Returns:
            default_batch_size (int): The configured number of items to process in a single campaign batch.
        """
        return self.CAMPAIGN_DEFAULT_BATCH_SIZE

    @property
    def campaign_default_timezone(self) -> str:
        """
        Default timezone used for campaign scheduling.
        
        Returns:
            The IANA timezone string used as the default for campaign scheduling.
        """
        return self.CAMPAIGN_DEFAULT_TIMEZONE

    # ---------------------------------------------------------------------
    # Convenience helpers
    # ---------------------------------------------------------------------

    def is_openai_enabled(self) -> bool:
        """
        Determine whether the OpenAI integration is enabled.
        
        Returns:
            `true` if an OpenAI API key is configured, `false` otherwise.
        """
        return bool(self.OPENAI_API_KEY)

    def is_bolna_enabled(self) -> bool:
        """
        Check whether Bolna.ai integration is enabled by verifying a configured API key.
        
        Returns:
            `true` if `BOLNA_API_KEY` is a non-empty value, `false` otherwise.
        """
        return bool(self.BOLNA_API_KEY)


@lru_cache()
def get_settings() -> Settings:
    """
    Create and return a Settings instance configured from environment variables and the project's .env file.
    
    Returns:
        Settings: A Settings instance populated from environment variables and the .env file.
    """
    return Settings()


# Legacy alias used across v17
get_app_settings = get_settings


settings = get_settings()
