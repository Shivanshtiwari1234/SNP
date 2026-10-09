# Changelog

## 0.1.0

- Initial SNP protocol specification and packet validation rules
- Request-tracking semantics based on the 32-bit sequence field
- Optional reliable delivery with bounded retry logic and duplicate suppression
- Public synchronous peer API and UDP server wrapper
- Application-level fragmentation for large logical messages
- LAN peer discovery over UDP
- HMAC-based authenticated packet wrapper and documented security guidance
- Package-based module layout for clearer protocol and transport separation
