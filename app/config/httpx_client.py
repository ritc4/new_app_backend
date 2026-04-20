from pydantic import BaseModel


class HttpxClientConfig(BaseModel):
    timeout: float = 10.0
    max_connections: int = 100
    max_keepalive: int = 20
