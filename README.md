# Shivi Network Protocol (SNP)

Version: 0.1.0

SNP is a lightweight UDP-based application protocol for simple request/response exchanges between a client and a server. The current implementation is intentionally small and focused on binary packet validation, transport over IPv4 UDP, and straightforward message delivery without higher-level reliability guarantees.

## Purpose

SNP is designed for:

- small payloads encoded as binary packets
- client/server communication over UDP
- simple request messages and corresponding responses
- protocol validation and predictable rejection of malformed data

It is a minimal protocol intended for experimentation and small local network services. It does not define a full distributed messaging system or robust end-to-end reliability.

## Current protocol version

- Protocol version: 1
- Magic signature: `SNPK`
- Header format: network byte order (big-endian)

## Packet format

Each SNP packet consists of a fixed 12-byte header followed by a payload.

### Header layout

The header is packed as:

- `4s` magic signature (`SNPK`)
- `B` protocol version
- `B` message type
- `I` sequence number
- `H` payload length

This is equivalent to the following layout:

| Field | Size | Byte order | Meaning |
| --- | ---: | --- | --- |
| Magic signature | 4 bytes | network | Identifies the packet as SNP; must be `SNPK` |
| Version | 1 byte | network | Current protocol version; only value `1` is accepted |
| Message type | 1 byte | network | Packet type: `1` = message, `2` = response |
| Sequence number | 4 bytes | network | Unsigned 32-bit value used to correlate requests and responses |
| Payload length | 2 bytes | network | Unsigned 16-bit payload size in bytes |

The overall structure is:

```text
+----------------------+---------------------+
| Header (12 bytes)     | Payload             |
+----------------------+---------------------+
```

The packed format is defined in Python as:

```python
HEADER = struct.Struct("!4sBBIH")
```

### Maximum sizes

- Maximum payload size: 1200 bytes
- Maximum packet size: 1212 bytes

This is calculated as:

```text
MAX_PACKET = HEADER_SIZE + MAX_PAYLOAD = 12 + 1200 = 1212 bytes
```

## Message types

The current implementation recognizes the following message types:

- `1` — MESSAGE
- `2` — RESPONSE

Unknown message types are rejected during decode and must not be treated as valid SNP packets.

## Sequence number behavior

The sequence number is an unsigned 32-bit integer in network order.

Current rules:

- Valid range is `0` through `4294967295` inclusive.
- The sender is responsible for choosing a valid sequence number.
- A response must use the same sequence number as the request it answers.
- The implementation currently uses the sequence number as the correlation identifier for a request/response exchange.

## Request/response behavior

The current client/server flow is intentionally simple:

1. The client creates a MESSAGE packet with a valid sequence number and UTF-8 payload.
2. The client sends the message to the server over UDP.
3. The server receives the datagram and validates the packet.
4. If the packet is a MESSAGE, the server decodes the payload as UTF-8 and prints it.
5. The server returns a RESPONSE packet with the same sequence number and payload of the form `Received: <original payload>`.
6. The client waits for a response on the same socket and validates:
   - response packet type is `RESPONSE`
   - sequence number matches the original request
   - sender host matches the server host

This is a basic synchronous request/response exchange for one request at a time.

## UDP semantics

SNP runs over UDP and therefore does not guarantee:

- delivery
- ordering
- duplicate prevention
- reliability
- end-to-end confirmation of processing

A UDP datagram may be lost, delayed, duplicated, or arrive out of order. The protocol implementation does not currently perform retransmission, acknowledgement, duplicate suppression, or persistent retry logic.

## Handling malformed packets

Malformed or unsupported packets are rejected by the decoder rather than processed.

The packet decoder currently rejects, raises `SNPError`, and does not continue processing if any of the following conditions are true:

- the packet is shorter than the 12-byte SNP header
- the packet exceeds the maximum allowed size of 1212 bytes
- the magic signature is not `SNPK`
- the protocol version is not `1`
- the message type is not `1` or `2`
- the declared payload length does not match the actual payload size

