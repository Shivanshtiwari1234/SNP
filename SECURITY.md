# SNP Security Design

## Threat model

SNP is a small UDP protocol intended for local and controlled network environments. The current implementation assumes that:

- packets may be observed or replayed by an attacker on the same local network
- peers may send malformed or tampered packets
- source IP addresses are not sufficient trust evidence
- application-level identity, key provisioning, and authorization are handled outside the protocol unless explicitly configured

## Requirements

The design goal for this update is to protect SNP traffic against:

- spoofing
- tampering
- replay of prior valid packets
- accidental acceptance of unauthenticated data

## Security model

The implementation uses a symmetric shared secret and a keyed HMAC to authenticate packet integrity:

- every secure packet includes a unique nonce
- the nonce and payload are combined with the shared secret
- a SHA-256 HMAC is generated over the nonce and payload
- the tag is stored in the secure packet payload and verified before the message is accepted

This provides message integrity and peer authentication for peers that already share a consented secret. It does not provide confidentiality by itself. For encrypted payload confidentiality, a stronger transport such as DTLS or another established encrypted protocol should be used at a higher layer or as an alternative transport.

## Key provisioning

Secrets must be provisioned out of band and stored outside the project source tree. The current implementation does not write keys to logs or the repository. A caller must provide the secret at runtime.

## Replay and nonce handling

- each secure packet uses a unique nonce derived from a monotonic timestamp and the shared secret
- receivers reject packets whose authentication tag does not match the expected HMAC
- repeated packets are not implicitly trusted; the caller is responsible for replay checking at the application layer when required

## Failure handling

If authentication fails, the packet is rejected with `SNPError`. The receiver must not silently fall back to insecure message processing, and the packet must not be treated as trusted merely because it arrived on a valid UDP socket.

## Limitations

This update does not claim full secure transport semantics. In particular:

- it does not provide confidentiality for payloads without a separate encrypted channel
- it does not define certificate-based trust or distributed key management
- it does not claim cryptographic review beyond the standard library HMAC primitives used here

## Recommendation

For production deployments, prefer a protocol such as DTLS or another maintained secure transport over direct UDP when confidentiality and strong session semantics are required. The SNP secure wrapper is best understood as a lightweight integrity/authentication layer for controlled local deployments.