The server catches `SNPError` and logs the rejection without crashing.

## Backward compatibility and version changes

The current protocol version is 1. Future changes must preserve compatibility rules:

- existing packets with valid magic and recognized version must keep working where possible
- incompatible wire-format changes require a documented protocol-version change
- old clients and servers should reject unsupported versions rather than guessing how to interpret the payload
- changes to packet semantics should be documented in the README before they are relied on by implementations

This ensures a clear migration path when the protocol expands in later updates.

## Running the server

Start the SNP server:

```bash
python snp.py server --host 127.0.0.1 --port 9000
```

The server binds to the UDP socket and waits for incoming SNP packets.

## Sending a message

Send a message from the client:

```bash
python snp.py send "Hello from SNP!" --host 127.0.0.1 --port 9000
```

The client sends a MESSAGE packet and waits for a RESPONSE packet with the same sequence number.

## Installation and local usage

Clone the repository and run the project from the root directory:

```bash
git clone <repository-url>
cd SNP
python -m unittest -q
```

The protocol library is importable as `snp` and the command-line interface remains available through the package entry point and the existing script pattern. For a basic local exchange, start one process as a server and then send a message from a client process using the public API or direct UDP helpers.

## Public peer API

The project also exposes a small synchronous client/server API for convenient request/response usage:

```python
from snp import SNPClient

with SNPClient("127.0.0.1", 9000) as client:
    response = client.request("Hello from SNP!")
    print(response)
```

The client sends the request with a valid sequence number, waits for the matching SNP response, and raises a predictable error if the remote side does not respond within the configured timeout.

## Application-level fragmentation

Large logical messages may be split into multiple SNP datagrams with a `TYPE_FRAGMENT` packet. Each fragment carries a two-byte fragment index and a two-byte total-fragment count in the payload prefix:

```text
payload = [index: 2 bytes][total: 2 bytes][fragment_data]
```

The receiver reassembles fragments in order by sequence number and accepts duplicate fragments without reprocessing the logical payload. Messages that fit within a single SNP datagram remain unfragmented and continue to use the normal `MESSAGE` packet type.

## Peer discovery

SNP supports an optional local UDP discovery request/response for peers on the same network segment. A discovery request uses a `TYPE_DISCOVERY_REQUEST` packet with payload `discover`; a discovery response returns JSON metadata describing the peer service, protocol version, and UDP port.

```python
from snp import discover_peers

peers = discover_peers("127.0.0.1", 9000, timeout=0.5)
print(peers)
```

This mechanism is intentionally lightweight and does not establish trust or authentication. A discovered peer is only an addressable SNP endpoint, not an authenticated service.

## Secure communication

The project includes an optional authenticated packet wrapper based on a shared secret and a keyed HMAC. Secure packets use `TYPE_SECURE` and include a nonce plus a SHA-256 HMAC tag so modifications are rejected before processing.

```python
from snp import secure_encode, secure_decode

secret = b"shared-secret"
packet = secure_encode(secret, b"secret payload")
print(secure_decode(packet, secret))
```

This layer provides integrity and peer authentication for trusted shared-secret deployments, but it does not provide confidentiality by itself. See [SECURITY.md](SECURITY.md) for the full threat model and design notes.

## Running the tests

Use the standard library test runner:

```bash
python -m unittest -q
```

This executes the current automated validation for packet encoding, decoding, validation edge cases, and core request/response behavior.

## Existing implementation notes

This specification reflects the current code in `snp.py` and the tests in `test_snp.py`.

The implementation is intentionally minimal and does not yet include:

- reliable delivery
- acknowledgements
- fragmentation
- peer discovery
- authentication or encryption
- application-level routing or service discovery

Those features, if added later, must be introduced with explicit protocol documentation and compatibility review.
